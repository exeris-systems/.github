#!/usr/bin/env python3
"""Cases for `judge_review.py` — the four dispositions, and every way a judgement is not filed.

`review-disposition` is an observational oracle: it never labels and its verdict is never summarised
in one figure with a calibrated one. That is exactly why its reading has to be pinned case by case —
an oracle nobody can label with is an oracle nobody notices is wrong, and the four values below are
what a reader of the dataset will join on for as long as the rows exist.

Each case drives `judge_review.main(argv, fetcher)` with a fake host, a synthetic stream carrying a
fenced verdict, and an inbox checkout to write into, and then reads what reached the inbox rather
than what the script said about it.

WHAT THIS SUITE ASSUMES, stated because it is written beside the implementation rather than after:

  * `judge_review.main(argv, fetcher=None) -> int` — `argv` without the program name, `fetcher` the
    injected REST reader, a real `gh api` one when absent.
  * The fetcher is `get(path, token=None, accept=None) -> object`: `path` is a `gh api` REST path
    with no leading slash, the return is the parsed body, and an absent resource is
    `{"status": "404"}` rather than an exception.
  * Without `--inbox-root` the script assembles and writes nothing into the inbox.

IT NEEDS THE ROW CONTRACT'S CHECKOUT, for the reason `capture_ci_row_suite.py` gives: the
derivations and the inbox's own rules are imported from it rather than copied, and the run row these
cases resolve against is built through the contract's own assembly so that it stays a valid row as
the contract moves.

Usage: judge_review_suite.py [--execution-root DIR]
"""
from __future__ import annotations

import argparse
import base64
import copy
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "judge")
sys.path.insert(0, HERE)
import capture_ci_row as capture                                          # noqa: E402
import judge_review as judge                                             # noqa: E402

CASES: list[tuple[str, object]] = []


def case(name):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


# ---------------------------------------------------------------------------------------------
# What the fixtures say. Every one of these is a value written into `scripts/fixtures/judge/`,
# repeated here so a case can name it; none is derived.

REPO = "exeris-systems/exeris-docs"
PR = 11
RUN = 41000000007
ARTIFACT = 20000000007
ARTIFACT_NAME = f"l2-execution-{PR}"
RUN_ID = f"ci-{RUN}-{ARTIFACT}"
AUTHOR = "a-person"
# The commit the review read, and the commit the pull request ended at. They are two values because
# the whole oracle is the difference between them.
REVIEWED = "1a2b3c4d" * 5
HEAD = "9f8e7d6c" * 5
# The ordinary shape of a reviewed pull request: reviewed one day, closed the next. The two dates
# are different on purpose — a producer that dated a judgement by the closing day and a row by the
# run's day would agree with itself all day and disagree at midnight.
STARTED_AT = "2026-09-21T08:15:00Z"
CLOSED_AT = "2026-09-22T11:30:00Z"
# The second close: a pull request reopened and closed again, which §C.12a admits and which a
# producer naming a judgement after its run alone would read as a collision.
SECOND_CLOSE = "2026-09-22T15:45:00Z"
RUN_DATE = STARTED_AT[:10]
JUDGED_DATE = CLOSED_AT[:10]
CLIENT_VERSION = "2.1.274"
# The fence the run's ROW names, which is the one its judgement carries. It is the run's day and
# not the closing day: ADR-086 §C.12a reads a run's outcome as the latest judgement inside the
# fence in force, so a judgement under a second id is one no reader partitioning by fence finds.
FENCE = f"{RUN_DATE}-ci-live-cc-2-1-274"
# A fence no derivation this producer can make would arrive at: another day, another client. What
# carries it can only have read it off the row.
EARLIER_FENCE = "2026-09-18-ci-live-cc-2-1-272"
# The judgement's name: its run and the instant it judged, the instant spelled without separators
# because the contract's pattern for an id admits none. `20260922T113000Z` is `CLOSED_AT`.
JUDGEMENT_ID = f"{RUN_ID}-disposition-20260922T113000Z"
SECOND_JUDGEMENT_ID = f"{RUN_ID}-disposition-20260922T154500Z"
MODEL = "claude-sonnet-5"
STREAMS_REPO = "exeris-systems/exeris-ai-execution-streams"
EXECUTION_REPO = "exeris-systems/exeris-ai-execution"
STREAM_PATH = f"streams/{RUN_DATE}/exeris-docs/{RUN}-{ARTIFACT}.json"
RUN_PATH = f"inbox/{RUN_DATE}/runs/{RUN_ID}.json"
JUDGEMENT_PATH = os.path.join("inbox", JUDGED_DATE, "judgements", JUDGEMENT_ID + ".json")
SECOND_JUDGEMENT_PATH = os.path.join("inbox", JUDGED_DATE, "judgements",
                                     SECOND_JUDGEMENT_ID + ".json")
