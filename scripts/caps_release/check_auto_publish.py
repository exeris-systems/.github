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

PLUGIN = "central-publishing-maven-plugin"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def contrary(effective_pom: str) -> tuple[list[str], int]:
    root = ET.parse(effective_pom).getroot()
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
    return problems, plugins


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--effective-pom", required=True)
    a = p.parse_args(argv)
    try:
        problems, plugins = contrary(a.effective_pom)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::{a.effective_pom} cannot be read ({exc}).", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"ok - {plugins} {PLUGIN} declaration(s); none sets autoPublish or waitUntil to a contrary value")
    return 0


if __name__ == "__main__":
    sys.exit(main())
