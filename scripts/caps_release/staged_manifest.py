#!/usr/bin/env python3
"""Bind a directory of gated release files to a manifest, and check the binding later.

The readiness gate stages the files it verified. A later job receives them as a downloaded workflow
artifact, which the job that produced it wrote and which travels through storage. The manifest is
what makes that travel checkable: it is produced by the gating job, handed to the later jobs as a job
OUTPUT, and compared with what arrived. A file that was swapped, added or dropped on the way is a
refusal.

A manifest is text, one line per file, sorted by name: `<64 lowercase hex SHA-256>  <name>` (two
spaces, the layout of `sha256sum`). A name is a plain file name: no separator, no leading dot, not
`.` or `..`, and no control, format, separator or unassigned character.

Usage:
  staged_manifest.py create --dir DIR --output FILE [--name KEY]
  staged_manifest.py verify --dir DIR --manifest-env VAR

create  Reads DIR (a real directory, not a link), requires it to hold regular files and nothing else,
        hashes each, prints the manifest, and appends it to FILE in the `GITHUB_OUTPUT` multi-line
        format as `KEY` (default `manifest`) with a delimiter that occurs in no line. Also appends
        `KEY-digest=<SHA-256 of the manifest text>` and `KEY-id=<its first 12 hex digits>`, which
        a workflow can use in a name.
verify  Reads the manifest from the environment variable VAR (never from an argument, never from a
        file in DIR) and compares it with DIR. Refuses when:
          * DIR is not a real directory (a link, a file, absent);
          * DIR holds an entry that is not a regular file (a directory, a link, a device, a socket,
            a FIFO) or a hard-linked file;
          * DIR holds a file the manifest does not list, or the manifest lists a file DIR lacks;
          * a file's SHA-256 differs from the manifest's;
          * the manifest is empty, malformed or lists a name twice;
          * DIR holds a file named `pom.xml`, or any file whose name is not one of the closed set of
            a coordinate: `<base>.jar`, `<base>-sources.jar`, `<base>-javadoc.jar`, `<base>.pom` and
            the `.asc` of each, all eight present for every `<base>`.
        Nothing in DIR is executed, imported or interpreted; files are read as bytes.

Exit status: 0 the directory is what the manifest says; 1 any difference (one `::error::` line per
finding on stderr); 2 usage error.
Output: `ok - <n> files match the manifest` on stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
import unicodedata

LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")
CHUNK = 1 << 20


def shown(name: str) -> str:
    return "".join(c if c.isprintable() and unicodedata.category(c)[0] not in "CZ" or c == " " else
                   f"\\u{ord(c):04x}" for c in name)


def plain_name(name: str) -> bool:
    if name in (".", "..") or name.startswith(".") or "/" in name or "\\" in name or "\x00" in name:
        return False
    return not any(unicodedata.category(c)[0] in "CZ" and c != " " for c in name) and name == name.strip()


def digest(path: str) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        h = hashlib.sha256()
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                return h.hexdigest()
            h.update(block)
    finally:
        os.close(fd)


def scan(directory: str, err) -> dict[str, str] | None:
    """Name -> SHA-256 of every entry of DIRECTORY, or None after reporting why it cannot be read."""
    try:
        if os.path.islink(directory) or not os.path.isdir(directory):
            err(f"{shown(directory)} is not a directory")
            return None
        names = sorted(os.listdir(directory))
    except OSError as exc:
        err(f"{shown(directory)} cannot be read ({exc})")
        return None
    found: dict[str, str] = {}
    bad = False
    for name in names:
        path = os.path.join(directory, name)
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            err(f"{shown(name)} is not a regular file; only regular files are released")
            bad = True
        elif info.st_nlink != 1:
            err(f"{shown(name)} is a hard link; only plain files are released")
            bad = True
        elif not plain_name(name):
            err(f"{shown(name)} is not a plain file name")
            bad = True
        else:
            try:
                found[name] = digest(path)
            except OSError as exc:
                err(f"{shown(name)} cannot be read ({exc})")
                bad = True
    return None if bad else found


def closed_set(names: list[str], err) -> bool:
    """Every name is a member of the closed set of some coordinate, and every coordinate is whole."""
    ok = True
    bases = {n[:-len(".jar")] for n in names
             if n.endswith(".jar") and not n.endswith(("-sources.jar", "-javadoc.jar"))}
    expected: set[str] = set()
    for base in bases:
        for f in (f"{base}.jar", f"{base}-sources.jar", f"{base}-javadoc.jar", f"{base}.pom"):
            expected.update((f, f + ".asc"))
    for n in names:
        if n == "pom.xml":
            err("pom.xml is not part of a release: nothing a project would build from is staged")
            ok = False
        elif n not in expected:
            err(f"{shown(n)} is not part of a release: only a main jar, its -sources and -javadoc jars, "
                "the pom and their .asc signatures are released")
            ok = False
    for want in sorted(expected - set(names)):
        err(f"{shown(want)} is missing - a release holds all eight files of a coordinate")
        ok = False
    if not bases:
        err("no main jar is staged")
        ok = False
    return ok


def parse(text: str, err) -> dict[str, str] | None:
    out: dict[str, str] = {}
    if not text.strip():
        err("the manifest is empty")
        return None
    for raw in text.split("\n"):
        if raw == "":
            continue
        m = LINE.match(raw)
        if not m or not plain_name(m.group(2)):
            err(f"manifest line is malformed: {shown(raw)[:120]}")
            return None
        if m.group(2) in out:
            err(f"manifest lists {shown(m.group(2))} twice")
            return None
        out[m.group(2)] = m.group(1)
    return out


def render(found: dict[str, str]) -> str:
    return "".join(f"{h}  {n}\n" for n, h in sorted(found.items()))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="staged_manifest.py", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--dir", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--name", default="manifest")
    v = sub.add_parser("verify")
    v.add_argument("--dir", required=True)
    v.add_argument("--manifest-env", required=True)
    a = p.parse_args(argv)

    def err(msg: str) -> None:
        print(f"::error::{msg}", file=sys.stderr)

    found = scan(a.dir, err)
    if found is None:
        return 1
    if a.cmd == "create":
        if not found:
            err("nothing is staged")
            return 1
        text = render(found)
        delimiter = "MANIFEST_" + hashlib.sha256(text.encode()).hexdigest()[:16]
        with open(a.output, "a", encoding="utf-8") as out:
            out.write(f"{a.name}<<{delimiter}\n{text}{delimiter}\n")
            whole = hashlib.sha256(text.encode()).hexdigest()
            out.write(f"{a.name}-digest={whole}\n{a.name}-id={whole[:12]}\n")
        sys.stdout.write(text)
        return 0

    want = parse(os.environ.get(a.manifest_env, ""), err)
    if want is None:
        return 1
    problems = 0
    for n in sorted(set(found) | set(want)):
        if n not in want:
            err(f"{shown(n)} is not in the manifest")
            problems += 1
        elif n not in found:
            err(f"{shown(n)} is in the manifest and not in the directory")
            problems += 1
        elif found[n] != want[n]:
            err(f"{shown(n)} differs from the manifest")
            problems += 1
    if not closed_set(sorted(found), err):
        problems += 1
    if problems:
        print("::error::the staged files are not what the gate staged", file=sys.stderr)
        return 1
    print(f"ok - {len(found)} files match the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
