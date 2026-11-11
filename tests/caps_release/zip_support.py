"""A hand-made ZIP writer and two independent readers, for the tests of the bundle's archive layout.

`build` writes every header field itself, so any header can be made to disagree with another, with the
data, or with the specification. `strict_reason` and `stream_view` are written here and share no code with
the gate: the first states why an archive is not exactly its central directory's entries laid end to end,
the second reads an archive the way a streaming extractor does, from the first local header onwards,
without looking at the central directory.
"""
from __future__ import annotations

import struct
import zlib
import zipfile

LOCAL, CENTRAL, END, DESCRIPTOR, ZIP64_LOCATOR = (b"PK\x03\x04", b"PK\x01\x02", b"PK\x05\x06", b"PK\x07\x08", b"PK\x06\x07")
UNICODE_PATH = 0x7075
ZIP64 = 0x0001
FILE_ATTR = 0o100644 << 16


class Entry:
    """One archive member. `data` is the uncompressed content; the keyword overrides replace what a header says."""

    def __init__(self, name, data=b"", method=0, flags=0, descriptor=None, extra=b"", central_extra=None,
                 local=None, central=None, attr=FILE_ATTR, descriptor_values=None, comment=b"", raw=None):
        self.name = name.encode("utf-8", "surrogateescape") if isinstance(name, str) else name
        self.data, self.method, self.flags, self.descriptor = data, method, flags, descriptor
        self.extra = extra
        self.central_extra = extra if central_extra is None else central_extra
        self.local, self.central = local or {}, central or {}        # per-header overrides of single fields
        self.attr, self.descriptor_values, self.comment, self.raw = attr, descriptor_values, comment, raw


def compress(data: bytes, method: int) -> bytes:
    if method == 8:
        c = zlib.compressobj(6, zlib.DEFLATED, -15)
        return c.compress(data) + c.flush()
    return data


def build(entries, prefix=b"", suffix=b"", comment=b"", end=None, locator=False, relative_offsets=True,
          order=None):
    """Return (bytes, fields): the archive and, for fuzzing, every fixed-width header field as (offset, width)."""
    out = bytearray(prefix)
    base = len(prefix) if relative_offsets else 0
    fields: list[tuple[int, int]] = []
    central = bytearray()
    central_fields: list[tuple[int, int]] = []
    records = []
    for e in entries:
        comp = e.raw if e.raw is not None else compress(e.data, e.method)
        crc, csize, usize = zlib.crc32(e.data) & 0xFFFFFFFF, len(comp), len(e.data)
        flags = e.flags | (0x8 if e.descriptor else 0)
        lv = {"flags": flags, "method": e.method, "crc": 0 if e.descriptor else crc, "csize": 0 if e.descriptor else csize,
              "usize": 0 if e.descriptor else usize, "name": e.name}
        lv.update(e.local)
        offset = len(out) - base
        start = len(out)
        out += struct.pack("<4sHHHHHIIIHH", LOCAL, 20, lv["flags"], lv["method"], 0, 0x21, lv["crc"], lv["csize"],
                           lv["usize"], len(lv["name"]), len(e.extra))
        for off, width in ((4, 2), (6, 2), (8, 2), (10, 2), (12, 2), (14, 4), (18, 4), (22, 4), (26, 2), (28, 2)):
            fields.append((start + off, width))
        out += lv["name"] + e.extra + comp
        if e.descriptor:
            d = e.descriptor_values or (crc, csize, usize)
            out += (DESCRIPTOR if e.descriptor == "sig" else b"") + struct.pack("<3I", *d)
        cv = {"flags": flags, "method": e.method, "crc": crc, "csize": csize, "usize": usize, "offset": offset,
              "name": e.name}
        cv.update(e.central)
        cstart = len(central)
        central += struct.pack("<4sHHHHHHIIIHHHHHII", CENTRAL, 0x031E, 20, cv["flags"], cv["method"], 0, 0x21, cv["crc"],
                               cv["csize"], cv["usize"], len(cv["name"]), len(e.central_extra), len(e.comment), cv.get("disk", 0), 0,
                               e.attr, cv["offset"])
        for off, width in ((4, 2), (6, 2), (8, 2), (10, 2), (16, 4), (20, 4), (24, 4), (28, 2), (30, 2), (32, 2), (42, 4)):
            central_fields.append((cstart + off, width))
        central += cv["name"] + e.central_extra + e.comment
        records.append(cstart)
    cd_off = len(out) - base
    if order is not None:
        recs = [bytes(central[a:b]) for a, b in zip(records, records[1:] + [len(central)])]
        central = bytearray(b"".join(recs[i] for i in order))
    cd_start = len(out)
    out += central
    fields.extend((cd_start + o, w) for o, w in central_fields)
    ev = {"disk": 0, "cd_disk": 0, "here": len(entries), "total": len(entries), "cd_size": len(central),
          "cd_off": cd_off, "comment": comment}
    ev.update(end or {})
    if locator:
        out += struct.pack("<4sIQI", ZIP64_LOCATOR, 0, len(out), 1)
    estart = len(out)
    out += struct.pack("<4sHHHHIIH", END, ev["disk"], ev["cd_disk"], ev["here"], ev["total"], ev["cd_size"], ev["cd_off"],
                       len(ev["comment"]))
    for off, width in ((4, 2), (6, 2), (8, 2), (10, 2), (12, 4), (16, 4), (20, 2)):
        fields.append((estart + off, width))
    out += ev["comment"] + suffix
    return bytes(out), fields


