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


def organisation_step() -> dict:
    with open(WORKFLOW, encoding="utf-8") as fh:
        steps = yaml.safe_load(fh)["jobs"]["produce"]["steps"]
    return next(s for s in steps if ric.ORGANISATION_ENV in (s.get("env") or {}))


def git(cwd: str, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
               GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


def put(root: str, files: dict) -> None:
    for path, text in files.items():
        target = os.path.join(root, path)
        if text is None:
            os.remove(target)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)


def instructions(base: dict, head: dict, later: dict | None = None):
    """The organisation's restore step, run as written over a pull request.

    `base` is the tree the branch started from, `head` what the pull request changed (`None`
    deletes), and `later` what the base branch changed after the branch left it. Answers the files
    of the checkout after the step, the paths it named, and the copies it kept.
    """
    with tempfile.TemporaryDirectory() as tmp:
        git(tmp, "init", "-q", "-b", "main")
        put(tmp, base)
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "base")
        git(tmp, "checkout", "-q", "-b", "pr")
        put(tmp, head)
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "head")
        if later:
            git(tmp, "checkout", "-q", "main")
            put(tmp, later)
            git(tmp, "add", "-A")
            git(tmp, "commit", "-q", "-m", "later")
            git(tmp, "checkout", "-q", "pr")
        with open(os.path.join(tmp, "pull-request.json"), "w", encoding="utf-8") as fh:
            json.dump({"base": {"sha": git(tmp, "rev-parse", "main")}}, fh)
        open(os.path.join(tmp, "restored-paths.txt"), "w").close()
        step = organisation_step()
        env = dict(os.environ, **{ric.ORGANISATION_ENV: step["env"][ric.ORGANISATION_ENV]})
        subprocess.run(["bash", "-c", step["run"]], cwd=tmp, env=env, check=True,
                       capture_output=True)
        tree, kept = {}, {}
        for top, dirs, names in os.walk(tmp):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in names:
                rel = os.path.relpath(os.path.join(top, name), tmp)
                with open(os.path.join(top, name), encoding="utf-8") as fh:
                    text = fh.read()
                if rel.startswith(ric.ORGANISATION_SNAPSHOT):
                    kept[rel[len(ric.ORGANISATION_SNAPSHOT):]] = text
                elif rel not in ("pull-request.json", "restored-paths.txt"):
                    tree[rel] = text
        with open(os.path.join(tmp, "restored-paths.txt"), encoding="utf-8") as fh:
            named = fh.read().split()
        return tree, named, kept


BASE = {"AGENTS.md": "base agents\n", ".agents/rule.md": "base rule\n", "README.md": "base\n",
        "docs/guide.md": "guide\n"}


@case("an instruction file the pull request edits or adds is read at the base, and its copy kept")
def _():
    tree, named, kept = instructions(BASE, {
        "AGENTS.md": "the branch's agents\n", "docs/AGENTS.md": "a nested one\n",
        ".agents/rule.md": "the branch's rule\n", ".github/copilot-instructions.md": "x\n",
        "README.md": "the branch's readme\n"})
    assert tree["AGENTS.md"] == "base agents\n" and tree[".agents/rule.md"] == "base rule\n", tree
    assert "docs/AGENTS.md" not in tree and ".github/copilot-instructions.md" not in tree, tree
    assert tree["README.md"] == "the branch's readme\n", tree
    assert sorted(named) == [".agents/rule.md", ".github/copilot-instructions.md", "AGENTS.md",
                             "docs/AGENTS.md"], named
    assert kept == {"AGENTS.md": "the branch's agents\n", "docs/AGENTS.md": "a nested one\n",
                    ".agents/rule.md": "the branch's rule\n",
                    ".github/copilot-instructions.md": "x\n"}, kept


@case("an instruction file the pull request deletes or renames comes back, and is named")
def _():
    tree, named, kept = instructions(BASE, {"AGENTS.md": None, ".agents/rule.md": None,
                                            ".agents/renamed.md": "base rule\n"})
    assert tree["AGENTS.md"] == "base agents\n" and tree[".agents/rule.md"] == "base rule\n", tree
    assert ".agents/renamed.md" not in tree, tree
    assert sorted(named) == [".agents/renamed.md", ".agents/rule.md", "AGENTS.md"], named
    assert kept == {".agents/renamed.md": "base rule\n"}, kept


@case("a branch behind its base reads the base's instructions, and names none it did not write")
def _():
    tree, named, _ = instructions(BASE, {"README.md": "x\n"}, later={"AGENTS.md": "newer\n"})
    assert tree["AGENTS.md"] == "newer\n", tree
    assert named == [], named


@case("an instruction file whose path carries a newline is read whole")
def _():
    odd = "docs/two\nlines/AGENTS.md"
    tree, _, kept = instructions(BASE, {odd: "the branch's nested agents\n"})
    assert odd not in tree, tree
    assert kept == {odd: "the branch's nested agents\n"}, kept


@case("a path that only resembles an instruction file is left as the branch wrote it")
def _():
    near = {"AGENTS.md.bak": "a\n", ".agentsX/a.md": "b\n", "docs/NOT-AGENTS.md": "c\n",
            "src/gemini.py": "d\n"}
    tree, named, kept = instructions(BASE, near)
    assert all(tree[path] == text for path, text in near.items()), tree
    assert named == [] and kept == {}, (named, kept)


@case("the check refuses the organisation's list one path short, or restored after the runner")
def _():
    listed = organisation_step()["env"][ric.ORGANISATION_ENV].split()
    assert sorted(listed) == sorted(ric.ORGANISATION_RESTORES), listed
    got = check_on(lambda t: t.replace("AGENTS.md .agents GEMINI.md", "AGENTS.md GEMINI.md", 1))
    assert got.returncode == 1 and ric.ORGANISATION_ENV in got.stdout, got.stdout

    def after_runner(text):
        start = text.index("      - name: The instruction files this pull request cannot write")
        end = text.index("      - name: The L1 gate results")
        block = text[start:end]
        text = text[:start] + text[end:]
        anchor = text.index("        uses: anthropics/claude-code-action@")
        close = text.index("\n      - ", anchor) + 1
        return text[:close] + block + text[close:]
    got = check_on(after_runner)
    assert got.returncode == 1 and "after the runner" in got.stdout, got.stdout


@case("the check refuses a step that restores nothing, and a prompt with no copy to send to")
def _():
    got = check_on(lambda t: t.replace('git checkout -q "$base" -- "$path"', 'true', 1))
    assert got.returncode == 1 and "back to the base" in got.stdout, got.stdout
    got = check_on(lambda t: t.replace("at `.exeris-pr/<path>` for the", "for the", 1))
    assert got.returncode == 1 and ".exeris-pr/" in got.stdout, got.stdout


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
    got = check_on(lambda t: t.replace("`.claude-pr/<path>` for the runner's own paths",
                                       "a copy for the runner's own paths", 1))
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
