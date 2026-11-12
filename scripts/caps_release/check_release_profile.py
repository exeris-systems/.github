#!/usr/bin/env python3
"""Refuse a ref whose release profile cannot build the files a GitHub Packages release uploads.

Maven treats `-P release` for a profile that does not exist as a warning and builds on, which
produces unsigned artifacts that fail much later with a message naming neither the profile nor the
cause. This reads the POM as XML (element values only, so a comment that mentions a profile is not
one) and refuses up front.

Refused: no profile whose <id> is `release`; a <modules> in the project or in ANY profile (a
capability release is one module: `-P release` must not build several, and the readiness gate, the
run artifact and the attestation all read the root `target/`); a release profile whose
<build><plugins> lacks `org.apache.maven.plugins:maven-gpg-plugin` (the signatures), `maven-source-plugin`
(the sources jar) or `maven-javadoc-plugin` (the javadoc jar); and a release profile that declares
`org.sonatype.central:central-publishing-maven-plugin` in <build><plugins> or <build><pluginManagement>,
because that plugin owns the `deploy` phase and uploads to a repository this workflow does not name.
A plugin elsewhere (the project's own <build>, a dependency, a property) does not count toward the
required ones. A document that declares a DOCTYPE is refused before any entity is read.

Usage: check_release_profile.py --pom pom.xml

Exit status: 0 ok; 1 refused or unreadable POM (every missing or forbidden item listed on one
`::error::` line on stderr); 2 usage error.
Output: stdout `ok - ...`.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_XML_DEPTH = 200

def read_xml(path: str) -> ET.Element:
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


PLUGIN_GROUP = "org.apache.maven.plugins"
REQUIRED = {
    "maven-gpg-plugin": "the signatures",
    "maven-source-plugin": "the sources jar",
    "maven-javadoc-plugin": "the javadoc jar",
}
FORBIDDEN_GROUP = "org.sonatype.central"
FORBIDDEN = "central-publishing-maven-plugin"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if local(c.tag) == name]


def text(el: ET.Element, name: str) -> str:
    return " ".join(c.text.strip() for c in children(el, name) if c.text)


def check(pom: str) -> list[str]:
    root = read_xml(pom)
    problems: list[str] = []
    profiles = [profile for container in children(root, "profiles") for profile in children(container, "profile")]
    release = [profile for profile in profiles if (text(profile, "id")) == "release"]
    if not release:
        problems.append("missing: the 'release' profile in pom.xml")
    if children(root, "modules") or any(children(profile, "modules") for profile in profiles):
        problems.append("missing: a single-module project (pom.xml declares <modules>, in the project or in a profile; "
                        "a capability release is one module)")
    builds = [build for profile in release for build in children(profile, "build")]
    plugins = [plugin for build in builds for container in children(build, "plugins")
               for plugin in children(container, "plugin")]
    managed = [plugin for build in builds for management in children(build, "pluginManagement")
               for container in children(management, "plugins") for plugin in children(container, "plugin")]
    if release:
        for artifact, what in REQUIRED.items():
            if not any(text(p, "groupId") in ("", PLUGIN_GROUP) and text(p, "artifactId") == artifact for p in plugins):
                problems.append(f"missing: {PLUGIN_GROUP}:{artifact} in the release profile's <build><plugins> ({what})")
    if any(text(p, "artifactId") == FORBIDDEN and text(p, "groupId") in ("", FORBIDDEN_GROUP)
           for p in plugins + managed):
        problems.append(f"forbidden: {FORBIDDEN_GROUP}:{FORBIDDEN} in the release profile; it uploads to a "
                        "repository this workflow does not name")
    return problems


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the release-profile check failed unexpectedly ({type(exc).__name__}: {' '.join(str(exc).split())}).",
              file=sys.stderr)
        return 1


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pom", required=True)
    a = p.parse_args(argv)
    try:
        problems = check(a.pom)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::{a.pom} cannot be read as a POM ({' '.join(str(exc).split())}).", file=sys.stderr)
        return 1
    if problems:
        print(f"::error::This ref cannot build a release - {'; '.join(problems)}. "
              "Release from a ref that carries the release machinery.", file=sys.stderr)
        return 1
    print("ok - this ref carries a release profile that signs and builds the sources and javadoc jars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
