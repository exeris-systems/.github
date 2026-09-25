#!/usr/bin/env python3
"""Cases for `review_aggregate.py` — one verdict from the runs of a review that ran as parts.

Every part's verdict is written into an execution log the way the runner leaves one, and validated
against this repository's own composed schema, so a case passes only if the aggregate is a verdict
the publication would accept. Each rule of the composition has a case: the worst decision wins, a
finding keeps its part, a check's worst report stands, a skipped part says why, and a part that ran
without a usable verdict is `missing` rather than dropped.

Usage: review_aggregate_suite.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import review_aggregate as ra  # noqa: E402
from publish_verdict import schema_errors  # noqa: E402

SCHEMA = os.path.join(ROOT, ".agents", "schemas", "verdict.schema.json")
FAILED: list[str] = []
TMP = tempfile.mkdtemp(prefix="review-aggregate-suite-")


def case(title):
    def wrap(fn):
        try:
            fn()
            print(f"ok    {title}")
        except Exception as exc:                            # every class is reported, none hidden
            FAILED.append(title)
            print(f"::error title=review_aggregate_suite::{title}: {type(exc).__name__}: {exc}")
        return fn
    return wrap


def validate(doc):
    return schema_errors(doc, SCHEMA)


def verdict(part, decision="PASS", findings=(), checks=None, scope="test-tooling", **extra):
    doc = {"agent": ra.AGENT, "decision": decision, "scope_class": scope,
           "findings": list(findings),
           "checks_run": checks or [{"check": "docs-lint", "result": "pass"}]}
    if part is not None:
        doc["part"] = part
    doc.update(extra)
    return doc


def finding(what, tag="STYLE"):
    doc = {"what": what, "why": "docs-style-guide.md#7", "fix": "state the boundary", "tag": tag}
    if tag == "HARD BLOCK":
        doc["blocking"] = True
    return doc


def log(name, *docs):
    """An execution log whose final message carries each document as a fenced `json` block."""
    text = "Review.\n" + "".join(f"\n```json\n{json.dumps(d)}\n```\n" for d in docs)
    path = os.path.join(TMP, f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([{"type": "result", "result": text}], fh)
    return path


PLAN = {"parts": ["pr", "docs", "records"],
        "skipped": {"code-docs": "no Java, TypeScript, Python, YAML or shell file in the diff",
                    "code": "no source, script, workflow or build file in the diff",
                    "repo": "the repository passes no `repo-routine`"}}


def status(agg):
    return {p["part"]: p["status"] for p in agg["parts"]}


@case("every planned part reviewed: the worst decision stands and the aggregate is a valid verdict")
def _():
    agg = ra.aggregate(PLAN, {
        "pr": log("a-pr", verdict("pr")),
        "docs": log("a-docs", verdict("docs", "CONDITIONAL", [finding("a page with no boundary")])),
        "records": log("a-rec", verdict("records", "BLOCKED", [
            finding("an amended ADR with no amendment", "HARD BLOCK")])),
    }, validate)
    assert agg["decision"] == "BLOCKED", agg
    assert agg["agent"] == ra.AGENT, agg
    assert validate(agg) == [], validate(agg)
    assert [f["part"] for f in agg["findings"]] == ["docs", "records"], agg["findings"]
    assert status(agg) == {"pr": "reviewed", "docs": "reviewed", "records": "reviewed",
                           "code-docs": "skipped", "code": "skipped",
                           "repo": "skipped"}, agg["parts"]
    assert [p.get("decision") for p in agg["parts"][:3]] == ["PASS", "CONDITIONAL", "BLOCKED"]


@case("a skipped part carries the plan's reason, and nothing is read for it")
def _():
    agg = ra.aggregate(PLAN, {"pr": log("b-pr", verdict("pr")), "docs": log("b-d", verdict("docs")),
                              "records": log("b-r", verdict("records")),
                              "code-docs": log("b-c", verdict("code-docs", "BLOCKED"))}, validate)
    skipped = {p["part"]: p for p in agg["parts"] if p["status"] == "skipped"}
    assert skipped["code-docs"]["reason"] == PLAN["skipped"]["code-docs"], skipped
    assert agg["decision"] == "PASS", "a log for a skipped part was read"


@case("a planned part with no log is missing, and the other parts' findings still stand")
def _():
    agg = ra.aggregate(PLAN, {
        "pr": log("c-pr", verdict("pr")),
        "docs": log("c-d", verdict("docs", "CONDITIONAL", [finding("a how-to that explains")])),
    }, validate)
    assert status(agg)["records"] == "missing", agg["parts"]
    assert "execution log" in [p for p in agg["parts"] if p["part"] == "records"][0]["reason"]
    assert agg["decision"] == "CONDITIONAL" and len(agg["findings"]) == 1, agg
    assert validate(agg) == [], validate(agg)


@case("a log with no verdict in it is missing, with a reason saying so")
def _():
    path = os.path.join(TMP, "d-empty.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([{"type": "result", "result": "I reviewed it and it is fine."}], fh)
    got, why = ra.part_verdict("records", path, validate)
    assert got is None and "no fenced" in why, why


@case("a verdict naming another part is not this part's answer")
def _():
    got, why = ra.part_verdict("records", log("e", verdict("docs")), validate)
    assert got is None and "`docs`" in why, why


@case("a verdict naming no part is the part of the stream it came from")
def _():
    got, why = ra.part_verdict("records", log("f", verdict(None)), validate)
    assert got is not None and why == "", why


@case("an invalid newest verdict is passed over for an older valid one, and alone it is missing")
def _():
    bad = verdict("docs", decision="MAYBE")
    good = verdict("docs", "CONDITIONAL", [finding("a how-to that explains")])
    got, _ = ra.part_verdict("docs", log("g1", good, bad), validate)
    assert got is not None and got["decision"] == "CONDITIONAL", got
    got, why = ra.part_verdict("docs", log("g2", bad), validate)
    assert got is None and "schema" in why and "MAYBE" in why, why


@case("one entry per check, and its worst report stands: fail over pass over not-run")
def _():
    agg = ra.aggregate({"parts": ["pr", "docs"], "skipped": {}}, {
        "pr": log("h-pr", verdict("pr", checks=[{"check": "docs-lint", "result": "pass"},
                                                {"check": "commit-lint", "result": "not-run"}])),
        "docs": log("h-d", verdict("docs", checks=[{"check": "docs-lint", "result": "fail"},
                                                   {"check": "commit-lint", "result": "pass"}])),
    }, validate)
    got = {c["check"]: c["result"] for c in agg["checks_run"]}
    assert got == {"docs-lint": "fail", "commit-lint": "pass"}, got


@case("the scope class is the `pr` part's, which is the part that judges it")
def _():
    agg = ra.aggregate({"parts": ["pr", "docs"], "skipped": {}}, {
        "docs": log("i-d", verdict("docs", scope="docs-only")),
        "pr": log("i-pr", verdict("pr", scope="runtime non-hot")),
    }, validate)
    assert agg["scope_class"] == "runtime non-hot", agg
    agg = ra.aggregate({"parts": ["pr", "docs"], "skipped": {}},
                       {"docs": log("i2-d", verdict("docs", scope="docs-only"))}, validate)
    assert agg["scope_class"] == "docs-only", "with `pr` missing, the first reviewed part's"


@case("suggestions are kept once each")
def _():
    agg = ra.aggregate({"parts": ["pr", "docs"], "skipped": {}}, {
        "pr": log("j-pr", verdict("pr", suggestions=["link the ADR"])),
        "docs": log("j-d", verdict("docs", suggestions=["link the ADR", "shorter title"])),
    }, validate)
    assert agg["suggestions"] == ["link the ADR", "shorter title"], agg


@case("a part the plan neither runs nor skips is missing, not silently absent")
def _():
    agg = ra.aggregate({"parts": ["pr"], "skipped": {"docs": "no `*.md` in the diff"}},
                       {"pr": log("n-pr", verdict("pr"))}, validate)
    got = {p["part"]: p for p in agg["parts"]}
    assert set(got) == set(ra.PARTS), got
    for part in ("records", "code-docs", "code", "repo"):
        assert got[part]["status"] == "missing" and "plan" in got[part]["reason"], got[part]
    assert got["docs"]["status"] == "skipped", got["docs"]


@case("handoffs from every reviewed part reach the composed verdict")
def _():
    handoff = {"from": ra.AGENT, "to": ra.AGENT, "reason": "the ADR registry is the owner",
               "blocking": False}
    agg = ra.aggregate({"parts": ["pr", "records"], "skipped": {}}, {
        "pr": log("o-pr", verdict("pr")),
        "records": log("o-r", verdict("records", handoffs=[handoff])),
    }, validate)
    assert agg.get("handoffs") == [handoff], agg
    assert validate(agg) == [], validate(agg)


@case("a composed verdict the schema refuses is an error, and nothing is written")
def _():
    # A schema every part's verdict satisfies and the composition cannot: it forbids `parts`, which
    # only an aggregate carries. The command must refuse to write what the publication would refuse.
    strict = os.path.join(TMP, "strict", "schemas", "verdict.schema.json")
    os.makedirs(os.path.dirname(strict), exist_ok=True)
    json.dump({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
               "properties": {"parts": False}}, open(strict, "w", encoding="utf-8"))
    plan = os.path.join(TMP, "p-plan.json")
    out = os.path.join(TMP, "p-verdict.json")
    json.dump({"parts": ["pr"], "skipped": {}}, open(plan, "w", encoding="utf-8"))
    got = subprocess.run([sys.executable, os.path.join(HERE, "review_aggregate.py"), "--plan",
                          plan, "--schema", strict, "--out", out,
                          "--log", "pr=" + log("p-pr", verdict("pr"))],
                         capture_output=True, text=True)
    assert got.returncode == 1, (got.returncode, got.stdout, got.stderr)
    assert "composed verdict does not satisfy the schema" in got.stdout, got.stdout
    assert not os.path.exists(out)


@case("no part reviewed: nothing to compose, and the command writes no verdict")
def _():
    assert ra.aggregate(PLAN, {}, validate) is None
    plan = os.path.join(TMP, "k-plan.json")
    out = os.path.join(TMP, "k-verdict.json")
    gh = os.path.join(TMP, "k-output")
    json.dump(PLAN, open(plan, "w", encoding="utf-8"))
    subprocess.run([sys.executable, os.path.join(HERE, "review_aggregate.py"), "--plan", plan,
                    "--schema", SCHEMA, "--out", out], check=True, capture_output=True,
                   env=dict(os.environ, GITHUB_OUTPUT=gh))
    lines = dict(x.split("=", 1) for x in open(gh, encoding="utf-8").read().splitlines())
    assert lines == {"written": "false", "missing": "pr,docs,records"}, lines
    assert not os.path.exists(out)


@case("the command writes the composed verdict and names what is missing")
def _():
    plan = os.path.join(TMP, "l-plan.json")
    out = os.path.join(TMP, "l-verdict.json")
    gh = os.path.join(TMP, "l-output")
    json.dump(PLAN, open(plan, "w", encoding="utf-8"))
    subprocess.run([sys.executable, os.path.join(HERE, "review_aggregate.py"), "--plan", plan,
                    "--schema", SCHEMA, "--out", out,
                    "--log", f"pr={log('l-pr', verdict('pr'))}",
                    "--log", "docs=" + log("l-d", verdict("docs", "CONDITIONAL",
                                                          [finding("a how-to that explains")]))],
                   check=True, capture_output=True, env=dict(os.environ, GITHUB_OUTPUT=gh))
    lines = dict(x.split("=", 1) for x in open(gh, encoding="utf-8").read().splitlines())
    assert lines == {"written": "true", "missing": "records"}, lines
    doc = json.load(open(out, encoding="utf-8"))
    assert doc["decision"] == "CONDITIONAL" and validate(doc) == [], doc


@case("a part name the plan does not know is refused on the command line")
def _():
    plan = os.path.join(TMP, "m-plan.json")
    json.dump(PLAN, open(plan, "w", encoding="utf-8"))
    got = subprocess.run([sys.executable, os.path.join(HERE, "review_aggregate.py"), "--plan",
                          plan, "--schema", SCHEMA, "--out", os.path.join(TMP, "m.json"),
                          "--log", "tests=x.json"], capture_output=True, text=True)
    assert got.returncode != 0 and "PART" in got.stderr, got.stderr


if __name__ == "__main__":
    total = sum(1 for line in open(__file__, encoding="utf-8") if line.startswith("@case("))
    print(f"review_aggregate_suite: ran {total} cases, {len(FAILED)} failures")
    sys.exit(1 if FAILED else 0)