BRANCH = f"inbox/{REPO.replace('/', '--')}/{JUDGED_DATE}"
ROW_BRANCH = f"inbox/{REPO.replace('/', '--')}/{RUN_DATE}"
CHANGED = "docs/b.md"

# The four findings the fixture's fenced verdict carries, by what each is for. Named here so a case
# can say which one it is asserting about rather than counting positions in a fixture.
BLOCKING_UNCHANGED, CHANGED_FILE, NO_LOCATION, NON_BLOCKING_UNCHANGED = 0, 1, 2, 3

INBOX_TOKEN = "an-installation-token"


def fixture(name: str) -> object:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def inlined(doc: object) -> dict:
    """A contents answer in the form the host gives a file it inlines.

    Base64 and not the raw body, because that is the form the producer meets first and the one it
    has to decode; the raw path is asserted by its own case.
    """
    return {"encoding": "base64",
            "content": base64.b64encode(
                json.dumps(doc, ensure_ascii=False).encode("utf-8")).decode("ascii")}


class FakeFetcher:
    """The canned REST bodies, and a record of what was asked for and under which credential.

    The credential is recorded because it is a rule of this producer rather than an accident: the
    two data repositories are read under the App's installation token and the reviewed repository
    under the job's own, and a producer that read the private one under the job's token would work
    only where the job happened to be privileged.
    """

    def __init__(self) -> None:
        self.bodies: dict = dict(fixture("rest.json"))
        # What one path answers under the raw media type, which is a DIFFERENT answer and not a
        # rendering of the same one: the host serves the file itself there and the metadata here.
        self.raws: dict = {}
        self.asked: list[str] = []
        self.tokens: dict[str, object] = {}
        self.accepts: dict[str, object] = {}

    def set(self, path: str, body: object) -> None:
        self.bodies[path] = body

    def set_raw(self, path: str, body: object) -> None:
        self.raws[path] = body

    def drop(self, path: str) -> None:
        self.bodies.pop(path, None)

    def get(self, path: str, token: str | None = None, accept: str | None = None) -> object:
        self.asked.append(path)
        self.tokens[path] = token
        self.accepts[path] = accept
        if accept and path in self.raws:
            return self.raws[path]
        if path in self.bodies:
            return self.bodies[path]
        return {"status": "404"}


