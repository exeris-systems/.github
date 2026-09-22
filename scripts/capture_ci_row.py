#!/usr/bin/env python3
"""One run record per L2 review run, assembled where the run happened — ADR-087 §C.13-§C.17.

The backfilling producer reconstructs a run's components from what the host still holds. This one
does not: the job that ran the model exported the digests of what it handed over, they arrive here
as inputs, and every component of the row is either one of those values, a count read from the
run's own event stream, or a fact read from the platform over REST. Nothing here renders a prompt,
reads a workflow file or guesses at a component — a producer that had to reconstruct would be the
other one.

THE DERIVATIONS ARE NOT HERE. `tools/ci_row.py` in the row contract's repository holds them, and
this script is handed that checkout and imports it. A copy would agree with the contract until one
of the two was edited, and the value of two producers writing one row shape is exactly that they
cannot drift apart unnoticed.

§C.14's rule governs every branch below: a component the inputs do not establish yields NO ROW with
a named reason, never a convenient value. The reason is counted and printed; the run is not failed
by it, because a capture that cannot write a row is not a defect in the pull request it was
watching.

TWO PHASES, ONE CODE PATH. Without `--stream-commit` the script decides — it reads the stream, asks
the platform what it needs, and writes the decision and the stream's own facts. The caller then
commits the stream, and runs the script again with the commit it made: `execution.event_stream.ref`
names that commit, so the row cannot be assembled before it exists, and nothing is committed for a
run that was never going to yield a row.

NO TEXT FROM THE RUN REACHES THE ROW. The stream is read for counts, a model reference and a client
version; the pull request's body is read for its scope class. Neither is copied. There is no cost
parameter anywhere in this file: under a subscription no per-run price exists, and a figure computed
from a price list is imputed rather than reported (ADR-086 §C.14).

Usage:
  capture_ci_row.py --execution-root DIR --log FILE --repository OWNER/NAME --pull-request N
                    --event-head-sha SHA --workflow-run-id N --execution-artifact NAME
                    --artifact-id N --verdict-source SOURCE [--capture-* ...]
                    [--stream-commit SHA] [--inbox-root DIR] [--out decision.json] [--row row.json]
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# The repository a stream lives in, and the producer this is in a fence id. The fence grammar is
# `docs/fences.md`'s in the row contract's repository: `<date>-<producer>-cc-<client version>`.
STREAMS_REPO = "exeris-systems/exeris-ai-execution-streams"
PRODUCER = "ci-live"

# Fixed for every row this producer writes, each for a stated reason. `anthropic` is the only
# provider whose model ids this producer recognises, and one it does not recognise costs the row
# rather than being filed under a provider nobody established. `claude-code` is the client the
# reviewing action runs. `full` is what this producer can see: every count on a row comes from the
# run's own event record. `UNKNOWN` is ADR-086 §E.19 — the oracle judges after the pull request
# closes, so a row written at review time has not been judged, and fail-closed says so.
PROVIDER = "anthropic"
MODEL_PREFIX = "claude-"
HARNESS_CLIENT = "claude-code"
CAPTURE_LEVEL = "full"
OUTCOME = "UNKNOWN"

# The one inbox that exists. A row whose repository is not public belongs in the enterprise sibling,
# which has not been created; such a row is counted and not written, never filed here instead —
# rule 1 of the inbox validator is fail-closed on exactly that, and a row filed under the wrong
# visibility is published by the act of filing it.
INBOX_VISIBILITY = "public"

# How long the produce job keeps the execution artefact, in days, and the only reason this producer
# knows it: the index entry records when the host would have dropped the artefact, and the producer
# cannot read that without the Actions API — a permission the capture job does not hold and a
# caller would have to grant. An override exists for a producer whose upload declares another
# retention, because a number stated in two files disagrees the moment one of them is edited.
EXECUTION_ARTIFACT_RETENTION_DAYS = 1

# The ten components the producing job exports, in the order it writes them. Named here as one list
# so that "the caller passed none of them" is one question rather than ten.
CAPTURE_INPUTS = (
    "prompt_sha256",
    "routine_sha256",
    "routine_sha",
    "agents_md_sha256",
    "system_prompt_sha256",
    "tool_surface",
    "bundle_version",
    "checkout_sha",
    "head_sha",
    "review_started_at",
)

# The components a row cannot be written without, with the reason each is required stated by the
# field it fills. A component the exports left empty is a component nobody read, and the contract's
# answer to that is no row.
REQUIRED_COMPONENTS = {
    "system_prompt_sha256": "agent.system_prompt_sha256 — the instructions the repository put in "
                            "front of the runner",
    "bundle_version": "repository_state.bundle_version — the rules the run was subject to",
    "head_sha": "repository_state.commit — the tree the run read",
    "review_started_at": "started_at — a fence is dated, so a row that is not dated is on neither "
                         "side of it",
}

RFC3339_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")

# What a fetcher answers where the host says there is nothing there. A 404 is an ANSWER — that pull
# request is gone — and it is deliberately not an exception, which is kept for a call that produced
# no answer at all.
ABSENT = {"status": "404"}


class FetchError(Exception):
    """A REST call did not answer — not a 404, which is an answer, but no answer at all.

    Kept separate from a 404 so that an expired token, a rate limit or an unplugged network never
    reads as a fact about the repository. The first is a run to repeat; the second decides a row.
    """


class Fetcher:
    """Every REST fact this producer reads, through `gh api` and through nothing else.

    The seam is one method — `get(path)`, where `path` is a REST path with no leading slash and the
    answer is the parsed body or `ABSENT`. A fake answering that one method substitutes completely,
    which is what lets a suite state this assembly without a network. REST and never porcelain: a
    REST path is an interface the host versions, and a porcelain rendering changes under its own
    releases.

    `token` and `accept` are per call, and both default to what this producer already used — the
    environment's credential and the JSON media type — so a caller naming neither reads exactly as
    it did. They are here because one producer's reads are not all made as one principal or in one
    form: a producer that reads a private data repository under an App's installation token and a
    reviewed repository under the job's own would otherwise need two seams, and a file past the
    contents endpoint's base64 ceiling is served only under the raw media type. The answer is parsed
    as JSON whichever is asked for, which is what every path this bundle reads returns.
    """

    def __init__(self) -> None:
        self.calls = 0

    def get(self, path: str, token: str | None = None, accept: str | None = None) -> object:
        self.calls += 1
        command = ["gh", "api", "-H",
                   f"Accept: {accept or 'application/vnd.github+json'}", path]
        # Handed to the child's environment rather than written into the command: a command line is
        # readable by every process on the runner and an environment is not.
        env = dict(os.environ, GH_TOKEN=token) if token else None
        try:
            done = subprocess.run(command, capture_output=True, text=True, check=False, env=env)
        except OSError as exc:                                  # `gh` is not on this runner
            raise FetchError(f"{path}: {exc}") from exc
        if done.returncode != 0:
            error = done.stderr.strip()
            if "HTTP 404" in error or "Not Found" in error:
                return dict(ABSENT)
            raise FetchError(f"{path}: {error[:500] or 'no answer'}")
        try:
            return json.loads(done.stdout or "null")
        except json.JSONDecodeError as exc:
            raise FetchError(f"{path}: the answer is not JSON ({exc})") from exc


def absent(body: object) -> bool:
    """Whether a fetcher's answer is the host saying there is nothing there."""
    return isinstance(body, dict) and str(body.get("status")) == "404"


