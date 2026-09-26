#!/usr/bin/env python3
"""Cases for `principal_check.py`: each rule is shown to fail on the edit it exists to catch.

The check reads the workflow expressions this repository ships, so the cases do the same: each one
copies the files the check reads, applies one edit to `docs-review.yml`'s text, and runs the check
over the copy. A case passes when the check refuses the edit and names what it refused, and the
unedited copy has to pass.

Usage: principal_check_suite.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")

FAILED: list[str] = []

ADMISSION = """      (!endsWith(github.event.pull_request.user.login, '[bot]') ||
       github.event.pull_request.user.login == 'exeris-agent[bot]') &&"""


def case(title):
    def wrap(fn):
        try:
            fn()
            print(f"ok    {title}")
        except Exception as exc:                            # every class is reported, none hidden
            FAILED.append(title)
            print(f"::error title=principal_check_suite::{title}: {type(exc).__name__}: {exc}")
        return fn
    return wrap


def check_on(edit) -> subprocess.CompletedProcess:
    """The check over a copy of the files it reads, with `edit` applied to `docs-review.yml`."""
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(WORKFLOWS, os.path.join(tmp, ".github", "workflows"))
        shutil.copytree(os.path.join(ROOT, "caller-example"), os.path.join(tmp, "caller-example"))
        os.makedirs(os.path.join(tmp, "scripts"))
        shutil.copy(os.path.join(HERE, "publish_verdict.py"), os.path.join(tmp, "scripts"))
        target = os.path.join(tmp, ".github", "workflows", "docs-review.yml")
        with open(target, encoding="utf-8") as fh:
            text = fh.read()
        edited = edit(text)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(edited)
        return subprocess.run([sys.executable, os.path.join(HERE, "principal_check.py"),
                               "--root", tmp], capture_output=True, text=True)


def once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"the shipped workflow no longer carries {old!r} exactly once"
    return text.replace(old, new)


@case("this repository's workflow passes")
def _():
    got = check_on(lambda t: t)
    assert got.returncode == 0, got.stdout


@case("a second bot admitted beside the execution identity is refused, and named")
def _():
    got = check_on(lambda t: once(t, "user.login == 'exeris-agent[bot]') &&",
                                  "user.login == 'exeris-agent[bot]' ||\n"
                                  "       github.event.pull_request.user.login == "
                                  "'other-bot[bot]') &&"))
    assert got.returncode == 1 and "other-bot[bot]" in got.stdout, got.stdout


@case("a bot let through without being named is refused")
def _():
    got = check_on(lambda t: once(t, ADMISSION,
                                  "      (!endsWith(github.event.pull_request.user.login, "
                                  "'[bot]') ||\n"
                                  "       github.event.pull_request.user.type == 'Bot') &&"))
    assert got.returncode == 1 and "without naming which one" in got.stdout, got.stdout


@case("the identity admitted with no restore of AGENTS.md and .agents is refused")
def _():
    got = check_on(lambda t: once(t, "            AGENTS.md .agents GEMINI.md",
                                  "            GEMINI.md"))
    assert got.returncode == 1 and "reviewed under instructions it wrote" in got.stdout, got.stdout


@case("the identity admitted with the restore step renamed away is refused")
def _():
    got = check_on(lambda t: t.replace("RESTORED_BY_ORGANISATION", "RESTORED_ELSEWHERE"))
    assert got.returncode == 1 and "reviewed under instructions it wrote" in got.stdout, got.stdout


@case("no bot admitted at all is a state the check accepts")
def _():
    got = check_on(lambda t: once(t, ADMISSION,
                                  "      !endsWith(github.event.pull_request.user.login, "
                                  "'[bot]') &&"))
    assert got.returncode == 0, got.stdout


@case("a produce condition that no longer asks the sender's type is refused")
def _():
    got = check_on(lambda t: once(t, "      github.event.sender.type == 'User' &&\n", ""))
    assert got.returncode == 1 and "github.event.sender.type" in got.stdout, got.stdout


if __name__ == "__main__":
    total = sum(1 for line in open(__file__, encoding="utf-8") if line.startswith("@case("))
    print(f"principal_check_suite: ran {total} cases, {len(FAILED)} failures")
    sys.exit(1 if FAILED else 0)
