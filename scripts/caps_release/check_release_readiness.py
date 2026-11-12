#!/usr/bin/env python3
"""The release-readiness gate: what a release would send is complete, signed and the same everywhere.

Inspects the root `target/` of a single-module build. The files it gates are exactly the files the
run artifact keeps and the attestation covers: every top-level `*.jar`, `*.pom` and `*.asc` of
`target/`, and the Central bundle. The allowed set is closed:

  * a main jar `<base>.jar`, `<base>-sources.jar`, `<base>-javadoc.jar`, `<base>.pom`;
  * a detached `<file>.asc` of each of those four;
  * nothing else. A `-tests` jar, any other classifier, a sources or javadoc jar without the main jar
    of the same name, a signature of a file that is not released, and any entry that is not a regular
    file (a symbolic link, a directory, a device) are refused by default.

A main jar is a `*.jar` that is not `-sources`, `-javadoc` or `-tests`. Every coordinate needs:

  * a sources jar, a javadoc jar and a pom beside it, none missing;
  * an `index.html` in the javadoc jar;
  * a detached `.asc` for the four files, each a good signature under the keyring `gpg` is pointed at
    (GNUPGHOME in the environment);
  * a version that is not a snapshot (Maven's own definition: a `SNAPSHOT` suffix in any case, or the
    timestamp form `-YYYYMMDD.HHMMSS-N`);
  * a pom that yields a groupId, an artifactId and a version (its own, or the group and version of its
    `<parent>`) and names the ones the files are called by; a pom that does not is refused, so the
    bundle is always bound to one full coordinate;
  * a version that is ASCII: any other character refuses the coordinate, because Maven's case-insensitive
    SNAPSHOT test folds characters that `str.lower()` does not.

With --expect-bundle true, `<target-dir>/central-publishing/central-bundle.zip` must exist, be a
regular file, stay within the entry and size bounds, and be bound to what was built:

  * the file set is EXACTLY the gated set: for each built coordinate, under
    `<group path of its pom>/<artifactId>/<version>/`, the four built files, the `.asc` of each, and
    all four of `.md5`, `.sha1`, `.sha256` and `.sha512` of each of those eight (the set the Central
    publishing plugin writes; a missing or additional checksum file is a finding); nothing else, and
    no other coordinate;
  * every entry name is a relative, normalised path (directory entries are plain relative paths and
    carry no payload), with no `.`, `..` or empty segment, no backslash and no control character; a
    name occurs once, and no two names collide under case folding or Unicode normalisation (NFKC); no
    entry is a symbolic link;
  * a bundle file has the bytes of its counterpart of the same name in `target/`;
  * each `.asc` in the bundle is a good signature of the bundle's own file, with the same key check;
  * each checksum file holds the digest of the file it names, and, when it also holds a file name,
    that name, with at most one leading `*`.

The archive layout is checked entry by entry: the local file header at each central-directory offset
carries the same name, flags, method and (without a data descriptor) sizes and CRC as the central
record, the entries follow one another without a gap from offset 0 to the central directory, and the
end record is the last 22 bytes. The central records are walked one by one: each starts on disk 0,
their lengths add up to the directory's size exactly and their number is the end record's count. The
extra fields of both headers are parsed as (id, size) records inside their bounds; one that is
malformed, a ZIP64 record, or any id outside a short list of timestamp and owner records (0x5455,
0x5855, 0x7855, 0x7875, 0x000A and the JDK's 0xCAFE) is refused, so no field can rename or redirect an
entry (the Unicode Path field 0x7075 replaces a name for the extractors that honour it). Only the
methods stored and deflated are accepted, and every payload is read from the private copy in bounded
chunks: a deflate stream must end exactly at the declared compressed size, and the bytes it yields must
number the declared uncompressed size and have the declared CRC. An archive comment, data before,
between or after the entries, a ZIP64 record and encryption refuse the bundle, so a streaming
extractor and this gate see the same files. Any failure to open or list the archive is one
`central bundle: <reason>` line that names the kind of failure and never echoes archive text.

The bundle is only listed and read in bounded streams, never extracted into the tree; the bounds are
MAX_ENTRIES entries, MAX_TOTAL_BYTES in all (a bundle file larger than that is refused unread), and a compression ratio of at most MAX_RATIO for an entry
of MIN_RATIO_BYTES or more. All findings are reported before the gate fails; no main jar is fatal at once.

WHAT IS STAGED IS WHAT WAS VERIFIED. Each gated file is opened once (`O_NOFOLLOW|O_NONBLOCK`, `fstat`
must say regular file), read to the end into a private directory of the gate while its SHA-256 is
computed, and every check (signature, POM, javadoc, bundle) is made on that private copy. Staging
re-hashes the live file and refuses on any difference, then copies from the private copy while hashing
again and refuses unless the digest equals the one taken when the file was read. What is staged is
byte-identical to what was verified. A run with any finding stages NOTHING, and a stage that ends before it is complete, by a finding,
an interrupt or any exception, is removed, so no directory a later step could mistake for a release exists after a refusal. Every
subprocess call is bounded by a timeout, and an expiry is a refusal.

Usage: check_release_readiness.py --target-dir DIR [--expect-bundle {true,false}] [--uploaded]
                                  [--gpg PATH] [--stage DIR]

  --expect-bundle  default false
  --uploaded       the run has already uploaded: the final refusal also says to drop the deployment
  --gpg            the gpg executable (default `gpg`)
  --stage          a directory that does not exist yet; on a run without findings the gated files are
                   copied into it (the bundle as `central-publishing/central-bundle.zip`), so that what
                   a later step uploads or attests is the set that was gated and nothing else; on a run
                   with a finding it is not created

Exit status: 0 ready; 1 any finding; 2 usage error.
Output: `coordinate: <name> - main, sources, javadoc, pom, signatures` per coordinate without a finding,
`central bundle: N file(s), M outside a coordinate`, `release-readiness: ok`; findings on stderr as
`::error::`.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import zlib
from xml.parsers import expat

MAX_ENTRIES = 2000
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_RATIO = 200
MIN_RATIO_BYTES = 1024 * 1024
MAX_XML_BYTES = 16 * 1024 * 1024
MAX_XML_DEPTH = 200
SUBPROCESS_TIMEOUT = 120
BUNDLE_KEY = "central-publishing/central-bundle.zip"
CHECKSUMS = {".md5": "md5", ".sha1": "sha1", ".sha256": "sha256", ".sha512": "sha512"}
CHUNK = 64 * 1024
# Extra-field ids an entry may carry: extended and Info-ZIP timestamps and owners, NTFS times and the
# JDK's marker. Every other id, in particular the Unicode Path field (0x7075), is refused.
HARMLESS_EXTRAS = frozenset({0x5455, 0x5855, 0x7855, 0x7875, 0x000A, 0xCAFE})
CLASSIFIER_SUFFIXES = ("-sources.jar", "-javadoc.jar", "-tests.jar")

# A version is a snapshot exactly when Maven's ArtifactUtils.isSnapshot says so: it ends with
# "SNAPSHOT" in any case, or it has the timestamped-snapshot form of Artifact.VERSION_FILE_PATTERN,
# `<anything>-<8 digits>.<6 digits>-<digits>`.
TIMESTAMPED = re.compile(r"(.*)-([0-9]{8}\.[0-9]{6})-([0-9]+)")


def is_snapshot(version: str) -> bool:
    """True when Maven says so. The suffix is compared the way Java's `regionMatches(ignoreCase)` does,
    which folds U+017F to S as `upper()` does and `lower()` does not; a non-ASCII version is refused
    separately, before this is asked."""
    return version[-8:].upper().lower() == "snapshot" or TIMESTAMPED.fullmatch(version) is not None


def unusual(ch: str) -> bool:
    return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")


def shown(name: str) -> str:
    """A name safe to put in a `::error::` line: an unusual character is written as an escape."""
    return "".join(f"\\u{ord(c):04x}" if unusual(c) else c for c in name)


def read_pom(path: str) -> ET.Element:
    """Parse a POM. A DOCTYPE is refused before any entity is read, and so is a document over
    MAX_XML_BYTES or nested deeper than MAX_XML_DEPTH; a POM needs none of that."""
    with open(path, "rb") as fh:
        data = fh.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise ET.ParseError(f"the document is larger than {MAX_XML_BYTES} bytes")
    depth = 0

    def refuse(*_args):
        raise ET.ParseError("the document declares a DOCTYPE; a POM never needs one")

    def start(*_args):
        nonlocal depth
        depth += 1
        if depth > MAX_XML_DEPTH:
            raise ET.ParseError(f"the document is nested deeper than {MAX_XML_DEPTH} elements")

    def end(*_args):
        nonlocal depth
        depth -= 1

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = refuse
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise ET.ParseError(str(exc)) from exc
    return ET.fromstring(data)


def pom_coordinate(root: ET.Element) -> tuple[str | None, str | None, str | None]:
    """(groupId, artifactId, version) the POM states for itself, falling back to its parent's group and version."""
    def child(el, name):
        for c in el:
            if c.tag.rsplit("}", 1)[-1] == name:
                return c
        return None

    def text(el, name):
        c = child(el, name) if el is not None else None
        value = (c.text or "").strip() if c is not None else ""
        return value or None

    parent = child(root, "parent")
    return (text(root, "groupId") or text(parent, "groupId"), text(root, "artifactId"),
            text(root, "version") or text(parent, "version"))