def tooling(root: str):
    """`ci_row` and the inbox validator, imported from the row contract's checkout.

    Imported rather than vendored, and late rather than at module scope, because the checkout is an
    argument: the producing repository holds no copy of the contract, and a copy it did hold would
    be the thing that drifts. A checkout that does not carry them is a defect in the job, not a
    fact about the run, so it raises rather than costing a row.
    """
    root = os.path.abspath(root)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tools import ci_row                                             # noqa: PLC0415
    from tools.inbox_validate import Report, check                       # noqa: PLC0415
    return ci_row, Report, check


# --------------------------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------------------------


@dataclasses.dataclass
class Decision:
    """What one capture produced: a row, or a counted reason there is none.

    `reason` is the whole of the no-row vocabulary — one value per way the contract refuses, so a
    step summary counts refusals rather than reading prose. `state` is what became of a row that
    was assembled: written, already there byte for byte, or refused.
    """

    repository: str = ""
    pull_request: int | None = None
    issue_key: str = ""
    reason: str | None = None
    detail: str = ""
    state: str = ""
    run_id: str = ""
    author: str = ""
    date: str = ""
    visibility: str = ""
    branch: str = ""
    row_path: str = ""
    fence: str = ""
    stream: dict | None = None
    refusals: list = dataclasses.field(default_factory=list)

    def no_row(self, reason: str, detail: str = "") -> "Decision":
        self.reason, self.detail, self.state = reason, detail, "no-row"
        return self

    def as_json(self) -> dict:
        return dataclasses.asdict(self)


