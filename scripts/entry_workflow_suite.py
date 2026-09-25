#!/usr/bin/env python3
"""`entry_workflow.sh`'s fixture suite — ADR-087's override turns on this answer.

The question decides whether `human-reviewed` may green a required check with no review behind
it, so a wrong `true` is a fail-open. Each case below is a `(workflow ref, repository, changed
paths)` triple and the answer it must give. They run the real script, because a suite that restates
the logic tests the restatement.

Usage: entry_workflow_suite.py
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "entry_workflow.sh")

ENTRY = "exeris-systems/.github/.github/workflows/guardrails.yml@refs/pull/56/merge"
REPO = "exeris-systems/.github"

CASES = [
    ("the entry workflow itself, among others",
     ENTRY, REPO, [".github/workflows/guardrails.yml", "README.md"], "true"),
    ("a reusable workflow the run only calls",
     ENTRY, REPO, [".github/workflows/docs-review.yml"], "false"),
    ("the entry workflow of a DIFFERENT repository, same file name",
     "exeris-systems/exeris-docs/.github/workflows/guardrails.yml@refs/pull/9/merge",
     "exeris-systems/exeris-docs", [".github/workflows/guardrails.yml"], "true"),
    ("no workflow in the diff at all",
     ENTRY, REPO, ["scripts/publish_verdict.py", "docs-guardrails-review.md"], "false"),
    # A prefix match is the failure this file exists to stop: the old test said `true` for every
    # one of these, which handed the override to pull requests a review could have judged.
    ("a path that merely starts like the entry file",
     ENTRY, REPO, [".github/workflows/guardrails.yml.bak"], "false"),
    ("a directory that merely starts like the workflows directory",
     ENTRY, REPO, [".github/workflows-old/guardrails.yml"], "false"),
    # Fail closed: an unanswerable question is not a `false` that grants nothing, it is a `false`
    # that must be reached deliberately. Both of these mean "the ref told us nothing".
    ("an empty ref answers false rather than guessing",
     "", REPO, [".github/workflows/guardrails.yml"], "false"),
    ("a ref that is not a workflow path answers false",
     "exeris-systems/.github/Makefile@refs/heads/main", REPO, ["Makefile"], "false"),
    ("a ref whose repository prefix does not match is not stripped into a match",
     "someone-else/fork/.github/workflows/guardrails.yml@refs/pull/1/merge",
     REPO, [".github/workflows/guardrails.yml"], "false"),
]


def main() -> int:
    failures = 0
    for name, ref, repo, files, want in CASES:
        got = subprocess.run([SCRIPT, ref, repo], input="\n".join(files) + "\n",
                             capture_output=True, text=True).stdout.strip()
        if got != want:
            failures += 1
            print(f"::error title=entry_workflow_suite::{name}: expected {want}, got {got!r}")
    print(f"entry_workflow_suite: ran {len(CASES)} cases, {failures} failures")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## entry_workflow_suite\n\nRan **{len(CASES)}** cases — "
                     f"**{failures} failures**.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