def valid_segments(name: str, directory: bool) -> list[str] | None:
    """The segments of a bundle entry name, or None when the name is not a plain relative path."""
    if directory != name.endswith("/"):
        return None
    body = name[:-1] if directory else name
    if not body or "\\" in body or any(unusual(c) for c in body):
        return None
    segments = body.split("/")
    if any(s in ("", ".", "..") for s in segments):
        return None
    return segments


def regular(path: str) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def open_regular(path: str) -> int:
    """A descriptor for PATH, opened without following a link or blocking, that is a regular file."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd


def digest_of_file(path: str) -> str:
    h = hashlib.sha256()
    with os.fdopen(open_regular(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class TooLarge(OSError):
    """A file over the size bound."""


def take(src: str, scratch: str, limit: int | None = None) -> tuple[str, str]:
    """Read SRC once, to the end: copy it into a private directory under SCRATCH (keeping its base name)
    while hashing the same bytes. Returns (private path, SHA-256 of what was read)."""
    h = hashlib.sha256()
    with os.fdopen(open_regular(src), "rb") as fin:
        if limit is not None and os.fstat(fin.fileno()).st_size > limit:
            raise TooLarge(f"larger than {limit} bytes")
        private = os.path.join(tempfile.mkdtemp(dir=scratch), os.path.basename(src) or "file")
        with open(private, "xb") as fout:
            for chunk in iter(lambda: fin.read(1 << 20), b""):
                h.update(chunk)
                fout.write(chunk)
    return private, h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::release-readiness failed unexpectedly ({type(exc).__name__}: "
              f"{shown(' '.join(str(exc).split()))}).", file=sys.stderr)
        return 1


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target-dir", required=True)
    p.add_argument("--expect-bundle", choices=["true", "false"], default="false")
    p.add_argument("--uploaded", action="store_true")
    p.add_argument("--gpg", default="gpg")
    p.add_argument("--stage", default="")
    a = p.parse_args(argv)
    scratch = tempfile.mkdtemp(prefix="bundle-verify-")
    try:
        return gate(a, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def gate(a: argparse.Namespace, scratch: str) -> int:
    findings: list[str] = []

    def err(msg: str) -> None:
        findings.append(msg)
        print(f"::error::{msg}", file=sys.stderr)

    try:
        names = sorted(os.listdir(a.target_dir))
    except OSError as exc:
        print(f"::error::{shown(a.target_dir)} cannot be read ({exc}).", file=sys.stderr)
        return 1
    t = a.target_dir
    selected = [n for n in names if n.endswith((".jar", ".pom", ".asc"))]
    mains = [n for n in selected if n.endswith(".jar") and not n.endswith(CLASSIFIER_SUFFIXES)
             and not stat.S_ISDIR(os.lstat(os.path.join(t, n)).st_mode)]
    if not mains:
        print("::error::the build produced no main jar", file=sys.stderr)
        return 1

    def good_signature(asc: str, f: str) -> bool:
        try:
            return subprocess.run([a.gpg, "--verify", asc, f], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=SUBPROCESS_TIMEOUT).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    held: dict[str, tuple[str, str]] = {}       # name -> (private copy, SHA-256 of the bytes that were read)

    def hold(name: str) -> bool:
        """Read the file once; every later check and the staging use that read. An unreadable file ends
        the run through the unexpected-error line."""
        held[name] = take(os.path.join(t, name), scratch)
        return True

    allowed: set[str] = set()
    built: dict[str, tuple[str | None, str | None, str | None]] = {}    # base -> (group, artifactId, version)
    for main_jar in mains:
        base = main_jar[:-len(".jar")]
        files = [main_jar, f"{base}-sources.jar", f"{base}-javadoc.jar", f"{base}.pom"]
        allowed.update(files)
        allowed.update(f + ".asc" for f in files)

    for main_jar in mains:
        before = len(findings)
        base = main_jar[:-len(".jar")]
        shown_base = shown(base)
        if not base.isascii():
            err(f"{shown_base} is not ASCII; a release version is ASCII only")
        elif is_snapshot(base):
            err(f"{shown_base} is a SNAPSHOT; a release is final")
        files = [main_jar, f"{base}-sources.jar", f"{base}-javadoc.jar", f"{base}.pom"]
        intact = []
        for want in files:
            path = os.path.join(t, want)
            if os.path.islink(path):
                err(f"{shown(want)} is a symbolic link; only regular files are released")
            elif want != main_jar and not os.path.lexists(path):
                err(f"{shown_base} is missing {shown(want)} - Central rejects a coordinate without it")
            elif os.path.lexists(path) and not regular(path):
                err(f"{shown(want)} is not a regular file; only regular files are released")
            elif os.path.lexists(path):
                if want == f"{base}.pom":
                    try:
                        hold(want)
                    except OSError as exc:
                        err(f"{shown_base}.pom cannot be read as a POM ({shown(' '.join(str(exc).split()))})")
                        continue
                else:
                    hold(want)
                intact.append(want)
        if f"{base}-javadoc.jar" in intact:
            try:
                with zipfile.ZipFile(held[f"{base}-javadoc.jar"][0]) as zf:
                    if "index.html" not in zf.namelist():
                        err(f"{shown_base}-javadoc.jar holds no index.html")
            except zipfile.BadZipFile:
                err(f"{shown_base}-javadoc.jar is not a zip file")
        coordinate: tuple[str | None, str | None, str | None] = (None, None, None)
        if f"{base}.pom" in intact:
            readable = True
            try:
                coordinate = pom_coordinate(read_pom(held[f"{base}.pom"][0]))
            except (OSError, ET.ParseError) as exc:
                readable = False
                err(f"{shown_base}.pom cannot be read as a POM ({shown(' '.join(str(exc).split()))})")
            group, artifact, version = coordinate
            if readable and not (group and artifact and version):
                err(f"{shown_base}.pom does not yield a groupId, an artifactId and a version (its own or its "
                    "parent's); the bundle cannot be bound to a coordinate")
            if not all(v.isascii() for v in (group, artifact, version) if v):
                err(f"{shown_base}.pom names a coordinate that is not ASCII; a release version is ASCII only")
            elif artifact and version and f"{artifact}-{version}" != base:
                err(f"{shown_base}.pom declares {shown(artifact)}:{shown(version)}, which the files are not named after")
            if version and version.isascii() and is_snapshot(version):
                err(f"{shown_base}.pom declares the SNAPSHOT version {shown(version)}; a release is final")
        built[base] = coordinate
        for f in intact:
            asc = f + ".asc"
            if os.path.islink(os.path.join(t, asc)):
                err(f"{shown(f)}.asc is a symbolic link; only regular files are released")
            elif not regular(os.path.join(t, asc)):
                err(f"{shown(f)} has no detached signature")
            elif hold(asc) and not good_signature(held[asc][0], held[f][0]):
                err(f"{shown(f)}.asc is not a good signature")
        if len(findings) == before:
            print(f"coordinate: {shown_base} - main, sources, javadoc, pom, signatures")

    for n in selected:
        if n not in allowed:
            err(f"{shown(n)} is not part of a release: only a main jar, its -sources and -javadoc jars, the pom "
                "and their .asc signatures are released, and any other classifier is refused")
    for n in names:
        if n.endswith((".jar", ".pom", ".asc")) and any(unusual(c) for c in n):
            err(f"{shown(n)} has a control or unassigned character in its name")

    bundle_path = os.path.join(t, "central-publishing", "central-bundle.zip")
    bundle_ok = False
    if a.expect_bundle == "true":
        bundle_ok = check_bundle(t, bundle_path, built, err, good_signature, held, scratch)

    if findings:
        tail = "; if a deployment was uploaded, DROP it in the portal." if a.uploaded else ""
        print(f"::error::release-readiness failed{tail}", file=sys.stderr)
        return 1

    if a.stage:
        wrote = stage(a.stage, t, sorted(f for f in held if f in allowed), bundle_path if bundle_ok else None, err, held)
        if findings:
            if wrote:
                shutil.rmtree(a.stage, ignore_errors=True)
            print("::error::release-readiness failed: the gated files could not be staged", file=sys.stderr)
            return 1
    print("release-readiness: ok")
    return 0


def stage(dest: str, t: str, files: list[str], bundle: str | None, err, held=None) -> bool:
    """Copy the gated files into DEST: what is staged is byte-identical to what was verified.

    A file in HELD (name -> (private copy, digest taken when it was read and verified)) is staged only
    if the live file still has that digest, and is copied from the private copy while hashing it again;
    a difference, a link, a special file or a vanished file is an error. A file with no record is
    copied from the live file, opened without following a link and required to be regular. Returns True
    when DEST was created here (the caller removes it if any file failed); an exception that ends the
    copying removes DEST here and propagates."""
    held = held or {}
    if os.path.lexists(dest) and (os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):
        err(f"{shown(dest)} is not an empty directory; the gated files cannot be staged there")
        return False
    os.makedirs(dest, mode=0o700, exist_ok=True)
    try:
        copies = [(f, os.path.join(t, f), os.path.join(dest, f)) for f in files]
        if bundle:
            os.makedirs(os.path.join(dest, "central-publishing"), mode=0o700, exist_ok=True)
            copies.append((BUNDLE_KEY, bundle, os.path.join(dest, "central-publishing", "central-bundle.zip")))
        for key, src, dst in copies:
            try:
                copy_gated(src, dst, held.get(key))
            except OSError as exc:
                err(f"{shown(src)} cannot be staged ({shown(' '.join(str(exc).split()))})")
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)         # an interrupted stage is not left behind
        raise
    return True


def copy_gated(src: str, dst: str, gated: tuple[str, str] | None) -> None:
    if gated is None:
        with os.fdopen(open_regular(src), "rb") as fin, open(dst, "xb") as fout:
            shutil.copyfileobj(fin, fout)
        return
    private, digest = gated
    if digest_of_file(src) != digest:
        raise OSError("it is not the file that was verified")
    h = hashlib.sha256()
    with os.fdopen(open_regular(private), "rb") as fin, open(dst, "xb") as fout:
        for chunk in iter(lambda: fin.read(1 << 20), b""):
            h.update(chunk)
            fout.write(chunk)
    if h.hexdigest() != digest:
        os.unlink(dst)
        raise OSError("the verified copy changed")


def layout_problem(path: str, infos: list[zipfile.ZipInfo]) -> str | None:
    """Why the archive at PATH is not exactly its central directory's entries laid end to end, or None.

    Every offset is bounds-checked by a short read, so any malformed input ends in a reason, not an exception."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size < 22:
                return "it has no end record"
            fh.seek(size - 22)
            sig, disk, cd_disk, here, total, cd_size, cd_off, comment = struct.unpack("<4s4H2LH", fh.read(22))
            if sig != b"PK\x05\x06" or comment:
                return "its end record is not the last 22 bytes (an archive comment or data after the entries)"
            if disk or cd_disk or here != total or total != len(infos):
                return "its end record does not describe one archive of the listed entries"
            if 0xFFFF in (here, total) or 0xFFFFFFFF in (cd_size, cd_off):
                return "it is a ZIP64 archive"
            if size >= 42:
                fh.seek(size - 42)
                if fh.read(4) == b"PK\x06\x07":
                    return "it is a ZIP64 archive"
            if cd_off + cd_size != size - 22:
                return "there is data before the entries or between them and the central directory"
            pos = 0
            for i in sorted(infos, key=lambda e: e.header_offset):
                if i.header_offset != pos:
                    return "its entries do not follow one another from the start (data before, between or overlapping)"
                if i.flag_bits & 0x1 or i.flag_bits & 0x40 or i.flag_bits & 0x2000:
                    return "an entry is encrypted"
                if i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    return "an entry uses a compression method other than stored or deflated"
                if 0xFFFFFFFF in (i.compress_size, i.file_size, i.header_offset) or zip64_extra(i.extra):
                    return "an entry has a ZIP64 record"
                fh.seek(pos)
                head = fh.read(30)
                if len(head) < 30:
                    return "a local header is cut short"
                (lsig, _ver, flags, method, _t, _d, crc, csize, usize, nlen, elen) = struct.unpack("<4s5H3L2H", head)
                if lsig != b"PK\x03\x04":
                    return "a central-directory offset does not point at a local header"
                raw = fh.read(nlen)
                extra = fh.read(elen)
                if len(raw) < nlen or len(extra) < elen:
                    return "a local header is cut short"
                try:
                    name = raw.decode("utf-8" if flags & 0x800 else "cp437")
                except UnicodeDecodeError:
                    return "a local header name cannot be decoded"
                if name != i.orig_filename:
                    return f"the local header name {shown(name)} differs from the central-directory name {shown(i.orig_filename)}"
                if flags != i.flag_bits or method != i.compress_type:
                    return f"the local header of {shown(name)} disagrees with the central record in flags or method"
                if zip64_extra(extra):
                    return "an entry has a ZIP64 record"
                if renaming_extra(extra):
                    return "an entry has an extra field that can rename or redirect it"
                end = pos + 30 + nlen + elen + i.compress_size
                if flags & 0x8:
                    fh.seek(end)
                    tail = fh.read(16)
                    fields = tail[4:16] if tail[:4] == b"PK\x07\x08" else tail[:12]
                    if len(fields) < 12 or struct.unpack("<3L", fields) != (i.CRC, i.compress_size, i.file_size):
                        return f"the data descriptor of {shown(name)} disagrees with the central record"
                    end += 16 if tail[:4] == b"PK\x07\x08" else 12
                elif (crc, csize, usize) != (i.CRC, i.compress_size, i.file_size):
                    return f"the local header of {shown(name)} disagrees with the central record in size or CRC"
                if end > cd_off:
                    return "an entry runs into the central directory"
                problem = payload_problem(fh, pos + 30 + nlen + elen, i)
                if problem:
                    return f"{problem} ({shown(name)})"
                pos = end
            if pos != cd_off:
                return "there is data between the last entry and the central directory"
            return central_problem(fh, cd_off, cd_size, total)
    except (OSError, struct.error, ValueError, OverflowError) as exc:
        return f"its layout cannot be read ({type(exc).__name__})"
    return None


