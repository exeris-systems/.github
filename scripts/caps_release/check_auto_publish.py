#!/usr/bin/env python3
"""Refuse a POM that configures the Central plugin to publish on its own or not to wait for validation.

A command-line `-DautoPublish=false` does NOT override a value the POM configures explicitly:
Maven applies a user property only to a parameter the POM leaves unset. Central's own default is
`autoPublish=false`, so what must be refused is an explicit contrary value in the POM. This reads
the EFFECTIVE POM (profiles applied, parents merged, properties interpolated) and, for every
`central-publishing-maven-plugin` <plugin> in it, looks at every <autoPublish> and <waitUntil>
element at any depth (plugin configuration and each execution's):

  <autoPublish>  must be exactly `false`; anything else, including an unresolved expression, is refused.
  <waitUntil>    must be `validated`, compared case-insensitively; `uploaded` would not wait for
                 validation and `published` would wait for a publication that never happens.

The same two values are required of a `<properties>` entry named `autoPublish` or `waitUntil`
anywhere in the document: the plugin reads them as user properties, and a command-line
`-DautoPublish=false` does not override a value the POM configures explicitly. A document that
declares a DOCTYPE is refused before any entity is read.

An absent element is accepted: the plugin's default is `false` / `VALIDATED`, and the workflow
also passes both on the command line, which decides a parameter the POM leaves unset.
A POM without the plugin passes: nothing is published through it.

Usage: check_auto_publish.py --effective-pom FILE

Exit status: 0 ok; 1 a contrary value, or an unreadable file; 2 usage error.
Output: stdout `ok - ...`; each contrary value on stderr as `::error::`.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_XML_DEPTH = 200

PLUGIN = "central-publishing-maven-plugin"


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


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def contrary(effective_pom: str) -> tuple[list[str], int]:
    root = read_xml(effective_pom)
    problems: list[str] = []
    plugins = 0
    for plugin in root.iter():
        if local(plugin.tag) != "plugin":
            continue
        if not any(local(c.tag) == "artifactId" and (c.text or "").strip() == PLUGIN for c in plugin):
            continue
        plugins += 1
        for el in plugin.iter():
            value = (el.text or "").strip()
            if local(el.tag) == "autoPublish" and value != "false":
                problems.append(f"<autoPublish>{value}</autoPublish> in the {PLUGIN} configuration; it must be false")
            if local(el.tag) == "waitUntil" and value.lower() != "validated":
                problems.append(f"<waitUntil>{value}</waitUntil> in the {PLUGIN} configuration; it must be validated")
    # The plugin reads the user properties `autoPublish` and `waitUntil` for a parameter its
    # configuration leaves unset, and a POM <properties> entry of that name sets them. They are
    # held to the same values, so the guard does not depend on what the command line passes.
    for properties in root.iter():
        if local(properties.tag) != "properties":
            continue
        for el in properties:
            value = (el.text or "").strip()
            if local(el.tag) == "autoPublish" and value != "false":
                problems.append(f"<properties><autoPublish>{value}</autoPublish> in the POM; it must be false")
            if local(el.tag) == "waitUntil" and value.lower() != "validated":
                problems.append(f"<properties><waitUntil>{value}</waitUntil> in the POM; it must be validated")
    return problems, plugins


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the auto-publish guard failed unexpectedly ({type(exc).__name__}: {' '.join(str(exc).split())}).",
              file=sys.stderr)
        return 1


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--effective-pom", required=True)
    a = p.parse_args(argv)
    try:
        problems, plugins = contrary(a.effective_pom)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::{a.effective_pom} cannot be read ({' '.join(str(exc).split())}).", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"ok - {plugins} {PLUGIN} declaration(s); none sets autoPublish or waitUntil to a contrary value")
    return 0


if __name__ == "__main__":
    sys.exit(main())
