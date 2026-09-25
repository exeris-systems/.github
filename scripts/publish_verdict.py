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
                           [--execution-log PATH] [--current-labels a,b] [--reviews PATH]
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
# REQUEST or merely about this event. A fork and a draft have nothing to review and green is
# honest: a fork can carry no credential, and a draft is not mergeable, so its colour decides
# nothing. A label change, a push with no review asked for, or a kind this file does not recognise
# say nothing, so the standing verdict decides instead — the difference was the fail-open on #40.
#
# `bot-authored` USED TO SIT IN THE FIRST SET, inside `draft-or-bot`, and it is the one member that
# does not belong there. A draft cannot merge; a pull request opened by a bot CAN, so greening it
# is a merge gate reporting a pass on a change nothing read. ADR-087 §B.8 never named it — it names
# a passing verdict and the path-filter skip whose producing job succeeded, and says every other
# state is red. The implementation was wider than the ADR it implements.
#
# Nothing had ever taken that branch, either: no pull request authored by a bot has ever reached a
# repository that calls this routine. A branch nothing has reached is not a working branch, and the
# first thing to reach this one would be the first pull request an agent harness opens — a green
# required check on the worst possible first exercise. Skipping the WORK on a dependency bump is a
# decision about cost and stays; claiming a PASS for it is not that decision.
# The decisions that may green a check on their own. `BLOCKED` is refused by name for the message it
# earns; everything else — `NONE`, and anything a later schema adds — is refused by absence, because
# the alternative is a list that has to be kept in step with an enum it does not own.
PASSING_DECISIONS = frozenset({"PASS", "CONDITIONAL"})
ABOUT_THE_PULL_REQUEST = frozenset({"fork", "draft"})
# `draft-or-bot` is deliberately in NEITHER set. A caller pinned before the split still sends it,
# and an unrecognised kind hands the colour to the standing verdict — which is the safe half of
# what it used to mean, and red where it used to be wrong.
# `review-event` is a review submitted or dismissed. It changes no diff and never starts the model,
# so what it can change is only whether a person has reviewed this head, and the standing branch
# is where that question is asked.
SAYS_NOTHING_ABOUT_THE_DIFF = frozenset({"not-ready", "bot-event", "bot-authored", "review-event"})
# THE TWO SETS ARE CONSULTED IN ORDER, not independently: `SAYS_NOTHING_ABOUT_THE_DIFF` is asked
# first and returns, so a kind in both would have its membership of the second silently dead. Found
# by a mutation that added `bot-authored` back to the green set and failed nothing at all — the
# mutation was a no-op, which reads exactly like a rule that holds.
assert not (ABOUT_THE_PULL_REQUEST & SAYS_NOTHING_ABOUT_THE_DIFF), \
    "a skip kind in both sets takes the first branch and its place in the second decides nothing"

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
    "draft": ("This pull request is a draft. The routine reads one when it is marked ready, and a "
              "draft cannot be merged in the meantime."),
}
NOTHING_TO_READ = ("No Markdown or Java changed in this pull request, so the routine had nothing "
                   "to read.")

