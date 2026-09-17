#!/usr/bin/env python3
"""The reviewer's copy of a check runs where the job that tests it runs — ADR-087 §B.12.

`repo-checks` hands the reviewer this repository's own gates as output, because the runner's
harness denies Bash and a prompt asking a model to run scripts gets them reported as `not-run`.
The jobs in the same file run several of the same scripts. Two places, one command — and when they
disagree about what is installed, the reviewer is handed a failure CI does not have and reads it as
the state of the repository.

Measured: `publish_verdict_suite.py` failed 57 of 129 cases under `repo-checks` on
`ModuleNotFoundError: No module named 'referencing'` while the `verdict-contract` job ran the same
command green, having installed first. It had been that way since `repo-checks` was wired and no
review had seen it, because every pull request in between changed the entry workflow and was never
reviewed at all.

What this compares: for every script `repo-checks` runs that a CI step also runs, the packages that
step's job installs before it must be installed by `repo-checks` too. Not the reverse — `repo-checks`
installing more than a job needs is its own business.

Usage: repo_checks_env_check.py [--root .]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import yaml

SCRIPT = re.compile(r"(?:python3?|py)\s+(\S*scripts/[A-Za-z0-9_./-]+\.py)")
INSTALL = re.compile(r"pip\s+install\s+([^\n;&|]+)")
NOT_A_PACKAGE = {"--quiet", "-q", "--upgrade", "-U", "--no-cache-dir", "--user"}


def packages(text: str) -> set[str]:
    found: set[str] = set()
    for m in INSTALL.finditer(text or ""):
        for word in m.group(1).split():
            if word not in NOT_A_PACKAGE and not word.startswith("-"):
                found.add(word)
    return found


def scripts(text: str) -> set[str]:
    return {os.path.basename(m.group(1)) for m in SCRIPT.finditer(text or "")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    root = os.path.abspath(ap.parse_args().root)
    with open(os.path.join(root, ".github", "workflows", "guardrails.yml"), encoding="utf-8") as fh:
        wf = yaml.safe_load(fh)

    checks = ""
    for job in (wf.get("jobs") or {}).values():
        value = (job.get("with") or {}).get("repo-checks")
        if value:
            checks = str(value)
    if not checks:
        print("repo_checks_env_check: this repository passes no repo-checks; nothing to compare")
        return 0

    reviewer_scripts = scripts(checks)
    reviewer_has = packages(checks)

    # What each job installs, and which of the reviewer's scripts it runs. A job installs for all of
    # its steps: `pip install` in one step and the script in the next is the ordinary shape, and is
    # exactly the arrangement `repo-checks` has to match.
    bad: list[str] = []
    for name, job in (wf.get("jobs") or {}).items():
        steps = job.get("steps") or []
        job_text = "\n".join(str(s.get("run") or "") for s in steps)
        installed = packages(job_text)
        shared = scripts(job_text) & reviewer_scripts
        for script in sorted(shared):
            missing = sorted(installed - reviewer_has)
            if missing:
                bad.append(f"`repo-checks` runs {script} without {', '.join(missing)}, which job "
                           f"`{name}` installs before running it — the reviewer is handed a failure "
                           f"that CI does not have, as this repository's own gate")

    for said in sorted(set(bad)):
        print(f"::error::repo_checks_env_check: {said}")
    if bad:
        return 1
    print(f"repo_checks_env_check: {len(reviewer_scripts)} script(s) in repo-checks, "
          f"each in the environment its job tests it in")
    return 0


if __name__ == "__main__":
    sys.exit(main())
