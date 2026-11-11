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
  * a pom that, where it names an artifactId and a version, names the ones the files are called by.

With --expect-bundle true, `<target-dir>/central-publishing/central-bundle.zip` must exist, be a
regular file, stay within the entry and size bounds, and be bound to what was built:

  * every entry name is a relative, normalised path of exactly `<group path>/<artifactId>/<version>/
    <file>` (directory entries are plain relative paths), with no `.`, `..` or empty segment, no
    backslash and no control character; a name occurs once; no entry is a symbolic link;
  * every file is named `<artifactId>-<version>.*` or `<artifactId>-<version>-*` and sits in a
    directory that holds `<artifactId>-<version>.pom`;
  * the coordinates in the bundle are exactly the coordinates built, and when a built pom names a
    groupId (its own or its parent's) the bundle's group path is that groupId; each built coordinate
    has its pom, main, sources and javadoc jar and their signatures in the bundle;
  * a bundle file that has a counterpart of the same name in `target/` is byte-identical to it;
  * each `.asc` in the bundle is a good signature of the bundle's own file, with the same key check;
  * each `.md5`, `.sha1`, `.sha256` or `.sha512` in the bundle matches the file it names.

The bundle is only listed and read in bounded streams, never extracted into the tree; the bounds are
MAX_ENTRIES entries, MAX_TOTAL_BYTES in all, and a compression ratio of at most MAX_RATIO for an entry
of MIN_RATIO_BYTES or more. All findings are reported before the gate fails; no main jar is fatal at once.

Usage: check_release_readiness.py --target-dir DIR [--expect-bundle {true,false}] [--uploaded]
                                  [--gpg PATH] [--stage DIR]

  --expect-bundle  default false
  --uploaded       the run has already uploaded: the final refusal also says to drop the deployment
  --gpg            the gpg executable (default `gpg`)
  --stage          a directory that does not exist yet; the gated files are copied into it (the bundle
                   as `central-publishing/central-bundle.zip`), so that what a later step uploads or
                   attests is the set that was gated and nothing else

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
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from xml.parsers import expat

MAX_ENTRIES = 2000
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_RATIO = 200
MIN_RATIO_BYTES = 1024 * 1024
CHECKSUMS = {".md5": "md5", ".sha1": "sha1", ".sha256": "sha256", ".sha512": "sha512"}
CLASSIFIER_SUFFIXES = ("-sources.jar", "-javadoc.jar", "-tests.jar")

# A version is a snapshot exactly when Maven's ArtifactUtils.isSnapshot says so: it ends with
# "SNAPSHOT" in any case, or it has the timestamped-snapshot form of Artifact.VERSION_FILE_PATTERN,
# `<anything>-<8 digits>.<6 digits>-<digits>`.
TIMESTAMPED = re.compile(r"(.*)-([0-9]{8}\.[0-9]{6})-([0-9]+)")


def is_snapshot(version: str) -> bool:
    return version[-8:].lower() == "snapshot" or TIMESTAMPED.fullmatch(version) is not None


def unusual(ch: str) -> bool:
    return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")


def shown(name: str) -> str:
    """A name safe to put in a `::error::` line: an unusual character is written as an escape."""
    return "".join(f"\\u{ord(c):04x}" if unusual(c) else c for c in name)


def read_pom(path: str) -> ET.Element:
    """Parse a POM. A DOCTYPE is refused before any entity is read; a POM never needs one."""
    with open(path, "rb") as fh:
        data = fh.read()

    def refuse(*_args):
        raise ET.ParseError("the document declares a DOCTYPE; a POM never needs one")

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = refuse
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


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
                                  stderr=subprocess.DEVNULL).returncode == 0
        except OSError:
            return False

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
        if is_snapshot(base):
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
                intact.append(want)
        javadoc = os.path.join(t, f"{base}-javadoc.jar")
        if f"{base}-javadoc.jar" in intact:
            try:
                with zipfile.ZipFile(javadoc) as zf:
                    if "index.html" not in zf.namelist():
                        err(f"{shown_base}-javadoc.jar holds no index.html")
            except zipfile.BadZipFile:
                err(f"{shown_base}-javadoc.jar is not a zip file")
        pom_path = os.path.join(t, f"{base}.pom")
        coordinate: tuple[str | None, str | None, str | None] = (None, None, None)
        if f"{base}.pom" in intact:
            try:
                coordinate = pom_coordinate(read_pom(pom_path))
            except (OSError, ET.ParseError) as exc:
                err(f"{shown_base}.pom cannot be read as a POM ({shown(' '.join(str(exc).split()))})")
            group, artifact, version = coordinate
            if artifact and version and f"{artifact}-{version}" != base:
                err(f"{shown_base}.pom declares {shown(artifact)}:{shown(version)}, which the files are not named after")
            if version and is_snapshot(version):
                err(f"{shown_base}.pom declares the SNAPSHOT version {shown(version)}; a release is final")
        built[base] = coordinate
        for f in intact:
            asc = os.path.join(t, f + ".asc")
            if os.path.islink(asc):
                err(f"{shown(f)}.asc is a symbolic link; only regular files are released")
            elif not regular(asc):
                err(f"{shown(f)} has no detached signature")
            elif not good_signature(asc, os.path.join(t, f)):
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
        bundle_ok = check_bundle(t, bundle_path, built, err, good_signature)

    if a.stage:
        stage(a.stage, t, sorted(f for f in allowed if regular(os.path.join(t, f))),
              bundle_path if bundle_ok else None, err)

    if findings:
        tail = "; if a deployment was uploaded, DROP it in the portal." if a.uploaded else ""
        print(f"::error::release-readiness failed{tail}", file=sys.stderr)
        return 1
    print("release-readiness: ok")
    return 0


