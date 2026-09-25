#!/usr/bin/env python3
"""Cases for `review_inputs_check.py` and the restored-path filter it holds the workflow to.

The filter is run, not read: the `jq` program is taken out of `docs-review.yml` as written and
executed over a pull request's files, so a case fails on the filter the job runs rather than on a
copy of it. The rest mutate the workflow and expect the check to name what went missing.

Usage: review_inputs_check_suite.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "docs-review.yml")
sys.path.insert(0, HERE)
import review_inputs_check as ric  # noqa: E402

FAILED: list[str] = []


def case(title):
    def wrap(fn):
        try:
            fn()
            print(f"ok    {title}")
        except Exception as exc:                            # every class is reported, none hidden
            FAILED.append(title)
            print(f"::error title=review_inputs_check_suite::{title}: {type(exc).__name__}: {exc}")
        return fn
    return wrap


def restore_step() -> dict:
    with open(WORKFLOW, encoding="utf-8") as fh:
        steps = yaml.safe_load(fh)["jobs"]["produce"]["steps"]
    return next(s for s in steps if ric.RESTORE_STEP_ENV in (s.get("env") or {}))


def restored(paths: list[str]) -> list[str]:
    """What the job's own filter writes to `restored-paths.txt` for a pull request changing
    `paths`."""
    step = restore_step()
    command = re.search(r"jq -r --arg restored .*?> restored-paths\.txt", step["run"], re.S)
    assert command, "the step has no jq command writing restored-paths.txt"
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "pull-request.json"), "w", encoding="utf-8") as fh:
            json.dump({"files": [{"path": p} for p in paths]}, fh)
        env = dict(os.environ, **{ric.RESTORE_STEP_ENV: step["env"][ric.RESTORE_STEP_ENV]})
        subprocess.run(["bash", "-c", command.group(0)], cwd=tmp, env=env, check=True)
        with open(os.path.join(tmp, "restored-paths.txt"), encoding="utf-8") as fh:
            return fh.read().split()


def check_on(edit) -> subprocess.CompletedProcess:
    """The check over a copy of this repository's workflow with `edit` applied to its text."""
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, ".github", "workflows")
        os.makedirs(target)
        with open(WORKFLOW, encoding="utf-8") as fh:
            text = edit(fh.read())
        with open(os.path.join(target, "docs-review.yml"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return subprocess.run([sys.executable, os.path.join(HERE, "review_inputs_check.py"),
                               "--root", tmp], capture_output=True, text=True)


@case("every path the runner restores is named when a pull request changes it, at any depth")
def _():
    changed = [".claude/agents/a.md", ".claude/skills/x/SKILL.md", ".claude/settings.json",
               "CLAUDE.md", "CLAUDE.local.md", ".mcp.json", ".claude.json", ".gitmodules",
               ".ripgreprc", ".husky/pre-commit"]
    assert restored(changed) == changed, restored(changed)


@case("a path the runner does not restore is not named, however close its name")
def _():
    assert restored(["docs/CLAUDE.md", ".claudeX/a", ".claude.json.bak", "src/.claude/a",
                     ".husky-notes.md", "README.md"]) == []


@case("the workflow names exactly the runner's list, and the check refuses one path short")
def _():
    listed = restore_step()["env"][ric.RESTORE_STEP_ENV].split()
    assert sorted(listed) == sorted(ric.RUNNER_RESTORES), listed
    got = check_on(lambda t: t.replace("CLAUDE.local.md .husky", "CLAUDE.local.md", 1))
    assert got.returncode == 1 and "RESTORED_BY_RUNNER" in got.stdout, got.stdout


@case("the check refuses a step that no longer derives the list from the runner's paths")
def _():
    got = check_on(lambda t: t.replace('--arg restored "$RESTORED_BY_RUNNER"',
                                       '--arg restored ".claude"', 1))
    assert got.returncode == 1 and "derives `restored-paths.txt`" in got.stdout, got.stdout


@case("the check refuses a prompt that does not send the reviewer to the runner's copy")
def _():
    got = check_on(lambda t: t.replace("wrote to each is at `.claude-pr/<path>`",
                                       "wrote to each is kept", 1))
    assert got.returncode == 1 and ".claude-pr/" in got.stdout, got.stdout


@case("this repository's workflow passes")
def _():
    got = check_on(lambda t: t)
    assert got.returncode == 0, got.stdout


if __name__ == "__main__":
    if not shutil.which("jq"):
        print("::error title=review_inputs_check_suite::jq is not on PATH, and the filter under "
              "test is a jq program")
        sys.exit(1)
    total = sum(1 for line in open(__file__, encoding="utf-8") if line.startswith("@case("))
    print(f"review_inputs_check_suite: ran {total} cases, {len(FAILED)} failures")
    sys.exit(1 if FAILED else 0)
