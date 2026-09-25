#!/usr/bin/env python3
"""One judgement record per L2 review run, written when the pull request closes — ADR-087 §C.16.

A run record is complete when the review ends and its outcome is `UNKNOWN`: the oracle has not
judged yet. `review-disposition` judges afterwards, from what the human did with the review, and its
verdict arrives as a SECOND record keyed by the run's id (ADR-086 §C.12a). The run record is never
touched — a row written at review time and filled in at merge would be a rewrite, and the inbox
appends and marks and never rewrites.

WHAT THE ORACLE READS, and what `rest-v1` says it cannot. ADR-086 §D.15 defines a finding as
*addressed* when the file its `location` names changed after the review **and its thread was
resolved**, as *overruled* when a blocking finding was merged over with the file unchanged, and as
*unresolved* otherwise. The host's REST API exposes no thread resolution, and the publication this
oracle reads is one comment carrying no threads, so the second half of the first clause is EMPTY
under this version — the oracle applies what it can read and `rest-v1` is what says which definition
was in force. Rows either side of an implementation that can read resolution are not one population.

NOTHING OF THE RUN'S TEXT REACHES THE RECORD. The stream is read for its fenced verdict's findings,
and for the client version a record kept for repair is dated under; the pull request is read for its
head, its merge and the instant it closed. A disposition is an index and a word — a reader joins to
the verdict.

NO JUDGEMENT WITHOUT ITS RUN. Rule 5 of the inbox validator refuses a judgement whose `run_id` does
not resolve to a run record in the same inbox, so the row is looked for before the judgement is
filed — on the default branch, and on the day's open branch only where that branch is the one this
judgement lands on. A row proposed and not yet merged is still a row this producer wrote, but a row
on another day's branch is not in the tree this judgement's own batch is validated over, and a
judgement filed beside a row that is not there is red for the whole batch. Where it is on neither,
the judgement is kept as an artefact and one issue is filed in the source repository: §C.16 calls
that the producer's defect to fix, not a gap to hide.

ONE FENCE FOR A RUN AND ITS JUDGEMENT, and it is the run's own, read from the row rather than
derived here. §C.12a reads a run's outcome as the latest judgement inside the fence in force, so a
judgement under a second id is a judgement a reader partitioning by fence never finds — and an id
minted per closing day resolves in no entry of the register, which holds one id per producer per
client version. Nothing of what the judgement SAYS comes out of that row; which partition it is IN
is a property of the run, and the run's record is where the run states it.

The derivations are the row contract's — `tools/ci_row.py` and `tools/inbox_validate.py` in the
repository the rows land in — and are imported from its checkout rather than copied, for the reason
`capture_ci_row.py` gives: two copies of one contract agree until one of them is edited.

Usage:
  judge_review.py --execution-root DIR --repository OWNER/NAME --pull-request N
                  [--streams-repository R] [--execution-repository R] [--inbox-root DIR]
                  [--out judge-decision.json] [--unresolved-dir DIR]
"""
from __future__ import annotations

import argparse
import base64
import binascii
import dataclasses
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import capture_ci_row as capture                                          # noqa: E402

# The producer this is, in a fence id, and it is the SAME producer as the row's: the fence marks how
# a measurement was made, and the judgement of a `ci-live` row is made by the `ci-live` producer at
# the client version that row ran under. A filed record takes the row's own fence; this name is
# spent on the provisional one a record kept for repair carries, and a second name there would
# describe a producer that does not exist.
PRODUCER = capture.PRODUCER

# ADR-086 §E.19, and by construction: `review-disposition` is observational and its calibration
# status is `not-run`, so the schema admits no other value here.
OUTCOME = "UNKNOWN"

# The one inbox that exists, and the same fail-closed reading §C.17 gives the row: a judgement about
# a run in a repository this inbox cannot hold belongs in the sibling that has not been created, and
# is counted rather than filed somewhere it can be read.
INBOX_VISIBILITY = "public"

EXECUTION_REPO = "exeris-systems/exeris-ai-execution"

# What the produce job names the execution artefact of one pull request: `l2-execution-<pr>-<part>`,
# the part being `all` for a run of the whole routine, and `l2-execution-<pr>` a stream that names
# no part. It is what joins a stream in the streams repository to the pull request this event is
# about, and it is read with `ci_row.pr_number`, the same reading the row's producer applies, so a
# part's stream joins the pull request its row was filed against.
ARTIFACT_NAME = "l2-execution-{pull_request}"

# The media type under which the host serves a file it declined to inline. The contents endpoint
# answers with base64 up to its own ceiling and with `encoding: "none"` and an empty body above it;
# an execution log is routinely above it.
RAW = "application/vnd.github.raw"