SKIP_IS_GREEN_BECAUSE = {
    "fork": ("the pull request comes from a fork, which receives no secrets, so the runner has no "
             "credential to review with"),
    "draft": ("the pull request is a draft, which this review does not read and GitHub does not "
              "merge"),
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


HUMAN_PRINCIPAL = "User"


def human_principal(login: str, kind: str) -> bool:
    """Is the principal that acted a person?

    `kind` is the webhook payload's `sender.type`: `User` for an account a person signs into, `Bot`
    for a GitHub App acting as itself. It is the field GitHub defines for this question, and it is
    asked HERE rather than in a workflow expression so that the answer has cases against it.

    The login suffix is asked as well, not instead. The two can only disagree if GitHub changes what
    it writes into either field, and at a door that decides whether a required check believes a
    human reviewed something, the second question costs nothing.

    NEITHER CAN SEE A MACHINE USER. An ordinary account a script holds a token for reports `User`
    exactly like a person, and telling those apart needs a list of people this does not have. What
    this closes is the door an App walks through — the one that is open today, and the one a second
    App in the organisation makes ordinary rather than hypothetical.

    Empty is not a person: an absent type means the caller passed none, and reading silence as a
    human would be this rule written fail-open.
    """
    return kind.strip() == HUMAN_PRINCIPAL and not login.strip().endswith("[bot]")


OVERRIDE_RE = re.compile(
    r"<!-- exeris-bot: l2-override by=([^\s]+) sha=([0-9a-f]{7,40}) -->")


def override_marker(by: str, sha: str) -> str:
    """The machine-readable header of a human's review of a change the routine refuses to read."""
    return f"<!-- exeris-bot: l2-override by={by} sha={sha} -->"


def override_refused_marker(by: str, sha: str) -> str:
    """The header of a refusal: the override label applied by something that is not a person.

    A marker of its own, so the refusal edits itself on the next attempt rather than overwriting a
    verdict — and so `standing_override` cannot read it back as a review. `OVERRIDE_RE` expects a
    space after `l2-override`; `-refused` is not one.
    """
    return f"<!-- exeris-bot: l2-override-refused by={by} sha={sha} -->"


def standing_override(comments_json: str, bot_login: str) -> tuple[str, str, str] | None:
    """The last human review recorded on this pull request, as `(login, sha, when)`.

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
            found = (m.group(1), m.group(2), c.get("updated_at") or c.get("created_at") or "")
    return found


# A role's earlier names, read as the role. The marker names the role that wrote a comment, so a
# comment published under a name the role no longer carries is still this role's: it is edited in
# place rather than left beside a new one, and its decision is this role's, never a second routine's
# for the arbiter to hold a label on.
ROLE_ALIASES = {"exeris-org-docs-reviewer": "exeris-org-reviewer"}


def role(name: str) -> str:
    return ROLE_ALIASES.get(name, name)


def blocking_standing(comments_json: str, agent: str, bot_login: str, head: str) -> str | None:
    """The `created_at` of a BLOCKED verdict that still covers this head, or None.

    A block is what a human override has to answer rather than step over. It is read from the bot's
    own marker, like every other standing state here, and only when it covers the commit under
    review — a block against a tree that has moved is not a block against this one.
    """
    stamp = None
    for c in comments(comments_json):
        if c.get("author") != bot_login:
            continue
        m = MARKER_RE.match(c["body"])
        if m and role(m.group(1)) == role(agent) and m.group(2) == "BLOCKED":
            sha = m.group(3) or ""
            if not head or not sha or sha[:7] == head[:7]:
                stamp = c.get("updated_at") or c.get("created_at") or ""
    return stamp


def reason_after(comments_json: str, who: str, since: str) -> str | None:
    """The first thing `who` said on this pull request AFTER the block, or None.

    The override is a person's judgement standing over the routine's, and a judgement that answers a
    block says what it answers. The label carries no text — a label event has none to carry — so the
    text is a comment by the same person, written after the block it addresses. Before it, they had
    not read it yet.
    """
    best = None
    for c in comments(comments_json):
        if (c.get("author") or "").lower() != (who or "").lower():
            continue
        when = c.get("updated_at") or c.get("created_at") or ""
        if since and when and when <= since:
            continue
        body = " ".join((c.get("body") or "").split())
        if body:
            best = body
    return best


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
        if m and role(m.group(1)) == role(agent):
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
        if m and role(m.group(1)) != role(exclude_agent):
            out[role(m.group(1))] = m.group(2)
    return out


def emit(text: str) -> None:
    """The report sink every checker here uses: the step summary in Actions, stdout otherwise."""
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)


def current_labels(args) -> set[str]:
    """The labels on the pull request as the event carried them.

    From a file, one per line. A label name may contain a comma — `area: kernel, core` is a legal
    label — and a comma-joined string turns one into two that exist nowhere.
    """
    path = getattr(args, "current_labels_file", "")
    if not (path and os.path.exists(path)):
        return set()
    with open(path, encoding="utf-8") as fh:
        return {line.rstrip("\n") for line in fh if line.strip()}


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
    harness denies. It is also the only source whose authorship is not a question: an artefact of
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
    it may not be able to reach. Where the harness denies the calls that would read one, every
    mandatory gate comes back `not-run` and the required check is red for ever — a verdict about the
    pull request's prose, defeated by the reviewer's inability to reach a step summary.
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
        billed: list[str] = []
        if isinstance(doc, dict):
            model = doc.get("model") or doc.get("model_id") or (doc.get("usage") or {}).get("model")
            h = doc.get("harness") if isinstance(doc.get("harness"), dict) else {}
            harness = h.get("client") or doc.get("client")
            version = h.get("version") or doc.get("version")
        elif isinstance(doc, list):
            # The shape the runner actually writes: an event list whose `system`/`init` event names
            # the model and the harness version, and whose `result` event names every model BILLED.
            # Those are two questions and this line used to answer the first with the second.
            # Measured over every execution log these repositories held on 2026-09-17: the ledger
            # names two models in every run, and in every run one of them produces no assistant turn
            # and spawns no subagent — the harness consulting a model for its own purposes. A footer
            # built from the ledger states that model reviewed the pull request, which it did not.
            # The stream says who acted; the ledger says who was billed. ADR-086, amendment of
            # 2026-09-17.
            init = next((e for e in doc if isinstance(e, dict) and e.get("type") == "system"
                         and e.get("subtype") == "init"), {})
            result = next((e for e in doc if isinstance(e, dict)
                           and e.get("type") == "result"), {})
            acted: list[str] = []
            for event in doc:
                if isinstance(event, dict) and event.get("type") == "assistant":
                    spoke = (event.get("message") or {}).get("model")
                    if spoke and spoke not in acted:
                        acted.append(spoke)
            model = ", ".join(acted) or init.get("model")
            # Named, never hidden: instrument cost is a published line item (ADR-086 §E.26), and a
            # footer that drops the second model entirely trades one wrong answer for another.
            billed = [m for m in sorted(result.get("modelUsage") or {})
                      if m not in acted and m != model]
            version = init.get("claude_code_version")
            harness = "claude-code" if version else None
        lines.append(f"model: {plain(model)}" if model else
                     "model: the execution log carries no model id")
        if billed:
            lines.append("harness-side, billed with no turn in the stream: "
                         + ", ".join(f"`{plain(m)}`" for m in billed))
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
           f"## Review — `{agent}` — **{decision}**", ""]
    label = verdict.get("decision_label")
    if label:
        out += [plain(label), ""]
    findings = verdict.get("findings") or []
    # A verdict composed from parts says which part raised each finding, and a reader looking for
    # the records part's findings finds them in one column rather than by reading every row.
    by_part = bool(verdict.get("parts"))
    if findings:
        columns = (["Part"] if by_part else []) + ["Tag", "Where", "Finding", "Fix"]
        out += ["| " + " | ".join(columns) + " |", "|" + ":--|" * len(columns)]
        for f in findings:
            tag = plain(f.get("tag"))
            where = plain(f.get("location"))
            blocking = " **(blocking)**" if f.get("blocking") else ""
            part = f"| {plain(f.get('part'))} " if by_part else ""
            # No backticks around `where`: CommonMark does not decode entities inside a code span,
            # so an escaped `Foo<T>.java` would render as `Foo&lt;T&gt;.java`. Escaped plain text
            # renders as the characters it means.
            out.append(f"{part}| {tag}{blocking} | {where} | {plain(f.get('what'))} — "
                       f"{plain(f.get('why'))} | {plain(f.get('fix'))} |")
        out.append("")
    else:
        out += ["No findings.", ""]
    parts = [p for p in (verdict.get("parts") or []) if isinstance(p, dict)]
    if parts:
        out += ["### Parts", ""]
        for p in parts:
            status = p.get("status")
            if status == "reviewed":
                said = f"reviewed — **{plain(p.get('decision'))}**"
            else:
                said = f"{plain(status)} — {plain(p.get('reason'))}"
            out.append(f"- `{plain(p.get('part'))}`: {said}")
        out.append("")
        missing = missing_parts(verdict)
        if missing:
            out += [f"> A part of this review produced no verdict: "
                    f"{', '.join('`' + plain(m) + '`' for m in missing)}. The findings above are "
                    f"the other parts' and they stand, but the pull request has not been reviewed "
                    f"whole, so the required check is red whatever the decision says.", ""]
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


def missing_parts(verdict: dict) -> list[str]:
    """Parts a review that ran as parts planned and got no verdict from.

    The aggregate keeps every finding the other parts reported, so the comment has something true
    to say — but a review missing a part has not judged the pull request, and a PASS composed from
    the parts that did report is a PASS about less than the pull request.
    """
    return [str(p.get("part")) for p in verdict.get("parts") or []
            if isinstance(p, dict) and p.get("status") == "missing"]


def blocking_findings(verdict: dict) -> list[str]:
    """The findings this verdict itself marked blocking, by where they are.

    The gate read `decision` and nothing else, so a review that set `CONDITIONAL` and marked a
    finding `blocking: true` produced a green check next to a comment rendering that finding as
    **(blocking)**, and the pull request came out mergeable beside it.
    A decision and a finding disagreeing is not a tie to resolve in the decision's favour — the
    stricter of the two is the one a reader acts on, which is §B.11's rule applied within one
    verdict rather than between two.
    """
    return [str(f.get("location") or f.get("why") or "?")
            for f in (verdict.get("findings") or []) if f.get("blocking") is True]


# How a standing human review was made, carried with the record so that what the pull request is
# told names the gesture the person actually made.
BY_LABEL = "label"
BY_APPROVAL = "approval"

# What takes a person's approval back, as GitHub counts one. A later `CHANGES_REQUESTED` from the
# same reviewer replaces it, and `DISMISSED` is the approval itself withdrawn. A later `COMMENTED`
# review is NOT here: GitHub keeps an approval standing through a comment from the person who gave
# it, and a gate that dropped it there would be red on a pull request GitHub reports as approved.
WITHDRAWS_APPROVAL = frozenset({"CHANGES_REQUESTED", "DISMISSED"})


def reviews(path: str) -> list[dict]:
    """The pull request's reviews as the API lists them, or none at all.

    A file that is missing or does not parse is NO APPROVALS. An approval can only add a green, so
    the one reading of a failed fetch that cannot green anything is that nobody approved.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, TypeError, ValueError):
        return []
    return [r for r in (payload if isinstance(payload, list) else []) if isinstance(r, dict)]


