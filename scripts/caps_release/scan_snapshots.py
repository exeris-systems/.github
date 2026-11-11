#!/usr/bin/env python3
"""Refuse a SNAPSHOT in the release build.

Reads the effective POM as XML (element values only: a comment that mentions a SNAPSHOT is not a
pin; a document that declares a DOCTYPE is refused before any entity is read) and the resolved
dependency list as text. A version is a snapshot exactly when Maven's ArtifactUtils.isSnapshot says
so: it ends with "SNAPSHOT" in any case, or it has the timestamped form of
Artifact.VERSION_FILE_PATTERN, `<anything>-<8 digits>.<6 digits>-<digits>`. That rule is applied to
every `<version>` of the project, a parent, a dependency, a plugin, an extension and a processor
path; any other element is judged by the literal `-SNAPSHOT`. Three classes:

  hard      a snapshot in the effective POM outside <properties> and outside a <dependency> that is
            not inside a <plugin>: the project version, a parent, a plugin, a processor path.
            Refused on every run.
  soft      a snapshot dependency, declared or managed in the effective POM or resolved in the
            dependency list. Refused when --upload is true; on a dry run it is a warning, listed in
            the summary file, because a capability that depends on another capability's snapshot
            could not otherwise rehearse.
  floating  a version that is a range (`[1.0,2.0)`, `(,1.0]`, a comma), `LATEST` or `RELEASE`,
            wherever such a version sits. What it resolves to changes without the POM changing, so
            the build is not reproducible. Refused when --upload is true; a warning on a dry run.

A property is judged where it is consumed, so it is not a class of its own.

Usage: scan_snapshots.py --effective-pom FILE --dependencies FILE --upload {true,false} [--summary FILE]

Exit status: 0 none, or soft or floating hits on a dry run; 1 a hard hit, a soft or floating hit with
--upload true, or an unreadable input; 2 usage error.
Output: the hits on stdout (`effective pom: <tag> value`, `floating version: <tag> value`,
`dependency: <line>`); errors and warnings as `::error::` / `::warning::`; with --summary a Markdown
section is appended on a soft or floating hit.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat

SNAPSHOT_TIMESTAMP = re.compile(r"(.*)-([0-9]{8}\.[0-9]{6})-([0-9]+)")
VERSION_PARENTS = {"project", "parent", "dependency", "plugin", "extension", "path"}
TOKEN = re.compile(r"[\s,\[\]()]+")
FLOATING = {"LATEST", "RELEASE"}


def is_snapshot(version: str) -> bool:
    return version[-8:].lower() == "snapshot" or SNAPSHOT_TIMESTAMP.fullmatch(version) is not None


def floating(version: str) -> bool:
    v = version.strip()
    return v in FLOATING or v[:1] in ("[", "(") or "," in v


def read_xml(path: str) -> ET.Element:
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


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def scan(effective_pom: str, dependencies: str) -> tuple[list[str], list[str], list[str]]:
    root = read_xml(effective_pom)
    parent = {c: p for p in root.iter() for c in p}
    hard: list[str] = []
    soft: set[str] = set()
    floats: set[str] = set()
    for el in root.iter():
        if not el.text:
            continue
        up, e = [], el
        while e in parent:
            e = parent[e]
            up.append(local(e.tag))
        if "properties" in up:
            continue
        is_version = local(el.tag) == "version" and up[:1] and up[0] in VERSION_PARENTS
        if is_version and floating(el.text):
            floats.add(f"floating version: <version> {el.text.strip()}")
        if "-SNAPSHOT" not in el.text and not (is_version and any(
                is_snapshot(tok) for tok in TOKEN.split(el.text) if tok)):
            continue
        line = f"effective pom: <{local(el.tag)}> {el.text.strip()}"
        if "dependency" in up and "plugin" not in up:
            soft.add(line)
        else:
            hard.append(line)
    with open(dependencies, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            # `group:artifact:type[:classifier]:version:scope`; only those fields can be a version
            fields = [f.split()[0] for f in raw.split(":")[3:] if f.split()]
            if "-SNAPSHOT" in raw or any(is_snapshot(f) for f in fields):
                soft.add(f"dependency: {raw.strip()}")
    return hard, sorted(soft), sorted(floats)


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the SNAPSHOT scan failed unexpectedly ({type(exc).__name__}: {' '.join(str(exc).split())}).",
              file=sys.stderr)
        return 1


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--effective-pom", required=True)
    p.add_argument("--dependencies", required=True)
    p.add_argument("--upload", required=True, choices=["true", "false"])
    p.add_argument("--summary", default="")
    a = p.parse_args(argv)
    try:
        hard, soft, floats = scan(a.effective_pom, a.dependencies)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::the SNAPSHOT scan cannot read its inputs ({' '.join(str(exc).split())}).", file=sys.stderr)
        return 1
    if hard:
        print("\n".join(hard))
        print("::error::SNAPSHOT pins in the release build (project version, parent, plugin or processor). "
              "Release the upstream first and pin its final version.", file=sys.stderr)
        return 1
    if soft or floats:
        print("\n".join(soft + floats))
        if a.upload == "true":
            if soft:
                print("::error::SNAPSHOT dependencies in an uploading run. Release the upstream first and "
                      "pin its final version.", file=sys.stderr)
            if floats:
                print("::error::Floating versions (a range, LATEST or RELEASE) in an uploading run: the build "
                      "would not be reproducible. Pin an exact version.", file=sys.stderr)
            return 1
        print("::warning::This dry run depends on SNAPSHOTs or floating versions. It rehearses the build; it "
              "could not be uploaded as it stands.")
        if a.summary:
            with open(a.summary, "a", encoding="utf-8") as fh:
                if soft:
                    fh.write("### WARNING: SNAPSHOT dependencies\n\nA run with `upload: true` would be refused. "
                             "Dependencies:\n\n" + "".join(f"- {s}\n" for s in soft))
                if floats:
                    fh.write("### WARNING: floating versions\n\nA run with `upload: true` would be refused. "
                             "Versions:\n\n" + "".join(f"- {s}\n" for s in floats))
        return 0
    print("ok - no SNAPSHOT in the effective POM or the resolved dependencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