def central_problem(fh, cd_off: int, cd_size: int, count: int) -> str | None:
    """Why the central directory is not exactly COUNT records, each on disk 0 with extra fields that
    cannot rename an entry, whose lengths add up to CD_SIZE; None when it is."""
    pos, limit = cd_off, cd_off + cd_size
    for _ in range(count):
        fh.seek(pos)
        head = fh.read(46)
        if len(head) < 46 or pos + 46 > limit or head[:4] != b"PK\x01\x02":
            return "a central record is missing or cut short"
        nlen, elen, clen, disk = struct.unpack_from("<4H", head, 28)
        if disk:
            return "a central record starts on another disk"
        length = 46 + nlen + elen + clen
        if pos + length > limit:
            return "a central record runs past the central directory"
        fh.seek(pos + 46 + nlen)
        extra = fh.read(elen)
        if len(extra) < elen:
            return "a central record is cut short"
        if zip64_extra(extra):
            return "an entry has a ZIP64 record"
        if renaming_extra(extra):
            return "an entry has an extra field that can rename or redirect it"
        pos += length
    if pos != limit:
        return "the central directory holds bytes after its last record"
    return None


def renaming_extra(extra: bytes) -> bool:
    """Whether a well-formed extra field holds a record outside HARMLESS_EXTRAS. The structure is
    checked by zip64_extra, which the caller asks first."""
    pos = 0
    while pos + 4 <= len(extra):
        ident, length = struct.unpack("<2H", extra[pos:pos + 4])
        if ident not in HARMLESS_EXTRAS:
            return True
        pos += 4 + length
    return False


