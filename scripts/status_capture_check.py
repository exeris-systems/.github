#!/usr/bin/env python3
"""A status read on a line of its own under `bash -e` can only ever read 0.

A `run:` step with no `shell:` runs under `bash -e`, and so does `shell: bash`. Under `-e` a command
that exits non-zero ends the step on that line, so a following `status=$?` is reached only when the
status is 0. The step then never gets to what it meant to do with a failure: count it, filter it,
report it and carry on to the next item. Nothing about that is visible in a green run. It shows the
first time the command fails, as a step that stops early for no reason its own code states.

A capture is sound when `-e` is off where it runs: `set +e` earlier in the step, or a shell given
without `-e`. `cmd || status=$?` never ends the step and is not on a line of its own, so it is not
read here.

Usage: status_capture_check.py [--root .]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import yaml

CAPTURE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=\$\?\s*(#.*)?$")
SET = re.compile(r"^\s*set\s+(.*)$")


def errexit_at_start(shell: str | None) -> bool:
    """Whether a step starts under `-e`. GitHub runs a step with no shell, and one naming plain
    `bash`, as `bash --noprofile --norc -eo pipefail {0}`; a custom shell string is taken as
    written."""
    if shell is None or shell.strip() == "bash":
        return True
    return any(w.startswith("-") and not w.startswith("--") and "e" in w[1:]
               for w in shell.split()[1:])


def apply_set(line: str, errexit: bool) -> bool:
    found = SET.match(line)
    if not found:
        return errexit
    for word in found.group(1).split():
        if word[0] in "-+" and "e" in word[1:]:
            errexit = word[0] == "-"
    return errexit


def findings(script: str, shell: str | None) -> list[int]:
    """1-based lines of `script` where a status is captured under `-e`."""
    errexit, out = errexit_at_start(shell), []
    for number, line in enumerate(script.splitlines(), 1):
        errexit = apply_set(line, errexit)
        if errexit and CAPTURE.match(line):
            out.append(number)
    return out


def shell_of(step: dict, job: dict, workflow: dict) -> str | None:
    for owner in (step, (job.get("defaults") or {}).get("run") or {},
                  (workflow.get("defaults") or {}).get("run") or {}):
        if isinstance(owner, dict) and owner.get("shell"):
            return str(owner["shell"])
    return None


def check(root: str) -> list[str]:
    problems = []
    for path in sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml"))):
        with open(path, encoding="utf-8") as fh:
            workflow = yaml.safe_load(fh) or {}
        rel = os.path.relpath(path, root)
        for job_id, job in (workflow.get("jobs") or {}).items():
            for index, step in enumerate((job or {}).get("steps") or []):
                if not isinstance(step, dict) or "run" not in step:
                    continue
                name = step.get("name") or step.get("id") or f"step {index + 1}"
                for line in findings(str(step["run"]), shell_of(step, job, workflow)):
                    problems.append(f"{rel}: job `{job_id}`, step `{name}`, line {line} of its "
                                    f"`run:` captures `$?` under `bash -e`, where it can only be 0 "
                                    f"— put `set +e` before the command, or write "
                                    f"`cmd || status=$?`")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    problems = check(os.path.abspath(ap.parse_args().root))
    for p in problems:
        print(f"::error title=status_capture_check::{p}")
    print(f"status_capture_check: {len(problems)} status capture(s) under `-e`")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