def standing_approvals(path: str, head: str) -> list[tuple[str, str, str, str]]:
    """Every reviewer whose LATEST word is an approval of this head, as `(login, type, sha, when)`.

    Latest per reviewer, because an approval is a state a person is in rather than an event: one
    they have since withdrawn is not standing, whatever it said when it was given. On this head and
    nothing else, because an approval names the commit it was given on and a push leaves it behind,
    exactly as a push leaves a verdict behind. An approval with no time on it cannot be ordered
    against a block, so it is not one this gate can weigh.
    """
    latest: dict[str, tuple[str, str, str, str]] = {}
    for r in sorted(reviews(path), key=lambda r: str(r.get("submitted_at") or "")):
        user = r.get("user") if isinstance(r.get("user"), dict) else {}
        row = (str(user.get("login") or ""), str(user.get("type") or ""),
               str(r.get("commit_id") or ""), str(r.get("submitted_at") or ""))
        if r.get("state") == "APPROVED":
            latest[row[0]] = row
        elif r.get("state") in WITHDRAWS_APPROVAL:
            latest.pop(row[0], None)
    return [row for row in latest.values() if head and row[2] == head and row[3]]


def person_approval(args, dump: str, blocked_at: str | None) -> tuple[str, str, str, str] | None:
    """The newest standing approval of this head BY A PERSON, as a human review record, or None.

    The same fact `human-reviewed` records, reached through the gesture GitHub already asks of a
    reviewer, so a person reviewing a pull request they did not open makes one gesture for one fact.
    The label stays the only door on a person's OWN pull request, which GitHub will not let them
    approve.

    A `Bot` principal's approval is never one: the identity that opens a pull request cannot be the
    one that says a person read it. And over a block that stands against this head, an approval
    counts only once the same person has said something after the block — the condition the label
    meets before its record is written. The review's own text counts, because the comment dump
    carries every review's body.
    """
    found = None
    for login, kind, sha, when in standing_approvals(getattr(args, "reviews", ""),
                                                     args.head_sha or ""):
        if not human_principal(login, kind):
            continue
        if blocked_at and not reason_after(dump, login, blocked_at):
            continue
        if found is None or when > found[2]:
            found = (login, sha, when, BY_APPROVAL)
    return found


