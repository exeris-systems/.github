#!/usr/bin/env python3
"""On a tag, the POM at the tagged commit must already say the tagged version.

A tag whose version disagrees with the POM it points at is a tag on the wrong commit, and
`versions:set` would overwrite the evidence, so a tag run checks instead of setting.

Usage: check_pom_version.py --pom pom.xml --want MAJOR.MINOR.PATCH

Exit status: 0 the project's own <version> equals --want; 1 it differs, is absent (an inherited
version is not the project's own), or the POM is unreadable (a DOCTYPE declaration makes it unreadable); 2 usage error.
Output: stdout `pom version <v> matches the tag`; the refusal on stderr as `::error::`.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat

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


def pom_version(pom: str) -> str | None:
    for el in read_xml(pom):
        if el.tag.rsplit("}", 1)[-1] == "version":
            return (el.text or "").strip()
    return None


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the POM version check failed unexpectedly ({type(exc).__name__}: {' '.join(str(exc).split())}).",
              file=sys.stderr)
        return 1


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pom", required=True)
    p.add_argument("--want", required=True)
    a = p.parse_args(argv)
    try:
        have = pom_version(a.pom)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::{a.pom} cannot be read as a POM ({' '.join(str(exc).split())}).", file=sys.stderr)
        return 1
    if have != a.want:
        print(f"::error::tag says {a.want}, the pom at this commit says {have if have is not None else '(no <version>)'} "
              "- the tag is on the wrong commit.", file=sys.stderr)
        return 1
    print(f"pom version {have} matches the tag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