def extra_block(ident: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HH", ident, len(payload)) + payload


def unicode_path_extra(name: bytes, replacement: str) -> bytes:
    return extra_block(UNICODE_PATH, b"\x01" + struct.pack("<I", zlib.crc32(name) & 0xFFFFFFFF) + replacement.encode())


def extras_ok(extra: bytes) -> bool:
    """Well-formed blocks, none of them ZIP64 or a Unicode path (an extension that renames an entry)."""
    pos = 0
    while pos < len(extra):
        if pos + 4 > len(extra):
            return False
        ident, length = struct.unpack_from("<HH", extra, pos)
        if ident in (ZIP64, UNICODE_PATH) or pos + 4 + length > len(extra):
            return False
        pos += 4 + length
    return True


def strict_reason(data: bytes, lenient_central: bool = False) -> str | None:
    """None when DATA is exactly the entries of its central directory laid end to end; otherwise why not.

    LENIENT_CENTRAL leaves out what concerns the central directory's own bookkeeping (a record that overruns the
    directory, bytes left after the last record, a per-entry disk number) and a deflate stream that goes on after the
    declared size, which have their own tests."""
    n = len(data)
    if n < 22 or data[n - 22:n - 18] != END:
        return "no end record in the last 22 bytes"
    disk, cd_disk, here, total, cd_size, cd_off, clen = struct.unpack_from("<HHHHIIH", data, n - 18)
    if clen:
        return "archive comment"
    if disk or cd_disk or here != total:
        return "multi-disk or inconsistent counts"
    if 0xFFFF in (here, total) or 0xFFFFFFFF in (cd_size, cd_off):
        return "zip64 marker"
    if n >= 42 and data[n - 42:n - 38] == ZIP64_LOCATOR:
        return "zip64 locator"
    if cd_off + cd_size != n - 22:
        return "central directory is not directly before the end record"
    pos, records = cd_off, []
    for _ in range(total):
        if pos + 46 > cd_off + cd_size or data[pos:pos + 4] != CENTRAL:
            return "bad central record"
        (_m, _v, flags, method, _t, _d, crc, csize, usize, nlen, elen, clen2, dsk, _ia, _ea, off) = \
            struct.unpack_from("<HHHHHHIIIHHHHHII", data, pos + 4)
        limit = cd_off + cd_size
        name = data[pos + 46:min(pos + 46 + nlen, limit)]
        extra = data[min(pos + 46 + nlen, limit):min(pos + 46 + nlen + elen, limit)]
        if not lenient_central and (len(name) < nlen or len(extra) < elen or pos + 46 + nlen + elen + clen2 > cd_off + cd_size):
            return "central record cut short"
        if (dsk and not lenient_central) or not extras_ok(extra):
            return "central record disk or extra field"
        records.append((off, name, flags, method, crc, csize, usize))
        pos += 46 + nlen + elen + clen2
    if pos != cd_off + cd_size and not lenient_central:
        return "bytes after the last central record"
    pos = 0
    for off, name, flags, method, crc, csize, usize in sorted(records):
        if off != pos:
            return "entries are not contiguous from offset 0"
        if flags & (0x1 | 0x40 | 0x2000) or method not in (0, 8):
            return "encrypted or unsupported method"
        if data[pos:pos + 4] != LOCAL or pos + 30 > n:
            return "no local header at a central offset"
        (_v, lflags, lmethod, _t, _d, lcrc, lcsize, lusize, nlen, elen) = struct.unpack_from("<HHHHHIIIHH", data, pos + 4)
        lname = data[pos + 30:pos + 30 + nlen]
        lextra = data[pos + 30 + nlen:pos + 30 + nlen + elen]
        if lname != name or lflags != flags or lmethod != method or len(lextra) < elen or not extras_ok(lextra):
            return "local header disagrees on name, flags, method or extra"
        end = pos + 30 + nlen + elen + csize
        if flags & 0x8:
            tail = data[end:end + 16]
            body = tail[4:16] if tail[:4] == DESCRIPTOR else tail[:12]
            if len(body) < 12 or struct.unpack("<3I", body) != (crc, csize, usize):
                return "data descriptor disagrees"
            end += 16 if tail[:4] == DESCRIPTOR else 12
        elif (lcrc, lcsize, lusize) != (crc, csize, usize):
            return "local sizes or CRC disagree"
        if end > cd_off:
            return "entry runs into the central directory"
        payload = data[pos + 30 + nlen + elen:pos + 30 + nlen + elen + csize]
        try:
            if method == 8 and lenient_central:
                raw = zlib.decompressobj(-15).decompress(payload, usize)
            else:
                raw = zlib.decompress(payload, -15) if method == 8 else payload
        except zlib.error:
            return "undecodable data"
        if len(raw) != usize or zlib.crc32(raw) & 0xFFFFFFFF != crc:
            return "content disagrees with CRC or size"
        pos = end
    if pos != cd_off:
        return "bytes between the last entry and the central directory"
    return None


def stream_view(data: bytes, honour_unicode_path: bool = True):
    """(name, content) of every entry as a streaming extractor reads them, or None when the walk cannot end cleanly."""
    pos, out = 0, []
    while data[pos:pos + 4] == LOCAL:
        if pos + 30 > len(data):
            return None
        (_v, flags, method, _t, _d, crc, csize, usize, nlen, elen) = struct.unpack_from("<HHHHHIIIHH", data, pos + 4)
        name = data[pos + 30:pos + 30 + nlen]
        extra = data[pos + 30 + nlen:pos + 30 + nlen + elen]
        start = pos + 30 + nlen + elen
        if honour_unicode_path:
            i = 0
            while i + 4 <= len(extra):
                ident, length = struct.unpack_from("<HH", extra, i)
                block = extra[i + 4:i + 4 + length]
                if ident == UNICODE_PATH and len(block) >= 5 and block[0] == 1 and \
                        struct.unpack_from("<I", block, 1)[0] == zlib.crc32(name) & 0xFFFFFFFF:
                    name = block[5:]
                i += 4 + length
        if flags & 0x8 and method == 8:
            d = zlib.decompressobj(-15)
            try:
                raw = d.decompress(data[start:])
            except zlib.error:
                return None
            consumed = len(data) - start - len(d.unused_data)
            end = start + consumed
            rest = data[end:end + 16]
            end += 16 if rest[:4] == DESCRIPTOR else 12
        elif flags & 0x8:
            return "unstreamable"               # a stored entry with a descriptor cannot be walked without the central sizes
        else:
            payload = data[start:start + csize]
            try:
                raw = zlib.decompress(payload, -15) if method == 8 else payload
            except zlib.error:
                return None
            end = start + csize
        out.append((name, raw))
        pos = end
    return out


def zipfile_view(path: str):
    with zipfile.ZipFile(path) as zf:
        return [(i.orig_filename.encode("utf-8", "surrogateescape") if i.flag_bits & 0x800 else i.orig_filename.encode("cp437"),
                 zf.read(i)) for i in zf.infolist()]
