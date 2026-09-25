#!/usr/bin/env python3
"""One verdict from the runs of a review that ran as parts — ADR-087.

Each part of `docs-guardrails-review.md` is judged by its own run, and each run leaves its verdict
in its own execution log. The publication reads one verdict, so this composes them into one, under
the same role and the same schema:

- `decision` is the worst any reviewed part reached: BLOCKED over CONDITIONAL over PASS.
- `findings` are every part's, each marked with the part that raised it.
- `checks_run` is one entry per check. Where two parts report one check differently, a failure
  outranks a pass and a pass outranks `not-run`: a part that could not see a gate says nothing
  against one that did.
- `parts` says what each part came to: `reviewed` with its decision, `skipped` with the plan's
  reason, or `missing` with the reason no verdict was taken from its run.

A part the plan ran and that left no verdict satisfying the schema is `missing`, never dropped,
and so is a part the plan does not name at all. The
aggregate still carries every finding the other parts reported, and the publication is what refuses
to pass a check on an incomplete one. With no part reviewed there is nothing to compose, and no
verdict is written.

Usage: review_aggregate.py --plan plan.json --schema SCHEMA --log PART=PATH [--log …] --out FILE
  With GITHUB_OUTPUT set, `written` (true/false) and `missing` (comma-separated parts) are written
  there as well.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from publish_verdict import execution_verdicts, schema_errors  # noqa: E402
from review_plan import PARTS  # noqa: E402

AGENT = "exeris-org-docs-reviewer"
SEVERITY = {"PASS": 0, "CONDITIONAL": 1, "BLOCKED": 2}
RESULT_RANK = {"not-run": 0, "pass": 1, "fail": 2}


def part_verdict(part: str, log: str | None, validate) -> tuple[dict | None, str]:
    """The newest verdict in one part's log that satisfies the schema and names this part, or why
    there is none. A verdict naming no part is taken as this part's: the stream it came from is the
    part's own. One naming another part is not this part's answer, whatever it says."""
    if not log or not os.path.exists(log):
        return None, "the part's run left no execution log"
    candidates = execution_verdicts(log)
    if not candidates:
        return None, "the part's run carries no fenced `json` verdict"
    refused = ""
    for doc in reversed(candidates):
        if doc.get("part", part) != part:
            refused = refused or f"its verdict names part `{doc.get('part')}`"
            continue
        errors = validate(doc)
        if errors:
            refused = refused or f"its verdict does not satisfy the schema: {first_cause(errors)}"
            continue
        return doc, ""
    return None, refused


def first_cause(errors: list[str]) -> str:
    """The first message that is a cause. A composition validates through a `$ref` into the base,
    and when anything in that branch fails, the root reports every property as unevaluated — a
    secondary line that names the verdict's own fields and never the fault."""
    real = [e for e in errors if not e.startswith("<root>: Unevaluated properties")]
    return (real or errors)[0]


def merge_checks(verdicts: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for verdict in verdicts:
        for entry in verdict.get("checks_run") or []:
            name = entry.get("check")
            held = merged.get(name)
            if held is None or RESULT_RANK[entry["result"]] > RESULT_RANK[held["result"]]:
                merged[name] = dict(entry)
    return list(merged.values())


def aggregate(plan: dict, logs: dict[str, str], validate) -> dict | None:
    """The composed verdict, or None when no part produced one to compose."""
    reviewed: list[tuple[str, dict]] = []
    parts: list[dict] = []
    for part in PARTS:
        if part in plan.get("skipped", {}):
            parts.append({"part": part, "status": "skipped", "reason": plan["skipped"][part]})
            continue
        if part not in plan.get("parts", []):
            # A plan names every part, run or skipped. One it is silent about was neither decided
            # to run nor decided not to, and calling it skipped would state a reason nobody gave.
            parts.append({"part": part, "status": "missing",
                          "reason": "the plan neither ran nor skipped this part"})
            continue
        verdict, why = part_verdict(part, logs.get(part), validate)
        if verdict is None:
            parts.append({"part": part, "status": "missing", "reason": why})
            continue
        reviewed.append((part, verdict))
        parts.append({"part": part, "status": "reviewed", "decision": verdict["decision"]})
    if not reviewed:
        return None

    decision = max((v["decision"] for _, v in reviewed), key=SEVERITY.__getitem__)
    scope = next((v["scope_class"] for p, v in reviewed if p == "pr"),
                 reviewed[0][1]["scope_class"])
    findings = [dict(f, part=p) for p, v in reviewed for f in v.get("findings") or []]
    suggestions: list[str] = []
    for _, v in reviewed:
        suggestions += [s for s in v.get("suggestions") or [] if s not in suggestions]
    out = {
        "agent": AGENT,
        "decision": decision,
        "scope_class": scope,
        "findings": findings,
        "checks_run": merge_checks([v for _, v in reviewed]),
        "parts": parts,
    }
    if suggestions:
        out["suggestions"] = suggestions
    handoffs = [h for _, v in reviewed for h in v.get("handoffs") or []]
    if handoffs:
        out["handoffs"] = handoffs
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--log", action="append", default=[], metavar="PART=PATH")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    logs = {}
    for item in a.log:
        part, sep, path = item.partition("=")
        if not sep or part not in PARTS:
            ap.error(f"--log takes PART=PATH with PART one of {', '.join(PARTS)}, not {item!r}")
        logs[part] = path

    verdict = aggregate(plan, logs, lambda doc: schema_errors(doc, a.schema))
    if verdict is not None:
        errors = schema_errors(verdict, a.schema)
        if errors:
            print(f"::error title=review_aggregate::the composed verdict does not satisfy the "
                  f"schema: {first_cause(errors)}")
            return 1
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(verdict, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    missing = [p["part"] for p in (verdict or {}).get("parts", []) if p["status"] == "missing"]
    if verdict is None:
        missing = list(plan.get("parts", []))
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"written={'true' if verdict is not None else 'false'}\n")
            fh.write(f"missing={','.join(missing)}\n")
    summary = (f"review_aggregate: {len(plan.get('parts', []))} part(s) planned, "
               f"{len(missing)} missing" + (f" ({', '.join(missing)})" if missing else "")
               + (f"; decision {verdict['decision']}" if verdict else "; no verdict written"))
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
