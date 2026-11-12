"""Shared fixtures of the readiness-gate tests: a target/ directory, a gpg double, and a real bundle.

The gpg double accepts a detached signature only when it is `SIG:<sha256 of the file>`, so a signature
made for one file never verifies another and the gate's pairing of file and signature is observable
without a keyring. `Fixture.real_coordinate` and `Fixture.bundle_entries` build a bundle that is bound
to what was built: the same bytes as `target/`, signatures by that rule, all four correct checksum files of each of the
eight files and the group path of the POM.
"""
from __future__ import annotations

import hashlib
import os
import zipfile

import caps_release_helpers as h

FAKE_GPG = """#!/bin/sh
if [ -n "$FAKE_GPG_LOG" ]; then printf '%s\\t%s\\t%s\\t%s\\n' "$1" "$2" "$3" "$(sha256sum "$3" | cut -d' ' -f1)" >> "$FAKE_GPG_LOG"; fi
[ $# -eq 3 ] && [ "$1" = "--verify" ] || exit 2
want="SIG:$(sha256sum "$3" | cut -d' ' -f1)"
[ "$(cat "$2")" = "$want" ]
"""

SUFFIXES = (".jar", "-sources.jar", "-javadoc.jar", ".pom")
GROUP = "eu.exeris.caps"
CHECKSUM_ALGORITHMS = ((".md5", "md5"), (".sha1", "sha1"), (".sha256", "sha256"), (".sha512", "sha512"))


def sig_of(path):
    with open(path, "rb") as fh:
        return "SIG:" + hashlib.sha256(fh.read()).hexdigest() + "\n"


def sig_bytes(data: bytes) -> bytes:
    return ("SIG:" + hashlib.sha256(data).hexdigest() + "\n").encode()


def make_zip(path, names, payload=b"x"):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, payload)


def write_zip(path, items, compression=zipfile.ZIP_DEFLATED):
    """items: (name, data) or (name, data, external_attr). A ZipInfo is built by hand so any name is written as given."""
    import warnings
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w", compression) as z:
            for item in items:
                name, data = item[0], item[1]
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = compression
                if len(item) > 2:
                    info.external_attr = item[2]
                z.writestr(info, data)


def pom_xml(group=GROUP, artifact="a", version="1.0.0", parent_group=None, extra=""):
    parent = f"<parent><groupId>{parent_group}</groupId><artifactId>p</artifactId><version>{version}</version></parent>" \
        if parent_group else ""
    g = f"<groupId>{group}</groupId>" if group else ""
    return f"<project>{parent}{g}<artifactId>{artifact}</artifactId><version>{version}</version>{extra}</project>"


def default_pom(base):
    """A POM that names the coordinate a file base name `<artifactId>-<version>` stands for, so the gate can bind
    it; a base that is not of that shape gets a POM that yields no coordinate."""
    artifact, sep, version = base.rpartition("-")
    if base.count("-") >= 1 and version[:1].isdigit() and artifact:
        return pom_xml(GROUP, artifact, version)
    return f"<project>{base}</project>"


