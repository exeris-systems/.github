#!/usr/bin/env python3
"""On a tag, the POM at the tagged commit must already say the tagged version.

A tag whose version disagrees with the POM it points at is a tag on the wrong commit, and
`versions:set` would overwrite the evidence, so a tag run checks instead of setting.

Usage: check_pom_version.py --pom pom.xml --want MAJOR.MINOR.PATCH

Exit status: 0 the project's own <version> equals --want; 1 it differs, is absent (an inherited
version is not the project's own), or the POM is unreadable; 2 usage error.
Output: stdout `pom version <v> matches the tag`; the refusal on stderr as `::error::`.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET


def pom_version(pom: str) -> str | None:
    for el in ET.parse(pom).getroot():
        if el.tag.rsplit("}", 1)[-1] == "version":
            return (el.text or "").strip()
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pom", required=True)
    p.add_argument("--want", required=True)
    a = p.parse_args(argv)
    try:
        have = pom_version(a.pom)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::{a.pom} cannot be read as a POM ({exc}).", file=sys.stderr)
        return 1
    if have != a.want:
        print(f"::error::tag says {a.want}, the pom at this commit says {have if have is not None else '(no <version>)'} "
              "- the tag is on the wrong commit.", file=sys.stderr)
        return 1
    print(f"pom version {have} matches the tag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