# `<path>:<line>` or `<path>:<line>-<line>` — the trailing anchor of a finding's `location`, which
# is taken off to leave the file. A location with no anchor is already a file.
LOCATION_ANCHOR = re.compile(r":\d+(?:-\d+)?$")

ADDRESSED, OVERRULED, UNRESOLVED = "addressed", "overruled", "unresolved"

# What the host calls a comparison whose base is still on the head's line. Anything else says the
# two commits have parted company, and a three-dot comparison then answers about a merge base that
# is not the commit asked about.
COMPARABLE = ("ahead", "identical")


@dataclasses.dataclass
class One:
    """What became of one run's judgement: a record, or a counted reason there is none.

    `reason` is the whole of the no-judgement vocabulary, one value per way this producer declines,
    so a step summary counts declines rather than reading prose. `state` is what became of a record
    that was assembled: filed, already there byte for byte, refused by the inbox's own rules, or
    kept back because the run it judges is not in the inbox.
    """

    run_id: str = ""
    judgement_id: str = ""
    reason: str | None = None
    detail: str = ""
    state: str = ""
    path: str = ""
    reviewed_sha: str = ""
    fence: str = ""
    findings: int = 0
    dispositions: list | None = None
    refusals: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Decision:
    """What one closed pull request produced, over every run that reviewed it."""

    repository: str = ""
    pull_request: int | None = None
    issue_key: str = ""
    author: str = ""
    merged: bool = False
    judged_at: str = ""
    date: str = ""
    branch: str = ""
    visibility: str = ""
    head_sha: str = ""
    reason: str | None = None
    detail: str = ""
    judgements: list = dataclasses.field(default_factory=list)

    def nothing(self, reason: str, detail: str = "") -> "Decision":
        self.reason, self.detail = reason, detail
        return self

    def counted(self, state: str) -> int:
        return sum(1 for one in self.judgements if one.get("state") == state)

    def as_json(self) -> dict:
        out = dataclasses.asdict(self)
        out["written"] = self.counted("new")
        out["skipped"] = self.counted("skip")
        out["kept_back"] = self.counted("unresolved") + self.counted("refused")
        return out


# --------------------------------------------------------------------------------------------
# What the host is asked
# --------------------------------------------------------------------------------------------


