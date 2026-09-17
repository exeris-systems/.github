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
# Why a producing job did not run, split by whether the reason is a statement ABOUT THE PULL
# REQUEST or merely about this event. A draft, a bot's own pull request and a fork have nothing to
# review and green is honest. A label change, a push with no review asked for, or a kind this file
# does not recognise say nothing, so the standing verdict decides instead — the difference between
# them was the fail-open measured on #40.
# The decisions that may green a check on their own. `BLOCKED` is refused by name for the message it
# earns; everything else — `NONE`, and anything a later schema adds — is refused by absence, because
# the alternative is a list that has to be kept in step with an enum it does not own.
PASSING_DECISIONS = frozenset({"PASS", "CONDITIONAL"})
ABOUT_THE_PULL_REQUEST = frozenset({"fork", "draft-or-bot"})
SAYS_NOTHING_ABOUT_THE_DIFF = frozenset({"not-ready", "bot-event"})

# Why a skip of one of those two kinds is a green, keyed by the kind itself. The caller computes the
# same sentence in a second YAML expression that asks the EVENT over again, and the two disagree: a
# fork whose event was a label change was described as "the event was a label change", and a
# `not-ready` run as "a draft or a dependency bump", neither of which was what happened. One of them
# has to be the authority, and it is the kind — the kind is what the colour is decided from, so a
# reason derived from anything else is a second opinion about a question already answered. The
# caller's string stays the fallback for a kind this file does not know; it is no longer consulted
# for one it does.
# The same two skips as a sentence addressed to a READER of the pull request rather than to a log.
# A notice on a pull request says what is true of it now; it does not narrate what an earlier run
# said, because replacing the notice IS the correction and a note explaining that it corrects
# something is a note about itself.
NOT_RUN_SAID = {
    "fork": ("This pull request comes from a fork. A fork receives no secrets, so the runner has no "
             "credential to review with."),
    "draft-or-bot": "This pull request is a draft or was opened by a bot. The routine reads neither.",
}
NOTHING_TO_READ = ("No Markdown or Java changed in this pull request, so the routine had nothing "
                   "to read.")

SKIP_IS_GREEN_BECAUSE = {
    "fork": ("the pull request comes from a fork, which receives no secrets, so the runner has no "
             "credential to review with"),
    "draft-or-bot": ("the pull request is a draft or was opened by a bot, and this review reads "
                     "neither"),
}

MANDATORY_DEFAULT = "docs-lint,commit-lint,pr-body-check"

# The one green that is not a verdict (§B.8). It is worded so the log says which skip it was:
# a filter that decided there was nothing to review reads differently from a runner that died.
SKIP_DEFAULT = ("the produce job was skipped by the deterministic path filter — no Markdown or "
                "Java changed, so there was no review to publish")

FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.S)

# The bot edits its own comment rather than adding one per push. A pull request reviewed eight
# times carries one verdict per routine — the current one — and the eight are in the job logs where
# a history belongs. The marker is how the apply step finds the comment to edit, and it is keyed by
# ROLE: ADR-087 §B.11 has a repository running its own routine and the organisation's, and one
# comment overwritten by the other is one of the two reviews suppressed.
#
# It also carries the decision, which is what lets a later run of a different routine see what this
# one concluded without re-reading a verdict it does not have. That is the whole arbiter: §B.11 says
# the stricter decides `hard-block`, and nothing else on a pull request records who blocked it.
MARKER_RE = re.compile(
    r"<!-- exeris-bot: l2-verdict agent=([^\s]+) decision=([A-Z]+)(?: sha=([0-9a-f]{7,40}))? -->")

