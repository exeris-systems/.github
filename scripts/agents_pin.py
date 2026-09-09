#!/usr/bin/env python3
"""Which exeris-agents ref a repository is pinned to, read from its own manifest.

`docs-lint.yml` fetches the bundle to run the agent-layer checks, and the ref it fetched came from
a workflow input while the ref the repository *means* sat in `.agents/manifest.yaml` under
`imports[].ref`. Nothing bound them, so a repository could be checked by tooling from a ref it does
not pin — silently, and in the direction that matters: the checks pass, against the wrong version
of the rules.

This reads the pin so the two cannot diverge. It is deliberately small and deliberately here
rather than in the bundle: the bundle is what the answer decides to fetch, so its own resolver
(`tools/_compose.pinned_import`) is not on disk yet when the question is asked. Everything past
this point uses the bundle's resolver; this reads one key.

Output is `key=value` lines for `$GITHUB_OUTPUT`:

    ref=<the pinned ref, or the fallback>
    source=manifest|input|absent

Usage: python3 agents_pin.py [--manifest .agents/manifest.yaml] [--fallback main]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# A ref reaches `actions/checkout`. It selects among refs that already exist in a repository the
# organisation controls — a pull request cannot introduce code this way, only choose an older
# commit of trusted code — but the value is still repository content, so it is shape-checked
# before it is used rather than trusted because of where it came from.
SAFE_REF = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,119}\Z")
BUNDLE = "exeris-agents"


def pinned_ref(text: str, bundle: str = BUNDLE) -> str | None:
    """The `ref` of the first import naming `bundle`, or None.

    Scoped to the `imports:` key: a `- ref:` under any other key belongs to something else, and
    reading the first one anywhere would answer a different question than the checker does.
    Block style only, which is what `agents_bundle.py vendor` writes; a flow-style manifest falls
    back rather than guessing.
    """
    inside = False
    item: dict[str, str] = {}
    for line in text.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if not line[0].isspace():                      # a top-level key
            inside = entry.split(":", 1)[0].strip() == "imports"
            item = {}
            continue
        if not inside:
            continue
        if entry.startswith("-"):                      # a new list item
            item = {}
            entry = entry[1:].strip()
        key, sep, value = entry.partition(":")
        if sep and key.strip() in ("bundle", "ref") and value.split():
            item[key.strip()] = value.split()[0].strip("'\"")
        if item.get("bundle") == bundle and item.get("ref"):
            return item["ref"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", default=os.path.join(".agents", "manifest.yaml"))
    ap.add_argument("--fallback", default="main")
    ap.add_argument("--bundle", default=BUNDLE)
    a = ap.parse_args()

    ref, source = None, "absent"
    if os.path.isfile(a.manifest):
        try:
            with open(a.manifest, encoding="utf-8") as fh:
                ref = pinned_ref(fh.read(), a.bundle)
        except (OSError, ValueError) as exc:
            # A manifest that cannot be read is a fallback, not a failed build: this step decides
            # which tools to fetch, and refusing to fetch any would turn one unreadable file into
            # the whole agent layer going unchecked.
            print(f"agents_pin: {a.manifest} is unreadable ({type(exc).__name__}), "
                  f"falling back to '{a.fallback}'", file=sys.stderr)
            ref = None
    if ref and not SAFE_REF.match(ref):
        print(f"agents_pin: pinned ref {ref!r} is not a plain ref name; falling back to "
              f"'{a.fallback}'", file=sys.stderr)
        ref = None
    if ref:
        source = "manifest"
    elif os.path.isfile(a.manifest):
        source = "input"

    print(f"ref={ref or a.fallback}")
    print(f"source={source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
