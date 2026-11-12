#!/usr/bin/env python3
"""Bind a directory of gated release files to a manifest, and check the binding later.

The readiness gate stages the files it verified. A later job receives them as a downloaded workflow
artifact, which the job that produced it wrote and which travels through storage. The manifest is
what makes that travel checkable: it is produced by the gating job, handed to the later jobs as a job
OUTPUT, and compared with what arrived. A file that was swapped, added or dropped on the way is a
refusal.

A manifest is text, one line per file, sorted by name: `<64 lowercase hex SHA-256>  <name>` (two
spaces, the layout of `sha256sum`), each line ended by a newline; the text may omit the last one.
A blank line anywhere, including after the final newline, is malformed. A name is a plain file
name: no separator, no leading dot, not `.` or `..`, and no control, format, separator or
unassigned character.

WHAT A RELEASABLE BASE NAME IS. The name of a coordinate's files is `<base>` plus a suffix, and the
upload step splices `<base>` into a comma separated argument list that runs in the job holding the
package credential. A base is therefore closed: `<artifactId>-<version>` where
  * the artifactId is made of `[A-Za-z0-9_.-]`, the character set Maven's model validation accepts
    for an artifactId, and starts with a letter, a digit or `_` (never `-` or `.`);
  * the version is ASCII MAJOR.MINOR.PATCH, each number `0` or without a leading zero and of at
    most 9 digits, the form `resolve_release.py` accepts (so never a SNAPSHOT of either shape);
  * the whole base is at most 200 characters.
Nothing else is a base: not a comma, a quote, a space, `$`, a backtick, `;`, a non-ASCII character.
`check_release_readiness.py` states the same rule in the same words and enforces it at the source of
the build. The two scripts cannot share a module: each runs under `python3 -I`, which puts no
directory on the import path, and the suite requires every module of this directory to carry its
own mutants; the rule is therefore written in both, and
`tests/caps_release/test_manifest_gate_agreement.py` proves that they agree. Two names that
are equal after Unicode normalisation (NFKC) and case folding are refused as a collision, because
a case-insensitive extraction would let one overwrite the other.

Usage:
  staged_manifest.py create --dir DIR --output FILE [--name KEY]
  staged_manifest.py verify --dir DIR --manifest-env VAR

create  Reads DIR (a real directory, not a link), requires it to hold regular files and nothing else,
        hashes each, prints the manifest, and appends it to FILE in the `GITHUB_OUTPUT` multi-line
        format as `KEY` (default `manifest`) with a delimiter that occurs in no line. Also appends
        `KEY-digest=<SHA-256 of the manifest text>` and `KEY-id=<its first 12 hex digits>`, which
        a workflow can use in a name. KEY matches `[A-Za-z][A-Za-z0-9_-]*` (anything else is a usage
        error). Every main jar of DIR must have a releasable base name (above), so no manifest binds a
        name the upload step could not safely splice; whether the set is whole is `verify`'s and the
        gate's judgement. An output file that cannot be written is a refusal.
verify  Reads the manifest from the environment variable VAR (never from an argument, never from a
        file in DIR) and compares it with DIR. Refuses when:
          * DIR is not a real directory (a link, a file, absent); a trailing separator or `.`
            component is not looked through: `link/` is judged as `link`, textually, and never resolved;
          * DIR holds an entry that is not a regular file (a directory, a link, a device, a socket,
            a FIFO) or a hard-linked file;
          * DIR holds a file the manifest does not list, or the manifest lists a file DIR lacks;
          * a file's SHA-256 differs from the manifest's;
          * the manifest is empty, malformed or lists a name twice;
          * DIR holds a file named `pom.xml`, or any file whose name is not one of the closed set of
            a coordinate: `<base>.jar`, `<base>-sources.jar`, `<base>-javadoc.jar`, `<base>.pom` and
            the `.asc` of each, all eight present for every `<base>`, with `<base>` a releasable
            base name (above); a `-tests.jar` is a classifier, never a main jar;
          * two names collide under case folding or Unicode normalisation.
        Nothing in DIR is executed, imported or interpreted; files are read as bytes.

Exit status: 0 the directory is what the manifest says; 1 any difference or any unexpected failure (one
`::error::` line per finding on stderr; every refusal of `verify` ends with the line
`the staged files are not what the gate staged`); 2 usage error.
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
FINAL = "the staged files are not what the gate staged"
CLASSIFIER_SUFFIXES = ("-sources.jar", "-javadoc.jar", "-tests.jar")
NUMBER = r"(?:0|[1-9][0-9]{0,8})"
MAX_BASE = 200
BASE = re.compile(rf"[A-Za-z0-9_][A-Za-z0-9_.-]*-{NUMBER}\.{NUMBER}\.{NUMBER}")
KEY = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def releasable_base(base: str) -> bool:
    """`<artifactId>-<version>`: artifactId in `[A-Za-z0-9_.-]` not starting with `-` or `.`, version
    ASCII MAJOR.MINOR.PATCH, at most MAX_BASE characters. The rule is stated in the module docstring."""
    return len(base) <= MAX_BASE and BASE.fullmatch(base) is not None


def literal(path: str) -> str:
    """PATH without trailing separators and trailing `.` components, computed on the text alone, so that
    a link named with a trailing slash is judged as the link and not as its target. Nothing is resolved."""
    while True:
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/") or "/"
        elif path.endswith("/."):
            path = path[:-2] or "/"
        else:
            return path


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
    directory = literal(directory)
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
        try:
            info = os.lstat(path)
        except OSError as exc:
            err(f"{shown(name)} cannot be read ({shown(' '.join(str(exc).split()))})")
            bad = True
            continue
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


def main_bases(names: list[str]) -> set[str]:
    """The bases of the main jars among NAMES: a `*.jar` that is not a -sources, -javadoc or -tests jar."""
    return {n[:-len(".jar")] for n in names if n.endswith(".jar") and not n.endswith(CLASSIFIER_SUFFIXES)}


def bases_releasable(names: list[str], err) -> bool:
    """Every base of NAMES is a releasable base name (the rule of the module docstring)."""
    ok = True
    for base in sorted(main_bases(names)):
        if not releasable_base(base):
            err(f"{shown(base)} is not a releasable coordinate name: it is <artifactId>-<MAJOR.MINOR.PATCH>, the "
                f"artifactId of [A-Za-z0-9_.-] not starting with '-' or '.', at most {MAX_BASE} characters")
            ok = False
    return ok


def closed_set(names: list[str], err) -> bool:
    """Every name is a member of the closed set of some coordinate, every coordinate is whole and has a
    releasable base name, and no two names collide under normalisation or case folding."""
    ok = bases_releasable(names, err)
    bases = main_bases(names)
    expected: set[str] = set()
    for base in sorted(bases):
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
    folded: dict[str, str] = {}
    for n in names:
        key = unicodedata.normalize("NFKC", n).casefold()
        if key in folded and folded[key] != n:
            err(f"{shown(n)} and {shown(folded[key])} are the same name under case folding or Unicode normalisation")
            ok = False
        folded.setdefault(key, n)
    return ok


def parse(text: str, err) -> dict[str, str] | None:
    out: dict[str, str] = {}
    if not text.strip():
        err("the manifest is empty")
        return None
    if text.endswith("\n"):
        text = text[:-1]
    for raw in text.split("\n"):
        if raw == "":
            err("manifest line is malformed: a blank line")
            return None
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


def key_name(value: str) -> str:
    if not KEY.fullmatch(value):
        raise argparse.ArgumentTypeError("must match [A-Za-z][A-Za-z0-9_-]*")
    return value


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the staged-files check failed unexpectedly ({type(exc).__name__}: "
              f"{shown(' '.join(str(exc).split()))}).", file=sys.stderr)
        return 1


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(prog="staged_manifest.py", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--dir", required=True)
    c.add_argument("--output", required=True)
    c.add_argument("--name", default="manifest", type=key_name)
    v = sub.add_parser("verify")
    v.add_argument("--dir", required=True)
    v.add_argument("--manifest-env", required=True)
    a = p.parse_args(argv)

    def err(msg: str) -> None:
        print(f"::error::{msg}", file=sys.stderr)

    def refuse() -> int:
        err(FINAL)
        return 1

    found = scan(a.dir, err)
    if a.cmd == "create":
        if found is None:
            return 1
        if not found:
            err("nothing is staged")
            return 1
        if not bases_releasable(sorted(found), err):
            return 1
        text = render(found)
        delimiter = "MANIFEST_" + hashlib.sha256(text.encode()).hexdigest()[:16]
        whole = hashlib.sha256(text.encode()).hexdigest()
        try:
            with open(a.output, "a", encoding="utf-8") as out:
                out.write(f"{a.name}<<{delimiter}\n{text}{delimiter}\n")
                out.write(f"{a.name}-digest={whole}\n{a.name}-id={whole[:12]}\n")
        except OSError as exc:
            err(f"{shown(a.output)} cannot be written ({shown(' '.join(str(exc).split()))})")
            return 1
        sys.stdout.write(text)
        return 0

    if found is None:
        return refuse()
    want = parse(os.environ.get(a.manifest_env, ""), err)
    if want is None:
        return refuse()
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
        return refuse()
    print(f"ok - {len(found)} files match the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