# Anything a model wrote is something the bot signs, because the bot copies a finding's words into
# its own comment. A finding whose text carried a marker forged the arbiter's channel — the one
# §B.11's "the stricter decides" stands on — from inside the review being judged, and the author
# check could not see it because the author really was the bot.
# Escaped rather than stripped. Cutting `<!--` out once is defeated by `<<!--!--`, whose remainder
# is `<!--` again; escaping the angle brackets leaves no way to spell a delimiter at all. Markdown
# renders the entities as the characters, so a reader still sees what the finding said.
def plain(value) -> str:
    """Text from the repository under review, unable to carry markup or break the table it lands in.

    EVERY string that reaches a comment the bot signs goes through here, not only a finding's: the
    validator quotes an instance value back at you, and a pin mismatch quotes a version string, and
    both come from the reviewed repository as surely as a finding does. Escaping at the call sites
    meant remembering; escaping at the boundary means the next path added gets it for free.

    The pipe is escaped because these values land in a Markdown table, and one pipe in a finding
    turns a five-column row into seven, dropping the `fix` into a cell GitHub truncates.
    """
    return (str(value if value is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("|", "\\|"))


def truthy(value: str) -> bool:
    """A workflow-expression boolean as it arrives here: the string `true`, and nothing else.

    Not `bool(value)`. Every one of these crosses a `with:` block as text, so the string `"false"`
    is truthy to Python and the empty string an absent signal rather than a `false` — the mistake
    that once turned a crashed producing job into a green path-filter skip.
    """
    return str(value).strip().lower() == "true"


OVERRIDE_RE = re.compile(
    r"<!-- exeris-bot: l2-override by=([^\s]+) sha=([0-9a-f]{7,40}) -->")


def override_marker(by: str, sha: str) -> str:
    """The machine-readable header of a human's review of a change the routine refuses to read."""
    return f"<!-- exeris-bot: l2-override by={by} sha={sha} -->"


def standing_override(comments_json: str, bot_login: str) -> tuple[str, str] | None:
    """The last human review recorded on this pull request, as `(login, sha)`.

    Read only from comments the BOT wrote, for the reason `standing_verdicts` gives: the marker is
    plain text in a public comment, and this one greens a required check. A person types the label;
    the bot is what turns the label into a record, and the record is what is trusted afterwards.
    """
    found = None
    for c in comments(comments_json):
        if c.get("author") != bot_login:
            continue
        m = OVERRIDE_RE.match(c["body"])
        if m:
            found = (m.group(1), m.group(2))
    return found


def marker(agent: str, decision: str, sha: str = "") -> str:
    """The comment's machine-readable header, carrying the commit the verdict covers.

    Without the commit a verdict outlives the tree it judged: the head moves and the published
    comment, and the green check beside it, go on describing code that is no longer there.
    """
    at = f" sha={sha}" if sha else ""
    return f"<!-- exeris-bot: l2-verdict agent={agent} decision={decision}{at} -->"


def standing_for(comments_json: str, agent: str, bot_login: str) -> tuple[str, str] | None:
    """This role's own last published verdict, as `(decision, sha)`, or None if it has none."""
    found = None
    for c in comments(comments_json):
        if c.get("author") != bot_login:
            continue
        m = MARKER_RE.match(c["body"])
        if m and m.group(1) == agent:
            found = (m.group(2), m.group(3) or "")
    return found


def standing_verdicts(comments_json: str, exclude_agent: str, bot_login: str) -> dict[str, str]:
    """What every OTHER routine's published comment currently says, by role.

    Read from the markers the bot itself wrote — and only those. The marker is plain text in a public
    comment, so anyone can type one; a forged `decision=BLOCKED` would pin a label nothing removes,
    and a forged `PASS` is worse. Author first, pattern second.
    """
    out: dict[str, str] = {}
    for c in comments(comments_json):
        if c.get("author") != bot_login:
            continue
        # Position 0 only. `compose_comment` always opens with the marker, so a marker anywhere else
        # in a comment the bot signed came from text the bot was handed, not from a decision it made.
        m = MARKER_RE.match(c["body"])
        if m and m.group(1) != exclude_agent:
            out[m.group(1)] = m.group(2)
    return out


def emit(text: str) -> None:
    """The report sink every checker here uses: the step summary in Actions, stdout otherwise."""
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)


def comments(comments_json: str) -> list[dict]:
    """The comment dump, as entries carrying who wrote them."""
    try:
        payload = json.loads(comments_json)
    except json.JSONDecodeError:
        return []
    return [c for c in (payload if isinstance(payload, list) else [payload])
            if isinstance(c, dict) and isinstance(c.get("body"), str)]


def fenced_verdicts(comments_json: str, trusted: set[str]) -> list[dict]:
    """Fenced `json` verdicts from comments a machine wrote, oldest first.

    ADR-087 §B.10's fallback is "the fenced block from the review THE RUNNER POSTED", and the author
    is the whole of that sentence. A pull request is a surface anyone with an account can write to:
    without this filter a comment saying `{"decision": "PASS"}` turns the required check green, which
    is the gate refusing nothing at all. The schema constrains the shape and can say nothing about
    who wrote it.

    Trust is a named list and an empty list trusts nobody. "Any Bot account" was the first reading
    and it is not a filter: `claude-code-action` posts as `github-actions[bot]`, an identity every
    workflow in the repository can write under, INCLUDING a workflow the reviewed pull request adds.
    That would let a pull request green its own required check, against the one invariant this whole
    path rests on — that a pull request is judged by a contract it does not control. Until a real run
    has shown what login the runner posts under, the fallback is off, and the file is the contract
    §B.10 always said it was.

    A review is prose with a block at the end of it, and prose can contain other blocks; requiring
    `agent` and `decision` separates the verdict from an illustration.
    """
    found = []
    if not trusted:
        return found
    for c in sorted(comments(comments_json), key=lambda c: str(c.get("created_at", ""))):
        if c.get("author_type") != "Bot" or c.get("author") not in trusted:
            continue
        for block in FENCE.findall(c["body"]):
            try:
                doc = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict) and "agent" in doc and "decision" in doc:
                found.append(doc)
    return found


