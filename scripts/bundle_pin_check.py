#!/usr/bin/env python3
"""The bundle this repository vendored is the one its own CI fetches — ADR-087 §B.6a.

One pin, two readers. `docs-lint.yml` decides which ref to check `exeris-systems/exeris-agents`
out at by running `agents_pin.py` over `.agents/manifest.yaml`, a line parser; `agents_bundle.py`
reads the same file with PyYAML and materialises the tree under
`.agents/vendor/exeris-agents-<version>/`. Nothing held the two answers together, and they come
apart in the quiet direction: the resolver treats anything it cannot read as a plain pin as absent
and falls back to its `agents-ref` input, so the agent-layer checks would run from a version this
repository does not vendor — and pass.

So this asks the resolver, rather than re-deriving what it would say. Both files are in this
repository, which is what makes the assertion checkable at all.

Usage: bundle_pin_check.py [--root .]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import agents_pin
from _common import Report

MANIFEST = os.path.join(".agents", "manifest.yaml")
BUNDLE = agents_pin.BUNDLE
# docs-lint.yml's `agents-ref` default. Named here only to say in a finding what the fallback
# would silently fetch instead; the workflow input owns the value.
FALLBACK = "main"


def pinned(manifest: dict) -> dict | None:
    for imp in manifest.get("imports") or []:
        if isinstance(imp, dict) and imp.get("bundle") == BUNDLE:
            return imp
    return None


def main() -> int:
    import yaml

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    rep = Report("bundle_pin_check")

    path = os.path.join(a.root, MANIFEST)
    if not os.path.exists(path):
        rep.error(MANIFEST, f"this repository vendors {BUNDLE} but has no manifest to pin it in",
                  rule="bundle-pin")
        sys.exit(rep.emit())
    rep.checked += 1
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        manifest = yaml.safe_load(text) or {}
    except Exception as exc:
        rep.error(MANIFEST, f"manifest.yaml is not valid YAML ({type(exc).__name__})",
                  rule="bundle-pin")
        sys.exit(rep.emit())

    imp = pinned(manifest) or {}
    version, ref = imp.get("version"), imp.get("ref")
    if not version or not ref:
        rep.error(MANIFEST, f"no '{BUNDLE}' import with both a version and a ref — the vendored "
                            f"tree then has no ref to be compared against", rule="bundle-pin")
        sys.exit(rep.emit())

    resolved = agents_pin.pinned_ref(text)
    if resolved is None:
        rep.error(MANIFEST, f"the pin reads as ref '{ref}' but agents_pin.py finds none, so "
                            f"docs-lint.yml would fetch '{FALLBACK}' and check this repository "
                            f"with tooling it does not pin", rule="bundle-pin")
    elif resolved != ref:
        rep.error(MANIFEST, f"agents_pin.py resolves ref '{resolved}' and the import pins '{ref}' "
                            f"— the tooling that runs and the version this repository claims to be "
                            f"on are two different commits", rule="bundle-pin")
    elif not agents_pin.SAFE_REF.match(resolved):
        rep.error(MANIFEST, f"ref '{resolved}' is not a plain ref name, so agents_pin.py discards "
                            f"it and docs-lint.yml falls back to '{FALLBACK}'", rule="bundle-pin")

    tree = os.path.join(".agents", "vendor", f"{BUNDLE}-{version}")
    if not os.path.isdir(os.path.join(a.root, tree)):
        rep.error(MANIFEST, f"the import pins {BUNDLE} {version} and {tree}/ does not exist — the "
                            f"ref that resolves is not a tree anything can read", rule="bundle-pin")

    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
