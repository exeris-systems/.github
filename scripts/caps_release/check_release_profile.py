#!/usr/bin/env python3
"""Refuse a ref that cannot build a release, and say whether a Central bundle is built.

Maven treats `-P release` for a profile that does not exist as a warning and builds on, which
produces unsigned artifacts that fail much later with a message naming neither the profile nor the
cause. This reads the POM as XML (element values only, so a comment that mentions a profile is not
one) and refuses up front.

Refused: no profile whose <id> is `release`; a <modules> in the project or in ANY profile (a
capability release is one module: `-P release` must not build several, and the readiness gate, the
run artifact and the attestation all read the root `target/`); and, for target `central`, no
`org.sonatype.central:central-publishing-maven-plugin` <plugin> under the release profile's
<build><plugins> whose <configuration> sets <publishingServerId> to `central`. A plugin elsewhere
(the project's own <build>, <pluginManagement>, a dependency, a property) does not count. A document
that declares a DOCTYPE is refused before any entity is read.

Usage: check_release_profile.py --pom pom.xml --target {none,central,github-packages} [--output FILE]

Exit status: 0 ok; 1 refused or unreadable POM (every missing item listed on one `::error::` line
on stderr); 2 usage error.
Output: stdout `ok - ...`. With --output, `has_central_plugin=<true|false>` is appended, on success only.
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


CENTRAL_GROUP = "org.sonatype.central"
CENTRAL_PLUGIN = "central-publishing-maven-plugin"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if local(c.tag) == name]


def text(el: ET.Element, name: str) -> str:
    return " ".join(c.text.strip() for c in children(el, name) if c.text)


def check(pom: str, target: str) -> tuple[list[str], bool]:
    root = read_xml(pom)
    missing: list[str] = []
    profiles = [profile for container in children(root, "profiles") for profile in children(container, "profile")]
    release = [profile for profile in profiles if (text(profile, "id")) == "release"]
    if not release:
        missing.append("the 'release' profile in pom.xml")
    if children(root, "modules") or any(children(profile, "modules") for profile in profiles):
        missing.append("a single-module project (pom.xml declares <modules>, in the project or in a profile; "
                       "a capability release is one module)")
    # the plugin is the <plugin> of the release profile's <build><plugins> with this groupId and artifactId
    plugins = [plugin for profile in release for build in children(profile, "build")
               for container in children(build, "plugins") for plugin in children(container, "plugin")
               if text(plugin, "groupId") == CENTRAL_GROUP and text(plugin, "artifactId") == CENTRAL_PLUGIN]
    central = bool(plugins)
    if target == "central":
        if not central:
            missing.append(f"{CENTRAL_GROUP}:{CENTRAL_PLUGIN} in the release profile's <build><plugins>")
        if not any(text(configuration, "publishingServerId") == "central"
                   for plugin in plugins for configuration in children(plugin, "configuration")):
            missing.append("<publishingServerId>central</publishingServerId> in that plugin's <configuration>")
    return missing, central


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
    p.add_argument("--target", required=True, choices=["none", "central", "github-packages"])
    p.add_argument("--output", default="")
    a = p.parse_args(argv)
    try:
        missing, central = check(a.pom, a.target)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::{a.pom} cannot be read as a POM ({' '.join(str(exc).split())}).", file=sys.stderr)
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
