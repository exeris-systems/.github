#!/usr/bin/env python3
"""The publish step's mutation suite — ADR-087 Engineering Protocol 2.

Every rule §B.8 states is a way for the required check to be red, and a fail-closed gate is worth
exactly what its red paths are worth. Each case below mutates one thing about a conforming run and
asserts what the plan becomes. They run against the real command line, with no network and no
token, because the half that decides is the half that has to be checked.

Two cases EP.2 lists are not here: a run record naming `exeris-bot` in `agent.*`, and one merge
event producing one issue. Both belong to the capture and cross-repo steps (§C, §D), which
Engineering Protocol 5 and 7 enable after this one. A case for a step that does not exist would
assert against nothing.

Usage: publish_verdict_suite.py [--root .]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLANNER = os.path.join(HERE, "publish_verdict.py")


def verdict(**over) -> dict:
    """A conforming verdict. Every case below is this, with one thing changed."""
    doc = {
        "agent": "exeris-org-docs-reviewer",
        "decision": "PASS",
        "scope_class": "docs-only",
        "findings": [],
        "checks_run": [
            {"check": "docs-lint", "result": "pass"},
            {"check": "commit-lint", "result": "pass"},
            {"check": "pr-body-check", "result": "pass"},
        ],
    }
    doc.update(over)
    return doc


def finding(**over) -> dict:
    doc = {"what": "the composed schema closes no object",
           "why": "agents-md-schema.md#rule-13",
           "fix": "add unevaluatedProperties: false to the composition"}
    doc.update(over)
    return doc


def run(root: str, tmp: str, *, verdict_doc=None, comments=None, outcome="success",
        current="", mandatory="", execution_log=None) -> dict:
    """Run `plan` over one fixture and return the plan it wrote."""
    args = [sys.executable, PLANNER, "plan",
            "--schema", os.path.join(root, ".agents", "schemas", "verdict.schema.json"),
            "--labels-map", os.path.join(root, "labels-from-verdict.json"),
            "--out", os.path.join(tmp, "plan.json"),
            "--produce-outcome", outcome, "--current-labels", current,
            "--runner", "claude-code-action", "--routine", "docs-guardrails-review.md"]
    if verdict_doc is not None:
        path = os.path.join(tmp, "verdict.json")
        with open(path, "w", encoding="utf-8") as fh:
            if isinstance(verdict_doc, str):
                fh.write(verdict_doc)
            else:
                json.dump(verdict_doc, fh)
        args += ["--verdict", path]
    else:
        args += ["--verdict", os.path.join(tmp, "absent.json")]
    if comments is not None:
        path = os.path.join(tmp, "comments.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(comments, fh)
        args += ["--comments", path]
    if mandatory:
        args += ["--mandatory", mandatory]
    if execution_log is not None:
        path = os.path.join(tmp, "execution.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(execution_log, fh)
        args += ["--execution-log", path]
    proc = subprocess.run(args, capture_output=True, text=True,
                          env={**os.environ, "GITHUB_STEP_SUMMARY": os.path.join(tmp, "summary.md")})
    if proc.returncode != 0:
        raise AssertionError(f"planner exited {proc.returncode}: {proc.stderr[-800:]}")
    with open(os.path.join(tmp, "plan.json"), encoding="utf-8") as fh:
        return json.load(fh)


def gate(tmp: str, plan: dict) -> int:
    """The conclusion as the workflow takes it: the exit code of the gate subcommand."""
    path = os.path.join(tmp, "gate.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh)
    return subprocess.run([sys.executable, PLANNER, "gate", "--plan", path],
                          capture_output=True, text=True).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    root = os.path.abspath(ap.parse_args().root)

    cases: list[tuple[str, callable]] = []

    def case(name):
        def wrap(fn):
            cases.append((name, fn))
            return fn
        return wrap

    @case("a conforming PASS is green, labels nothing, and posts the review")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict())
        assert p["conclusion"] == "green", p
        assert p["labels_add"] == [] and p["labels_remove"] == [], p
        assert "L2 documentation and hygiene review" in p["comment"], p
        assert gate(tmp, p) == 0

    @case("an absent verdict is red, and says the produce job's outcome")
    def _(tmp):
        p = run(root, tmp, verdict_doc=None, outcome="failure")
        assert p["conclusion"] == "red", p
        assert p["verdict_source"] == "none", p
        assert "failure" in p["reason"], p
        assert gate(tmp, p) == 1

    @case("a verdict that is not JSON is red, not a crash")
    def _(tmp):
        p = run(root, tmp, verdict_doc="{not json at all")
        assert p["conclusion"] == "red" and "not valid JSON" in p["reason"], p
        assert gate(tmp, p) == 1

    @case("a schema-invalid verdict is red and nothing is labelled")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict(agent="some-other-role",
                                               findings=[finding(tag="HARD BLOCK")]))
        assert p["conclusion"] == "red", p
        assert p["labels_add"] == [], p
        assert "does not validate" in p["reason"], p
        assert gate(tmp, p) == 1

    @case("BLOCKED applies hard-block and is red")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict(
            decision="BLOCKED", findings=[finding(tag="HARD BLOCK", blocking=True)]))
        assert p["labels_add"] == ["hard-block"], p
        assert p["conclusion"] == "red" and "BLOCKED" in p["reason"], p
        assert gate(tmp, p) == 1

    @case("a PASS after a BLOCKED removes hard-block and is green")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict(), current="hard-block,type: documentation")
        assert p["labels_remove"] == ["hard-block"], p
        assert p["labels_add"] == [], p
        assert p["conclusion"] == "green", p
        assert gate(tmp, p) == 0

    @case("a label the map does not own survives a publication run")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict(), current="area: kernel,hard-block")
        assert "area: kernel" not in p["labels_remove"], p
        assert p["labels_remove"] == ["hard-block"], p

    @case("a mandatory gate reported not-run is published and not green")
    def _(tmp):
        v = verdict()
        v["checks_run"][0] = {"check": "docs-lint", "result": "not-run"}
        p = run(root, tmp, verdict_doc=v)
        assert p["conclusion"] == "red" and "docs-lint" in p["reason"], p
        assert "not-run" in p["comment"] and "docs-lint" in p["comment"], p
        assert gate(tmp, p) == 1

    @case("a non-mandatory gate reported not-run is published and stays green")
    def _(tmp):
        v = verdict()
        v["checks_run"].append({"check": "javadoc-gate", "result": "not-run"})
        p = run(root, tmp, verdict_doc=v)
        assert p["conclusion"] == "green", p
        assert "javadoc-gate" in p["comment"] and "not-run" in p["comment"], p

    @case("a deterministic skip is green and distinguishable from a crash")
    def _(tmp):
        p = run(root, tmp, verdict_doc=None, outcome="skipped")
        assert p["conclusion"] == "green", p
        assert "path filter" in p["reason"], p
        assert gate(tmp, p) == 0

    @case("a draft skip says which skip it was, not merely that one happened")
    def _(tmp):
        args = [sys.executable, PLANNER, "plan",
                "--schema", os.path.join(root, ".agents", "schemas", "verdict.schema.json"),
                "--labels-map", os.path.join(root, "labels-from-verdict.json"),
                "--out", os.path.join(tmp, "plan.json"), "--produce-outcome", "skipped",
                "--skip-reason", "the pull request is a draft or a dependency bump"]
        # Same redirect every other case gets through `run`: without it this planner appends to the
        # real step summary and the suite's own report arrives with a stray plan on top of it.
        subprocess.run(args, capture_output=True, text=True, check=True,
                       env={**os.environ, "GITHUB_STEP_SUMMARY": os.path.join(tmp, "summary.md")})
        with open(os.path.join(tmp, "plan.json"), encoding="utf-8") as fh:
            p = json.load(fh)
        assert p["conclusion"] == "green" and "draft" in p["reason"], p
        assert "path filter" not in p["reason"], p

    @case("CONDITIONAL is green — it is a merge precondition, not a refusal")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict(decision="CONDITIONAL",
                                               findings=[finding(tag="CONTRACT")]))
        assert p["conclusion"] == "green", p
        assert gate(tmp, p) == 0

    @case("every finding's tag maps, not just the first")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict(
            decision="CONDITIONAL",
            findings=[finding(tag="CROSS-REPO"), finding(tag="DOC DEBT"), finding(tag="STYLE")]))
        assert p["labels_add"] == ["cross-repo", "doc-debt"], p

    @case("with no file, the fenced block in a posted review is the verdict")
    def _(tmp):
        body = ("DOCS & HYGIENE — exeris-systems/.github\n\nSome prose.\n\n"
                "```json\n" + json.dumps(verdict(decision="CONDITIONAL",
                                                 findings=[finding(tag="DOC DEBT")])) + "\n```\n")
        p = run(root, tmp, verdict_doc=None, comments=[{"body": body}])
        assert p["verdict_source"] == "fenced block", p
        assert p["labels_add"] == ["doc-debt"], p
        assert p["conclusion"] == "green", p

    @case("a fenced block that is not a verdict is not mistaken for one")
    def _(tmp):
        body = "A finding quotes a schema:\n\n```json\n{\"type\": \"object\"}\n```\n"
        p = run(root, tmp, verdict_doc=None, comments=[{"body": body}])
        assert p["conclusion"] == "red" and p["verdict_source"] == "none", p

    @case("the file wins over a fenced block when both exist")
    def _(tmp):
        body = "```json\n" + json.dumps(verdict(decision="BLOCKED")) + "\n```"
        p = run(root, tmp, verdict_doc=verdict(), comments=[{"body": body}])
        assert p["verdict_source"] == "file" and p["conclusion"] == "green", p

    @case("the footer names the model when the runner exposed one")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict(), execution_log={"model": "claude-opus-5"})
        assert "model: `claude-opus-5`" in p["comment"], p["comment"][-400:]

    @case("the footer says the log is missing rather than implying a model")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict())
        assert "exposed no execution log" in p["comment"], p["comment"][-400:]
        assert "Engineering Protocol 4" in p["comment"], p["comment"][-400:]

    @case("the comment carries the marker the apply step edits in place on")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict())
        assert p["comment"].startswith("<!-- exeris-bot: l2-verdict -->"), p["comment"][:80]
        bad = run(root, tmp, verdict_doc=verdict(agent="nope"))
        assert "<!-- exeris-bot: l2-verdict -->" in bad["comment"], bad["comment"][:80]

    @case("the comment names the publisher and does not call it the reviewer")
    def _(tmp):
        p = run(root, tmp, verdict_doc=verdict())
        assert "publisher, never the reviewer" in p["comment"], p
        assert "runner: `claude-code-action`" in p["comment"], p

    failures = 0
    for name, fn in cases:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(tmp)
            except AssertionError as exc:
                failures += 1
                print(f"::error title=publish_verdict_suite::{name}: {exc}")
            except Exception as exc:  # a case that cannot run is a case that did not pass
                failures += 1
                print(f"::error title=publish_verdict_suite::{name}: {type(exc).__name__}: {exc}")

    # The count goes to stdout unconditionally, and to the step summary as well when there is one.
    # A gate that reports only into the summary leaves a log in which a passing run and a run that
    # did nothing look identical, and the run that did nothing is the one worth catching.
    print(f"publish_verdict_suite: ran {len(cases)} cases, {failures} failures")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## publish_verdict_suite\n\nRan **{len(cases)}** cases — "
                     f"**{failures} failures**.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
