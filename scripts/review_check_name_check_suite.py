#!/usr/bin/env python3
"""Cases for `review_check_name_check.py` — ADR-087 §B.8, and its amendment on the check's name.

The checker derives the required check's name from the workflow files and compares it with what the
callers and the rulesets say. Each name it protects is the one a branch protection rule waits for,
and a wrong one never reports. So each way of getting it wrong has a case here, and each case asserts
the message of the rule it covers, so it can pass only through that rule.

Every case copies the files the checker reads, applies one edit, and runs it. The shipped files must
pass first: a suite whose baseline is red proves nothing about the edits.

Usage: review_check_name_check_suite.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHECKER = os.path.join(HERE, "review_check_name_check.py")
CASES: list[tuple[str, object]] = []


def case(name: str):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


def copy(tmp: str) -> str:
    shutil.copytree(os.path.join(ROOT, ".github", "workflows"), os.path.join(tmp, ".github", "workflows"))
    shutil.copytree(os.path.join(ROOT, "caller-example"), os.path.join(tmp, "caller-example"))
    shutil.copytree(os.path.join(ROOT, "rulesets"), os.path.join(tmp, "rulesets"))
    return tmp


def run(tmp: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, CHECKER, "--root", tmp], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def edit(tmp: str, rel: str, old: str, new: str, count: int = 1) -> None:
    path = os.path.join(tmp, rel)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert text.count(old) == count, f"{rel} no longer carries {old!r} {count} time(s): {text.count(old)}"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, new))


def refused(tmp: str, needle: str) -> None:
    code, out = run(tmp)
    assert code == 1 and needle in out, (code, out)


WF = ".github/workflows/"


@case("the shipped files pass, and say which two names they protect")
def _(tmp):
    code, out = run(copy(tmp))
    assert code == 0 and "review / verdict" in out and "docs-review / publish / verdict" in out, out


@case("a `verdict` that calls another workflow is refused: it would add a segment to the name")
def _(tmp):
    copy(tmp)
    path = os.path.join(tmp, WF, "review.yml")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("\n  verdict:\n")
    end = text.index("\n  capture:\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text[:start] + "\n  verdict:\n    uses: ./.github/workflows/publish-verdict.yml\n" + text[end:])
    refused(tmp, "not a job with steps of its own")


@case("the wrapper's job renamed is refused: the callers that have not moved would wait for ever")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "docs-review.yml", "\n  publish:\n    uses:", "\n  review:\n    uses:")
    refused(tmp, "not a single job `publish`")


@case("an input review.yml gains and the wrapper does not is refused")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "review.yml", "      extra-paths:\n        type: string",
         "      brand-new:\n        type: string\n        default: \"\"\n      extra-paths:\n        type: string")
    refused(tmp, "declare different inputs")


@case("a default that differs between the wrapper and review.yml is refused")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "docs-review.yml", "        default: \"needs-review\"", "        default: \"needs-look\"")
    refused(tmp, "input `review-label` differs in `default`")


@case("an input the wrapper does not hand over is refused")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "docs-review.yml", "      capture: ${{ inputs.capture }}\n", "")
    refused(tmp, "does not hand input `capture`")


@case("a secret the wrapper does not hand over is refused")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "docs-review.yml",
         "      exeris_inbox_private_key: ${{ secrets.exeris_inbox_private_key }}\n", "")
    refused(tmp, "does not hand 1 secret(s) to review.yml unchanged")


@case("a fix made to review.yml's `verdict` and not to publish-verdict.yml's is refused, step named")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "review.yml", "      - uses: actions/setup-python@v7\n        with: { python-version: \"3.14\" }\n      - run: pip install --quiet pyyaml jsonschema referencing\n",
         "      - uses: actions/setup-python@v7\n        with: { python-version: \"3.14\" }\n      - run: pip install --quiet pyyaml jsonschema referencing==0.1\n")
    refused(tmp, "differs from publish-verdict.yml's")


@case("a fix made to publish-verdict.yml's `capture` and not to review.yml's is refused")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "publish-verdict.yml", "      - run: pip install --quiet jsonschema\n",
         "      - run: pip install --quiet jsonschema==4.0\n")
    refused(tmp, "`capture` differs")


@case("a `verdict` job that holds `id-token` is refused: the publishing jobs never did")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "review.yml", "    permissions:\n      contents: read\n      pull-requests: read\n      issues: read\n    runs-on: ubuntu-latest\n    # WHAT THE PLAN DECIDED",
         "    permissions:\n      contents: read\n      pull-requests: read\n      issues: read\n      id-token: write\n    runs-on: ubuntu-latest\n    # WHAT THE PLAN DECIDED")
    refused(tmp, "`id-token`")


@case("a `capture` condition that reads the hand-over as a boolean is refused: 'false' is truthy")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "review.yml", "needs.handover.outputs.capture == 'true'", "needs.handover.outputs.capture")
    refused(tmp, "'false'` is truthy")


@case("this repository's caller under another job id is refused: its check would not be `review / verdict`")
def _(tmp):
    copy(tmp)
    edit(tmp, WF + "guardrails.yml", "\n  review:\n    # WAITS ON", "\n  docs-review:\n    # WAITS ON")
    refused(tmp, "has no job `review`")


@case("the caller example under another job id is refused: every repository copies it")
def _(tmp):
    copy(tmp)
    edit(tmp, "caller-example/guardrails.yml", "\n  review:\n    needs:", "\n  docs-review:\n    needs:")
    refused(tmp, "caller-example/guardrails.yml has no job `review`")


@case("a ruleset that requires the wrong name is refused")
def _(tmp):
    copy(tmp)
    edit(tmp, "rulesets/exeris-code-review.json", '"review / verdict"', '"review / publish / verdict"')
    refused(tmp, "exeris-code-review.json requires")


@case("a ruleset that requires a check from another integration is refused")
def _(tmp):
    copy(tmp)
    edit(tmp, "rulesets/exeris-code-verdict.json", '"integration_id": 15368', '"integration_id": 1')
    refused(tmp, "exeris-code-verdict.json requires")


@case("a repository in both rulesets is refused: it would require two names and one never reports")
def _(tmp):
    copy(tmp)
    path = os.path.join(tmp, "rulesets", "exeris-code-review.json")
    with open(path, encoding="utf-8") as fh:
        ruleset = json.load(fh)
    ruleset["conditions"]["repository_name"]["include"].append("exeris-docs")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ruleset, fh)
    refused(tmp, "sit in both rulesets")


@case("`.github` left in the old ruleset is refused: its own caller reports the new name")
def _(tmp):
    copy(tmp)
    edit(tmp, "rulesets/exeris-code-verdict.json", '"exeris-agent-harness",', '".github",\n        "exeris-agent-harness",')
    refused(tmp, "belongs to exeris-code-review.json")


def main() -> int:
    failures = 0
    for name, fn in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(tmp)
            except AssertionError as exc:
                failures += 1
                print(f"::error title=review_check_name_check_suite::{name}: {exc}")
            except Exception as exc:  # a case that cannot run is a case that did not pass
                failures += 1
                print(f"::error title=review_check_name_check_suite::{name}: {type(exc).__name__}: {exc}")
            else:
                print(f"ok    {name}")
    print(f"review_check_name_check_suite: ran {len(CASES)} cases, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
