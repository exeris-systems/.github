#!/usr/bin/env python3
"""Refuse a SNAPSHOT in the release build.

Reads the effective POM as XML (element values only: a comment that mentions a SNAPSHOT is not a
pin) and the resolved dependency list as text. Two classes:

  hard  a -SNAPSHOT in the effective POM outside <properties> and outside a <dependency> that is
        not inside a <plugin>: the project version, a parent, a plugin, a processor path. Refused
        on every run.
  soft  a -SNAPSHOT dependency, declared or managed in the effective POM or resolved in the
        dependency list. Refused when --upload is true; on a dry run it is a warning, listed in the
        summary file, because a capability that depends on another capability's snapshot could not
        otherwise rehearse.

A property is judged where it is consumed, so it is not a class of its own.

Usage: scan_snapshots.py --effective-pom FILE --dependencies FILE --upload {true,false} [--summary FILE]

Exit status: 0 none, or soft hits on a dry run; 1 a hard hit, or a soft hit with --upload true, or
an unreadable input; 2 usage error.
Output: the hits on stdout (`effective pom: <tag> value`, `dependency: <line>`); errors and
warnings as `::error::` / `::warning::`; with --summary a Markdown section is appended on a soft hit.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def scan(effective_pom: str, dependencies: str) -> tuple[list[str], list[str]]:
    root = ET.parse(effective_pom).getroot()
    parent = {c: p for p in root.iter() for c in p}
    hard: list[str] = []
    soft: set[str] = set()
    for el in root.iter():
        if not (el.text and "-SNAPSHOT" in el.text):
            continue
        up, e = [], el
        while e in parent:
            e = parent[e]
            up.append(local(e.tag))
        if "properties" in up:
            continue
        line = f"effective pom: <{local(el.tag)}> {el.text.strip()}"
        if "dependency" in up and "plugin" not in up:
            soft.add(line)
        else:
            hard.append(line)
    with open(dependencies, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if "-SNAPSHOT" in raw:
                soft.add(f"dependency: {raw.strip()}")
    return hard, sorted(soft)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--effective-pom", required=True)
    p.add_argument("--dependencies", required=True)
    p.add_argument("--upload", required=True, choices=["true", "false"])
    p.add_argument("--summary", default="")
    a = p.parse_args(argv)
    try:
        hard, soft = scan(a.effective_pom, a.dependencies)
    except (OSError, ET.ParseError) as exc:
        print(f"::error::the SNAPSHOT scan cannot read its inputs ({exc}).", file=sys.stderr)
        return 1
    if hard:
        print("\n".join(hard))
        print("::error::SNAPSHOT pins in the release build (project version, parent, plugin or processor). "
              "Release the upstream first and pin its final version.", file=sys.stderr)
        return 1
    if soft:
        print("\n".join(soft))
        if a.upload == "true":
            print("::error::SNAPSHOT dependencies in an uploading run. Release the upstream first and "
                  "pin its final version.", file=sys.stderr)
            return 1
        print("::warning::This dry run depends on SNAPSHOTs. It rehearses the build; it could not be "
              "uploaded as it stands.")
        if a.summary:
            with open(a.summary, "a", encoding="utf-8") as fh:
                fh.write("### WARNING: SNAPSHOT dependencies\n\nA run with `upload: true` would be refused. "
                         "Dependencies:\n\n" + "".join(f"- {s}\n" for s in soft))
        return 0
    print("ok - no SNAPSHOT in the effective POM or the resolved dependencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