def payload_problem(fh, start: int, info: zipfile.ZipInfo) -> str | None:
    """Why the data at START is not the entry INFO declares, or None. The data is stored or a raw deflate
    stream of exactly INFO.compress_size bytes that yields INFO.file_size bytes with the CRC INFO.CRC.
    It is read in chunks and never yields more than one byte past the declared size, so the work is
    bounded by the declared sizes."""
    fh.seek(start)
    left, made, crc = info.compress_size, 0, 0
    inflater = zlib.decompressobj(-15) if info.compress_type == zipfile.ZIP_DEFLATED else None
    try:
        while left:
            chunk = fh.read(min(CHUNK, left))
            if not chunk:
                return "an entry is cut short"
            left -= len(chunk)
            if inflater is None:
                out, chunk = chunk, b""
                made += len(out)
                crc = zlib.crc32(out, crc)
            while chunk:
                if inflater.eof:
                    return "a deflate stream goes on after its end"
                out = inflater.decompress(chunk, max(info.file_size - made, 0) + 1)
                made += len(out)
                crc = zlib.crc32(out, crc)
                if made > info.file_size:
                    return "an entry inflates to more than its declared size"
                if inflater.eof:
                    chunk = b""
                    if inflater.unused_data or left:
                        return "a deflate stream ends before its declared compressed size"
                else:
                    chunk = inflater.unconsumed_tail
                    if chunk and not out:
                        return "a deflate stream cannot be inflated"
            if made > info.file_size:
                return "an entry holds more than its declared size"
    except zlib.error:
        return "a deflate stream cannot be inflated"
    if inflater is not None and not inflater.eof:
        return "a deflate stream does not end"
    if made != info.file_size:
        return "an entry is not the size it declares"
    if crc & 0xFFFFFFFF != info.CRC:
        return "an entry does not have the CRC it declares"
    return None