def slug(repository: str) -> str:
    """A repository name as a branch segment: `owner/name` with the slash written `--`.

    A branch carries the repository it holds rows for, so one day's rows from two repositories are
    two branches and two pull requests — which is what §C.15 asks for, and what keeps a refusal in
    one repository's batch from holding up another's.
    """
    return repository.replace("/", "--")


def stream_path(date: str, repository: str, workflow_run_id: object, artifact_id: object) -> str:
    """Where one stream lands in the streams repository, in that repository's own layout.

    `streams/<date>/<repo>/<workflow run>-<artefact>.json`, which is the shape every stream already
    there is named by. The producer writing a second spelling into the same directories would leave
    one tree carrying two conventions, and a reader that reconstructs a path from a row's identity
    rather than from the index would resolve the wrong name for half the corpus.

    The date is the artefact's creation day in UTC, which is what the receiving repository fixes,
    so the directory a stream lands in does not depend on where it was produced.
    """
    return f"streams/{date}/{repository.split('/')[-1]}/{workflow_run_id}-{artifact_id}.json"


def artifact_expiry(created_at: str, retention_days: int) -> str:
    """When the host would drop the execution artefact, from its creation and the upload's retention.

    Computed rather than read, because reading it is a call on the Actions API and the capture job
    holds no Actions permission — one it cannot be given without every caller granting it.
    """
    when = datetime.datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
    return (when + datetime.timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def decide(args, fetcher, ci_row) -> Decision:
    """Everything that is known before the stream is committed, in the order it is cheapest to ask.

    The order is deliberate: what the caller passed is free, the stream is local, and the platform
    is last. Each test returns at the first value it cannot establish, because §C.14's answer to a
    missing component is no row and there is nothing to gather after the first failure.
    """
    out = Decision(repository=args.repository, pull_request=args.pull_request,
                   issue_key=f"{args.repository}#{args.pull_request}/capture")

    supplied = {name: (getattr(args, name) or "").strip() for name in CAPTURE_INPUTS}
    if not any(supplied.values()):
        return out.no_row("capture-inputs-absent",
                          "the producing job exported none of its components — a caller pinned to "
                          "a producing half that predates them passes ten empty values, and a row "
                          "assembled from them would state what nobody measured")

    try:
        with open(args.log, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return out.no_row("stream-missing", str(exc))
    digest = ci_row.stream_digest(data)
    try:
        events = json.loads(data)
    except json.JSONDecodeError as exc:
        return out.no_row("stream-unreadable", str(exc))
    if not isinstance(events, list):
        return out.no_row("stream-unreadable", "the stream is not an array of events")
    facts = ci_row.stream_facts(events)

    if not facts.has_result:
        return out.no_row("result-absent", "the stream carries no `result` event")
    if facts.turns is None or facts.wall_time_ms is None:
        return out.no_row("result-incomplete", "the `result` event names no turns or no duration")
    if ci_row.names_a_publisher(facts.model) or \
            any(ci_row.names_a_publisher(m) for m in facts.acted_models):
        return out.no_row("publisher-as-agent",
                          "the stream names one of the organisation's writing identities as the "
                          "model — the bot is the pen, never the agent")
    if not facts.acted_models:
        return out.no_row("model-absent", "no `assistant` event names a model")
    if len(facts.acted_models) > 1:
        return out.no_row("model-ambiguous",
                          f"{len(facts.acted_models)} models took turns: "
                          f"{', '.join(facts.acted_models)}")
    if not facts.acted_models[0].startswith(MODEL_PREFIX):
        return out.no_row("provider-unresolved",
                          f"`{facts.acted_models[0]}` is not a provider this producer can name")
    if not facts.harness_version:
        return out.no_row("harness-version-absent", "the `init` event names no client version")
    if ci_row.accounting_mode(facts.api_key_source) is None:
        return out.no_row("credential-ambiguous",
                          "the runner's `apiKeySource` names a credential class this producer does "
                          "not record, so the ledger a row belongs to is not established")

    missing = [why for name, why in REQUIRED_COMPONENTS.items() if not supplied[name]]
    if missing:
        return out.no_row("components-absent",
                          "the producing job exported no " + "; no ".join(sorted(missing)))
    if not RFC3339_UTC.match(supplied["review_started_at"]):
        return out.no_row("started-at-unparsed",
                          f"`{supplied['review_started_at']}` is not an RFC 3339 UTC instant")
    if not SHA1.match(supplied["head_sha"]):
        return out.no_row("head-sha-unparsed", f"`{supplied['head_sha']}` is not a commit")
    if supplied["head_sha"] != args.event_head_sha:
        return out.no_row("head-sha-mismatch",
                          f"the producing job read `{supplied['head_sha']}` and this event names "
                          f"`{args.event_head_sha}` — the row would describe a tree this pull "
                          f"request did not have reviewed")
    # `checkout-sha` names the tree the components were hashed from and `head-sha` names the pull
    # request's head; the row records the second. While they are one commit the hash describes the
    # tree the row names, and where they part the row would carry a digest over a tree no reader
    # can resolve from it.
    if supplied["checkout_sha"] and supplied["checkout_sha"] != supplied["head_sha"]:
        return out.no_row("components-off-head",
                          f"the components were read at `{supplied['checkout_sha']}` and the row "
                          f"names `{supplied['head_sha']}`")
    if args.verdict_source not in ci_row.VERDICT_ROUTES:
        return out.no_row("verdict-route-unknown",
                          f"the publication reports `{args.verdict_source}`, which is not a "
                          f"transport this contract admits")

    out.date = supplied["review_started_at"][:10]
    out.fence = ci_row.fence_id(out.date, PRODUCER, facts.harness_version)
    out.branch = f"inbox/{slug(args.repository)}/{out.date}"

    # VISIBILITY IS ASKED FIRST, and it decides two things. It decides which inbox the row belongs
    # to — fail-closed, one way only, because a row filed under the wrong one is published by the
    # act of filing it. And it decides whether anything else is asked at all: the two reads here
    # are a repository and a pull request, so the job needs `contents: read` and `pull-requests:
    # read` and nothing beyond what a caller already grants the review. A repository whose
    # visibility is anything else is refused here, before a read of a tree this inbox cannot hold.
    repo_json = fetcher.get(f"repos/{args.repository}")
    out.visibility = ci_row.visibility(None if absent(repo_json) else repo_json)
    if out.visibility != INBOX_VISIBILITY:
        return out.no_row("inbox-absent",
                          f"the repository is `{out.visibility}` and the inbox that holds such "
                          f"rows does not exist yet, so the row is counted and not written")

    pull = fetcher.get(f"repos/{args.repository}/pulls/{args.pull_request}")
    if absent(pull) or not isinstance(pull, dict):
        return out.no_row("pr-unreadable",
                          f"pull request {args.pull_request} did not answer, so neither its scope "
                          f"class nor the human accountable for it is established")
    out.author = str((pull.get("user") or {}).get("login") or "")
    if ci_row.scope_from_body(pull.get("body")) is None:
        return out.no_row("scope-unparsed",
                          f"pull request {args.pull_request} declares no scope class this table "
                          f"admits")

    # The artefact's own id, which is half of the row's identity and the whole of the stream's file
    # name. The run alone would not be unique: one run uploads one execution artefact today and
    # nothing stops a second, and two rows named alike are one row lost.
    #
    # HANDED OVER, NOT LOOKED UP. The step that uploaded the artefact is told its id by the host,
    # and the producing job carries it out beside the components it hashed. Asking the platform
    # instead would mean `GET /repos/…/actions/runs/…/artifacts`, which is gated on the Actions
    # permission: this job holds `contents: read`, a called workflow cannot widen past its caller,
    # and the read would refuse on every capture rather than on an unusual one.
    artifact_id = (args.artifact_id or "").strip()
    if not artifact_id.isdigit():
        return out.no_row("artifact-unresolved",
                          f"the producing job named no id for `{args.execution_artifact}`, so the "
                          f"stream the row references cannot be named")
    out.run_id = ci_row.run_id(args.workflow_run_id, artifact_id)
    out.row_path = os.path.join("inbox", out.date, "runs", out.run_id + ".json")
    # The artefact is uploaded by the run whose start this is, so the run's own start is what dates
    # it — and the two dates a record carries are then one date by construction, where an artefact
    # creation instant read from the platform could fall on the other side of midnight from the
    # review it belongs to.
    created_at = supplied["review_started_at"]
    out.stream = {
        "repo": args.repository,
        "workflow_run_id": int(args.workflow_run_id),
        "artifact_id": int(artifact_id),
        "artifact_name": args.execution_artifact,
        "path": stream_path(created_at[:10], args.repository, args.workflow_run_id, artifact_id),
        "sha256": digest,
        "size_bytes": len(data),
        "event_count": facts.event_count,
        "created_at": created_at,
        "artifact_expires_at": artifact_expiry(created_at, args.artifact_retention_days),
    }
    out.state = "decided"
    return out


# --------------------------------------------------------------------------------------------
# The row
# --------------------------------------------------------------------------------------------


def build(args, out: Decision, fetcher, ci_row) -> dict:
    """The row itself, from the exported components, the stream's own counts and the REST facts.

    Every argument of `ci_row.assemble` is named here rather than defaulted, so a field this
    producer stops deriving is a `TypeError` at assembly instead of a row missing a key the inbox
    discovers later.
    """
    with open(args.log, "rb") as handle:
        data = handle.read()
    facts = ci_row.stream_facts(json.loads(data))
    pull = fetcher.get(f"repos/{args.repository}/pulls/{args.pull_request}")

    return ci_row.assemble(
        run_id=out.run_id,
        started_at=args.review_started_at,
        fingerprint=ci_row.fingerprint_ci(args.repository, args.pull_request, args.head_sha),
        domain=ci_row.REVIEW_LIVE_DOMAIN,
        scope=ci_row.scope_from_body((pull or {}).get("body")),
        provider=PROVIDER,
        model_id=facts.acted_models[0],
        harness_client=HARNESS_CLIENT,
        harness_version=facts.harness_version,
        system_prompt_sha256=args.system_prompt_sha256,
        repository=args.repository,
        visibility=out.visibility,
        commit=args.head_sha,
        bundle_version=args.bundle_version,
        turns=facts.turns,
        tool_calls=facts.tool_calls,
        wall_time_ms=facts.wall_time_ms,
        event_stream_ref=ci_row.event_stream_ref(
            args.streams_repository, out.stream["path"], args.stream_commit),
        event_stream_sha256=out.stream["sha256"],
        event_count=out.stream["event_count"],
        accounting_mode=ci_row.accounting_mode(facts.api_key_source),
        usage=facts.usage,
        oracle=ci_row.REVIEW_DISPOSITION_ORACLE,
        outcome=OUTCOME,
        capture_version=capture_version(args.execution_root),
        fence=out.fence,
        tool_surface=args.tool_surface or None,
        verdict_route=ci_row.VERDICT_ROUTES[args.verdict_source],
        permission_denials=facts.permission_denials,
        capture_level=CAPTURE_LEVEL,
        human_prompts=facts.human_prompts,
        # ABSENT, ALWAYS, AND NEVER EMPTY. The contract fills this field from a producer that owns
        # the run's worktree and lists the commits between the commit the run started from and its
        # branch head; an empty array is that producer's measurement, saying it watched the branch
        # and the run committed nothing. This producer watches no branch — it reviews a tree it
        # does not write — so it cannot say what the run committed, and the two readings are not
        # recoverable from each other once a row is in the dataset.
        result_commits=None,
    )


def capture_version(root: str) -> str:
    """The row contract's version, read from the checkout the derivations came from.

    `instrument.capture_version` says which contract a row answers to, so it is read from the same
    tree that supplied the shape rather than written down here: two values for one row are one of
    them wrong, and the checkout is the one that can be checked.
    """
    with open(os.path.join(root, "schemas", "VERSION"), encoding="utf-8") as handle:
        return handle.read().strip()


def validate(row: dict, out: Decision, root: str, ci_row, Report, check) -> list[str]:
    """The row through the inbox's own gate, before anything is proposed to the inbox.

    Both halves, because each sees what the other cannot. The validator holds the cross-file rules
    and the names this organisation owns; `jsonschema` holds the shape. They run in a throwaway
    inbox declaring the visibility this row is bound for, since rule 1 is fail-closed on that
    identity and a row checked against the wrong one passes a test it was never subject to.

    A refusal here is a producer defect and is recorded as one (§C.15): the row never enters a
    batch, so one bad row does not hold up good ones.
    """
    where = tempfile.mkdtemp(prefix="capture-ci-row-")
    try:
        shutil.copytree(os.path.join(root, "schemas"), os.path.join(where, "schemas"))
        target = os.path.join(where, out.row_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(ci_row.dump(row))
        with open(os.path.join(where, "inbox", "inbox.json"), "w", encoding="utf-8") as handle:
            json.dump({"visibility": out.visibility}, handle)
        report = Report()
        check(where, report)
        refusals = [message for _path, message in report.bad]
    finally:
        shutil.rmtree(where, ignore_errors=True)
    return refusals + schema_refusals(row, os.path.join(root, "schemas"))


def schema_refusals(row: dict, schemas: str) -> list[str]:
    """Every way the row's shape disagrees with the contract, or nothing where it agrees.

    Separate from the validator above because it needs an installed Draft 2020-12 validator, which
    the validator deliberately does not: a producer checking its own rows where no validator is
    installed still gets the cross-file half. Here both are available and both are asked.
    """
    try:
        from jsonschema import Draft202012Validator                      # noqa: PLC0415
    except ImportError:
        return ["`jsonschema` is not installed, so the row's shape was never checked against the "
                "contract — the inbox's own gate would be the first to read it"]
    with open(os.path.join(schemas, "run-record.schema.json"), encoding="utf-8") as handle:
        validator = Draft202012Validator(json.load(handle))
    return [f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
            for error in sorted(validator.iter_errors(row), key=lambda e: list(e.path))]


def write_row(root: str, out: Decision, text: str) -> None:
    """Append a row to the inbox clone, or refuse. `inbox/` is appended to and never rewritten.

    Identical bytes are a second capture of one run and are a skip, which is what makes a re-run of
    this job harmless. Different bytes under one name are two answers about one run, and the repair
    is a new row and a fence — never an overwrite, which would take the first answer out of the
    record as though it had never been given.
    """
    target = os.path.join(root, out.row_path)
    if os.path.exists(target):
        with open(target, encoding="utf-8") as handle:
            if handle.read() == text:
                out.state = "skip"
                return
        out.state = "refused"
        out.refusals = [f"`{out.row_path}` already holds a different row for this run"]
        out.reason = "row-exists-differs"
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    out.state = "new"


# --------------------------------------------------------------------------------------------
# What the caller is told
# --------------------------------------------------------------------------------------------


def pull_request_body(out: Decision) -> str:
    """The inbox pull request's body, in the shape the receiving repository's gate requires.

    It names the human whose pull request produced the rows, which is §C.15's requirement and the
    reason the body is assembled rather than left to a template: the accountable person is a fact
    about the batch, and a body that did not carry it would make the batch anonymous.

    Written once, when the branch is opened. The branch collects the day's rows, so the body speaks
    of the day rather than of a count it would have to be edited to keep true.
    """
    who = f"@{out.author}" if out.author else "an author the platform did not name"
    return "\n".join([
        f"Motivation: the L2 reviews of {out.repository} on {out.date} produced run records; a row "
        f"that is not filed is a measurement that was not taken.",
        "",
        f"Modification: adds the day's rows under `inbox/{out.date}/runs/`, captured by the "
        f"reviewing workflow of {out.repository}. The pull request behind the first of them was "
        f"opened by {who}.",
        "",
        "Result: the inbox holds one row per review run of that day. The producer ran this "
        "repository's own validator before opening this pull request, so a row that fails it never "
        "reaches the batch.",
        "",
        "## Classification",
        "",
        "Scope class: docs-only",
        "Wall impact: none",
        "Generated files touched: no",
        "TCK obligation: n/a",
        "Compatibility impact: none",
        f"Cross-repo impact: {out.repository}: the rows describe review runs in that repository",
        "ADRs referenced: ADR-086, ADR-087",
        "Evidence state: citable",
        "",
        "## Verification",
        "",
        "The producer validated every row against the cross-file rules and the record schema "
        "before this branch was pushed; the required checks on this pull request read them again.",
        "",
        "Refs: ADR-086, ADR-087",
    ]) + "\n"


def commit_message(out: Decision) -> str:
    """The commit in the organisation's grammar, sections included.

    A `feat` commit carries Motivation, Modification and Result, and this one is written by a
    producer — so it is written correctly here rather than fixed by hand afterwards. The subject is
    the pull request's title too: one branch per repository per day, so the two describe the same
    batch and the squash subject needs no second spelling.
    """
    return "\n".join([
        f"feat(inbox): rows from {out.repository} on {out.date}",
        "",
        "Motivation: one run record per L2 review run, captured where the run happened "
        "(ADR-087 §C.13).",
        "",
        f"Modification: adds {out.row_path}, referencing its event stream by commit and digest.",
        "",
        "Result: the day's review runs are in the inbox, validated at the producer before they "
        "were proposed.",
        "",
        "Refs: ADR-086, ADR-087",
    ]) + "\n"


def issue_body(out: Decision) -> str:
    """The issue a refused row files in the SOURCE repository, keyed and naming its human.

    Keyed so a re-run finds it and files nothing (§D.21's shape); in the source repository because
    the defect is the producer's to fix there, not the inbox's to quarantine (§C.15).
    """
    who = f"@{out.author}" if out.author else "the pull request's author"
    refusals = "\n".join(f"- {said}" for said in out.refusals) or "- (no refusal was recorded)"
    return "\n".join([
        f"Key: `{out.issue_key}`",
        "",
        f"The capture step assembled a run record for run `{out.run_id}` of pull request "
        f"#{out.pull_request} ({who}) and the row did not pass the inbox's own rules, so it was "
        f"not filed. The row is kept as the workflow artefact `l2-row-{out.pull_request}-invalid` "
        f"of that run.",
        "",
        "What the validator said:",
        "",
        refusals,
        "",
        "A row is repaired at the producer, never in the inbox: the record that reaches the "
        "dataset says what the run did, and a row edited afterwards says what its editor later "
        "believed.",
    ]) + "\n"


def refusal_issue(out: Decision, args) -> None:
    """The text of the issue a refusal files, written where the caller can hand it to the host.

    Written by the producer rather than assembled in a shell, because the body carries the key a
    re-run finds it by and the refusals the validator gave, and a body assembled by string
    substitution somewhere else is a body that can lose either.
    """
    with open(args.issue_body, "w", encoding="utf-8") as handle:
        handle.write(issue_body(out))


def summary(out: Decision) -> str:
    """The Markdown half of the log — what this capture did, in one table.

    Every no-row reason is printed with the row it cost, because the question this producer is read
    for is not whether a row is possible but how many runs yield one and what stops the rest.
    """
    lines = [
        "## capture_ci_row",
        "",
        f"- run: `{out.run_id or '(unresolved)'}`",
        f"- repository: `{out.repository}`, pull request #{out.pull_request}",
        f"- row: **{out.state or 'none'}**" + (f" — `{out.row_path}`" if out.row_path else ""),
    ]
    if out.reason:
        lines.append(f"- no row: `{out.reason}` — {out.detail}")
    if out.refusals:
        lines += ["", "| Refusal |", "|:--|"] + [f"| {said} |" for said in out.refusals]
    return "\n".join(lines) + "\n"


def emit(out: Decision, args) -> None:
    """One JSON line for a log, the decision as a file, and the summary where CI shows it."""
    print(json.dumps(out.as_json(), sort_keys=True, ensure_ascii=False))
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(out.as_json(), handle, indent=2, sort_keys=True, ensure_ascii=False)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as handle:
            handle.write(summary(out))


def main(argv: list[str] | None = None, fetcher=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execution-root", required=True,
                        help="a checkout of the row contract's repository: `tools/` and `schemas/`")
    parser.add_argument("--log", default="",
                        help="the runner's execution log, as the produce job uploaded it")
    parser.add_argument("--repository", required=True, help="the reviewed repository")
    parser.add_argument("--pull-request", type=int, required=True)
    # The event's own head, beside the producing job's exported one. Two answers to one question
    # are kept apart so that they can be compared: a producing job that read another commit is a
    # row about a tree this pull request is not.
    parser.add_argument("--event-head-sha", default="",
                        help="the commit under review, as this event names it")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--execution-artifact", default="",
                        help="the artefact name the produce job uploaded the log under")
    parser.add_argument("--artifact-id", default="",
                        help="the id the host gave that artefact, as the produce job's upload step "
                             "reported it")
    parser.add_argument("--artifact-retention-days", type=int,
                        default=EXECUTION_ARTIFACT_RETENTION_DAYS,
                        help="the retention the produce job's upload declared, for the index "
                             "entry's expiry")
    parser.add_argument("--verdict-source", default="none",
                        help="which transport carried the verdict, as the publication reports it")
    parser.add_argument("--streams-repository", default=STREAMS_REPO)
    parser.add_argument("--stream-commit", default="",
                        help="the commit the stream was committed at; without it this decides and "
                             "assembles nothing")
    parser.add_argument("--inbox-root", default="",
                        help="a checkout of the inbox repository on the day's branch")
    parser.add_argument("--out", default="capture-decision.json")
    parser.add_argument("--row", default="row.json")
    # The message and the body are written BESIDE the clone, never inside it: a file written into
    # the inbox checkout is a file the next commit carries into the inbox, and the inbox holds
    # records and nothing else.
    parser.add_argument("--commit-message", default="capture-commit-message.txt")
    parser.add_argument("--pull-request-body", default="capture-pull-request-body.md")
    parser.add_argument("--issue-body", default="capture-issue-body.md",
                        help="where the text of a refusal's issue is written, when there is one")
    for name in CAPTURE_INPUTS:
        parser.add_argument("--" + name.replace("_", "-"), default="",
                            help="the producing job's exported component of that name")
    args = parser.parse_args(argv)

    try:
        ci_row, Report, check = tooling(args.execution_root)
    except ImportError as exc:
        # The checkout, not the run. A branch of the contract's repository that does not carry the
        # derivations yet is a capture that cannot assemble a row at all, and saying so is not the
        # same as saying this run yielded none.
        print(f"::error::capture_ci_row: `{args.execution_root}` does not carry the row contract's "
              f"derivations ({exc}) — nothing about this run was read")
        return 2
    try:
        out = decide(args, fetcher or Fetcher(), ci_row)
    except FetchError as exc:
        print(f"::error::capture_ci_row: {exc}")
        return 2
    if out.reason or not args.stream_commit:
        emit(out, args)
        return 0

    try:
        row = build(args, out, fetcher or Fetcher(), ci_row)
    except ci_row.PublisherAsAgent as exc:
        out.no_row("publisher-as-agent", str(exc))
        emit(out, args)
        return 0
    except FetchError as exc:
        print(f"::error::capture_ci_row: {exc}")
        return 2
    except OSError as exc:
        # The checkout, not the run: a tree that does not carry the contract is a defect in the job
        # rather than a fact about the review, so it is reported as one instead of costing a row.
        print(f"::error::capture_ci_row: the row contract's checkout is incomplete ({exc})")
        return 2
    text = ci_row.dump(row)
    with open(args.row, "w", encoding="utf-8") as handle:
        handle.write(text)

    out.refusals = validate(row, out, args.execution_root, ci_row, Report, check)
    if out.refusals:
        out.state, out.reason = "refused", "validator-refused"
        out.detail = "; ".join(out.refusals)
        refusal_issue(out, args)
        emit(out, args)
        return 0
    if args.inbox_root:
        write_row(args.inbox_root, out, text)
        if out.state == "refused":
            refusal_issue(out, args)
        if out.state in ("new", "skip"):
            with open(args.pull_request_body, "w", encoding="utf-8") as handle:
                handle.write(pull_request_body(out))
            with open(args.commit_message, "w", encoding="utf-8") as handle:
                handle.write(commit_message(out))
    else:
        out.state = "assembled"
    emit(out, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
