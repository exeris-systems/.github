#!/usr/bin/env python3
"""Refuse a ref that cannot build a release, and say whether a Central bundle is built.

Maven treats `-P release` for a profile that does not exist as a warning and builds on, which
produces unsigned artifacts that fail much later with a message naming neither the profile nor the
cause. This reads the POM as XML (element values only, so a comment that mentions a profile is not
one) and refuses up front.

Refused: no profile whose <id> is `release`; a root <modules> (a capability release is one module:
the readiness gate, the run artifact and the attestation all read the root `target/`); and, for
target `central`, no `central-publishing-maven-plugin` <artifactId> or no <publishingServerId> of
`central`.

Usage: check_release_profile.py --pom pom.xml --target {none,central,github-packages} [--output FILE]

Exit status: 0 ok; 1 refused or unreadable POM (every missing item listed on one `::error::` line
on stderr); 2 usage error.
Output: stdout `ok - ...`. With --output, `has_central_plugin=<true|false>` is appended, on success only.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def check(pom: str, target: str) -> tuple[list[str], bool]:
    root = ET.parse(pom).getroot()
    missing: list[str] = []
    ids = [(c.text or "").strip()
           for profiles in root if local(profiles.tag) == "profiles"
           for profile in profiles if local(profile.tag) == "profile"
           for c in profile if local(c.tag) == "id"]
    if "release" not in ids:
        missing.append("the 'release' profile in pom.xml")
    if any(local(c.tag) == "modules" for c in root):
        missing.append("a single-module project (pom.xml declares <modules>; a capability release is one module)")
    values = {}
    for el in root.iter():
        values.setdefault(local(el.tag), []).append((el.text or "").strip())
    central = "central-publishing-maven-plugin" in values.get("artifactId", [])
    if target == "central":
        if not central:
            missing.append("central-publishing-maven-plugin in the release profile")
        if "central" not in values.get("publishingServerId", []):
            missing.append("<publishingServerId>central</publishingServerId>")
    return missing, central


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pom", required=True)
    p.add_argument("--target", required=True, choices=["none", "central", "github-packages"])
    p.add_argument("--output", default="")
    a = p.parse_args(argv)
    try:
        missing, central = check(a.pom, a.target)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::{a.pom} cannot be read as a POM ({exc}).", file=sys.stderr)
        return 1
    if missing:
        print(f"::error::This ref cannot build a release - missing: {'; '.join(missing)}. "
              "Release from a ref that carries the release machinery.", file=sys.stderr)
        return 1
    if a.output:
        with open(a.output, "a", encoding="utf-8") as fh:
            fh.write(f"has_central_plugin={'true' if central else 'false'}\n")
    print(f"ok - this ref carries the release profile (Central plugin: {'true' if central else 'false'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