def zip64_extra(extra: bytes) -> bool:
    """Whether an extra-field block holds a ZIP64 record (header id 0x0001); a malformed block counts as one."""
    pos = 0
    while pos < len(extra):
        if pos + 4 > len(extra):
            return True
        ident, length = struct.unpack("<2H", extra[pos:pos + 4])
        if ident == 1 or pos + 4 + length > len(extra):
            return True
        pos += 4 + length
    return False


def check_bundle(t, bundle, built, err, good_signature, held=None, scratch=None) -> bool:
    """Judge the Central bundle against what was built. True when it is a bounded zip that may be kept.

    The bundle is read once into a private copy; the layout check, the listing and every read are made
    on that copy, and its digest is recorded in HELD for staging."""
    held = held if held is not None else {}
    directory = os.path.dirname(bundle)
    if os.path.islink(directory) or os.path.islink(bundle) or not os.path.lexists(bundle):
        err(f"{shown(bundle)} is missing; the release profile builds it at deploy")
        return False
    if not regular(bundle):
        err(f"{shown(bundle)} is not a regular file")
        return False
    own = scratch is None
    scratch = tempfile.mkdtemp(prefix="bundle-verify-") if own else scratch
    try:
        try:
            held[BUNDLE_KEY] = take(bundle, scratch, MAX_TOTAL_BYTES)
        except TooLarge as exc:
            err(f"central bundle: {exc}")
            return False
        return judge_private_copy(t, bundle, held[BUNDLE_KEY][0], built, err, good_signature, held)
    finally:
        if own:
            shutil.rmtree(scratch, ignore_errors=True)


