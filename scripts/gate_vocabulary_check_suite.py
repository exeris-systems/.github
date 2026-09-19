#!/usr/bin/env python3
"""`gate_vocabulary_check.vendored_base`'s fixture suite.

The resolver decides which vendored base the gate vocabulary is checked against. It answers from
the tree rather than from a literal, so the states worth pinning are the ones a tree can be in:
none vendored, exactly one, and more than one. The middle answer must not depend on the version in
the directory name — that dependence is the defect the resolver replaced.

Usage: gate_vocabulary_check_suite.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate_vocabulary_check as gv                                     # noqa: E402

BASE = '{"properties": {"checks_run": {"items": {"properties": {"result": {"enum": ["pass", "fail", "not-run"]}}}}}}'


def tree(*versions: str) -> str:
    d = tempfile.mkdtemp(prefix="gate-vocab-")
    for v in versions:
        s = os.path.join(d, ".agents", "vendor", f"exeris-agents-{v}", "schemas")
        os.makedirs(s)
        with open(os.path.join(s, "verdict.base.schema.json"), "w", encoding="utf-8") as fh:
            fh.write(BASE)
    return d


def resolve(*versions: str):
    d = tree(*versions)
    try:
        return gv.vendored_base(d)
    except SystemExit as exc:
        return f"refused: {exc}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    failures, ran = 0, 0

    def check(name: str, got, want) -> None:
        nonlocal failures, ran
        ran += 1
        if got != want:
            failures += 1
            print(f"::error title=gate_vocabulary_check_suite::{name}: expected {want!r}, "
                  f"got {got!r}")

    check("no vendored bundle is refused", str(resolve()).startswith("refused:"), True)
    check("two vendored bundles are refused",
          str(resolve("2.0.0", "2.1.0")).startswith("refused:"), True)
    check("exactly one resolves", os.path.basename(str(resolve("2.1.0"))),
          "verdict.base.schema.json")
    # The version in the name is not the resolver's business: it reads the tree, and the tree is
    # whatever the pin last vendored.
    check("any version name resolves", os.path.basename(os.path.dirname(os.path.dirname(
          str(resolve("9.9.9"))))), "exeris-agents-9.9.9")

    d = tree("2.1.0")
    try:
        check("and the enum comes off the base it found", gv.enum_of(gv.vendored_base(d)),
              ["pass", "fail", "not-run"])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"gate_vocabulary_check_suite: ran {ran} cases, {failures} failures")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## gate_vocabulary_check_suite\n\nRan **{ran}** cases — "
                     f"**{failures} failures**.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
