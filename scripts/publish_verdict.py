#!/usr/bin/env python3
"""Plan the publication of one L2 review verdict — ADR-087 §B.5-B.10.

This script decides; it never writes. It reads the verdict a produce job left behind, validates it
against the composed schema in this repository, and writes `plan.json`: the labels to add, the
labels to remove, the comment to post, and the conclusion the required check must take. The
workflow applies that plan with the `exeris-bot` installation token and then gates on the
conclusion. Splitting it this way is what makes §B.8 testable — every rule below is exercised by
`publish_verdict_suite.py` with no network and no token, and a rule that cannot be exercised is a
rule nobody has checked.

Two sources, in the order §B.10 fixes. The file `verdict.json` is the contract. Where the runner
cannot write files the same object is a fenced `json` block at the end of the review it posted, and
that is the stated fallback, not an equal alternative: the plan records which one it used, so a
repository that silently stopped producing the file is visible rather than merely still green.

Fail-closed is the whole point (§B.8). A verdict that is absent, unparseable, invalid, `BLOCKED`, or
resting on an unrun mandatory gate is red. The one green that is not a verdict is the deterministic
path filter: a produce job the filter skipped never had a review to publish, and the plan says so in
those words so that the log distinguishes it from a runner that crashed.

Not handled here: §B.11's two verdicts on one pull request. This publishes the one verdict its
produce job made. Which of two routines decides `hard-block` is a question about running both, and
nothing in this repository runs both yet.

Usage:
  publish_verdict.py plan  --schema PATH --labels-map PATH --out plan.json
                           [--verdict PATH] [--comments PATH] [--produce-outcome OUTCOME]
                           [--mandatory a,b,c] [--runner NAME] [--routine FILE] [--routine-sha SHA]
                           [--execution-log PATH] [--current-labels a,b]
  publish_verdict.py gate  --plan plan.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# The gates the routine reads before it reviews, and the ones a verdict may not rest on as `not-run`.
# `docs-guardrails-review.md` names them; this default mirrors that sentence and `--mandatory`
# overrides it for a repository whose caller runs more.
MANDATORY_DEFAULT = "docs-lint,commit-lint,pr-body-check"

# The one green that is not a verdict (§B.8). It is worded so the log says which skip it was:
# a filter that decided there was nothing to review reads differently from a runner that died.
SKIP_DEFAULT = ("the produce job was skipped by the deterministic path filter — no Markdown or "
                "Java changed, so there was no review to publish")

FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.S)

# The bot edits its own comment rather than adding one per push. A pull request reviewed eight
# times carries one verdict — the current one — and the eight are in the job logs where a history
# belongs. The marker is how the apply step finds the comment to edit; it is invisible in the
# rendered body.
MARKER = "<!-- exeris-bot: l2-verdict -->"


def emit(text: str) -> None:
    """The report sink every checker here uses: the step summary in Actions, stdout otherwise."""
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)


def fenced_verdicts(comments_json: str) -> list[dict]:
    """Every fenced `json` block in a comment dump that looks like a verdict, oldest comment first.

    A review is prose with a block at the end of it, and prose can contain other blocks — a schema
    fragment a finding quotes, say. Requiring `agent` and `decision` is what separates the verdict
    from an illustration, and it is the same pair the schema requires.
    """
    try:
        payload = json.loads(comments_json)
    except json.JSONDecodeError:
        return []
    bodies = []
    for item in payload if isinstance(payload, list) else [payload]:
        if isinstance(item, dict) and isinstance(item.get("body"), str):
            bodies.append(item["body"])
    found = []
    for body in bodies:
        for block in FENCE.findall(body):
            try:
                doc = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict) and "agent" in doc and "decision" in doc:
                found.append(doc)
    return found


def load_verdict(args) -> tuple[dict | None, str, str]:
    """The verdict, the source it came from, and why it is absent when it is."""
    if args.verdict and os.path.exists(args.verdict):
        try:
            with open(args.verdict, encoding="utf-8") as fh:
                doc = json.load(fh)
        except json.JSONDecodeError as exc:
            return None, "file", f"`{args.verdict}` is not valid JSON ({exc})"
        if not isinstance(doc, dict):
            return None, "file", f"`{args.verdict}` is not a JSON object"
        return doc, "file", ""
    if args.comments and os.path.exists(args.comments):
        with open(args.comments, encoding="utf-8") as fh:
            candidates = fenced_verdicts(fh.read())
        if candidates:
            return candidates[-1], "fenced block", ""
        return None, "none", ("no `verdict.json` and no fenced `json` verdict in any comment on this "
                              "pull request")
    return None, "none", "no `verdict.json` was produced and no comments were read"


def schema_errors(verdict: dict, schema_path: str) -> list[str]:
    """Validation messages, most specific first, or an empty list."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    root = os.path.dirname(os.path.dirname(os.path.abspath(schema_path)))
    registry = Registry()
    for base, _, names in os.walk(root):
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (json.JSONDecodeError, OSError):
                continue
            registry = registry.with_resource(
                "file://" + os.path.abspath(path).replace(os.sep, "/"),
                Resource.from_contents(doc, default_specification=DRAFT202012))
    # The composed schema carries no `$id`, so its relative `$ref`s resolve against the URI it was
    # retrieved from. Validating through a `$ref` to that URI is what gives them a base.
    uri = "file://" + os.path.abspath(schema_path).replace(os.sep, "/")
    validator = Draft202012Validator({"$ref": uri}, registry=registry)
    out = []
    for err in sorted(validator.iter_errors(verdict), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        out.append(f"{where}: {err.message}")
    return out


def plan_labels(verdict: dict, mapping: dict, current: set[str]) -> tuple[list[str], list[str]]:
    """Labels to add and to remove, from the decision and from every finding's tag (§B.7).

    Keyed off a finding's tag rather than a verdict-wide severity, because one review reports a
    `[CROSS-REPO]` and a `[DOC DEBT]` and both labels belong on the pull request. A label the map
    does not name is never touched: a repository's own `area:` labels and anything a human applied
    survive a publication run.
    """
    decision = verdict.get("decision")
    want: set[str] = set()
    by_decision = mapping.get("decision", {}).get(decision)
    if by_decision:
        want.add(by_decision)
    tag_map = {k: v for k, v in mapping.get("tag", {}).items() if k != "$comment"}
    for finding in verdict.get("findings") or []:
        label = tag_map.get(finding.get("tag"))
        if label:
            want.add(label)
    # A label this verdict asks for is never also removed, and a label the pull request does not
    # carry is never removed either: the apply step would be deleting something that is not there.
    remove = set(mapping.get("remove-on", {}).get(decision) or []) - want
    return sorted(want - current), sorted(remove & current)


def unrun_mandatory(verdict: dict, mandatory: list[str]) -> list[str]:
    """Mandatory gates the verdict reports as `not-run` — §B.8's second red."""
    names = []
    for entry in verdict.get("checks_run") or []:
        if entry.get("result") == "not-run" and entry.get("check") in mandatory:
            names.append(entry["check"])
    return sorted(set(names))


def provenance(args) -> list[str]:
    """The footer of §A.3 — who ran, under what routine, at what SHA.

    `model_id` and the harness version come from the runner's execution log. Where the runner does
    not expose one the footer says exactly that rather than leaving the reader to assume a model:
    ADR-087 Engineering Protocol 4 asks whether the action exposes it, and this is the line that
    answers the question on the first real run instead of by prediction.
    """
    lines = [f"runner: `{args.runner or 'unknown'}`"]
    if args.routine:
        at = f" at `{args.routine_sha[:7]}`" if args.routine_sha else ""
        lines.append(f"routine: `{args.routine}`{at}")
    log = args.execution_log
    if log and os.path.exists(log):
        try:
            with open(log, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (json.JSONDecodeError, OSError):
            doc = None
        model = None
        if isinstance(doc, dict):
            model = doc.get("model") or doc.get("model_id") or (doc.get("usage") or {}).get("model")
        lines.append(f"model: `{model}`" if model else
                     "model: the execution log carries no model id")
    else:
        lines.append("model: the runner exposed no execution log (ADR-087 Engineering Protocol 4)")
    return lines


def compose_comment(verdict: dict, args, unrun: list[str], source: str) -> str:
    """The published review: the verdict's own words, every `not-run` verbatim, then provenance."""
    decision = verdict.get("decision", "?")
    out = [MARKER, f"## L2 documentation and hygiene review — **{decision}**", ""]
    label = verdict.get("decision_label")
    if label:
        out += [str(label), ""]
    findings = verdict.get("findings") or []
    if findings:
        out += ["| Tag | Where | Finding | Fix |", "|:--|:--|:--|:--|"]
        for f in findings:
            tag = f.get("tag") or ""
            where = f.get("location") or ""
            blocking = " **(blocking)**" if f.get("blocking") else ""
            out.append(f"| {tag}{blocking} | `{where}` | {f.get('what','')} — {f.get('why','')} "
                       f"| {f.get('fix','')} |")
        out.append("")
    else:
        out += ["No findings.", ""]
    checks = verdict.get("checks_run") or []
    if checks:
        out += ["### Gates the review read", ""]
        for c in checks:
            out.append(f"- `{c.get('check')}`: **{c.get('result')}**"
                       + (f" — {c['detail']}" if c.get("detail") else ""))
        out.append("")
    # §B.9: never swallowed, and said in the place a reader looks rather than only in the exit code.
    if unrun:
        out += [f"> A mandatory gate did not run: {', '.join('`' + n + '`' for n in unrun)}. "
                f"This verdict rests on a check nobody performed, so the required check is red "
                f"whatever the decision says.", ""]
    out += ["---", "", f"Published by `exeris-bot`; it is the publisher, never the reviewer. "
                       f"Verdict read from the {source}.", ""]
    out += [f"- {line}" for line in provenance(args)]
    return "\n".join(out)


def cmd_plan(args) -> int:
    plan: dict = {"labels_add": [], "labels_remove": [], "comment": "", "conclusion": "red",
                  "reason": "", "verdict_source": "none"}

    if args.produce_outcome == "skipped":
        plan.update(conclusion="green", verdict_source="none",
                    reason=args.skip_reason or SKIP_DEFAULT)
        return finish(plan, args)

    verdict, source, why = load_verdict(args)
    plan["verdict_source"] = source
    if verdict is None:
        plan["reason"] = (f"no verdict to publish: {why}. The produce job reported "
                          f"`{args.produce_outcome or 'unknown'}`.")
        return finish(plan, args)

    errors = schema_errors(verdict, args.schema)
    if errors:
        plan["reason"] = ("the verdict does not validate against the composed schema — "
                          + "; ".join(errors[:5]))
        plan["comment"] = (MARKER + "\n## L2 review verdict refused\n\nA verdict was produced and it does not "
                           "conform to `.agents/schemas/verdict.schema.json`:\n\n"
                           + "\n".join(f"- `{e}`" for e in errors[:10])
                           + "\n\nNothing was labelled. The required check is red.\n")
        return finish(plan, args)

    with open(args.labels_map, encoding="utf-8") as fh:
        mapping = json.load(fh)
    current = {s for s in (args.current_labels or "").split(",") if s}
    add, remove = plan_labels(verdict, mapping, current)
    mandatory = [s for s in (args.mandatory or MANDATORY_DEFAULT).split(",") if s]
    unrun = unrun_mandatory(verdict, mandatory)

    plan["labels_add"] = add
    plan["labels_remove"] = remove
    plan["comment"] = compose_comment(verdict, args, unrun, source)
    decision = verdict.get("decision")
    if decision == "BLOCKED":
        plan["reason"] = "the verdict is BLOCKED"
    elif unrun:
        plan["reason"] = ("the verdict rests on a mandatory gate that did not run: "
                          + ", ".join(unrun))
    else:
        plan["conclusion"] = "green"
        plan["reason"] = f"the verdict is {decision} and every mandatory gate reported"
    return finish(plan, args)


def finish(plan: dict, args) -> int:
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    emit(f"## publish_verdict\n\n"
         f"- source: **{plan['verdict_source']}**\n"
         f"- conclusion: **{plan['conclusion']}** — {plan['reason']}\n"
         f"- labels + `{'`, `'.join(plan['labels_add']) if plan['labels_add'] else '(none)'}`\n"
         f"- labels − `{'`, `'.join(plan['labels_remove']) if plan['labels_remove'] else '(none)'}`")
    return 0


def cmd_gate(args) -> int:
    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    green = plan.get("conclusion") == "green"
    marker = "::notice::" if green else "::error::"
    print(f"{marker}publish_verdict: {plan.get('conclusion')} — {plan.get('reason')}")
    return 0 if green else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--schema", required=True)
    p.add_argument("--labels-map", required=True)
    p.add_argument("--out", default="plan.json")
    p.add_argument("--verdict")
    p.add_argument("--comments")
    p.add_argument("--produce-outcome", default="")
    p.add_argument("--skip-reason", default="")
    p.add_argument("--mandatory", default="")
    p.add_argument("--runner", default="")
    p.add_argument("--routine", default="")
    p.add_argument("--routine-sha", default="")
    p.add_argument("--execution-log", default="")
    p.add_argument("--current-labels", default="")
    p.set_defaults(func=cmd_plan)

    g = sub.add_parser("gate")
    g.add_argument("--plan", default="plan.json")
    g.set_defaults(func=cmd_gate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
