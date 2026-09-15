#!/usr/bin/env python3
"""A caller's bundle pin against this repository's — ADR-087 §B.6a.

The review's verdict is validated here, against the base vendored here, while the routine that
produced it ran in the caller's checkout against the caller's pin. Those are two versions of one
contract, and the difference between them matters in one direction.

A differing MAJOR is a finding either way: nothing promises anything across one, and the failure to
catch it is a verdict validated against a shape it was never written to.

Within a MAJOR the direction decides. ADR-087 §B.6a reasons that the bundle's SemVer promises a
MINOR adds and never requires, so a differing MINOR or PATCH is not a finding — and that holds only
while the validating schema is open. This repository's composed schema closes what it composes
(`unevaluatedProperties: false` at four objects, because 2.0.0's bases close nothing), so a field a
newer MINOR added is a field this repository's copy has no name for, and an unevaluated property is
refused. A caller *behind* still validates: it emits a subset of what is named here. A caller
*ahead* does not. §B.6a does not make that distinction and is owed the amendment that does; this
script refuses the ahead case now, because the alternative is a red publication step whose message
names the wrong cause.

Both versions are named in the finding. "Incompatible pin" without them sends the reader to two
repositories to discover which way round it was.

A caller that pins no bundle is not a finding either: `docs-lint.yml`'s `agent-check: false` is
there for a repository with no `.agents/` at all, and such a repository is validated against this
one's base with nothing to compare.

Usage: caller_bundle_check.py --caller <path to a caller's .agents/manifest.yaml> [--root .]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _common import Report

MANIFEST = os.path.join(".agents", "manifest.yaml")
BUNDLE = "exeris-agents"
SEMVER = re.compile(r"\A(\d+)\.(\d+)\.(\d+)(?:[-+].*)?\Z")


def pinned_version(path: str, rep: Report) -> str | None:
    """The version this manifest pins, None when it pins none, and "" when it could not be read.

    Three outcomes, not two. A manifest that will not parse and a manifest that pins nothing are
    opposite facts — the second is explicitly not a finding — and collapsing them printed
    "pins no exeris-agents … with nothing to compare" directly under the error saying the file could
    not be read at all.
    """
    import yaml
    rel = os.path.relpath(path)
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh) or {}
    except Exception as exc:
        rep.error(rel, f"manifest.yaml is not valid YAML ({type(exc).__name__})", rule="caller-pin")
        return ""
    for imp in manifest.get("imports") or []:
        if isinstance(imp, dict) and imp.get("bundle") == BUNDLE and imp.get("version"):
            return str(imp["version"])
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--caller", action="append", required=True,
                    help="a caller's .agents/manifest.yaml; repeatable")
    a = ap.parse_args()
    rep = Report("caller_bundle_check")

    ours = pinned_version(os.path.join(a.root, MANIFEST), rep)
    if not ours:
        rep.error(MANIFEST, f"this repository composes over a vendored {BUNDLE} base but pins no "
                            f"version of it, so there is nothing to compare a caller against",
                  rule="caller-pin")
        sys.exit(rep.emit())
    mine = SEMVER.match(ours)
    if not mine:
        rep.error(MANIFEST, f"pinned version '{ours}' is not MAJOR.MINOR.PATCH, and the comparison "
                            f"is a SemVer one", rule="caller-pin")
        sys.exit(rep.emit())

    for path in a.caller:
        rel = os.path.relpath(path)
        if not os.path.exists(path):
            rep.error(rel, "caller manifest does not exist", rule="caller-pin")
            continue
        rep.checked += 1
        theirs = pinned_version(path, rep)
        if theirs == "":
            continue  # already reported, and it is not a repository that pins nothing
        if theirs is None:
            print(f"{rel}: pins no {BUNDLE} — validated against {BUNDLE} {ours} with nothing "
                  f"to compare")
            continue
        their = SEMVER.match(theirs)
        if not their:
            rep.error(rel, f"pins {BUNDLE} '{theirs}', which is not MAJOR.MINOR.PATCH — a version "
                           f"that cannot be compared with '{ours}' cannot be called compatible "
                           f"with it either", rule="caller-pin")
            continue
        if their.group(1) != mine.group(1):
            rep.error(rel, f"pins {BUNDLE} {theirs} and this repository vendored {ours}: MAJOR "
                           f"{their.group(1)} against MAJOR {mine.group(1)}. Nothing carries a "
                           f"verdict across a MAJOR, so the base it was written to is not the base "
                           f"it would be validated against", rule="caller-pin")
            continue
        if (int(their.group(2)), int(their.group(3))) > (int(mine.group(2)), int(mine.group(3))):
            rep.error(rel, f"pins {BUNDLE} {theirs} and this repository vendored {ours}: within "
                           f"MAJOR {mine.group(1)} the caller is ahead. The composed schema here "
                           f"closes what it composes, so a property {theirs} added is a property "
                           f"{ours} has no name for and the verdict is refused as unevaluated. "
                           f"Vendor {theirs} here, or pin the caller back", rule="caller-pin")
            continue
        if (their.group(2), their.group(3)) != (mine.group(2), mine.group(3)):
            print(f"{rel}: pins {BUNDLE} {theirs}, this repository vendored {ours} — same MAJOR and "
                  f"behind it, validated against {ours}")

    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