def judge_private_copy(t, bundle, copy, built, err, good_signature, held) -> bool:
    try:
        zf = zipfile.ZipFile(copy)
        infos = zf.infolist()
    except zipfile.BadZipFile:
        err(f"{shown(bundle)} is not a zip file")
        return False
    except (NotImplementedError, UnicodeDecodeError, OSError, ValueError, RuntimeError, zlib.error, EOFError) as exc:
        err(f"central bundle: its directory cannot be read ({type(exc).__name__})")
        return False
    with zf:
        if len(infos) > MAX_ENTRIES:
            err(f"central bundle: {len(infos)} entries exceed the limit of {MAX_ENTRIES}")
            return False
        total = sum(i.file_size for i in infos)
        if total > MAX_TOTAL_BYTES:
            err(f"central bundle: {total} bytes uncompressed exceed the limit of {MAX_TOTAL_BYTES}")
            return False
        for i in infos:
            if i.file_size >= MIN_RATIO_BYTES and i.file_size > MAX_RATIO * max(i.compress_size, 1):
                err(f"central bundle: {shown(i.filename)} expands by more than {MAX_RATIO} times")
                return False
        problem = layout_problem(copy, infos)
        if problem:
            err(f"central bundle: {problem}")
            return False
        try:
            judge_bundle(t, zf, infos, built, err, good_signature, held)
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as exc:
            err(f"central bundle: an entry cannot be read ({type(exc).__name__})")
            return False
        return True