def machine_approvals(args) -> list[str]:
    """The logins that approved this head and are not people, when nobody else has.

    Never counted, and named so the red says why: an approval that is visibly on the pull request
    and silently ignored reads as a gate that is broken rather than one that refused.
    """
    rows = standing_approvals(getattr(args, "reviews", ""), args.head_sha or "")
    if any(human_principal(login, kind) for login, kind, _, _ in rows):
        return []
    return [login for login, _, _, _ in rows]


def recorded_override(dump: str, bot_login: str, head: str) -> tuple[str, str, str, str] | None:
    """The bot's record of `human-reviewed`, when it covers this head."""
    standing = standing_override(dump, bot_login)
    if standing and head and standing[1][:7] == head[:7]:
        return (*standing, BY_LABEL)
    return None


def human_review(args) -> tuple[str, str, str, str] | None:
    """A standing human review that still covers this head, as `(login, sha, when, how)`, or None.

    Two gestures make one: the bot's record of `human-reviewed`, and an approving review by a
    person on this head. Both are read here so that every branch asking "has a person reviewed
    this?" gets the same answer from one place.

    NOT scoped to a workflow change. It was, and that was half a rule: the branch that RECORDS an
    override was made universal while this one — the half every later run reads — still refused
    anything but a workflow change. The two disagreed in the gap between them, and the gap is one
    second wide: recording an override removes the label, the removal is an `unlabeled` event, that
    event reruns the workflow on the same commit with no `override_by`, and the rerun asks this
    function, which refused the record written a moment earlier. The check went green and back to
    red with nothing pushed.
    """
    dump = ""
    if args.comments and os.path.exists(args.comments):
        with open(args.comments, encoding="utf-8") as fh:
            dump = fh.read()
    head = args.head_sha or ""
    if not head:
        return None
    blocked_at = blocking_standing(dump, args.expect_agent or "unknown", args.bot_login, head)
    for found in (recorded_override(dump, args.bot_login, head),
                  person_approval(args, dump, blocked_at)):
        # A BLOCK THAT ARRIVED AFTER THE RECORD IS NOT ANSWERED BY IT. The condition belongs to the
        # moment the override was made — the branch that records one refuses to green a standing
        # block the person has not answered — and re-deriving it here would ask the same question
        # twice and risk two answers. What this does ask is whether a block has landed SINCE, which
        # the record cannot have answered because it did not exist yet. Re-reviews on one commit
        # are ordinary, so this is not a hypothetical. An approval is held to the same rule.
        if found and not (blocked_at and found[2] and blocked_at > found[2]):
            return found
    return None