class World:
    """A tempdir holding an inbox checkout to write into, and the fake host with its two files."""

    def __init__(self, tmp: str, execution_root: str, ci_row) -> None:
        self.tmp = tmp
        self.execution_root = execution_root
        self.ci_row = ci_row
        self.inbox = os.path.join(tmp, "inbox-clone")
        self.unresolved = os.path.join(tmp, "unresolved-judgements")
        self.decision_path = os.path.join(tmp, "judge-decision.json")
        self.issue_path = os.path.join(tmp, "issue.md")
        self.body_path = os.path.join(tmp, "body.md")
        self.message_path = os.path.join(tmp, "message.txt")
        self.events = copy.deepcopy(fixture("stream.json"))
        self.index = [{
            "repo": REPO,
            "workflow_run_id": RUN,
            "artifact_id": ARTIFACT,
            "artifact_name": ARTIFACT_NAME,
            "path": STREAM_PATH,
            "sha256": "0" * 64,
            "size_bytes": 1234,
            "event_count": 4,
            "created_at": STARTED_AT,
            "artifact_expires_at": "2026-09-22T08:15:00Z",
        }]
        self.rest = FakeFetcher()
        self.row_ref = "main"
        self.row = run_row(ci_row, execution_root)

    def row_date(self) -> str:
        """The day the run's row is filed under, read from the index as the producer reads it."""
        return str(self.index[0]["created_at"])[:10] if self.index else RUN_DATE

    def run_path(self) -> str:
        return f"inbox/{self.row_date()}/runs/{RUN_ID}.json"

    def row_branch(self) -> str:
        """The open branch the run's own day's batch is proposed on."""
        return f"inbox/{REPO.replace('/', '--')}/{self.row_date()}"

    def build(self) -> "World":
        os.makedirs(self.inbox, exist_ok=True)
        self.rest.set(f"repos/{STREAMS_REPO}/contents/index.json?ref=main", inlined(self.index))
        self.rest.set(f"repos/{STREAMS_REPO}/contents/{STREAM_PATH}?ref=main",
                      inlined(self.events))
        # Every ref a previous build answered the row at, so that a case which moved the run to
        # another day is not answered from where the row used to be.
        for path in [p for p in self.rest.bodies if f"/runs/{RUN_ID}.json" in p]:
            self.rest.drop(path)
        if self.row is not None:
            self.rest.set(f"repos/{EXECUTION_REPO}/contents/{self.run_path()}?ref={self.row_ref}",
                          inlined(self.row))
        return self

    def compare(self, *filenames: str) -> "World":
        """What the host answers while the reviewed commit is still on the head's line: the merge
        base of the two commits IS the commit the review read, so the files are what changed after
        it."""
        self.rest.set(f"repos/{REPO}/compare/{REVIEWED}...{HEAD}",
                      {"status": "ahead",
                       "merge_base_commit": {"sha": REVIEWED},
                       "files": [{"filename": name} for name in filenames]})
        return self

    def diverged(self, *filenames: str) -> "World":
        """What the host answers once that commit is off the line — the branch was rebased,
        amended or force-pushed after the review. The comparison is from the branch point, so
        `files` is the pull request's whole diff and says nothing about what changed after the
        review."""
        self.rest.set(f"repos/{REPO}/compare/{REVIEWED}...{HEAD}",
                      {"status": "diverged",
                       "merge_base_commit": {"sha": "c" * 40},
                       "files": [{"filename": name} for name in filenames]})
        return self

    def closed_at(self, when: str) -> "World":
        """The pull request closed again, at a later instant — what a reopen and a second close
        leave for the next run of this producer to read."""
        pull = dict(self.rest.bodies[f"repos/{REPO}/pulls/{PR}"])
        pull.update(closed_at=when)
        self.rest.set(f"repos/{REPO}/pulls/{PR}", pull)
        return self

    def unmerged(self) -> "World":
        pull = dict(self.rest.bodies[f"repos/{REPO}/pulls/{PR}"])
        pull.update(merged=False, merged_at=None, state="closed")
        self.rest.set(f"repos/{REPO}/pulls/{PR}", pull)
        return self

    def verdict(self, doc: object) -> "World":
        """Replace the fenced verdict the run's final message carries, or take it away."""
        tail = "" if doc is None else \
            "\n\n```json\n" + json.dumps(doc, indent=2, ensure_ascii=False) + "\n```\n"
        self.events[-1]["result"] = "placeholder final message" + tail
        self.rest.set(f"repos/{STREAMS_REPO}/contents/{STREAM_PATH}?ref=main",
                      inlined(self.events))
        return self

    def run(self, *extra: str, inbox: bool = True) -> tuple[int, dict]:
        argv = ["--execution-root", self.execution_root,
                "--repository", REPO,
                "--pull-request", str(PR),
                "--streams-repository", STREAMS_REPO,
                "--execution-repository", EXECUTION_REPO,
                "--unresolved-dir", self.unresolved,
                "--out", self.decision_path,
                "--commit-message", self.message_path,
                "--pull-request-body", self.body_path,
                "--issue-body", self.issue_path]
        if inbox:
            argv += ["--inbox-root", self.inbox]
        argv += list(extra)
        held, sys.stdout = sys.stdout, io.StringIO()
        try:
            code = judge.main(argv, fetcher=self.rest)
        finally:
            sys.stdout = held
        with open(self.decision_path, encoding="utf-8") as fh:
            return code, json.load(fh)

    def filed(self) -> dict[str, dict]:
        found = {}
        for here, _dirs, names in os.walk(self.inbox):
            if os.path.basename(here) != "judgements":
                continue
            for name in sorted(names):
                if name.endswith(".json"):
                    path = os.path.join(here, name)
                    with open(path, encoding="utf-8") as fh:
                        found[os.path.relpath(path, self.inbox)] = json.load(fh)
        return found

    def kept(self) -> list[str]:
        if not os.path.isdir(self.unresolved):
            return []
        return sorted(os.listdir(self.unresolved))