def fold(name: str) -> str:
    """A key under which two names that a case-folding or normalising file system would merge are equal."""
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", name.rstrip("/")).casefold())


def judge_bundle(t, zf, infos, built, err, good_signature, held=None) -> None:
    held = held or {}
    counts: dict[str, int] = {}
    for i in infos:
        counts[i.filename] = counts.get(i.filename, 0) + 1
    for name in sorted(n for n, c in counts.items() if c > 1):
        err(f"central bundle: {shown(name)} occurs {counts[name]} times")

    folded: dict[str, set[str]] = {}
    for n in counts:
        folded.setdefault(fold(n), set()).add(n)
    for names in sorted(folded.values(), key=sorted):
        if len(names) > 1:
            err("central bundle: " + ", ".join(shown(n) for n in sorted(names)) +
                " collide under case folding or Unicode normalisation")

    files: dict[str, zipfile.ZipInfo] = {}
    stray: list[str] = []
    for i in infos:
        name = i.filename
        if name.endswith("/"):
            if valid_segments(name, True) is None:
                stray.append(name)
                err(f"central bundle: {shown(name)} is not a file of a published coordinate (an unsafe name)")
            elif i.file_size:
                stray.append(name)
                err(f"central bundle: {shown(name)} is a directory entry that carries a payload")
            continue
        if (i.external_attr >> 16) & 0o170000 == 0o120000:
            stray.append(name)
            err(f"central bundle: {shown(name)} is not a file of a published coordinate (a symbolic link)")
            continue
        segments = valid_segments(name, False)
        if segments is None or len(segments) < 4:
            stray.append(name)
            err(f"central bundle: {shown(name)} is not a file of a published coordinate")
            continue
        files.setdefault(name, i)

    # a coordinate directory is <group path>/<artifactId>/<version>; it needs its pom
    dirs: dict[str, str] = {}                               # directory -> stem
    for name in files:
        d, _, filename = name.rpartition("/")
        parts = d.split("/")
        stem = f"{parts[-2]}-{parts[-1]}"
        if f"{d}/{stem}.pom" in files and filename.startswith((stem + ".", stem + "-")):
            dirs[d] = stem
        else:
            stray.append(name)
            err(f"central bundle: {shown(name)} is not a file of a published coordinate")
    print(f"central bundle: {len(files)} file(s), {len(stray)} outside a coordinate")

    # the coordinates in the bundle are the coordinates that were built
    by_stem: dict[str, list[str]] = {}
    for d, stem in dirs.items():
        by_stem.setdefault(stem, []).append(d)
    for stem, where in sorted(by_stem.items()):
        if stem not in built:
            for d in where:
                err(f"central bundle: {shown(d)} is a coordinate that was not built")
        elif len(where) > 1:
            err(f"central bundle: {shown(stem)} is in {len(where)} directories")
        else:
            group = built[stem][0]
            if not group:
                err(f"central bundle: {shown(where[0])} cannot be bound to a group: the built pom yields no coordinate")
            elif "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):
                err(f"central bundle: {shown(where[0])} is not under the group {shown(group)} of the built pom")
    for stem in sorted(built):
        if stem not in by_stem:
            err(f"central bundle: it holds no coordinate for the built {shown(stem)}")
            continue
        d = by_stem[stem][0]
        for suffix in (".pom", ".jar", "-sources.jar", "-javadoc.jar"):
            for extra in ("", ".asc"):
                if f"{d}/{stem}{suffix}{extra}" not in files:
                    err(f"central bundle: {shown(d)} holds no {shown(stem + suffix + extra)}")
                    continue
                for c in CHECKSUMS:
                    if f"{d}/{stem}{suffix}{extra}{c}" not in files:
                        err(f"central bundle: {shown(d)} holds no {shown(stem + suffix + extra + c)}")

    # the file set is exactly the gated set
    expected: set[str] = set()
    for stem, (group, artifact, version) in built.items():
        if group and artifact and version:
            d = f"{group.replace('.', '/')}/{artifact}/{version}"
            for suffix in (".pom", ".jar", "-sources.jar", "-javadoc.jar"):
                for sig in ("", ".asc"):
                    expected.add(f"{d}/{stem}{suffix}{sig}")
                    expected.update(f"{d}/{stem}{suffix}{sig}{c}" for c in CHECKSUMS)
    reported = set(stray)
    for name in sorted(files):
        if name not in expected and name not in reported:
            err(f"central bundle: {shown(name)} is not one of the gated files: only the four built files, their "
                "signatures and the checksums of those are released")

    # the bundle's files are the files that were built
    for name in sorted(files):
        filename = name.rpartition("/")[2]
        if name.rpartition("/")[0] in dirs and filename in held:
            if digest_of(zf, files[name]) != held[filename][1]:
                err(f"central bundle: {shown(name)} differs from target/{shown(filename)}")

    # signatures and checksums of the bundle's own files
    scratch = tempfile.mkdtemp(prefix="bundle-verify-")
    try:
        for name in sorted(files):
            if name.rpartition("/")[0] not in dirs:
                continue
            if name.endswith(".asc"):
                subject = name[:-len(".asc")]
                if subject not in files:
                    err(f"central bundle: {shown(name)} signs {shown(subject.rpartition('/')[2])}, which the bundle does not hold")
                    continue
                pair = []
                for member in (name, subject):
                    out = os.path.join(scratch, f"{len(pair)}")
                    with zf.open(files[member]) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    pair.append(out)
                if not good_signature(pair[0], pair[1]):
                    err(f"central bundle: {shown(name)} is not a good signature of the bundle's own file")
            for suffix, algorithm in CHECKSUMS.items():
                if name.endswith(suffix):
                    subject = name[:-len(suffix)]
                    if subject not in files:
                        err(f"central bundle: {shown(name)} is a checksum of {shown(subject.rpartition('/')[2])}, "
                            "which the bundle does not hold")
                        continue
                    h = hashlib.new(algorithm)
                    with zf.open(files[subject]) as src:
                        for chunk in iter(lambda: src.read(1 << 20), b""):
                            h.update(chunk)
                    with zf.open(files[name]) as src:
                        raw = src.read(4097)
                    stated = raw.decode("ascii", "replace").split() if len(raw) <= 4096 else []
                    subject_name = subject.rpartition("/")[2]
                    if (len(stated) not in (1, 2) or stated[0].lower() != h.hexdigest()
                            or (len(stated) == 2 and stated[1].removeprefix("*") != subject_name)):
                        err(f"central bundle: {shown(name)} does not match {shown(subject_name)}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def digest_of(zf, info) -> str:
    h = hashlib.sha256()
    with zf.open(info) as src:
        for chunk in iter(lambda: src.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
