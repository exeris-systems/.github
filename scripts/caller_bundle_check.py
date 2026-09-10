#!/usr/bin/env python3
"""A caller's bundle pin against this repository's — ADR-087 §B.6a.

The review's verdict is validated here, against the base vendored here, while the routine that
produced it ran in the caller's checkout against the caller's pin. Those are two versions of one
contract, and only one difference between them matters: the bundle's SemVer promises that a MINOR
adds and never requires, so a verdict written against 1.5.0 still satisfies 1.4.0's base and a
differing MINOR or PATCH is not a finding. A differing MAJOR is, because nothing promises anything
across one — and the failure to catch it is a verdict validated against a shape it was never
written to.

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
    """The version this manifest pins for the bundle, or None when it pins none."""
    import yaml
    rel = os.path.relpath(path)
    try:
        manifest = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception as exc:
        rep.error(rel, f"manifest.yaml is not valid YAML ({type(exc).__name__})", rule="caller-pin")
        return None
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
        if (their.group(2), their.group(3)) != (mine.group(2), mine.group(3)):
            print(f"{rel}: pins {BUNDLE} {theirs}, this repository vendored {ours} — same MAJOR, "
                  f"validated against {ours}")

    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
