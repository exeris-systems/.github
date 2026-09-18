#!/usr/bin/env python3
"""Cases for `repo_checks_env_check.py` — ADR-087 Engineering Protocol 2.

That checker exists because two places ran one command in two environments and nothing compared
them. It decides two things and each can be wrong on its own: comparing package names says nothing
about the interpreter they resolve in, and an ordering rule with no case behind it is a rule nobody
has watched fail. A checker with no cases is the thing it checks for.

Each case below builds a pair of workflow files on disk, runs the checker over them, and asserts
what it says. The fixture is a conforming pair; every case is that with one thing changed.

Usage: repo_checks_env_check_suite.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "repo_checks_env_check.py")

CASES: list[tuple[str, object]] = []


def case(name: str):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


GUARDRAILS = """
name: guardrails
on: { pull_request: {} }
jobs:
  docs-review:
    uses: ./.github/workflows/docs-review.yml
    with:
      repo-checks: >-
        pip install --quiet pyyaml jsonschema;
        python3 scripts/thing_suite.py --root .
  verdict-contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v7
      - name: the same script, in a job
        run: |
          pip install --quiet jsonschema
          python scripts/thing_suite.py --root .
"""

ROUTINE = """
name: docs-review
on: { workflow_call: {} }
jobs:
  produce:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with: { python-version: "3.14" }
      - name: This repository's own checks
        if: ${{ inputs.repo-checks != '' }}
        run: bash -c "$REPO_CHECKS"
"""


def build(root: str, guardrails: str = GUARDRAILS, routine: str = ROUTINE) -> None:
    d = os.path.join(root, ".github", "workflows")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "guardrails.yml"), "w", encoding="utf-8") as fh:
        fh.write(guardrails)
    if routine is not None:
        with open(os.path.join(d, "docs-review.yml"), "w", encoding="utf-8") as fh:
            fh.write(routine)


def run(root: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, CHECKER, "--root", root],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


@case("a conforming pair says so and says how many scripts it compared")
def _(root):
    build(root)
    code, out = run(root)
    assert code == 0, out
    assert "1 script(s)" in out and "managed interpreter" in out, out


# THE PACKAGE HALF. A job installs `jsonschema` before the script; `repo-checks` must too, or the
# reviewer is handed an ImportError as the state of the repository.
@case("a package the job installs and repo-checks does not is named")
def _(root):
    build(root, guardrails=GUARDRAILS.replace("pip install --quiet pyyaml jsonschema;",
                                              "pip install --quiet pyyaml;"))
    code, out = run(root)
    assert code == 1, out
    assert "jsonschema" in out and "thing_suite.py" in out, out


@case("repo-checks installing MORE than a job needs is its own business")
def _(root):
    build(root, guardrails=GUARDRAILS.replace("pip install --quiet pyyaml jsonschema;",
                                              "pip install --quiet pyyaml jsonschema rich;"))
    code, out = run(root)
    assert code == 0, out


# THE INTERPRETER HALF, which shipped with no case and is why this file exists. Names matching is
# not environments matching: the runner image's system `python3` carried an older `jsonschema`,
# `pip install` called it satisfied, and 57 of 129 cases failed on a 4.18 keyword.
@case("no setup-python before the checks step is a broken rule")
def _(root):
    build(root, routine=ROUTINE.replace(
        '      - uses: actions/setup-python@v7\n        with: { python-version: "3.14" }\n', ""))
    code, out = run(root)
    assert code == 1, out
    assert "without setting Python up first" in out, out


@case("and so is setting it up afterwards — order is the property")
def _(root):
    build(root, routine="""
name: docs-review
on: { workflow_call: {} }
jobs:
  produce:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: This repository's own checks
        if: ${{ inputs.repo-checks != '' }}
        run: bash -c "$REPO_CHECKS"
      - uses: actions/setup-python@v7
""")
    code, out = run(root)
    assert code == 1, out
    assert "without setting Python up first" in out, out


@case("a routine with no step running repo-checks at all is a broken rule")
def _(root):
    build(root, routine="""
name: docs-review
on: { workflow_call: {} }
jobs:
  produce:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
""")
    code, out = run(root)
    assert code == 1, out
    assert "no step running" in out, out


# A caller that passes no `repo-checks` hands the reviewer nothing, so there is nothing to compare
# and nothing to complain about. Green here is the absence of a question, not an answer to one.
@case("a repository passing no repo-checks is green and says why")
def _(root):
    build(root, guardrails="""
name: guardrails
on: { pull_request: {} }
jobs:
  docs-review:
    uses: ./.github/workflows/docs-review.yml
""")
    code, out = run(root)
    assert code == 0, out
    assert "nothing to compare" in out, out


# The routine is another repository's file for every caller but this one. Absent, the package half
# still answers: a missing routine is not a failed interpreter check, it is no check.
@case("a missing routine leaves the package half doing its job")
def _(root):
    build(root, routine=None)
    code, out = run(root)
    assert code == 0, out


def main() -> int:
    failures = 0
    for name, fn in CASES:
        with tempfile.TemporaryDirectory() as root:
            try:
                fn(root)
            except AssertionError as exc:
                failures += 1
                print(f"::error title=repo_checks_env_check_suite::{name}: {exc}")
            except Exception as exc:  # a case that cannot run is a case that did not pass
                failures += 1
                print(f"::error title=repo_checks_env_check_suite::{name}: "
                      f"{type(exc).__name__}: {exc}")
    print(f"repo_checks_env_check_suite: ran {len(CASES)} cases, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
