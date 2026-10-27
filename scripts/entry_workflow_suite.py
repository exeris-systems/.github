#!/usr/bin/env python3
"""`entry_workflow.sh`'s fixture suite — ADR-087's override turns on this answer.

The question decides whether `human-reviewed` may green a required check with no review behind
it, so a wrong `true` is a fail-open. Each case below is a `(workflow ref, repository, changed
paths)` triple, with the entry workflow's text where the answer needs it, and the answer it must
give. They run the real script, because a suite that restates the logic tests the restatement.

Usage: entry_workflow_suite.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "entry_workflow.sh")

ENTRY = "exeris-systems/.github/.github/workflows/guardrails.yml@refs/pull/56/merge"
REPO = "exeris-systems/.github"

# No entry file: the script fetches the entry from the host, through a `gh` that fails.
FETCH_FAILS = object()

# The entry's text, as the cases that need it read it. One local call, one quoted local call, and one
# call to another repository whose file name collides with a local one.
CALLS = """
jobs:
  review:
    uses: ./.github/workflows/review.yml
  lint:
    uses: "./.github/workflows/docs-lint.yml"
  remote:
    uses: exeris-systems/other/.github/workflows/publish.yml@0123456789abcdef
"""

CASES = [
    ("the entry workflow itself, among others",
     ENTRY, REPO, [".github/workflows/guardrails.yml", "README.md"], "true"),
    # The runner refuses when a workflow of this repository that the entry calls differs from the
    # default branch's copy, so such a change answers `true` as the entry itself does.
    ("a workflow of this repository the entry calls",
     ENTRY, REPO, [".github/workflows/review.yml"], "true", CALLS),
    ("a quoted local call counts the same",
     ENTRY, REPO, [".github/workflows/docs-lint.yml"], "true", CALLS),
    ("a workflow of this repository the entry does not call",
     ENTRY, REPO, [".github/workflows/labels-sync.yml"], "false", CALLS),
    ("a local file named like a workflow called from another repository",
     ENTRY, REPO, [".github/workflows/publish.yml"], "false", CALLS),
    ("a workflow file in a subdirectory is not a workflow",
     ENTRY, REPO, [".github/workflows/old/review.yml"], "false", CALLS),
    # The entry's text is read only when another workflow file changed. A read that is needed and
    # fails exits non-zero with no answer, since either answer would be a guess.
    ("nothing is read when no other workflow file changed",
     ENTRY, REPO, ["scripts/x.py"], "false", None),
    ("a needed read that fails gives no answer",
     ENTRY, REPO, [".github/workflows/review.yml"], "", None),
    ("a needed fetch from the host that fails gives no answer",
     ENTRY, REPO, [".github/workflows/review.yml"], "", FETCH_FAILS),
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
    for name, ref, repo, files, want, *entry in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            # No case reaches the network: each passes an entry file, or puts a failing `gh` first
            # on PATH. `None` names an entry file that does not exist, which is what a failed read
            # looks like to the script.
            path = os.path.join(tmp, "entry.yml")
            args, env = [SCRIPT, ref, repo, path], None
            if entry and entry[0] is FETCH_FAILS:
                stub = os.path.join(tmp, "gh")
                with open(stub, "w", encoding="utf-8") as fh:
                    fh.write("#!/bin/sh\nexit 1\n")
                os.chmod(stub, 0o755)
                args, env = args[:3], {**os.environ, "PATH": tmp + os.pathsep + os.environ["PATH"]}
            elif entry and entry[0] is not None:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(entry[0])
            p = subprocess.run(args, input="\n".join(files) + "\n",
                               capture_output=True, text=True, env=env)
        got = p.stdout.strip()
        if want == "" and p.returncode == 0:
            got = f"exit 0 with {got!r}"
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