def run_row(ci_row, execution_root: str, started_at: str = STARTED_AT,
            fence: str = FENCE) -> dict:
    """The run this pull request's judgement is about, assembled through the contract's own code.

    Built rather than kept as a fixture so that it stays a row the inbox's rules accept as the
    contract moves: rule 5 is what the judgement is checked against, and a stale hand-written row
    would start failing rules that have nothing to do with the judgement under test.

    The day and the fence are arguments because both are what a case varies to ask where the
    judgement got its own from.
    """
    return ci_row.assemble(
        run_id=RUN_ID,
        started_at=started_at,
        fingerprint=ci_row.fingerprint_ci(REPO, PR, REVIEWED),
        domain=ci_row.REVIEW_LIVE_DOMAIN,
        scope="docs-only",
        provider="anthropic",
        model_id=MODEL,
        harness_client="claude-code",
        harness_version=CLIENT_VERSION,
        system_prompt_sha256="a" * 64,
        repository=REPO,
        visibility="public",
        commit=REVIEWED,
        bundle_version="2.1.0",
        turns=3,
        tool_calls=1,
        wall_time_ms=123456,
        event_stream_ref=ci_row.event_stream_ref(STREAMS_REPO, STREAM_PATH, "b" * 40),
        event_stream_sha256="0" * 64,
        event_count=4,
        accounting_mode="subscription",
        oracle=ci_row.REVIEW_DISPOSITION_ORACLE,
        outcome="UNKNOWN",
        capture_version=capture.capture_version(execution_root),
        fence=fence,
    )


def dispositions(record: dict) -> list[str]:
    """The record's dispositions as a list indexed by finding, which is how a reader joins them."""
    return [entry["disposition"] for entry in record.get("dispositions") or []]


def world(execution_root: str, ci_row):
    tmp = tempfile.mkdtemp(prefix="judge-review-suite-")
    return World(tmp, execution_root, ci_row).build().compare(CHANGED), tmp


# ---------------------------------------------------------------------------------------------
# The cases.


