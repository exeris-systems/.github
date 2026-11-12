#!/usr/bin/env python3
"""The release-readiness gate: what a release would send is complete, signed and bound to one coordinate.

Inspects the root `target/` of a single-module build. The files it gates are exactly the files the
run artifact keeps and the attestation covers: every top-level `*.jar`, `*.pom` and `*.asc` of
`target/`. The allowed set is closed:

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
    release is always bound to one full coordinate;
  * a version that is ASCII: any other character refuses the coordinate, because Maven's case-insensitive
    SNAPSHOT test folds characters that `str.lower()` does not.

All findings are reported before the gate fails; no main jar is fatal at once.

WHAT IS STAGED IS WHAT WAS VERIFIED. Each gated file is opened once (`O_NOFOLLOW|O_NONBLOCK`, `fstat`
must say regular file), read to the end into a private directory of the gate while its SHA-256 is
computed, and every check (signature, POM, javadoc) is made on that private copy. Staging
re-hashes the live file and refuses on any difference, then copies from the private copy while hashing
again and refuses unless the digest equals the one taken when the file was read. What is staged is
byte-identical to what was verified. A run with any finding stages NOTHING, and a stage that ends before it is complete, by a finding,
an interrupt or any exception, is removed, so no directory a later step could mistake for a release exists after a refusal. Every
subprocess call is bounded by a timeout, and an expiry is a refusal.

Usage: check_release_readiness.py --target-dir DIR [--gpg PATH] [--stage DIR]

  --gpg            the gpg executable (default `gpg`)
  --stage          a directory that does not exist yet or exists and is empty (a symbolic link, a file
                   and a directory with content are refused); on a run without findings the gated
                   files are copied into it, so that what a later step uploads or attests is the set
                   that was gated and nothing else; on a run with a finding it is not created

Exit status: 0 ready; 1 any finding; 2 usage error.
Output: `coordinate: <name> - main, sources, javadoc, pom, signatures` per coordinate without a finding,
`release-readiness: ok`; findings on stderr as `::error::`.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from xml.parsers import expat

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_XML_DEPTH = 200
SUBPROCESS_TIMEOUT = 120
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


def take(src: str, scratch: str) -> tuple[str, str]:
    """Read SRC once, to the end: copy it into a private directory under SCRATCH (keeping its base name)
    while hashing the same bytes. Returns (private path, SHA-256 of what was read)."""
    h = hashlib.sha256()
    with os.fdopen(open_regular(src), "rb") as fin:
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
    p.add_argument("--gpg", default="gpg")
    p.add_argument("--stage", default="")
    a = p.parse_args(argv)
    scratch = tempfile.mkdtemp(prefix="release-verify-")
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
                err(f"{shown_base} is missing {shown(want)} - a release holds all four files")
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
                    "parent's); the release cannot be bound to a coordinate")
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

    if findings:
        print("::error::release-readiness failed", file=sys.stderr)
        return 1

    if a.stage:
        wrote = stage(a.stage, t, sorted(f for f in held if f in allowed), err, held)
        if findings:
            if wrote:
                shutil.rmtree(a.stage, ignore_errors=True)
            print("::error::release-readiness failed: the gated files could not be staged", file=sys.stderr)
            return 1
    print("release-readiness: ok")
    return 0


def stage(dest: str, t: str, files: list[str], err, held=None) -> bool:
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


if __name__ == "__main__":
    sys.exit(main())