def stage(dest: str, t: str, files: list[str], bundle: str | None, err) -> None:
    """Copy the gated files into DEST. Each is opened without following a link and must be a regular file."""
    if os.path.lexists(dest) and (os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):
        err(f"{shown(dest)} is not an empty directory; the gated files cannot be staged there")
        return
    os.makedirs(dest, mode=0o700, exist_ok=True)
    copies = [(os.path.join(t, f), os.path.join(dest, f)) for f in files]
    if bundle:
        os.makedirs(os.path.join(dest, "central-publishing"), mode=0o700, exist_ok=True)
        copies.append((bundle, os.path.join(dest, "central-publishing", "central-bundle.zip")))
    for src, dst in copies:
        try:
            fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as fin:
                if not stat.S_ISREG(os.fstat(fin.fileno()).st_mode):
                    raise OSError("not a regular file")
                with open(dst, "xb") as fout:
                    shutil.copyfileobj(fin, fout)
        except OSError as exc:
            err(f"{shown(src)} cannot be staged ({exc})")


def check_bundle(t, bundle, built, err, good_signature) -> bool:
    """Judge the Central bundle against what was built. True when it is a bounded zip that may be kept."""
    directory = os.path.dirname(bundle)
    if os.path.islink(directory) or os.path.islink(bundle) or not os.path.lexists(bundle):
        err(f"{shown(bundle)} is missing; the release profile builds it at deploy")
        return False
    if not regular(bundle):
        err(f"{shown(bundle)} is not a regular file")
        return False
    try:
        zf = zipfile.ZipFile(bundle)
    except zipfile.BadZipFile:
        err(f"{shown(bundle)} is not a zip file")
        return False
    with zf:
        infos = zf.infolist()
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
        judge_bundle(t, zf, infos, built, err, good_signature)
        return True


def judge_bundle(t, zf, infos, built, err, good_signature) -> None:
    counts: dict[str, int] = {}
    for i in infos:
        counts[i.filename] = counts.get(i.filename, 0) + 1
    for name in sorted(n for n, c in counts.items() if c > 1):
        err(f"central bundle: {shown(name)} occurs {counts[name]} times")

    files: dict[str, zipfile.ZipInfo] = {}
    stray: list[str] = []
    for i in infos:
        name = i.filename
        if name.endswith("/"):
            if valid_segments(name, True) is None:
                stray.append(name)
                err(f"central bundle: {shown(name)} is not a file of a published coordinate (an unsafe name)")
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
            if group and "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):
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

    # the bundle's files are the files that were built
    for name in sorted(files):
        filename = name.rpartition("/")[2]
        counterpart = os.path.join(t, filename)
        if name.rpartition("/")[0] in dirs and regular(counterpart):
            if digest_of(zf, files[name]) != sha256_of(counterpart):
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
                        stated = src.read(4096).decode("ascii", "replace").split()
                    if not stated or stated[0].lower() != h.hexdigest():
                        err(f"central bundle: {shown(name)} does not match {shown(subject.rpartition('/')[2])}")
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