def human_said(found: tuple[str, str, str, str]) -> tuple[str, str]:
    """A standing human review named for the log and for the notice, by the gesture that made it."""
    login, sha = found[0], found[1][:7]
    if found[3] == BY_APPROVAL:
        return f"approved by {login} on {sha}", f"Approved by `{plain(login)}` on `{sha}`."
    return (f"{login} reviewed this by hand, recorded against {sha}",
            f"`{plain(login)}` reviewed this change by hand, recorded against `{sha}`.")


def restate_notice(plan: dict, args, said: str) -> None:
    """Put the CURRENT state in the standing `not run` notice.

    The notice is a statement about the pull request, not a log line: a reader takes it for what is
    true now. Every branch that publishes one edits it in place on the next run — except the
    branches that conclude green without a verdict, which wrote nothing at all, so a notice naming
    a gate that had since passed stands next to a green check, naming it as failing long after it
    passed.

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
                       + "\n## Review — not run\n\n"
                       + said + " The required check is green.\n")


def standing_decision(plan: dict, args) -> None:
    """No verdict came out of this run, so the STANDING one decides the colour.

    The reason a run produced nothing is not itself an answer about the pull request. Only two
    reasons are: it is a draft, which cannot merge while it stays one, and it is a fork this
    workflow can carry no credential for. A pull request OPENED BY A BOT is not among them: it can
    merge, so greening it is a merge gate reporting a pass on a change nothing read.

    Every other reason — no review was asked for, the event was a label change, a bot opened the
    pull request, a skip kind nobody has seen before — leaves the question open, and the answer is the last verdict: it is
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
        logged, told = human_said(by_hand)
        plan.update(conclusion="green",
                    reason=f"{logged} — a human review outranks this routine's")
        # The same restatement: a person reviewing by hand is the current state of this pull
        # request, and the standing notice has no way to learn that on its own.
        restate_notice(plan, args, told)
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
        # a verdict that passed, because this branch only ever refused `BLOCKED`. A run that
        # published `NONE` and was then cancelled leaves its replacement reporting that the standing
        # verdict still covers the head — green, on a pull request nothing had reviewed.
        #
        # Named forward rather than backward: a decision this file does not recognise is not a pass
        # either. The enum can grow in the schema without this turning into a hole the day it does.
        plan["reason"] = (f"the standing comment records `{standing[0]}`, which is not a verdict that "
                          f"passes — it is what the publication writes when no review ran")
    else:
        plan.update(conclusion="green",
                    reason=f"the standing verdict is {standing[0]} and still covers {head}")
    refused = machine_approvals(args) if plan["conclusion"] != "green" else []
    if refused:
        plan["reason"] += (f"; the approval of {head} is by {', '.join(refused)}, which is not a "
                           f"person, and only a person's approval is a human review")