class Fixture(h.Case):
    """A target/ directory and a gpg double that accepts a signature only of the file it is handed."""

    def setUp(self):
        super().setUp()
        self.target = self.path("target")
        os.makedirs(self.target)
        self.gpg = self.write("fake-gpg", FAKE_GPG)
        os.chmod(self.gpg, 0o755)
        self.log = self.path("gpg.log")

    def use_py_gpg(self):
        """Replace the gpg double by one that logs its argument vector as JSON, so a name with a newline or a leading dash
        can be seen intact; returns the log path."""
        import sys
        with open(self.gpg, "w") as fh:
            fh.write(PY_GPG.format(python=sys.executable))
        os.chmod(self.gpg, 0o755)
        return self.log

    def gpg_calls(self):
        import json
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [json.loads(ln) for ln in fh]

    def coordinate(self, base="a-1.0.0", sign=True, skip=(), javadoc_names=("index.html", "a/B.html"), pom_text=None):
        t = self.target
        make_zip(os.path.join(t, f"{base}.jar"), ["a/B.class"])
        make_zip(os.path.join(t, f"{base}-sources.jar"), ["a/B.java"])
        make_zip(os.path.join(t, f"{base}-javadoc.jar"), list(javadoc_names))
        with open(os.path.join(t, f"{base}.pom"), "w") as fh:
            fh.write(pom_text if pom_text is not None else default_pom(base))
        for suffix in SUFFIXES:
            f = os.path.join(t, base + suffix)
            if suffix in skip:
                os.remove(f)
            elif sign:
                with open(f + ".asc", "w") as fh:
                    fh.write(sig_of(f))
        return base

    def real_coordinate(self, group=GROUP, artifact="a", version="1.0.0", **kw):
        """A coordinate whose POM names its group, artifactId and version."""
        return self.coordinate(f"{artifact}-{version}", pom_text=pom_xml(group, artifact, version), **kw)

    def bundle(self, names, payload=b"x"):
        os.makedirs(os.path.join(self.target, "central-publishing"), exist_ok=True)
        make_zip(os.path.join(self.target, "central-publishing", "central-bundle.zip"), names, payload)

    @property
    def bundle_path(self):
        return os.path.join(self.target, "central-publishing", "central-bundle.zip")

    def read_target(self, name) -> bytes:
        with open(os.path.join(self.target, name), "rb") as fh:
            return fh.read()

    def bundle_entries(self, coords=(("a", "1.0.0"),), group=GROUP, checksums=True) -> dict:
        """name -> bytes of a correct bundle for the coordinates built: target/ bytes, their signatures, checksums."""
        entries = {}
        for artifact, version in coords:
            base = f"{artifact}-{version}"
            d = f"{group.replace('.', '/')}/{artifact}/{version}"
            for suffix in SUFFIXES:
                data = self.read_target(base + suffix)
                signature = self.read_target(base + suffix + ".asc")
                for name, content in ((f"{d}/{base}{suffix}", data), (f"{d}/{base}{suffix}.asc", signature)):
                    entries[name] = content
                    if checksums:
                        for ext, algo in CHECKSUM_ALGORITHMS:
                            entries[name + ext] = hashlib.new(algo, content).hexdigest().encode()
        return entries

    def write_bundle(self, entries, compression=zipfile.ZIP_DEFLATED):
        os.makedirs(os.path.dirname(self.bundle_path), exist_ok=True)
        write_zip(self.bundle_path, list(entries.items()), compression)

    @staticmethod
    def good_bundle(g="eu/exeris/caps", a="a", v="1.0.0"):
        """Names only, with placeholder payloads: enough for the tests of what a bundle may contain."""
        d = f"{g}/{a}/{v}/{a}-{v}"
        return [f"{d}.pom", f"{d}.jar", f"{d}-sources.jar", f"{d}-javadoc.jar", f"{d}.pom.asc", f"{d}.jar.asc",
                f"{d}.jar.md5", f"{d}.jar.sha1", f"{d}-sources.jar.asc", f"{d}-javadoc.jar.asc", f"{d}.module"]

    def check(self, *extra):
        return self.both("check_release_readiness", ["--target-dir", self.target, "--gpg", self.gpg, *extra])

    def check_bundle(self, entries=None, **kw):
        self.write_bundle(self.bundle_entries(**kw) if entries is None else entries)
        return self.check("--expect-bundle", "true")

    def tree(self):
        """Every path under the temporary root, for a 'nothing was written' comparison."""
        out = set()
        for root, dirs, files in os.walk(self.tmp):
            out.update(os.path.join(root, n) for n in dirs + files)
        return out


def raw_zip(path, entries):
    """Write a zip by hand, so that headers can disagree with the data and with each other.

    Each entry is a dict: `name` (str), `data` (the bytes as stored, already compressed when `method` is 8),
    `method` (0 or 8), `crc`, `usize`, `csize` (default to the truth for a stored entry), `local_name`
    (the name in the local header, default `name`) and `attr` (the external attributes).
    """
    import struct
    import zlib
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body, central = bytearray(), bytearray()
    for e in entries:
        name = e["name"].encode("utf-8", "surrogateescape")
        local_name = e.get("local_name", e["name"]).encode("utf-8", "surrogateescape")
        data = e["data"]
        method = e.get("method", 0)
        crc = e.get("crc", zlib.crc32(data) & 0xFFFFFFFF if method == 0 else 0)
        usize = e.get("usize", len(data))
        csize = e.get("csize", len(data))
        offset = len(body)
        body += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, method, 0, 0x21, crc, csize, usize, len(local_name), 0)
        body += local_name + data
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 0x031E, 20, 0, method, 0, 0x21, crc, csize, usize,
                               len(name), 0, 0, 0, 0, e.get("attr", 0o100644 << 16), offset)
        central += name
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), len(central), len(body), 0)
    with open(path, "wb") as fh:
        fh.write(bytes(body) + bytes(central) + end)


def deflate_zeros(total: int, level: int = 1) -> bytes:
    """A raw deflate stream that inflates to `total` zero bytes, built without holding them in memory."""
    import zlib
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    chunk, out, left = b"\0" * (1 << 20), [], total
    while left > 0:
        n = min(left, len(chunk))
        out.append(c.compress(chunk[:n]))
        left -= n
    out.append(c.flush())
    return b"".join(out)


PY_GPG = """#!{python}
import hashlib, json, os, stat, sys, time
args = sys.argv[1:]
log = os.environ.get("PYGPG_LOG")
sleep = os.environ.get("PYGPG_SLEEP")


def mode(path):
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return None


if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({{"argv": args, "dir_modes": [mode(os.path.dirname(a)) for a in args[1:]],
                             "scratch_modes": [mode(os.path.dirname(os.path.dirname(a))) for a in args[1:]]}}) + "\\n")
if sleep:
    time.sleep(float(sleep))
if len(args) != 3 or args[0] != "--verify":
    sys.exit(2)
with open(args[2], "rb") as fh:
    want = "SIG:" + hashlib.sha256(fh.read()).hexdigest()
with open(args[1], "r") as fh:
    sys.exit(0 if fh.read().strip() == want else 1)
"""
