#!/usr/bin/env python3
"""The gate-result mapping speaks the verdict's vocabulary — and keeps speaking it.

`docs-review.yml` hands the L1 gate results to the reviewer and tells it to copy them into
`checks_run` as they are. They arrive in GitHub's words (`success`, `failure`, `cancelled`) and
`verdict.base.schema.json` requires `pass`, `fail`, `not-run` under a `check` key, so the workflow
maps between them. Two things can drift apart afterwards and neither shows up until a verdict is
refused: the mapping, and the enum it maps into.

This runs the mapping AS IT SHIPS — extracted from the workflow, not restated here — over every
result GitHub can report, and checks the output against the schema the verdict is validated with.

Usage: gate_vocabulary_check.py [--root .]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Every value `needs.<job>.result` can take. A value this file does not know is a failure, not a
# default: the mapping's `else` branch is `not-run`, which is right for "reported nothing" and wrong
# for anything GitHub might add that means something else.
GITHUB_RESULTS = ["success", "failure", "cancelled", "skipped"]


def jq_program(workflow: str) -> str:
    """The mapping as the workflow ships it."""
    text = open(workflow, encoding="utf-8").read()
    m = re.search(r"jq -c '(\[to_entries\[\].*?)'\s*>", text, re.S)
    if not m:
        raise SystemExit("gate_vocabulary_check: the mapping is not where this check looks for it "
                         "in docs-review.yml — it moved, and a check that cannot find what it "
                         "checks is not a check")
    return m.group(1)


def enum_of(schema: str) -> list[str]:
    doc = json.load(open(schema, encoding="utf-8"))
    return doc["properties"]["checks_run"]["items"]["properties"]["result"]["enum"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default=".")
    args = p.parse_args()

    program = jq_program(os.path.join(args.root, ".github", "workflows", "docs-review.yml"))
    allowed = enum_of(os.path.join(args.root, ".agents", "vendor", "exeris-agents-2.0.0",
                                   "schemas", "verdict.base.schema.json"))
    sample = json.dumps({f"gate-{i}": v for i, v in enumerate(GITHUB_RESULTS)})
    out = subprocess.run(["jq", "-c", program], input=sample, capture_output=True, text=True)
    if out.returncode:
        print(f"::error title=gate_vocabulary_check::the mapping does not run: {out.stderr[:300]}")
        return 1

    problems = []
    entries = json.loads(out.stdout)
    if len(entries) != len(GITHUB_RESULTS):
        problems.append(f"{len(GITHUB_RESULTS)} results in, {len(entries)} entries out")
    for entry in entries:
        if sorted(entry) != ["check", "result"]:
            problems.append(f"an entry carries {sorted(entry)}, and the schema requires "
                            f"`check` and `result`")
        if entry.get("result") not in allowed:
            problems.append(f"`{entry.get('result')}` is not one of {allowed} — the mapping and the "
                            f"schema have drifted, and a verdict built from it is refused")
    for problem in problems:
        print(f"::error title=gate_vocabulary_check::{problem}")
    print(f"gate_vocabulary_check: {len(GITHUB_RESULTS)} gate results mapped, "
          f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