def json_file(fetcher, repo: str, path: str, ref: str, token: str | None) -> object | None:
    """One JSON file of a repository at a ref, whatever its size, or None where there is none.

    The contents endpoint inlines a file as base64 up to its own ceiling and answers with
    `encoding: "none"` above it; an execution log is routinely above it. So the answer is read
    rather than assumed, and where the host declined to inline the bytes the same path is asked for
    again under the raw media type. One function for both, because a producer that read small files
    one way and large files another would work until the first stream that grew.
    """
    body = fetcher.get(f"repos/{repo}/contents/{path}?ref={ref}", token=token)
    if capture.absent(body) or not isinstance(body, dict):
        return None
    if body.get("encoding") == "base64":
        try:
            return json.loads(base64.b64decode(body.get("content") or "").decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
    raw = fetcher.get(f"repos/{repo}/contents/{path}?ref={ref}", token=token, accept=RAW)
    return None if capture.absent(raw) else raw


def changed_files(fetcher, repository: str, base: str,
                  head: str) -> tuple[set[str] | None, str]:
    """The files that differ between the commit the review read and the pull request's head.

    Two commits rather than a pull request's file list, because the question is what changed AFTER
    the review: a pull request's files are its whole diff from the base branch, which includes
    everything the reviewer already read and would make every finding read as addressed.

    AND THE COMPARISON'S OWN VERDICT IS READ, not its file list alone. `compare/<base>...<head>` is
    a THREE-DOT comparison: the host diffs from the merge base of the two commits rather than from
    `base`. While the reviewed commit is on the head's line the merge base IS that commit and the
    answer is the one this oracle wants. Once the branch is rewritten after the review — rebased,
    amended, force-pushed, which is exactly what acting on a finding by rewriting history looks
    like — the reviewed commit is orphaned, the merge base falls back to where the branch left its
    base, and `files` becomes the pull request's whole diff. That is the file set that makes every
    finding read as addressed, which is the reading this function exists to refuse.

    So the answer is a file set or a named reason there is none, and never a file set that is not
    what changed after the review.
    """
    body = fetcher.get(f"repos/{repository}/compare/{base}...{head}")
    if capture.absent(body) or not isinstance(body, dict):
        return None, "compare-unreadable"
    merge_base = str((body.get("merge_base_commit") or {}).get("sha") or "")
    if str(body.get("status") or "") not in COMPARABLE or merge_base != base:
        return None, "reviewed-history-gone"
    files = body.get("files")
    if not isinstance(files, list):
        return set(), ""
    return {str(one.get("filename")) for one in files if isinstance(one, dict)
            and one.get("filename")}, ""


# --------------------------------------------------------------------------------------------
# The oracle
# --------------------------------------------------------------------------------------------


def location_file(location: object) -> str | None:
    """The file a finding is anchored to, or None where it names no site.

    `location` is `<path>:<line>` and is optional: a finding may be about the change as a whole.
    Such a finding has no file to watch, so nothing about the subsequent history can say it was
    addressed — which is what makes `unresolved` the honest answer rather than a default.
    """
    if not isinstance(location, str) or not location.strip():
        return None
    return LOCATION_ANCHOR.sub("", location.strip()) or None


def disposition(finding: object, changed: set[str], merged: bool) -> str:
    """What the human did with one finding, in `review-disposition`'s three values.

    The order is the definition's (ADR-086 §D.15) and each branch answers a different question. A
    finding with no site cannot be watched. A finding whose file changed after the review was acted
    on, and that is true whether or not the pull request merged — a change is a change. A blocking
    finding that the human merged over with the file untouched was overruled, which needs the merge:
    a pull request closed without merging overrode nothing, it was abandoned. Everything else is
    unresolved, which is the value that carries no claim.
    """
    if not isinstance(finding, dict):
        return UNRESOLVED
    where = location_file(finding.get("location"))
    if where is None:
        return UNRESOLVED
    if where in changed:
        return ADDRESSED
    if merged and finding.get("blocking") is True:
        return OVERRULED
    return UNRESOLVED


def dispositions(findings: list, changed: set[str], merged: bool) -> list[dict]:
    """One entry per finding, keyed by its position in the verdict's `findings[]`.

    A position rather than an identifier because a finding has none, and it is sound only because a
    published verdict is immutable. Nothing of the finding is copied: a reader joins to the verdict.
    """
    return [{"finding_index": index, "disposition": disposition(finding, changed, merged)}
            for index, finding in enumerate(findings)]


def judgement_id_of(run_id: str, judged_at: str) -> str:
    """`<run>-disposition-<instant>` — a judgement is named by its run AND the instant it judged.

    ADR-086 §C.12a admits many judgements of one run, and a pull request reopened and closed again
    produces one: a second `closed` event, a later `judged_at`, a different record. A name carrying
    the run alone would make that second answer collide with the first, and the producer would
    report as its own defect what is a human reopening a pull request. Two answers about ONE
    closing instant remain one name, which is the collision worth refusing.

    The instant is spelled without its separators because the contract's pattern for an id admits
    none.
    """
    return f"{run_id}-disposition-{re.sub(r'[^0-9A-Za-z]', '', judged_at)}"


def row_fence(run_row: object) -> str:
    """The fence the run's own row names, or "" where there is no row or it names none."""
    instrument = run_row.get("instrument") if isinstance(run_row, dict) else None
    return str(instrument.get("fence") or "") if isinstance(instrument, dict) else ""


def record(judgement_id: str, run_id: str, judged_at: str, fence: str, capture_version: str,
           disposed: list | None, ci_row) -> dict:
    """One judgement record, in the shape `judgement-record.schema.json` fixes.

    `dispositions` is ABSENT where no verdict was found and EMPTY where one was found with no
    findings. The two are different facts — an oracle that had nothing to read, and an oracle that
    read a review which found nothing — and a producer writing `[]` for both would make them one
    value in a column that cannot tell them apart.
    """
    out = {
        "judgement_id": judgement_id,
        "run_id": run_id,
        "oracle": ci_row.REVIEW_DISPOSITION_ORACLE,
        "judged_at": judged_at,
        "outcome": OUTCOME,
        "instrument": {"capture_version": capture_version, "fence": fence},
    }
    if disposed is not None:
        out["dispositions"] = disposed
    return out


# --------------------------------------------------------------------------------------------
# The inbox's own gate
# --------------------------------------------------------------------------------------------


def validate(judgement: dict, run_row: object, out: One, date: str, run_date: str,
             visibility: str, root: str, ci_row, Report, check) -> list[str]:
    """The judgement through the inbox's own rules, before anything is proposed to the inbox.

    Both halves, because each sees what the other cannot: the validator holds the cross-file rules —
    rule 5 among them, which is the whole reason the run row is fetched — and `jsonschema` holds the
    shape. They run in a throwaway inbox declaring the visibility this record is bound for, and
    carrying the run row where one was found, because rule 5 asks whether the run is in THIS inbox
    and a judgement checked against an inbox that holds no runs fails a test it was never subject to.
    """
    where = tempfile.mkdtemp(prefix="judge-review-")
    try:
        shutil.copytree(os.path.join(root, "schemas"), os.path.join(where, "schemas"))
        target = os.path.join(where, "inbox", date, "judgements", out.judgement_id + ".json")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(ci_row.dump(judgement))
        if isinstance(run_row, dict):
            beside = os.path.join(where, "inbox", run_date, "runs", out.run_id + ".json")
            os.makedirs(os.path.dirname(beside), exist_ok=True)
            with open(beside, "w", encoding="utf-8") as handle:
                handle.write(ci_row.dump(run_row))
        with open(os.path.join(where, "inbox", "inbox.json"), "w", encoding="utf-8") as handle:
            json.dump({"visibility": visibility}, handle)
        report = Report()
        check(where, report)
        refusals = [message for _path, message in report.bad]
    finally:
        shutil.rmtree(where, ignore_errors=True)
    return refusals + schema_refusals(judgement, os.path.join(root, "schemas"))


def schema_refusals(judgement: dict, schemas: str) -> list[str]:
    """Every way the record's shape disagrees with the contract, or nothing where it agrees.

    The judgement schema states most of its fields as `$ref`s into the run record's, so a shape has
    one home and a change to it reaches both records. A validator built over the file alone cannot
    follow them — the schemas carry no `$id`, so a relative reference has no base to resolve
    against — and reports every such field as unresolvable rather than as valid. So the directory is
    registered first and the validation goes through the file's own URI, which is what gives the
    references a base.
    """
    try:
        from jsonschema import Draft202012Validator                      # noqa: PLC0415
        from referencing import Registry, Resource                       # noqa: PLC0415
        from referencing.jsonschema import DRAFT202012                   # noqa: PLC0415
    except ImportError:
        return ["`jsonschema` and `referencing` are not both installed, so the record's shape was "
                "never checked against the contract — the inbox's own gate would be the first to "
                "read it"]
    registry = Registry()
    for name in sorted(os.listdir(schemas)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(schemas, name), encoding="utf-8") as handle:
                doc = json.load(handle)
        except (json.JSONDecodeError, OSError):
            continue
        registry = registry.with_resource(
            "file://" + os.path.abspath(os.path.join(schemas, name)).replace(os.sep, "/"),
            Resource.from_contents(doc, default_specification=DRAFT202012))
    uri = "file://" + os.path.abspath(
        os.path.join(schemas, "judgement-record.schema.json")).replace(os.sep, "/")
    validator = Draft202012Validator({"$ref": uri}, registry=registry)
    return [f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
            for error in sorted(validator.iter_errors(judgement),
                                key=lambda e: list(e.absolute_path))]


def write_judgement(root: str, out: One, text: str) -> None:
    """Append the record to the inbox clone, or refuse. `inbox/` is appended to, never rewritten.

    Identical bytes are the same closing instant judged twice and are a skip, which is what makes
    a re-run harmless. A later close is not this case at all — it judges at another instant and is
    named by it, so it appends. Different bytes under ONE name are two answers about one closing
    instant, and the repair is a new record and a fence, never an overwrite: overwriting takes the
    first answer out of the record as though it had never been given.
    """
    target = os.path.join(root, out.path)
    if os.path.exists(target):
        with open(target, encoding="utf-8") as handle:
            if handle.read() == text:
                out.state = "skip"
                return
        out.state = "refused"
        out.reason = "judgement-exists-differs"
        out.refusals = [f"`{out.path}` already holds a different judgement of this run"]
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    out.state = "new"


# --------------------------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------------------------


def judge_one(args, out: Decision, entry: dict, fetcher, ci_row, tools, token) -> One:
    """The judgement of one run of this pull request, from the stream it produced and the history.

    Every reason there is no judgement returns at the point it is established, because a component
    this producer cannot read is answered with no record and a named reason rather than with a
    convenient value — §C.14's rule, applied to the second record.
    """
    Report, check = tools
    workflow_run_id, artifact_id = entry.get("workflow_run_id"), entry.get("artifact_id")
    one = One(run_id=ci_row.run_id(workflow_run_id, artifact_id))
    one.judgement_id = judgement_id_of(one.run_id, out.judged_at)
    one.path = os.path.join("inbox", out.date, "judgements", one.judgement_id + ".json")

    # THE COMMIT THE REVIEW READ, asked of the run that produced the stream. The row carries it too,
    # and this producer does not take it from there: the row is what rule 5 is about, and a
    # judgement that derived its own subject from the record it is being checked against would agree
    # with that record however wrong the record was.
    run_json = fetcher.get(f"repos/{args.repository}/actions/runs/{workflow_run_id}")
    reviewed_sha = "" if capture.absent(run_json) or not isinstance(run_json, dict) \
        else str(run_json.get("head_sha") or "")
    if not capture.SHA1.match(reviewed_sha):
        one.reason = "reviewed-sha-unresolved"
        one.detail = (f"run {workflow_run_id} names no head commit, so there is nothing to compare "
                      f"the pull request's history against")
        return one
    one.reviewed_sha = reviewed_sha

    path = str(entry.get("path") or "")
    events = json_file(fetcher, args.streams_repository, path, "main", token) if path else None
    if not isinstance(events, list):
        one.reason = "stream-unreadable"
        one.detail = f"`{path or '(unnamed)'}` did not answer as an array of events"
        return one
    facts = ci_row.stream_facts(events)

    # THE RUN ROW, and it is asked before anything is assembled because the record's fence comes
    # out of it. The default branch, and the day's open branch only where that branch is the one
    # this judgement lands on: a row proposed and not yet merged is still a row this organisation
    # wrote, so a judgement is not held back for want of a human's merge — but a row on ANOTHER
    # day's open branch is in no tree this judgement's batch is validated over, and filing beside
    # it would be red for the whole batch.
    run_date = str(entry.get("created_at") or "")[:10]
    run_path = f"inbox/{run_date}/runs/{one.run_id}.json"
    run_row = json_file(fetcher, args.execution_repository, run_path, "main", token)
    if run_row is None and run_date == out.date:
        run_row = json_file(fetcher, args.execution_repository, run_path, out.branch, token)

    # THE FENCE IS THE RUN'S OWN. A row that names none is a row nothing can be judged inside, and
    # a fence invented here would resolve in no entry of the register.
    fence = row_fence(run_row)
    if run_row is not None and not fence:
        one.reason = "run-row-fence-absent"
        one.detail = (f"`{run_path}` names no `instrument.fence`, so there is no partition to "
                      f"judge this run inside and none can be minted for it")
        return one
    # With no row there is nothing to inherit from, and what is assembled below is kept for the
    # repair rather than filed. It is dated by the RUN's own day under this producer — the id the
    # row will carry when it lands — so that a record read off the artefact is not on the far side
    # of a fence from the run it names.
    one.fence = fence or ci_row.fence_id(run_date, PRODUCER, facts.harness_version)

    # THE LAST FENCED VERDICT, which is the one the publisher published: a routine that ran twice in
    # one run publishes its latest answer, and the dispositions are about the review that stands.
    verdict = facts.verdicts[-1] if facts.verdicts else None
    findings = verdict.get("findings") if isinstance(verdict, dict) else None
    findings = findings if isinstance(findings, list) else ([] if verdict is not None else None)

    disposed = None
    if findings is not None:
        changed, why = changed_files(fetcher, args.repository, reviewed_sha, out.head_sha)
        if changed is None:
            one.reason = why
            one.detail = (
                f"the host did not compare `{reviewed_sha[:8]}` with the pull request's head, so "
                f"nothing says which files changed after the review"
                if why == "compare-unreadable" else
                f"`{reviewed_sha[:8]}` is no longer on this pull request's line — the history was "
                f"rewritten after the review, so what changed since it cannot be read")
            return one
        one.findings = len(findings)
        disposed = dispositions(findings, changed, out.merged)
    one.dispositions = disposed

    judgement = record(one.judgement_id, one.run_id, out.judged_at, one.fence,
                       capture.capture_version(args.execution_root), disposed, ci_row)

    one.refusals = validate(judgement, run_row, one, out.date, run_date, out.visibility,
                            args.execution_root, ci_row, Report, check)
    text = ci_row.dump(judgement)
    if run_row is None:
        # §C.16's own case, and it is red BY THE RULE rather than by a defect in this run: a
        # judgement whose run is not in the inbox is refused there, so it is kept where it can be
        # read and reported where it is fixed.
        one.state, one.reason = "unresolved", "run-row-absent"
        if run_date == out.date:
            one.detail = (f"`{run_path}` is on neither the default branch nor the open branch this "
                          f"judgement lands on, so rule 5 refuses a judgement of it")
        else:
            one.detail = (f"`{run_path}` is not on the default branch, and a row of {run_date} "
                          f"belongs to that day's batch rather than to this judgement's, so rule 5 "
                          f"refuses a judgement of it")
        keep(args, one, text)
        return one
    if one.refusals:
        one.state, one.reason = "refused", "validator-refused"
        one.detail = "; ".join(one.refusals)
        keep(args, one, text)
        return one
    if args.inbox_root:
        write_judgement(args.inbox_root, one, text)
        if one.state == "refused":
            keep(args, one, text)
    else:
        one.state = "assembled"
    return one


def keep(args, one: One, text: str) -> None:
    """A record that was not filed, written where the caller can upload it as the artefact.

    The record itself and not a message about it: a defect is read from what was assembled, and a
    producer that reported only its own summary would leave the thing it got wrong unreadable.
    """
    os.makedirs(args.unresolved_dir, exist_ok=True)
    with open(os.path.join(args.unresolved_dir, one.judgement_id + ".json"), "w",
              encoding="utf-8") as handle:
        handle.write(text)


# --------------------------------------------------------------------------------------------
# One pull request
# --------------------------------------------------------------------------------------------


def judge(args, fetcher, ci_row, tools, token) -> Decision:
    """Every run that reviewed this pull request, in the order the streams were produced.

    The order is deliberate: what decides whether anything is written at all — the visibility, the
    pull request, the index — is asked before any stream is fetched, because each of those costs one
    call and a pull request in a repository this inbox cannot hold yields nothing whatever the
    streams say.
    """
    out = Decision(repository=args.repository, pull_request=args.pull_request,
                   issue_key=f"{args.repository}#{args.pull_request}/judgement")

    # Fail-closed, and first, for the reason §C.17 gives the row: which inbox a record belongs to is
    # decided one way only, and a record filed under the wrong one is published by the act of filing.
    repo_json = fetcher.get(f"repos/{args.repository}")
    out.visibility = ci_row.visibility(None if capture.absent(repo_json) else repo_json)
    if out.visibility != INBOX_VISIBILITY:
        return out.nothing("inbox-absent",
                           f"the repository is `{out.visibility}` and the inbox that holds such "
                           f"records does not exist yet, so the judgement is counted and not "
                           f"written")

    # The pull request, read from the platform rather than taken from the event: the event says what
    # was true when it fired, and this job runs after it. Three facts come out of the one call —
    # when it closed, whether it merged, and the head its history ends at.
    pull = fetcher.get(f"repos/{args.repository}/pulls/{args.pull_request}")
    if capture.absent(pull) or not isinstance(pull, dict):
        return out.nothing("pr-unreadable",
                           f"pull request {args.pull_request} did not answer, so neither the "
                           f"instant it closed nor the history to read is established")
    closed_at = str(pull.get("closed_at") or "")
    if not capture.RFC3339_UTC.match(closed_at):
        return out.nothing("closed-at-unparsed",
                           f"`{closed_at}` is not an RFC 3339 UTC instant — a judgement is dated by "
                           f"when the oracle judged, and an undated one is on neither side of a "
                           f"fence")
    # The human whose pull request produced these records, carried for the batch's own pull
    # request: §C.15 asks that it name them, and a batch this half opens would otherwise be
    # anonymous where the same batch opened by the capture half is not.
    out.author = str((pull.get("user") or {}).get("login") or "")
    out.judged_at, out.date = closed_at, closed_at[:10]
    out.branch = f"inbox/{capture.slug(args.repository)}/{out.date}"
    out.merged = bool(pull.get("merged") or pull.get("merged_at"))
    out.head_sha = str((pull.get("head") or {}).get("sha") or "")
    if not capture.SHA1.match(out.head_sha):
        return out.nothing("head-sha-unparsed",
                           "the pull request names no head commit, so there is no history to read")

    index = json_file(fetcher, args.streams_repository, "index.json", "main", token)
    if not isinstance(index, list):
        return out.nothing("index-unreadable",
                           f"`{args.streams_repository}` did not answer with an index, so the runs "
                           f"that reviewed this pull request are not established")
    wanted = ARTIFACT_NAME.format(pull_request=args.pull_request)
    entries = [e for e in index if isinstance(e, dict) and e.get("repo") == args.repository
               and ci_row.pr_number(e.get("artifact_name")) == args.pull_request]
    if not entries:
        return out.nothing("no-stream",
                           f"the index holds no stream named `{wanted}` from this repository, so no "
                           f"run of this pull request was captured and there is nothing to judge")
    for entry in sorted(entries, key=lambda e: str(e.get("created_at") or "")):
        out.judgements.append(dataclasses.asdict(
            judge_one(args, out, entry, fetcher, ci_row, tools, token)))
    return out


# --------------------------------------------------------------------------------------------
# What the caller is told
# --------------------------------------------------------------------------------------------


def commit_message(out: Decision) -> str:
    """The commit in the organisation's grammar, sections included.

    One subject for the day's judgements from one repository, because they share a branch: the
    branch is `inbox/<repository>/<date>` exactly as the rows' is, so a pull request opened for
    either collects both and the squash subject needs no second spelling.

    It carries no count, and that is what lets the same text stand as the pull request's title when
    a re-run found its records already on the branch: a count would be a number this producer would
    have to keep true across every later commit to the same batch.
    """
    return "\n".join([
        f"feat(inbox): judgements from {out.repository} on {out.date}",
        "",
        "Motivation: a review-domain run is judged when the pull request closes, and the verdict "
        "arrives as its own record (ADR-087 §C.16).",
        "",
        f"Modification: adds the judgement records of pull request #{out.pull_request} under "
        f"`inbox/{out.date}/judgements/`, each keyed by the run it judges.",
        "",
        "Result: what the human did with each finding is in the inbox, beside the run that "
        "produced it and without the run record being touched.",
        "",
        "Refs: ADR-086, ADR-087",
    ]) + "\n"


def pull_request_body(out: Decision) -> str:
    """The inbox pull request's body, in the shape the receiving repository's gate requires.

    It names the human whose pull request produced the records, which is §C.15's requirement and
    the reason the body is assembled rather than left to a template: either half of this producer
    may be the one that opens the day's pull request, and a batch is not anonymous because the
    judgement half got there first.

    Written once, when the branch is opened, and speaking of the day rather than of a count it would
    have to be edited to keep true — the branch collects the day's records from this repository,
    rows and judgements alike.
    """
    who = f"@{out.author}" if out.author else "an author the platform did not name"
    return "\n".join([
        f"Motivation: the L2 reviews of {out.repository} were judged as their pull requests closed "
        f"on {out.date}; a judgement that is not filed is a verdict nobody can join to its run.",
        "",
        f"Modification: adds the day's judgement records under `inbox/{out.date}/judgements/`, "
        f"written by the closing workflow of {out.repository}. Each names the run it judges and "
        f"nothing of the review's text. The pull request whose close produced the first of them "
        f"was opened by {who}.",
        "",
        "Result: the inbox holds the disposition of every finding of every judged run. The producer "
        "ran this repository's own validator before opening this pull request, so a record that "
        "fails it never reaches the batch.",
        "",
        "## Classification",
        "",
        "Scope class: docs-only",
        "Wall impact: none",
        "Generated files touched: no",
        "TCK obligation: n/a",
        "Compatibility impact: none",
        f"Cross-repo impact: {out.repository}: the records judge review runs in that repository",
        "ADRs referenced: ADR-086, ADR-087",
        "Evidence state: citable",
        "",
        "## Verification",
        "",
        "The producer validated every record against the cross-file rules — rule 5 included, which "
        "is why each run row was resolved before its judgement was filed — and against the record "
        "schema, before this branch was pushed; the required checks on this pull request read them "
        "again.",
        "",
        "Refs: ADR-086, ADR-087",
    ]) + "\n"


def issue_body(out: Decision) -> str:
    """The issue a record that was not filed opens in the SOURCE repository, keyed and explained.

    Keyed so a re-run finds it and files nothing; in the source repository because the defect is the
    producer's to fix there rather than the inbox's to quarantine (§C.15, §C.16).
    """
    lines = [
        f"Key: `{out.issue_key}`",
        "",
        f"The closing workflow judged the L2 review runs of pull request #{out.pull_request} and "
        f"one or more judgement records were not filed. Each is kept as the workflow artefact "
        f"`l2-judgement-{out.pull_request}-unresolved` of that run.",
        "",
        "| Judgement | Run | Why it was not filed |",
        "|:--|:--|:--|",
    ]
    for one in out.judgements:
        if one.get("state") not in ("unresolved", "refused"):
            continue
        lines.append(f"| `{one['judgement_id']}` | `{one['run_id']}` | "
                     f"{one.get('detail') or one.get('reason') or '(none recorded)'} |")
    lines += [
        "",
        "A judgement resolves to its run or it is about nothing: rule 5 of the inbox validator "
        "refuses one whose run record is not in the same inbox, so the batch is red for the whole "
        "pull request if such a record is filed. The repair is at the producer — the run's own row "
        "reaching the inbox — never an edited record, which would say what its editor later "
        "believed rather than what the run did.",
    ]
    return "\n".join(lines) + "\n"


def summary(out: Decision) -> str:
    """The Markdown half of the log — one row per run, with the disposition counts.

    The counts are printed because the question this oracle is read for is not whether a judgement
    is possible but what became of the findings, and a producer that printed only a state would make
    every reader open the records to learn it.
    """
    lines = [
        "## judge_review",
        "",
        f"- repository: `{out.repository}`, pull request #{out.pull_request}"
        f" — {'merged' if out.merged else 'closed without merging'}",
        f"- judged at: `{out.judged_at or '(unresolved)'}`",
    ]
    if out.reason:
        lines.append(f"- no judgement: `{out.reason}` — {out.detail}")
    if out.judgements:
        lines += ["", "| Run | State | Findings | addressed | overruled | unresolved | Why |",
                  "|:--|:--|--:|--:|--:|--:|:--|"]
        for one in out.judgements:
            disposed = one.get("dispositions") or []
            counts = {name: sum(1 for d in disposed if d["disposition"] == name)
                      for name in (ADDRESSED, OVERRULED, UNRESOLVED)}
            lines.append(
                f"| `{one['run_id']}` | {one.get('state') or 'none'} | {one.get('findings', 0)} | "
                f"{counts[ADDRESSED]} | {counts[OVERRULED]} | {counts[UNRESOLVED]} | "
                f"{one.get('detail') or ''} |")
    return "\n".join(lines) + "\n"


def emit(out: Decision, args) -> None:
    """One JSON line for a log, the decision as a file, and the summary where CI shows it."""
    print(json.dumps(out.as_json(), sort_keys=True, ensure_ascii=False))
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(out.as_json(), handle, indent=2, sort_keys=True, ensure_ascii=False)
    # Both for a batch that gained a record AND for one whose records were already there: the
    # subject is the pull request's title too, and a re-run that found everything on the branch may
    # still be the run that has to open the pull request for it.
    if out.counted("new") or out.counted("skip"):
        with open(args.commit_message, "w", encoding="utf-8") as handle:
            handle.write(commit_message(out))
        with open(args.pull_request_body, "w", encoding="utf-8") as handle:
            handle.write(pull_request_body(out))
    if out.counted("unresolved") or out.counted("refused"):
        with open(args.issue_body, "w", encoding="utf-8") as handle:
            handle.write(issue_body(out))
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as handle:
            handle.write(summary(out))


def main(argv: list[str] | None = None, fetcher=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execution-root", required=True,
                        help="a checkout of the row contract's repository: `tools/` and `schemas/`")
    parser.add_argument("--repository", required=True, help="the reviewed repository")
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--streams-repository", default=capture.STREAMS_REPO)
    parser.add_argument("--execution-repository", default=EXECUTION_REPO)
    parser.add_argument("--inbox-root", default="",
                        help="a checkout of the inbox repository on the day's branch; without it "
                             "records are assembled and nothing is written")
    parser.add_argument("--out", default="judge-decision.json")
    parser.add_argument("--unresolved-dir", default="unresolved-judgements",
                        help="where a record that was not filed is kept for the artefact")
    # Written BESIDE the clone, never inside it: a file written into the inbox checkout is a file
    # the next commit carries into the inbox, and the inbox holds records and nothing else.
    parser.add_argument("--commit-message", default="judge-commit-message.txt")
    parser.add_argument("--pull-request-body", default="judge-pull-request-body.md")
    parser.add_argument("--issue-body", default="judge-issue-body.md")
    # The credential the two DATA repositories are read under, named rather than carried: the
    # streams repository is private and the inbox's open branches are the pen's, while the reviewed
    # repository is read under the job's own token. A token on a command line is readable by every
    # process on the runner.
    parser.add_argument("--inbox-token-env", default="EXERIS_INBOX_TOKEN")
    args = parser.parse_args(argv)

    try:
        ci_row, Report, check = capture.tooling(args.execution_root)
    except ImportError as exc:
        print(f"::error::judge_review: `{args.execution_root}` does not carry the row contract's "
              f"derivations ({exc}) — nothing about this pull request was read")
        return 2
    token = os.environ.get(args.inbox_token_env) or None
    try:
        out = judge(args, fetcher or capture.Fetcher(), ci_row, (Report, check), token)
    except capture.FetchError as exc:
        print(f"::error::judge_review: {exc}")
        return 2
    except OSError as exc:
        # The checkout, not the pull request: a tree that does not carry the contract is a defect in
        # the job rather than a fact about the review.
        print(f"::error::judge_review: the row contract's checkout is incomplete ({exc})")
        return 2
    emit(out, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