@case("the four dispositions, one closed pull request, one record that validates")
def green(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        code, decision = here.run()
        check("the job is not failed by a judgement", code, 0)
        check("no reason is recorded", decision["reason"], None)
        check("one record was filed", decision["written"], 1)
        check("nothing was kept back", decision["kept_back"], 0)
        filed = here.filed()
        check("it reached the inbox under the judged day", sorted(filed), [JUDGEMENT_PATH])
        record = filed[JUDGEMENT_PATH]
        check("named by the run it judges", record["judgement_id"], JUDGEMENT_ID)
        check("and it names that run", record["run_id"], RUN_ID)
        check("the oracle is the disposition reader", record["oracle"]["id"], "review-disposition")
        check("at the version that says what it could read", record["oracle"]["version"],
              "rest-v1")
        check("uncalibrated, and the record says so",
              record["oracle"]["calibration"]["status"], "not-run")
        check("so the outcome is never a pass", record["outcome"], "UNKNOWN")
        check("dated by the instant the pull request closed", record["judged_at"], CLOSED_AT)
        # THE RUN'S OWN FENCE, and this pull request closed on a day the run did not: a judgement
        # dated by the closing day would sit in a partition its run is not in, and resolve in no
        # entry of the register.
        check("the fence is the run's, not the closing day's",
              record["instrument"]["fence"], FENCE)
        check("the capture version comes from the checkout",
              record["instrument"]["capture_version"],
              capture.capture_version(root))
        # THE ORACLE ITSELF, all four values in one reading (ADR-086 §D.15).
        check("a blocking finding merged over with its file untouched is overruled",
              dispositions(record)[BLOCKING_UNCHANGED], "overruled")
        check("a finding whose file changed after the review is addressed",
              dispositions(record)[CHANGED_FILE], "addressed")
        check("a finding with no site to watch is unresolved",
              dispositions(record)[NO_LOCATION], "unresolved")
        check("and a non-blocking finding nobody touched is unresolved",
              dispositions(record)[NON_BLOCKING_UNCHANGED], "unresolved")
        check("the dispositions are keyed by position and carry nothing of the finding",
              sorted(record["dispositions"][0]), ["disposition", "finding_index"])
        check("nothing was kept for an artefact", here.kept(), [])
        # AND THE BATCH NAMES ITS HUMAN (§C.15). Either half of this producer may be the one that
        # opens the day's pull request, so a body written by this half that named nobody would
        # make the same batch anonymous depending on which half got there first.
        with open(here.body_path, encoding="utf-8") as fh:
            body = fh.read()
        check("the batch's pull request names the human whose pull request produced the records",
              f"@{AUTHOR}" in body, True)
        # WHICH CREDENTIAL READ WHAT. The two data repositories are private to this organisation's
        # pen; the reviewed repository is read under the job's own token, which is what keeps the
        # App's installation out of every repository the review runs in.
        check("the streams repository is read under the App's token",
              here.rest.tokens[f"repos/{STREAMS_REPO}/contents/index.json?ref=main"], INBOX_TOKEN)
        check("and the reviewed repository under the job's own",
              here.rest.tokens[f"repos/{REPO}/pulls/{PR}"], None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a pull request closed without merging overrules nothing")
def unmerged(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # Nothing changed after the review and nothing merged: there is no act to read, and the
        # oracle's third value is the one that carries no claim.
        here.unmerged().compare()
        _code, decision = here.run()
        record = here.filed()[JUDGEMENT_PATH]
        check("every finding is unresolved", dispositions(record),
              ["unresolved"] * 4)
        check("the record still names the run it judges", record["run_id"], RUN_ID)
        check("and it is filed like any other", decision["written"], 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a file changed after the review is addressed whether or not the pull request merged")
def addressed_without_merge(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.unmerged()
        _code, _decision = here.run()
        record = here.filed()[JUDGEMENT_PATH]
        check("the changed file is still addressed", dispositions(record)[CHANGED_FILE],
              "addressed")
        # The blocking one is not: overruling needs the merge. A pull request abandoned overrode
        # nothing, and reading it as an override would score the reviewer against a decision nobody
        # took.
        check("and the blocking one is not overruled", dispositions(record)[BLOCKING_UNCHANGED],
              "unresolved")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a verdict with no findings is a judgement with no dispositions")
def no_findings(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.verdict({"agent": "exeris-org-docs-reviewer", "decision": "PASS", "findings": []})
        _code, decision = here.run()
        record = here.filed()[JUDGEMENT_PATH]
        check("the record is filed", decision["written"], 1)
        check("and it carries an empty list, not an absent one", record["dispositions"], [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("no verdict in the stream leaves the dispositions absent, which is not the same as empty")
def no_verdict(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.verdict(None)
        _code, decision = here.run()
        record = here.filed()[JUDGEMENT_PATH]
        check("the record is still filed", decision["written"], 1)
        check("and says nothing about findings it never read",
              "dispositions" in record, False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("the run's row is not in the inbox — nothing is committed, and the defect is reported")
def run_row_absent(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.row = None
        here.build().compare(CHANGED)
        code, decision = here.run()
        check("the job is not failed by it", code, 0)
        check("nothing reached the inbox", here.filed(), {})
        check("nothing counts as written", decision["written"], 0)
        check("the record is kept back", decision["kept_back"], 1)
        check("and the reason names rule 5's subject",
              decision["judgements"][0]["reason"], "run-row-absent")
        check("the record itself is kept where it can be read",
              here.kept(), [JUDGEMENT_ID + ".json"])
        # AND IT IS THE INBOX'S OWN RULE THAT SAYS SO, not this producer's bookkeeping: the record
        # was put through the validator that gates the inbox pull request, and rule 5 is what
        # refused it. A producer that only counted the missing row would be asserting a rule it had
        # stopped running.
        check("rule 5 is what refused it",
              any("not a run record in this inbox" in said
                  for said in decision["judgements"][0]["refusals"]), True)
        with open(here.issue_path, encoding="utf-8") as fh:
            issue = fh.read()
        check("an issue body is written", f"{REPO}#{PR}/judgement" in issue, True)
        check("and it names the record that was not filed", JUDGEMENT_ID in issue, True)
        check("no pull request body is written for a batch with nothing in it",
              os.path.exists(here.body_path), False)
        # AND ONLY THE DEFAULT BRANCH IS ASKED, because this pull request closed on a day the run
        # did not: the judgement lands on the closing day's branch, and a row on another day's
        # open branch is in no tree this batch is validated over. The other day's branch is asked
        # by the case where it IS this judgement's own.
        check("only the default branch is asked for a run of another day",
              [p for p in here.rest.asked if RUN_PATH in p],
              [f"repos/{EXECUTION_REPO}/contents/{RUN_PATH}?ref=main"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("the run's row on the judgement's OWN open branch resolves it, and the judgement is filed")
def run_row_on_branch(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # A pull request reviewed and closed on one day: the run's batch and the judgement's are
        # the same branch, so a row proposed there and not yet merged is a row this judgement will
        # be validated beside. Holding the judgement back for want of a human's merge would report
        # a producer defect that is not one.
        same_day = f"{JUDGED_DATE}T08:15:00Z"
        here.index[0]["created_at"] = same_day
        here.row = run_row(ci_row, root, started_at=same_day,
                           fence=f"{JUDGED_DATE}-ci-live-cc-2-1-274")
        here.row_ref = here.row_branch()
        here.build().compare(CHANGED)
        _code, decision = here.run()
        check("the record is filed", decision["written"], 1)
        check("and it reached the inbox", sorted(here.filed()), [JUDGEMENT_PATH])
        check("it carries that row's fence",
              here.filed()[JUDGEMENT_PATH]["instrument"]["fence"],
              f"{JUDGED_DATE}-ci-live-cc-2-1-274")
        # BOTH REFS ARE ASKED, and in that order.
        check("the default branch and this judgement's own open branch are both asked",
              [p for p in here.rest.asked if here.run_path() in p],
              [f"repos/{EXECUTION_REPO}/contents/{here.run_path()}?ref=main",
               f"repos/{EXECUTION_REPO}/contents/{here.run_path()}?ref={BRANCH}"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a row on ANOTHER day's open branch is not in this batch's tree, and is not filed against")
def run_row_on_another_days_branch(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # The ordinary case this producer must not mistake for a resolution: reviewed one day,
        # closed the next, the run's batch still open. The judgement goes on the closing day's
        # branch, whose tree holds no such row — so filing it there is rule 5 red for the whole
        # batch, which is what producer-side validation exists to prevent. Kept back instead, and
        # §C.16 names the state: the inbox pull request was never merged.
        here.row_ref = ROW_BRANCH
        here.build().compare(CHANGED)
        code, decision = here.run()
        check("the job is not failed by it", code, 0)
        check("nothing reached the inbox", here.filed(), {})
        check("the record is kept back", decision["kept_back"], 1)
        check("and the reason is that its run is not in the inbox",
              decision["judgements"][0]["reason"], "run-row-absent")
        check("the other day's open branch is never asked",
              [p for p in here.rest.asked if ROW_BRANCH in p], [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("the same closed event twice is one record, not two")
def twice(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.run()
        _code, decision = here.run()
        check("the second reading writes nothing new", decision["written"], 0)
        check("it is a skip rather than a refusal", decision["skipped"], 1)
        check("and one record stands", sorted(here.filed()), [JUDGEMENT_PATH])
        # THE SUBJECT IS THE PULL REQUEST'S TITLE, and the run that finds every record already on
        # the branch may still be the run that has to open the pull request for the batch — a
        # branch whose pull request was closed unmerged is exactly that. So it is written here too,
        # and it carries no count for the same reason.
        with open(here.message_path, encoding="utf-8") as fh:
            subject = fh.read().splitlines()[0]
        check("the subject a pull request would be titled by is written for a skip too",
              subject, f"feat(inbox): judgements from {REPO} on {JUDGED_DATE}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a different judgement under one name is refused, never overwritten")
def differs(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.run()
        before = here.filed()[JUDGEMENT_PATH]
        # A second reading of the same run that disagrees about what the human did. The repair is a
        # new record and a fence; overwriting would take the first answer out of the record as
        # though it had never been given.
        here.compare()
        _code, decision = here.run()
        check("it is refused", decision["judgements"][0]["state"], "refused")
        check("the first answer still stands", here.filed()[JUDGEMENT_PATH], before)
        check("and it is kept where the defect can be read",
              here.kept(), [JUDGEMENT_ID + ".json"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a repository this inbox cannot hold yields nothing, and reads no stream")
def visibility(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.rest.set(f"repos/{REPO}", {"private": True, "visibility": "private"})
        _code, decision = here.run()
        check("the reason is the missing inbox", decision["reason"], "inbox-absent")
        check("nothing reached this one", here.filed(), {})
        check("and the streams repository was never asked",
              [p for p in here.rest.asked if STREAMS_REPO in p], [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a pull request with no captured run is nothing to judge, not a defect")
def no_stream(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.index = []
        here.build().compare(CHANGED)
        code, decision = here.run()
        check("the job is green", code, 0)
        check("and says why there is no record", decision["reason"], "no-stream")
        check("nothing reached the inbox", here.filed(), {})
        check("and nothing is kept for an artefact", here.kept(), [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a stream too large for the host to inline is read under the raw media type")
def raw_stream(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # What the host answers above the contents endpoint's base64 ceiling: the metadata, the
        # size, and no bytes. An execution log is routinely above it.
        here.rest.set(f"repos/{STREAMS_REPO}/contents/{STREAM_PATH}?ref=main",
                      {"encoding": "none", "content": "", "size": 4194304})
        here.rest.set_raw(f"repos/{STREAMS_REPO}/contents/{STREAM_PATH}?ref=main", here.events)
        _code, decision = here.run()
        check("the record is filed all the same", decision["written"], 1)
        check("and the raw media type is what read it",
              here.rest.accepts[f"repos/{STREAMS_REPO}/contents/{STREAM_PATH}?ref=main"],
              judge.RAW)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a run whose head commit the host does not name yields no judgement")
def reviewed_sha_absent(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.rest.drop(f"repos/{REPO}/actions/runs/{RUN}")
        code, decision = here.run()
        check("the job is not failed by it", code, 0)
        check("the reason names the component", decision["judgements"][0]["reason"],
              "reviewed-sha-unresolved")
        check("nothing reached the inbox", here.filed(), {})
        # A judgement is never assembled from a commit nobody established: with no commit to compare
        # from, every disposition would read `unresolved` and the record would state a reading the
        # oracle never made.
        check("and nothing was kept for an artefact either", here.kept(), [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("the fence a judgement carries is read off its run's row, not derived here")
def fence_from_the_row(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # A row written on neither the run's day nor the closing one, under a client the stream
        # does not name at all. Nothing this producer reads could arrive at this id, so a record
        # carrying it read it off the row — which is the whole of the rule.
        here.row = run_row(ci_row, root, fence=EARLIER_FENCE)
        here.events[0].pop("claude_code_version")
        here.build().compare(CHANGED)
        _code, decision = here.run()
        check("the record is filed", decision["written"], 1)
        check("and its fence is the row's", here.filed()[JUDGEMENT_PATH]["instrument"]["fence"],
              EARLIER_FENCE)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a run row naming no fence is a run there is no partition to judge inside")
def run_row_fence_absent(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        here.row = run_row(ci_row, root)
        here.row["instrument"].pop("fence")
        here.build().compare(CHANGED)
        code, decision = here.run()
        check("the job is not failed by it", code, 0)
        check("the reason names what the row does not carry",
              decision["judgements"][0]["reason"], "run-row-fence-absent")
        check("nothing reached the inbox", here.filed(), {})
        # Nothing is kept either: a record cannot be assembled without the id that says which
        # population it belongs to, and an invented one would resolve in no entry of the register.
        check("and nothing was assembled to keep", here.kept(), [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a history rewritten after the review is not a file set, and yields no judgement")
def reviewed_history_gone(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # What a three-dot comparison answers once the reviewed commit is off the head's line: the
        # pull request's whole diff, in which every located finding reads `addressed` — including
        # the ones nobody touched. Rewriting history is exactly what acting on a finding often
        # looks like, so this is the reading the oracle is most likely to be offered.
        here.diverged(CHANGED, "docs/a.md", "docs/c.md")
        code, decision = here.run()
        check("the job is not failed by it", code, 0)
        check("the reason names the history rather than the host",
              decision["judgements"][0]["reason"], "reviewed-history-gone")
        check("nothing reached the inbox", here.filed(), {})
        check("and nothing was kept for an artefact", here.kept(), [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("the last fenced verdict is the one judged, as the publisher publishes the last")
def last_verdict(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # A run that answered twice. The publication takes the latest, so the dispositions are about
        # the review that stands — a judgement of the earlier one would dispose of findings nobody
        # was shown.
        earlier = {"agent": "exeris-org-docs-reviewer", "decision": "PASS", "findings": []}
        later = {"agent": "exeris-org-docs-reviewer", "decision": "BLOCKED", "findings": [
            {"what": "placeholder", "why": "adr-conventions.md#7", "fix": "placeholder",
             "location": f"{CHANGED}:4"}]}
        here.events[-1]["result"] = (
            "first answer\n\n```json\n" + json.dumps(earlier) + "\n```\n"
            "second answer\n\n```json\n" + json.dumps(later) + "\n```\n")
        here.rest.set(f"repos/{STREAMS_REPO}/contents/{STREAM_PATH}?ref=main",
                      inlined(here.events))
        _code, _decision = here.run()
        record = here.filed()[JUDGEMENT_PATH]
        check("the later verdict's one finding is what was disposed of",
              dispositions(record), ["addressed"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a pull request reopened and closed again is a second record, not a collision")
def reopened_and_closed_again(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # Only a pull request that closed without merging can be reopened, so both closes here are
        # of that kind. §C.12a admits many judgements of one run; what distinguishes them is the
        # instant each judged, and a name carrying the run alone would make the second a conflict
        # with the first and be reported as this producer's defect.
        here.unmerged()
        here.run()
        first = sorted(here.filed())
        here.closed_at(SECOND_CLOSE)
        _code, decision = here.run()
        check("the later close is a record of its own", decision["written"], 1)
        check("nothing is refused", decision["kept_back"], 0)
        check("and the first judgement still stands beside it",
              sorted(here.filed()), sorted(first + [SECOND_JUDGEMENT_PATH]))
        record = here.filed()[SECOND_JUDGEMENT_PATH]
        check("the second is dated by the second close", record["judged_at"], SECOND_CLOSE)
        check("and judges the same run", record["run_id"], RUN_ID)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("the capture version is the checkout's, and is read from it every time")
def capture_version_read(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        # A checkout of the contract that answers something else. Nothing else about this case
        # differs, so a producer with the version written down would file the same record either
        # way — which is what makes this the only case that can tell the two apart.
        copy = os.path.join(tmp, "another-contract")
        for name in ("tools", "schemas"):
            shutil.copytree(os.path.join(root, name), os.path.join(copy, name))
        with open(os.path.join(copy, "schemas", "VERSION"), "w", encoding="utf-8") as fh:
            fh.write("9.9.9\n")
        here.execution_root = copy
        _code, decision = here.run()
        check("the record is filed", decision["written"], 1)
        check("and it answers to the contract the checkout carries",
              here.filed()[JUDGEMENT_PATH]["instrument"]["capture_version"], "9.9.9")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("without an inbox checkout nothing is written anywhere")
def assembled_only(root, ci_row, check):
    here, tmp = world(root, ci_row)
    try:
        _code, decision = here.run(inbox=False)
        check("the record is assembled", decision["judgements"][0]["state"], "assembled")
        check("nothing counts as written", decision["written"], 0)
        check("and the branch it would land on is named for the caller",
              decision["branch"], BRANCH)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# What the checkout has to carry for these cases to mean anything. Named as files rather than as
# directories, because a checkout that carries the directories and not these is the state a stacked
# change is in before the half it depends on has landed — and that state has to read as "the
# dependency is not there yet" rather than as a suite of failures.
NEEDED = ("tools/ci_row.py", "tools/inbox_validate.py", "schemas/VERSION",
          "schemas/run-record.schema.json", "schemas/judgement-record.schema.json")


def execution_root(named: str | None) -> str:
    """Where the record contract's checkout is, or a refusal naming what is missing from it."""
    tried = []
    for candidate in (named, os.environ.get("EXERIS_EXECUTION_ROOT"), "execution"):
        if not candidate:
            continue
        missing = [one for one in NEEDED if not os.path.exists(os.path.join(candidate, one))]
        if not missing:
            return os.path.abspath(candidate)
        tried.append(f"{candidate} (no {', '.join(missing)})")
    print("::error title=judge_review_suite::the record contract's checkout does not carry what "
          "these cases import: " + ("; ".join(tried) or "nowhere to look") + ". Pass "
          "`--execution-root DIR`, set `EXERIS_EXECUTION_ROOT`, or check "
          "`exeris-systems/exeris-ai-execution` out into `execution/` — and note that the judgement "
          "job itself reads the same files from that repository's default branch, so a branch that "
          "does not carry them yet is a job that cannot assemble a record either.")
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execution-root", default="")
    root = execution_root(parser.parse_args().execution_root or None)
    ci_row, _Report, _check = capture.tooling(root)
    # The credential the two data repositories are read under, as the job hands it over: through the
    # environment, never on a command line.
    os.environ["EXERIS_INBOX_TOKEN"] = INBOX_TOKEN

    failures, ran = 0, 0

    def check(name: str, got, want) -> None:
        nonlocal failures, ran
        ran += 1
        if got != want:
            failures += 1
            print(f"::error title=judge_review_suite::{name}: expected {want!r}, got {got!r}")

    for name, run in CASES:
        try:
            run(root, ci_row, check)
        except Exception as exc:                                  # a case that cannot run failed
            failures += 1
            print(f"::error title=judge_review_suite::{name}: raised "
                  f"{type(exc).__name__}: {exc}")

    print(f"judge_review_suite: ran {len(CASES)} case(s), {ran} assertion(s), "
          f"{failures} failure(s)")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## judge_review_suite\n\nRan **{len(CASES)}** case(s), **{ran}** "
                     f"assertion(s) — **{failures} failure(s)**.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