def execution_verdicts(path: str) -> list[dict]:
    """Fenced `json` verdicts in what the runner itself said, oldest first.

    The third source and the best one. The runner writes an execution log, the produce job uploads it
    already, and the model's own final message is in it — so the verdict reaches the publish step
    without the runner needing permission to write a file or to post a comment, both of which its
    harness denies (measured: one `Write` call and twenty-five `gh` calls, all refused by the action's
    permission mode). It is also the only source whose authorship is not a question: an artefact of
    the run is not a surface anyone can write to, which is why §B.10's comment fallback needs a
    trusted-author list and this needs none.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return []
    try:
        doc = json.loads(raw)
        events = doc if isinstance(doc, list) else [doc]
    except json.JSONDecodeError:
        events = []
        for line in raw.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    texts: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        message = ev.get("message")
        for part in (message.get("content") if isinstance(message, dict) else None) or []:
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                texts.append(part["text"])
        if ev.get("type") == "result" and isinstance(ev.get("result"), str):
            texts.append(ev["result"])
    found = []
    for block in FENCE.findall("\n".join(texts)):
        try:
            doc = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict) and "agent" in doc and "decision" in doc:
            found.append(doc)
    return found


def load_verdict(args, validates) -> tuple[dict | None, str, str]:
    """The verdict, the source it came from, and why it is absent when it is.

    The fenced fallback searches a pull request that may carry more than one review. ADR-087 §B.11
    puts a repository's own routine and the organisation's on the same pull request, each posting its
    own fenced verdict, and taking "the last block on the page" would publish whichever review
    finished later under this routine's name. The schema is the filter: a composed schema names the
    role it belongs to, so a candidate that validates here is this routine's and one that does not is
    somebody else's. Newest first, because a routine that ran twice should publish its latest answer.
    """
    if args.verdict and os.path.exists(args.verdict):
        try:
            with open(args.verdict, encoding="utf-8") as fh:
                doc = json.load(fh)
        except json.JSONDecodeError as exc:
            return None, "file", f"`{args.verdict}` is not valid JSON ({exc})"
        if not isinstance(doc, dict):
            return None, "file", f"`{args.verdict}` is not a JSON object"
        return doc, "file", ""
    if args.execution_log and os.path.exists(args.execution_log):
        candidates = execution_verdicts(args.execution_log)
        for doc in reversed(candidates):
            if validates(doc):
                return doc, "execution log", ""
        if candidates:
            return candidates[-1], "execution log", ""
    if args.comments and os.path.exists(args.comments):
        trusted = {s for s in (args.verdict_authors or "").split(",") if s}
        if not trusted:
            return None, "none", ("no `verdict.json`, and the fenced fallback is off because no "
                                  "trusted author is named (`verdict-authors`)")
        with open(args.comments, encoding="utf-8") as fh:
            candidates = fenced_verdicts(fh.read(), trusted)
        for doc in reversed(candidates):
            if not validates(doc):
                continue
            return doc, "fenced block", ""
        if candidates:
            # Report against the newest, which is the one a reader will look at.
            return candidates[-1], "fenced block", ""
        return None, "none", ("no `verdict.json`, and no comment by a trusted author carries a "
                              "fenced `json` verdict")
    return None, "none", ("no `verdict.json`, no verdict in the runner's execution log, and no "
                          "comments were read")


_VALIDATOR_CACHE: dict[str, object] = {}


def schema_errors(verdict: dict, schema_path: str) -> list[str]:
    """Validation messages, most specific first, or an empty list.

    The validator is built once per schema. It is called once per fenced candidate and again for the
    verdict itself, and rebuilding it walked the whole `.agents/` tree each time — O(candidates ×
    files) of I/O inside the step that gates a merge.
    """
    cached = _VALIDATOR_CACHE.get(schema_path)
    if cached is not None:
        return _errors(cached, verdict)

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
    _VALIDATOR_CACHE[schema_path] = validator
    return _errors(validator, verdict)


def _errors(validator, verdict: dict) -> list[str]:
    out = []
    for err in sorted(validator.iter_errors(verdict), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        out.append(f"{where}: {err.message}")
    return out


def plan_labels(verdict: dict, mapping: dict, current: set[str],
                standing: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    """Labels to add and to remove, from the decision and from every finding's tag (§B.7).

    Keyed off a finding's tag rather than a verdict-wide severity, because one review reports a
    `[CROSS-REPO]` and a `[DOC DEBT]` and both labels belong on the pull request.

    A label the map names is applied when a verdict asks for it; whether it comes back off when a
    verdict stops asking is `retire-when-absent`, a decision the map makes per label. A debt is
    retired — a `[DOC DEBT]` finding used to leave `doc-debt` standing after a later review found
    nothing, the pull request asserting a debt its own current review denies (exeris-docs#123). A
    label stating what the change IS is not: `cross-repo` survives a verdict that raises no
    cross-repo finding, because such a review has not made the change single-repo.

    A label the map does not name is still never touched: a repository's own `area:` labels, and
    anything a human applied that this file knows nothing about, survive a publication run.
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
    # Which labels come back off is the map's decision per label, not a rule over all of them. A debt
    # is retired by a verdict that no longer finds it; a label stating what the change IS is not —
    # `cross-repo` stays, because a review raising no cross-repo finding has not made the change
    # single-repo. `remove-on` is unioned in: it can name a label the two maps do not.
    retire = set(mapping.get("retire-when-absent", {}).get("labels") or [])
    # A label this verdict asks for is never also removed, and a label the pull request does not
    # carry is never removed either: the apply step would be deleting something that is not there.
    remove = (retire | set(mapping.get("remove-on", {}).get(decision) or [])) - want
    # §B.11's arbiter. A `PASS` from one routine does not take the block off a pull request another
    # routine is still blocking — the stricter decides. Without this the two reviews race, and the
    # one that finishes last wins regardless of what it found.
    held = {mapping.get("decision", {}).get(d) for d in (standing or {}).values()}
    held.discard(None)
    remove -= held
    return sorted(want - current), sorted(remove & current)


def ci_results(raw: str) -> dict[str, str]:
    """What CI knows about its own gates, as `{gate: conclusion}`.

    The authority on whether `docs-lint` ran is the workflow that ran it, not a model reading a page
    it may not be able to reach. Measured on the first real run: the runner's harness denied every
    `gh` call, so the review reported all three mandatory gates as `not-run` and the required check
    was red for ever — a verdict about the pull request's prose, defeated by the reviewer's inability
    to read a step summary.
    """
    try:
        doc = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return {k: str(v) for k, v in doc.items()} if isinstance(doc, dict) else {}


def unrun_mandatory(verdict: dict, mandatory: list[str], ci: dict[str, str] | None = None) -> list[str]:
    """Mandatory gates this verdict does not stand on — §B.8's second red.

    Two ways to not stand on one, and only the first was implemented. A gate reported `not-run` says
    so. A gate the verdict never mentions says the same thing more quietly: the schema requires
    `checks_run` to be non-empty and requires no particular entry in it, so a review naming one gate
    it liked satisfied every check here and went green claiming every mandatory gate had reported.
    Absence and `not-run` are the same epistemic state and get the same answer.
    """
    reported = {}
    for entry in verdict.get("checks_run") or []:
        if entry.get("check") in mandatory:
            reported[entry["check"]] = entry.get("result")
    # CI's own conclusion wins where it has one. The verdict still publishes what the review read —
    # §B.9 — but what the gate decides on is what the workflow observed.
    for gate, conclusion in (ci or {}).items():
        if gate in mandatory and conclusion:
            reported[gate] = "pass" if conclusion == "success" else "fail"
    return sorted(g for g in mandatory if reported.get(g, "not-run") == "not-run")


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
        model = harness = version = None
        if isinstance(doc, dict):
            model = doc.get("model") or doc.get("model_id") or (doc.get("usage") or {}).get("model")
            h = doc.get("harness") if isinstance(doc.get("harness"), dict) else {}
            harness = h.get("client") or doc.get("client")
            version = h.get("version") or doc.get("version")
        elif isinstance(doc, list):
            # The shape the runner actually writes: an event list whose `system`/`init` event names
            # the model and the harness version, and whose `result` event names every model used.
            init = next((e for e in doc if isinstance(e, dict) and e.get("type") == "system"
                         and e.get("subtype") == "init"), {})
            result = next((e for e in doc if isinstance(e, dict)
                           and e.get("type") == "result"), {})
            used = sorted((result.get("modelUsage") or {}))
            model = ", ".join(used) or init.get("model")
            version = init.get("claude_code_version")
            harness = "claude-code" if version else None
        lines.append(f"model: {plain(model)}" if model else
                     "model: the execution log carries no model id")
        # §A.3 names provider, model id, harness AND version, and "provenance survives a swap" is
        # the reason: a footer that cannot say which client ran, at what version, cannot tell one
        # runner from another after the swap it exists to survive. Absent is said, never implied.
        lines.append(f"harness: {plain(harness)} {plain(version)}" if harness and version else
                     f"harness: the execution log names "
                     f"{'no version' if harness else 'no client'}")
    else:
        lines.append("model: the runner exposed no execution log (ADR-087 Engineering Protocol 4)")
    return lines


def compose_comment(verdict: dict, args, unrun: list[str], source: str,
                    pin_problem: str = "") -> str:
    """The published review: the verdict's own words, every `not-run` verbatim, then provenance."""
    decision = verdict.get("decision", "?")
    agent = str(verdict.get("agent", "unknown"))
    out = [marker(agent, str(decision), args.head_sha),
           f"## L2 review — `{agent}` — **{decision}**", ""]
    label = verdict.get("decision_label")
    if label:
        out += [plain(label), ""]
    findings = verdict.get("findings") or []
    if findings:
        out += ["| Tag | Where | Finding | Fix |", "|:--|:--|:--|:--|"]
        for f in findings:
            tag = plain(f.get("tag"))
            where = plain(f.get("location"))
            blocking = " **(blocking)**" if f.get("blocking") else ""
            # No backticks around `where`: CommonMark does not decode entities inside a code span,
            # so an escaped `Foo<T>.java` would render as `Foo&lt;T&gt;.java`. Escaped plain text
            # renders as the characters it means.
            out.append(f"| {tag}{blocking} | {where} | {plain(f.get('what'))} — "
                       f"{plain(f.get('why'))} | {plain(f.get('fix'))} |")
        out.append("")
    else:
        out += ["No findings.", ""]
    # Three fields the schema carries and the comment dropped. A review that writes a non-blocking
    # nit, or names what must be re-checked before merge, or says another role has to look, had all
    # of it discarded between the verdict and the page a human reads — so the reader saw "No
    # findings" where the reviewer had written several paragraphs.
    suggestions = [s for s in (verdict.get("suggestions") or []) if s]
    if suggestions:
        out += ["### Suggestions — none of these blocks the merge", ""]
        out += [f"- {plain(s)}" for s in suggestions]
        out.append("")
    required = [r for r in (verdict.get("required_validation") or []) if r]
    if required:
        out += ["### Before this merges, re-check", ""]
        out += [f"- {plain(r)}" for r in required]
        out.append("")
    handoffs = [h for h in (verdict.get("handoffs") or []) if isinstance(h, dict)]
    if handoffs:
        out += ["### Handed to another role", ""]
        for h in handoffs:
            block = " **(blocking)**" if h.get("blocking") else ""
            out.append(f"- {plain(h.get('from'))} → {plain(h.get('to'))}{block}: "
                       f"{plain(h.get('reason'))}")
        out.append("")
    checks = verdict.get("checks_run") or []
    if checks:
        out += ["### Gates the review read", ""]
        for c in checks:
            out.append(f"- {plain(c.get('check'))}: **{plain(c.get('result'))}**"
                       + (f" — {plain(c['detail'])}" if c.get("detail") else ""))
        out.append("")
    # §B.9: never swallowed, and said in the place a reader looks rather than only in the exit code.
    if unrun:
        out += [f"> A mandatory gate did not run: {', '.join('`' + n + '`' for n in unrun)}. "
                f"This verdict rests on a check nobody performed, so the required check is red "
                f"whatever the decision says.", ""]
    if pin_problem:
        out += [f"> The pull request's own bundle pin does not match the one this verdict was "
                f"validated against: {plain(pin_problem)} A verdict written to one shape and checked "
                f"against another is not a verdict about this pull request, so the required check "
                f"is red whatever the decision says (ADR-087 §B.6a).", ""]
    out += ["---", "", f"Published by `exeris-bot`; it is the publisher, never the reviewer. "
                       f"Verdict read from the {source}.", ""]
    out += [f"- {line}" for line in provenance(args)]
    return "\n".join(out)


def blocking_findings(verdict: dict) -> list[str]:
    """The findings this verdict itself marked blocking, by where they are.

    The gate read `decision` and nothing else, so a review that set `CONDITIONAL` and marked a
    finding `blocking: true` produced a green check next to a comment rendering that finding as
    **(blocking)**. Measured on exeris-docs#121: the routine said the forbidden-import list
    contradicted the guard it cites, marked it blocking, and the pull request came out mergeable.
    A decision and a finding disagreeing is not a tie to resolve in the decision's favour — the
    stricter of the two is the one a reader acts on, which is §B.11's rule applied within one
    verdict rather than between two.
    """
    return [str(f.get("location") or f.get("why") or "?")
            for f in (verdict.get("findings") or []) if f.get("blocking") is True]


def human_review(args) -> tuple[str, str] | None:
    """A standing human review that still covers this head, or None.

    Scoped to a pull request that changes `.github/workflows/`, which is the one case the routine
    cannot read at all: `claude-code-action` refuses to start when a workflow file differs from the
    default branch's copy, so its BLOCKED there is a refusal rather than a judgement. Anywhere else
    the review decides and this is not a way around it — the label is taken off and ignored.

    It ages exactly as a verdict does. The record carries the commit the person looked at, so the
    next push leaves it behind and the check goes red again rather than trading on an old reading.
    """
    if not truthy(args.workflow_touching):
        return None
    if not (args.comments and os.path.exists(args.comments)):
        return None
    with open(args.comments, encoding="utf-8") as fh:
        standing = standing_override(fh.read(), args.bot_login)
    head = (args.head_sha or "")[:7]
    if standing and head and standing[1][:7] == head:
        return standing
    return None


def restate_notice(plan: dict, args, said: str) -> None:
    """Put the CURRENT state in the standing `not run` notice.

    The notice is a statement about the pull request, not a log line: a reader takes it for what is
    true now. Every branch that publishes one edits it in place on the next run — except the
    branches that conclude green without a verdict, which wrote nothing at all, so a notice naming
    a gate that had since passed stood next to a green check. Measured on exeris-ai-execution#1,
    where `docs-lint` was named as failing forty minutes after it passed.

    `said` is that current state in one sentence. It does not mention the notice it replaces:
    replacing it IS the correction, and a note explaining that it corrects something is a note
    about itself rather than about the pull request.

    Only an existing `NONE` notice is rewritten, and only when one is actually there. Writing one
    where none stood would leave `standing_gate` a `NONE` to refuse on the next label event, turning
    a pull request that is legitimately green red — the fix would have grown the fault it removes.
    A comment carrying a real verdict is never touched: the marker this searches for names `NONE`.
    """
    plan["agent"] = plan["agent"] or args.expect_agent or "unknown"
    if not (args.comments and os.path.exists(args.comments)):
        return
    with open(args.comments, encoding="utf-8") as fh:
        standing = standing_for(fh.read(), plan["agent"], args.bot_login)
    if not standing or standing[0] != "NONE":
        return
    plan["marker_search"] = f"<!-- exeris-bot: l2-verdict agent={plan['agent']} decision=NONE"
    plan["comment"] = (marker(plan["agent"], "NONE", args.head_sha)
                       + "\n## L2 review — not run\n\n"
                       + said + " The required check is green.\n")


def standing_gate(plan: dict, args) -> int:
    """No verdict came out of this run, so the STANDING one decides the colour.

    The reason a run produced nothing is not itself an answer about the pull request. Only two
    reasons are: it is a draft or a bot's own pull request, and it is a fork this workflow cannot
    review. Every other reason — no review was asked for, the event was a label change, a skip kind
    nobody has seen before — leaves the question open, and the answer is the last verdict: it is
    green only if one exists, still covers this head, and did not block.
    """
    plan["agent"] = args.expect_agent or "unknown"
    plan["marker_search"] = f"<!-- exeris-bot: l2-verdict agent={plan['agent']} decision=NONE"
    standing = None
    if args.comments and os.path.exists(args.comments):
        with open(args.comments, encoding="utf-8") as fh:
            standing = standing_for(fh.read(), plan["agent"], args.bot_login)
    head = (args.head_sha or "")[:7]
    by_hand = human_review(args)
    if by_hand:
        plan.update(conclusion="green",
                    reason=(f"{by_hand[0]} reviewed this workflow change by hand, recorded against "
                            f"{by_hand[1][:7]}"))
        # The same restatement: a person reviewing by hand is the current state of this pull
        # request, and the standing notice has no way to learn that on its own.
        restate_notice(plan, args, f"`{plain(by_hand[0])}` reviewed this change by hand, "
                                   f"recorded against `{by_hand[1][:7]}`.")
    elif standing is None:
        plan["reason"] = ("no review has run on this pull request yet — apply the review label "
                          "when it is ready to look at")
    elif standing[1] and head and standing[1][:7] != head:
        plan["reason"] = (f"the standing verdict covers {standing[1][:7]} and this pull request "
                          f"is at {head} — it has moved since the review, so the review does not "
                          f"describe it")
    elif standing[0] == "BLOCKED":
        plan["reason"] = "the standing verdict is BLOCKED and nothing has been reviewed since"
    elif standing[0] not in PASSING_DECISIONS:
        # `NONE` above all. The publication writes that marker precisely when NO review ran — gates
        # red, verdict unreadable, runner produced nothing — and a later run was reading it back as
        # a verdict that passed, because this branch only ever refused `BLOCKED`. Measured on
        # exeris-docs#123: one run published `decision=NONE` and was cancelled, the run that replaced
        # it reported "the standing verdict is NONE and still covers ac4b63d" and went green on a
        # pull request nothing had reviewed.
        #
        # Named forward rather than backward: a decision this file does not recognise is not a pass
        # either. The enum can grow in the schema without this turning into a hole the day it does.
        plan["reason"] = (f"the standing comment records `{standing[0]}`, which is not a verdict that "
                          f"passes — it is what the publication writes when no review ran")
    else:
        plan.update(conclusion="green",
                    reason=f"the standing verdict is {standing[0]} and still covers {head}")
    return finish(plan, args)


def cmd_plan(args) -> int:
    plan: dict = {"labels_add": [], "labels_remove": [], "comment": "", "conclusion": "red",
                  "reason": "", "verdict_source": "none", "standing": {}, "agent": "",
                  "marker_search": ""}

    # A person closing the hole the routine names in its own Trigger section. `claude-code-action`
    # refuses to start on a pull request that changes a workflow file, so the routine never reviews
    # one, and in this repository that is nine of the last ten pull requests. Making the check
    # required without this would mean an administrator's override on almost every merge, and an
    # override used routinely has stopped being one.
    #
    # The bot records who looked and at which commit; the label is only the request, and it comes
    # straight back off, exactly as `needs-l2-review` does. What the check reads afterwards is the
    # record, not the label — a label anyone can re-apply after a push, while the record carries the
    # commit it was made against and is left behind by the next one.
    if args.override_by:
        if truthy(args.workflow_touching):
            head = (args.head_sha or "")[:7]
            plan["marker_search"] = "<!-- exeris-bot: l2-override"
            plan["comment"] = (override_marker(plain(args.override_by), args.head_sha or "")
                               + "\n## L2 review — by hand\n\n"
                               + f"`{plain(args.override_by)}` reviewed this change themselves and "
                               + f"recorded it against `{head}`.\n\nThis routine cannot read a pull "
                               + "request that changes a workflow file: the runner refuses to start "
                               + "when one differs from the default branch's copy. The record covers "
                               + f"`{head}` and nothing after it — a push leaves it behind and the "
                               + "check goes red again.\n")
            plan.update(conclusion="green",
                        reason=(f"{args.override_by} reviewed this workflow change by hand and it "
                                f"is recorded against {head}"))
            return finish(plan, args)
        # Off a pull request the routine CAN read, the label decides nothing. Falling through rather
        # than going red on it: someone labelling the wrong pull request should not turn a passing
        # review into a failure, and the review that did run is still the answer.
        plan["reason"] = "the human-review label does not apply here; the review itself decides"

    # A producing job skipped because a gate it depends on failed is not a skip with nothing to
    # review — it is a review that never happened on a pull request that is already broken. Green
    # there would be the skipped-required-check problem wearing a different hat.
    ci = ci_results(args.l1_results)
    failed_l1 = sorted(g for g, c in ci.items() if c and c != "success")
    # The readiness trigger's own path. No review ran because none was asked for, so the question is
    # whether the last one still describes this tree — ADR-087 §B.8's fourth red. A verdict is about
    # the commit it read; once the head moves past it, publishing its green would be publishing a
    # review of code that is gone.
    if args.skip_kind in SAYS_NOTHING_ABOUT_THE_DIFF:
        return standing_gate(plan, args)
    if args.produce_outcome == "skipped" and failed_l1:
        # `cancelled` is not `failure`. A gate cancelled by `concurrency` reported nothing, and
        # telling the author it "did not pass" sends them to fix three green checks — measured on
        # exeris-docs#124, where a label applied seconds after opening killed the run and the comment
        # blamed the gates it had killed.
        cancelled = sorted(g for g in failed_l1 if ci.get(g) == "cancelled")
        broke = [g for g in failed_l1 if g not in cancelled]
        said, said_md = [], []
        if broke:
            said.append("did not pass: " + ", ".join(broke))
            said_md.append("did not pass: " + ", ".join(f"`{g}`" for g in broke))
        if cancelled:
            said.append("were cancelled before they finished: " + ", ".join(cancelled))
            said_md.append("were cancelled before they finished: "
                           + ", ".join(f"`{g}`" for g in cancelled))
        plan.update(conclusion="red", verdict_source="none",
                    reason="the review did not run because the gates it waits on " + "; ".join(said))
        # The readiness trigger fires once and was being consumed even when it produced nothing: a
        # run that WAS ready but lost its gates left the pull request with no review and no way back
        # to one except a human re-applying the label. The request is re-applied here, so the next
        # run with green gates performs the review the lost one was asked for. It is removed again
        # only when a review has actually run, which is the branch that removes it.
        if args.skip_kind == "ready" and args.review_label:
            plan["labels_add"] = [args.review_label]
        plan["agent"] = args.expect_agent or "unknown"
        plan["marker_search"] = f"<!-- exeris-bot: l2-verdict agent={plan['agent']} decision=NONE"
        # The same words as the reason above. They were split there and left hardcoded here, so a
        # reader of the comment was told three cancelled gates "did not pass" while the log beside it
        # said they were cancelled — the fix reached one of the two places that say the same thing.
        tail = ("A cancelled gate reported nothing rather than failing: the run carrying it was "
                "replaced, and the one that replaced it may already have them green.\n"
                if cancelled and not broke else
                "Fix those first; the review runs once they are green.\n")
        plan["comment"] = (marker(plan["agent"], "NONE", args.head_sha)
                           + "\n## L2 review — not run\n\nThe L1 gates this review waits on "
                           + "; ".join(said_md) + ".\n\n" + tail)
        return finish(plan, args)
    # §B.8's one green without a verdict, and the only one. It is decided here rather than in the
    # workflow's shell because it is the rule most likely to be got wrong and it was: an early crash
    # leaves `produce-relevant` EMPTY, and "not true" read as "filtered out" turned every crash into
    # a green skip with a log line claiming a filter had run. Absence of a signal is not a `false`.
    # A skip whose kind is not one of the two above says nothing about whether this pull request has
    # been reviewed, so it cannot be a green on its own — it falls back to the standing verdict, like
    # `not-ready` does. Measured: on #40 the publication applied `hard-block` from a BLOCKED verdict,
    # the label event started a run whose ACTOR was the bot, that run reported green, and because it
    # was the last run for the check name the pull request read as CLEAN with a BLOCKED verdict
    # standing on it. An unrecognised skip kind lands here too, and fails closed rather than open.
    if args.produce_outcome == "skipped" and args.skip_kind not in ABOUT_THE_PULL_REQUEST:
        return standing_gate(plan, args)
    if args.produce_outcome == "skipped":
        plan.update(conclusion="green", verdict_source="none",
                    reason=(SKIP_IS_GREEN_BECAUSE.get(args.skip_kind)
                            or args.skip_reason or "the producing job did not run"))
        restate_notice(plan, args, NOT_RUN_SAID.get(args.skip_kind,
                                                    "The producing job did not run."))
        return finish(plan, args)
    if args.produce_outcome == "success" and args.produce_relevant == "false":
        plan.update(conclusion="green", verdict_source="none", reason=SKIP_DEFAULT)
        restate_notice(plan, args, NOTHING_TO_READ)
        return finish(plan, args)

    verdict, source, why = load_verdict(args, lambda d: not schema_errors(d, args.schema))
    plan["verdict_source"] = source
    if verdict is None:
        plan["agent"] = args.expect_agent or "unknown"
        plan["reason"] = (f"no verdict to publish: {why}. The producing job reported "
                          f"`{args.produce_outcome or 'unknown'}`.")
        # The absent verdict is the case §B.9's reasoning matters most for, and it was the one case
        # that posted nothing: a required check went red with the explanation only in a job log.
        # Replaces only a previous no-verdict notice, never a comment carrying a real verdict. A
        # later run that produced nothing — a crashed runner, a refused actor — otherwise overwrote
        # findings somebody has to act on, and the pull request lost them. Both can stand: the last
        # verdict, and a note that a later run reached none.
        plan["marker_search"] = f"<!-- exeris-bot: l2-verdict agent={plan['agent']} decision=NONE"
        plan["comment"] = (marker(plan["agent"], "NONE", args.head_sha)
                           + "\n## L2 review — no verdict\n\n"
                           + f"The producing job reported `{args.produce_outcome or 'unknown'}` and "
                           + f"{why}.\n\nThe required check is red because nothing was reviewed, "
                             "not because a review found something. Re-run the job, or look at its "
                             "log to see why it produced nothing.\n")
        return finish(plan, args)

    plan["agent"] = str(verdict.get("agent", ""))
    # A real verdict replaces whatever this role last published, decision included.
    plan["marker_search"] = f"<!-- exeris-bot: l2-verdict agent={plan['agent']} "
    errors = schema_errors(verdict, args.schema)
    if errors:
        plan["reason"] = ("the verdict does not validate against the composed schema — "
                          + "; ".join(errors[:5]))
        # A refused verdict still gets a marker, so the comment is edited in place on the next push
        # instead of a fresh refusal joining the last one. Its decision reads INVALID: it is not a
        # decision the arbiter may act on, and nothing in the label map names that word.
        # The role comes from the caller, not from a verdict that just failed validation: the field
        # was never checked against anything, and it is about to key a marker.
        refused_agent = args.expect_agent or "unknown"
        plan["agent"] = refused_agent
        plan["comment"] = (marker(refused_agent, "INVALID", args.head_sha)
                           + "\n## L2 review verdict refused\n\nA verdict was produced and it does not "
                           "conform to `.agents/schemas/verdict.schema.json`:\n\n"
                           # The validator quotes the instance value it refused, so these
                           # strings are the reviewed repository's words too.
                           + "\n".join(f"- {plain(e)}" for e in errors[:10])
                           + "\n\nNothing was labelled. The required check is red.\n")
        return finish(plan, args)

    with open(args.labels_map, encoding="utf-8") as fh:
        mapping = json.load(fh)
    # From a file, one per line. A label name may contain a comma — `area: kernel, core` is a legal
    # label — and the comma-joined string turned one into two labels that exist nowhere. The apply
    # step already takes this care with spaces; this is the same care one step earlier.
    current: set[str] = set()
    if args.current_labels_file and os.path.exists(args.current_labels_file):
        with open(args.current_labels_file, encoding="utf-8") as fh:
            current = {line.rstrip("\n") for line in fh if line.strip()}
    standing = {}
    if args.comments and os.path.exists(args.comments):
        with open(args.comments, encoding="utf-8") as fh:
            standing = standing_verdicts(fh.read(), str(verdict.get("agent", "")),
                                         args.bot_login)
    add, remove = plan_labels(verdict, mapping, current, standing)
    plan["standing"] = standing
    # Extends the routine's list, never replaces it. A caller naming its own gate meant to add
    # one; silently dropping the three the routine makes mandatory is the opposite of what a
    # fail-closed gate should do with an ambiguous input.
    mandatory = sorted({s for s in (MANDATORY_DEFAULT + "," + (args.mandatory or "")).split(",") if s})
    unrun = unrun_mandatory(verdict, mandatory, ci)

    plan["labels_add"] = add
    plan["labels_remove"] = remove
    plan["comment"] = compose_comment(verdict, args, unrun, source, args.pin_problem)
    decision = verdict.get("decision")
    if args.pin_problem:
        # §B.6a's mismatch is about this verdict — it was written against one base and validated
        # against another — so it belongs in this verdict's comment and this verdict's conclusion.
        # A second red step beside the gate would be a red the author cannot tell from BLOCKED.
        plan["reason"] = f"the reviewed repository's bundle pin is not this one's: {args.pin_problem}"
    elif decision == "BLOCKED" and human_review(args):
        by_hand = human_review(args)
        plan["conclusion"] = "green"
        plan["reason"] = (f"the verdict is BLOCKED because this routine cannot read a workflow "
                          f"change, and {by_hand[0]} reviewed it by hand against {by_hand[1][:7]}")
    elif decision == "BLOCKED":
        plan["reason"] = "the verdict is BLOCKED"
    elif blocking_findings(verdict):
        at = blocking_findings(verdict)
        plan["reason"] = (f"the verdict is {decision}, but it marks "
                          + (f"{len(at)} findings as blocking" if len(at) > 1
                             else "a finding as blocking")
                          + f" ({', '.join(at[:3])}) — a finding that blocks blocks, whatever the "
                          f"decision beside it says")
    elif unrun:
        plan["reason"] = ("the verdict rests on a mandatory gate that did not run: "
                          + ", ".join(unrun))
    else:
        plan["conclusion"] = "green"
        plan["reason"] = f"the verdict is {decision} and every mandatory gate reported"
    return finish(plan, args)


def finish(plan: dict, args) -> int:
    # In `finish` rather than in the branch that records the override, because the verdict path
    # assigns `labels_remove` wholesale from the label map and would drop it. The label is a request;
    # once this run has read it, it has been answered whatever the answer was.
    if getattr(args, "override_by", "") and getattr(args, "override_label", ""):
        if args.override_label not in plan["labels_remove"]:
            plan["labels_remove"] = plan["labels_remove"] + [args.override_label]
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    print(f"publish_verdict: source={plan['verdict_source']} conclusion={plan['conclusion']} "
          f"add={plan['labels_add']} remove={plan['labels_remove']} — {plan['reason']}")
    emit(f"## publish_verdict\n\n"
         f"- source: **{plan['verdict_source']}**\n"
         f"- conclusion: **{plan['conclusion']}** — {plan['reason']}\n"
         f"- labels + `{'`, `'.join(plan['labels_add']) if plan['labels_add'] else '(none)'}`\n"
         f"- labels − `{'`, `'.join(plan['labels_remove']) if plan['labels_remove'] else '(none)'}`")
    return 0


def cmd_gate(args) -> int:
    try:
        with open(args.plan, encoding="utf-8") as fh:
            plan = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::publish_verdict: no plan to gate on ({type(exc).__name__}). The planning "
              f"step did not finish, so nothing about this review is known — red.")
        return 1
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
    p.add_argument("--current-labels-file", default="",
                   help="labels already on the pull request, one per line")
    p.add_argument("--produce-relevant", default="true")
    p.add_argument("--l1-results", default="",
                   help='{"docs-lint": "success", ...} — what CI concluded about its own gates')
    p.add_argument("--verdict-authors", default="",
                   help="logins whose comments may carry a verdict; any Bot when empty")
    p.add_argument("--expect-agent", default="",
                   help="the role this publication is for; it keys the marker when no verdict exists")
    p.add_argument("--pin-problem", default="",
                   help="what caller_bundle_check.py said, when it said anything (ADR-087 §B.6a)")
    p.add_argument("--skip-kind", default="",
                   help="why the producing job did not run. `fork` and `draft-or-bot` are about the pull request and are a green on their own; `not-ready`, `bot-event` and anything this file does not recognise hand the colour to the standing verdict")
    p.add_argument("--head-sha", default="",
                   help="the pull request head: recorded in the marker when a review runs, and\n                        compared with the standing verdict's commit when one does not")
    p.add_argument("--review-label", default="needs-l2-review",
                   help="the label that asks for a review. Re-applied when a ready run lost its "
                        "gates, so the request survives the run that carried it")
    p.add_argument("--override-label", default="l2-human-reviewed",
                   help="the label a person applies to record that they reviewed a change this "
                        "routine cannot read — one that touches a workflow file")
    p.add_argument("--override-by", default="",
                   help="the login that applied the override label IN THIS EVENT, empty otherwise")
    p.add_argument("--workflow-touching", default="false",
                   help="whether this pull request changes a file under .github/workflows/, which "
                        "is the only place the override applies")
    p.add_argument("--bot-login", default="exeris-bot[bot]",
                   help="the only author whose published markers the arbiter reads")
    p.set_defaults(func=cmd_plan)

    g = sub.add_parser("gate")
    g.add_argument("--plan", default="plan.json")
    g.set_defaults(func=cmd_gate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