def standing_gate(plan: dict, args) -> int:
    """The same decision, written out. Split so a branch can ASK what the standing state is without
    also concluding the run — the refusal below needs the colour and supplies its own record."""
    standing_decision(plan, args)
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
    # straight back off, exactly as `needs-review` does. What the check reads afterwards is the
    # record, not the label — a label anyone can re-apply after a push, while the record carries the
    # commit it was made against and is left behind by the next one.
    # THE LABEL IS A CLAIM THAT A PERSON READ THIS. Anything holding `pull-requests: write` can
    # apply it — `exeris-bot` included, and with a second App in the organisation that stops being
    # hypothetical. Applying this label IS the capability "make the required check believe a human
    # reviewed", and a gate able to green itself is not a gate.
    #
    # The guard existed before this, as `!endsWith(github.actor, '[bot]')` in a workflow expression,
    # and it was two things short. It read a login where GitHub publishes a TYPE, and it lived where
    # nothing tests it. Worse, when it fired it did nothing visible: the override was dropped and
    # the LABEL STAYED ON THE PULL REQUEST, still saying to every reader — and to any rule written
    # over labels later — that a person had reviewed this change.
    #
    # So: the label comes off, the refusal is written down naming the principal, and the COLOUR is
    # whatever was already true. Not red. A bot flicking a label is not evidence about the change in
    # either direction, and turning a legitimately green pull request red on one would be the same
    # fault as greening it, pointed the other way.
    if args.override_by and not human_principal(args.override_by, args.override_by_type):
        standing_decision(plan, args)
        plan["marker_search"] = "<!-- exeris-bot: l2-override-refused"
        plan["comment"] = (override_refused_marker(plain(args.override_by), args.head_sha or "")
                           + "\n## Review — the override was refused\n\n"
                           + f"`{plain(args.override_by)}` applied "
                           + f"`{plain(args.override_label or 'human-reviewed')}`. That label "
                           + "records that a **person** reviewed a change this routine cannot "
                           + f"read, and the principal that applied it is "
                           + f"`{plain(args.override_by_type or 'unknown')}` — not one. No review "
                           + "has been recorded and the label has been removed.\n\nThe check says "
                           + "what was already known about this pull request: "
                           + plan["reason"] + ".\n")
        plan["reason"] = (f"{args.override_by} is a "
                          f"{plain(args.override_by_type or 'unknown')}, not a person, so the "
                          f"override label was removed and the refusal recorded — "
                          + plan["reason"])
        return finish(plan, args)

    if args.override_by:
        head = (args.head_sha or "")[:7]
        agent_for_block = args.expect_agent or "unknown"
        blocked_at = None
        said = None
        if args.comments and os.path.exists(args.comments):
            with open(args.comments, encoding="utf-8") as fh:
                dump = fh.read()
            blocked_at = blocking_standing(dump, agent_for_block, args.bot_login, args.head_sha or "")
            if blocked_at:
                said = reason_after(dump, args.override_by, blocked_at)
        # A HUMAN REVIEW OUTRANKS THIS ROUTINE'S, ALWAYS. It used to count only where the runner
        # refuses to start — a pull request changing the workflow its run enters through — and
        # decided nothing anywhere else. That was the wrong shape: the routine is an instrument, a
        # person reading the diff is not, and a layer that lets its own verdict outrank the person it
        # reports to has stopped being a review and become an authority.
        #
        # ONE CONDITION, AND IT IS NOT A LIMIT ON THE PERSON. Where a BLOCKED verdict stands against
        # this same commit, the override greens it only once that person has said something on the
        # pull request AFTER the block. Not approval — the label is the approval — but an account:
        # what the block got wrong, or what was done about it. A label event carries no text, so the
        # text is a comment, and "after" is what makes it an answer rather than something written
        # before there was anything to answer.
        #
        # The cost, stated rather than hidden: this makes a block overridable, which it was not. What
        # keeps it from being a bypass is that the record names the person, names the commit, quotes
        # what they said, and is left behind by the next push — the same properties the workflow case
        # already had, now carrying a reason as well.
        if blocked_at and not said:
            plan["agent"] = agent_for_block
            plan["marker_search"] = f"<!-- exeris-bot: l2-verdict agent={agent_for_block} decision=NONE"
            plan["comment"] = (marker(agent_for_block, "NONE", args.head_sha)
                               + "\n## Review — the block still stands\n\n"
                               + f"`{plain(args.override_by)}` applied "
                               + f"`{plain(args.override_label or 'human-reviewed')}` while a "
                               + "**BLOCKED** verdict stands against this commit. A human review "
                               + "outranks this routine's and can lift that block — but not "
                               + "silently.\n\nComment on this pull request saying what the block "
                               + "got wrong or what was done about it, then apply the label again. "
                               + "The record will quote you.\n")
            plan.update(conclusion="red",
                        reason=(f"{args.override_by} applied the override over a standing BLOCKED "
                                f"verdict without saying what it answers"))
            return finish(plan, args)

        why_here = ("This routine cannot read a pull request that changes the workflow file its run "
                    "enters through: the runner refuses to start when it differs from the default "
                    "branch's copy."
                    if truthy(args.workflow_touching) else
                    "A human review outranks this routine's, and this is the record of one.")
        quoted = ""
        if said:
            clipped = said if len(said) <= 400 else said[:397] + "..."
            quoted = ("\n\nWhat it answers, in their words:\n\n> " + plain(clipped))
        plan["marker_search"] = "<!-- exeris-bot: l2-override"
        plan["comment"] = (override_marker(plain(args.override_by), args.head_sha or "")
                           + "\n## Review — by hand\n\n"
                           + f"`{plain(args.override_by)}` reviewed this change themselves and "
                           + f"recorded it against `{head}`. " + why_here + quoted
                           + f"\n\nThe record covers `{head}` and nothing after it — a push leaves "
                           + "it behind and the check goes red again.\n")
        plan.update(conclusion="green",
                    reason=(f"{args.override_by} reviewed this by hand and it is recorded against "
                            f"{head}" + (" over a standing block they answered" if said else "")))
        return finish(plan, args)

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
        # telling the author it "did not pass" sends them to fix green checks. A label applied
        # seconds after opening kills the run, and the comment then blames the gates it killed.
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
        # A cancelled run has nothing to say, and saying it is how a pull request ends up with a
        # notice naming gates that are green in the run which replaced this one.
        #
        # `!cancelled()` on the publish job does NOT keep this run out of here, and the reason is not
        # a race. The caller enters this workflow through a job carrying `if: always()`, so inside
        # the called workflow nothing was cancelled and the function is false. The publish job
        # starts well after the cancellation is recorded on the gates, so this is not a window to
        # narrow: the guard simply does not see what happened outside its own workflow.
        #
        # So the decision is taken from the gate results, which no workflow expression can
        # misreport: when every gate that is not green was cancelled rather than broken, this run
        # was replaced, the run that replaced it reports the same check name, and there is nothing
        # here for a reader. The check still goes red — a cancelled run is not evidence of a green
        # one, and §B.8's fail-closed half does not soften because the cause was concurrency.
        # THE REQUEST IS PUT BACK, NEVER INVENTED. A readiness trigger fires once and a run that
        # was ready but lost its gates consumes it, leaving the pull request with no review and no
        # way back to one, so the label goes on again here and comes off only when a review has
        # actually run.
        #
        # Only when it was there. `ready` also means `opened`, `reopened` and `ready_for_review`,
        # where no label was ever applied and there is nothing to restore: adding one then is the
        # bot asking for a review nobody requested. That request cannot be honoured either — the
        # label change starts a run whose actor is the bot, and the runner refuses a non-human
        # actor whatever this workflow allows — so it leaves the pull request carrying a request
        # no run can take.
        if (args.skip_kind == "ready" and args.review_label
                and args.review_label in current_labels(args)):
            plan["labels_add"] = [args.review_label]
        plan["agent"] = args.expect_agent or "unknown"
        # Nothing a READER sees. The label above is the request being put back, which the next run
        # needs; a comment is addressed to a person, and this run has nothing to tell one.
        if cancelled and not broke:
            return finish(plan, args)
        plan["marker_search"] = f"<!-- exeris-bot: l2-verdict agent={plan['agent']} decision=NONE"
        # The same words as the reason above. They were split there and left hardcoded here, so a
        # reader of the comment was told three cancelled gates "did not pass" while the log beside it
        # said they were cancelled — the fix reached one of the two places that say the same thing.
        tail = ("A cancelled gate reported nothing rather than failing: the run carrying it was "
                "replaced, and the one that replaced it may already have them green.\n"
                if cancelled and not broke else
                "Fix those first; the review runs once they are green.\n")
        plan["comment"] = (marker(plan["agent"], "NONE", args.head_sha)
                           + "\n## Review — not run\n\nThe L1 gates this review waits on "
                           + "; ".join(said_md) + ".\n\n" + tail)
        return finish(plan, args)
    # §B.8's one green without a verdict, and the only one. It is decided here rather than in the
    # workflow's shell because it is the rule most likely to be got wrong and it was: an early crash
    # leaves `produce-relevant` EMPTY, and "not true" read as "filtered out" turned every crash into
    # a green skip with a log line claiming a filter had run. Absence of a signal is not a `false`.
    # A skip whose kind is not one of the two above says nothing about whether this pull request has
    # been reviewed, so it cannot be a green on its own — it falls back to the standing verdict, like
    # `not-ready` does. A label event started by the publication runs with the bot as its actor; if
    # such a run reports green it becomes the last run for the check name, and the pull request reads
    # as CLEAN with a BLOCKED verdict standing on it. An unrecognised skip kind lands here too, and
    # fails closed rather than open.
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
        # WHEN WE KNOW WHY, SAY WHY. The runner refuses to start on a pull request that changes the
        # workflow file the run enters through, and a refusal leaves a signature: the produce job
        # reports success, no verdict exists, and no execution log was uploaded either, because the
        # runner stopped before writing one. All three together are the refusal; any one of them
        # alone is not, which is why this asks for the conjunction. A model that ran and produced
        # nothing DID leave a log, and it gets the general message — it is a different fault and
        # sending its author to apply a review label would be sending them to the wrong place.
        #
        # `Re-run the job, or look at its log` is the right advice only while nobody knows the
        # cause. Here the publish half knows it deterministically, and a notice that tells a person
        # to go read a log for something the notice could have said is how a correct message
        # becomes a useless one.
        refused = (truthy(args.workflow_touching)
                   and not (args.execution_log and os.path.exists(args.execution_log)))
        plan["reason"] = (
            "no verdict to publish: the runner refuses a pull request that changes the workflow "
            "this run enters through, and left no execution log, which is that refusal"
            if refused else
            f"no verdict to publish: {why}. The producing job reported "
            f"`{args.produce_outcome or 'unknown'}`.")
        # The absent verdict is the case §B.9's reasoning matters most for, and it was the one case
        # that posted nothing: a required check went red with the explanation only in a job log.
        # Replaces only a previous no-verdict notice, never a comment carrying a real verdict. A
        # later run that produced nothing — a crashed runner, a refused actor — otherwise overwrote
        # findings somebody has to act on, and the pull request lost them. Both can stand: the last
        # verdict, and a note that a later run reached none.
        plan["marker_search"] = f"<!-- exeris-bot: l2-verdict agent={plan['agent']} decision=NONE"
        if refused:
            plan["comment"] = (marker(plan["agent"], "NONE", args.head_sha)
                               + "\n## Review — not run\n\n"
                               + "This pull request changes the workflow file this run enters "
                               + "through, and the runner refuses to start on one: its own "
                               + "supply-chain guard, which no caller can configure away. Nothing "
                               + "was reviewed, and the required check is red rather than green so "
                               + "that nobody reads the absence as a pass.\n\n"
                               + "A person reviews the change and applies `"
                               + plain(args.override_label or "human-reviewed")
                               + "`. The record covers this commit and nothing after it.\n")
        else:
            plan["comment"] = (marker(plan["agent"], "NONE", args.head_sha)
                               + "\n## Review — no verdict\n\n"
                               + f"The producing job reported `{args.produce_outcome or 'unknown'}` "
                               + f"and {why}.\n\nThe required check is red because nothing was "
                                 "reviewed, not because a review found something. Re-run the job, "
                                 "or look at its log to see why it produced nothing.\n")
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
                           + "\n## Review verdict refused\n\nA verdict was produced and it does not "
                           "conform to `.agents/schemas/verdict.schema.json`:\n\n"
                           # The validator quotes the instance value it refused, so these
                           # strings are the reviewed repository's words too.
                           + "\n".join(f"- {plain(e)}" for e in errors[:10])
                           + "\n\nNothing was labelled. The required check is red.\n")
        return finish(plan, args)

    with open(args.labels_map, encoding="utf-8") as fh:
        mapping = json.load(fh)
    current = current_labels(args)
    standing = {}
    if args.comments and os.path.exists(args.comments):
        with open(args.comments, encoding="utf-8") as fh:
            standing = standing_verdicts(fh.read(), str(verdict.get("agent", "")),
                                         args.bot_login)
    add, remove = plan_labels(verdict, mapping, current, standing)
    # A part that did not report cannot say its debt is paid: retiring `doc-debt` because the part
    # that raises it produced nothing would be a label asserting a review nobody made.
    incomplete = missing_parts(verdict)
    if incomplete:
        remove = []
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
    # A BLOCKED verdict published by THIS run is newer than any approval already on the pull
    # request, so an approval does not answer it — `human_review`'s rule for a block that landed
    # after the record, applied to the block this run is about to publish.
    by_hand = human_review(args) if decision == "BLOCKED" else None
    if args.pin_problem:
        # §B.6a's mismatch is about this verdict — it was written against one base and validated
        # against another — so it belongs in this verdict's comment and this verdict's conclusion.
        # A second red step beside the gate would be a red the author cannot tell from BLOCKED.
        plan["reason"] = f"the reviewed repository's bundle pin is not this one's: {args.pin_problem}"
    elif incomplete:
        plan["reason"] = ("the review ran as parts and "
                          + ", ".join(f"`{m}`" for m in incomplete)
                          + " produced no verdict, so the pull request has not been reviewed whole")
    elif by_hand and by_hand[3] == BY_LABEL:
        plan["conclusion"] = "green"
        plan["reason"] = (f"the verdict is BLOCKED and {by_hand[0]} reviewed this by hand against "
                          f"{by_hand[1][:7]} — a human review outranks this routine's")
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


