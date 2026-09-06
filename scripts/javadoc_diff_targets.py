#!/usr/bin/env python3
"""Changed-file targets for the diff half of the Javadoc gate — javadoc-conventions.md rule 11.

Rule 11 makes rules 2-9 apply to *changed files* on Kernel Core, Community and tooling: no backfill
mandate, but a file a pull request touches has to comply. That is a different question from the one
the whole-module gate answers, and it needs a different input — not "is this module clean" but "is
every file this pull request touched clean".

This turns a base..head range into the two forms the two halves of the gate consume, per module:

  <out>/<n>.module    the module's path, as `-pl` wants it
  <out>/<n>.files     one absolute path per line — javadoc reads it as `@argfile`, so no shell
                      word-splitting stands between the file list and the tool
  <out>/<n>.includes  the same files relative to the module's source root, comma-joined, which is
                      the form `-Dcheckstyle.includes` takes (measured: 266 files/646 findings on
                      exeris-kernel-spi narrows to 1/1 with a single include)

A module with no changed Java file gets no group at all, so the gate stays silent on modules the
pull request did not touch rather than reporting them green.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def changed_files(base: str, head: str) -> list[str]:
    """Paths added or modified between the merge base and head.

    Three-dot: the comparison is against the merge base, so commits that landed on the base branch
    after this one forked are not this pull request's changed files. `--diff-filter=d` (lower case
    excludes) drops deletions — a file that is gone cannot be linted, and asking javadoc to read it
    is an error about the gate rather than about the code.
    """
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", f"{base}...{head}"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", required=True, help="comma-separated Maven module paths")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--source-root", default="src/main/java")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    modules = [m.strip() for m in a.modules.split(",") if m.strip()]
    changed = changed_files(a.base, a.head)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    total = 0
    for n, module in enumerate(modules):
        root = f"{module.rstrip('/')}/{a.source_root.strip('/')}/"
        hits = sorted(p for p in changed if p.startswith(root) and p.endswith(".java"))
        if not hits:
            print(f"{module}: no changed Java files")
            continue
        (out / f"{n}.module").write_text(module + "\n", encoding="utf-8")
        (out / f"{n}.files").write_text(
            "".join(str(Path(p).resolve()) + "\n" for p in hits), encoding="utf-8"
        )
        (out / f"{n}.includes").write_text(
            ",".join(p[len(root):] for p in hits), encoding="utf-8"
        )
        total += len(hits)
        print(f"{module}: {len(hits)} changed Java file(s)")
        for p in hits:
            print(f"  {p}")

    print(f"\n{total} file(s) across {len(modules)} module(s) in diff mode")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"any={'true' if total else 'false'}\n")
            fh.write(f"count={total}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
