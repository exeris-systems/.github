#!/usr/bin/env python3
"""The reviewer's copy of a check runs where the job that tests it runs — ADR-087 §B.12.

`repo-checks` hands the reviewer this repository's own gates as output, because the runner's
harness denies Bash and a prompt asking a model to run scripts gets them reported as `not-run`.
The jobs in the same file run several of the same scripts. Two places, one command — and when they
disagree about what is installed, the reviewer is handed a failure CI does not have and reads it as
the state of the repository.

The failure is invisible from either side alone. The job passes, because it installs first; the
reviewer is handed an `ImportError` and reads it as the state of the repository. Nothing compares
the two, and a pull request that changes the entry workflow is never reviewed at all, so the
disagreement can stand for a long time without anything reporting it.

What this compares, in two halves, because the first alone was not enough. The PACKAGES: for every
script `repo-checks` runs that a CI step also runs, the packages that step's job installs before it
must be installed by `repo-checks` too — not the reverse, since installing more than a job needs is
its own business. And the INTERPRETER: the job that runs `repo-checks` must set Python up, as every
job compared against it does.

The second half exists because the first passed while the environments still disagreed. The names
matched; the runner image's system `python3` already carried an older `jsonschema`, `pip install`
reported it satisfied and installed nothing, and 57 of 129 cases failed on a keyword argument that
arrived in 4.18. A list of package names is not an environment, and this file was named as though
it were.

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

    # THE INTERPRETER, asked of the routine rather than of this repository's own workflow:
    # `repo-checks` runs inside `docs-review.yml`'s produce job, and a caller cannot put a step
    # there. Read from the routine as it ships, for the reason `gate_vocabulary_check.py` reads the
    # mapping that ships — a guarantee is worth what the file says, not what a comment claims.
    routine = os.path.join(root, ".github", "workflows", "docs-review.yml")
    bad_interp: list[str] = []
    if os.path.exists(routine):
        with open(routine, encoding="utf-8") as fh:
            produce = (yaml.safe_load(fh).get("jobs") or {}).get("produce") or {}
        steps = produce.get("steps") or []
        sets_up = next((i for i, st in enumerate(steps)
                        if "setup-python" in str(st.get("uses") or "")), None)
        runs_checks = next((i for i, st in enumerate(steps)
                            if "own checks" in str(st.get("name") or "")), None)
        if runs_checks is None:
            bad_interp.append("docs-review.yml's produce job has no step running `repo-checks`")
        elif sets_up is None or sets_up > runs_checks:
            bad_interp.append(
                "docs-review.yml's produce job runs `repo-checks` without setting Python up first, "
                "so a caller's `pip install` goes to the runner image's system interpreter and "
                "reports an older package satisfied instead of resolving the one a job resolves")

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

    bad = bad + bad_interp
    for said in sorted(set(bad)):
        print(f"::error::repo_checks_env_check: {said}")
    if bad:
        return 1
    print(f"repo_checks_env_check: {len(reviewer_scripts)} script(s) in repo-checks, a managed "
          f"interpreter under them, each in the environment its job tests it in")
    return 0


if __name__ == "__main__":
    sys.exit(main())