def marker_searches(search: str) -> list[str]:
    """Every prefix a comment this role published may start with: the search itself, and the same
    search under each of the role's earlier names."""
    found = [search]
    for old, new in ROLE_ALIASES.items():
        if f"agent={new} " in search:
            found.append(search.replace(f"agent={new} ", f"agent={old} "))
    return found


def finish(plan: dict, args) -> int:
    # In `finish` rather than in the branch that records the override, because the verdict path
    # assigns `labels_remove` wholesale from the label map and would drop it. The label is a request;
    # once this run has read it, it has been answered whatever the answer was.
    if getattr(args, "override_by", "") and getattr(args, "override_label", ""):
        if args.override_label not in plan["labels_remove"]:
            plan["labels_remove"] = plan["labels_remove"] + [args.override_label]
    plan["marker_searches"] = marker_searches(plan.get("marker_search") or "")
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
                   help="why the producing job did not run. `fork` and `draft` are about the pull request and are a green on their own; `bot-authored`, `not-ready`, `bot-event`, `review-event` and anything this file does not recognise — `draft-or-bot` from a caller pinned before the split included — hand the colour to the standing verdict")
    p.add_argument("--head-sha", default="",
                   help="the pull request head: recorded in the marker when a review runs, and\n                        compared with the standing verdict's commit when one does not")
    p.add_argument("--review-label", default="needs-review",
                   help="the label that asks for a review. Re-applied when a ready run lost its "
                        "gates, so the request survives the run that carried it")
    p.add_argument("--override-label", default="human-reviewed",
                   help="the label a person applies to record that they reviewed a change this "
                        "routine cannot read — one that touches a workflow file")
    p.add_argument("--override-by", default="",
                   help="the login that applied the override label IN THIS EVENT, empty otherwise")
    p.add_argument("--override-by-type", default="",
                   help="that principal's `sender.type` — `User` is a person, `Bot` is a GitHub "
                        "App, and empty is not a person either")
    p.add_argument("--workflow-touching", default="false",
                   help="whether this pull request changes a file under .github/workflows/, which "
                        "is the only place the override applies")
    p.add_argument("--reviews", default="",
                   help="the pull request's reviews as `pulls/N/reviews` lists them. An approval of "
                        "the head by a person is a human review; missing or unreadable is none")
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
