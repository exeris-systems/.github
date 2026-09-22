#!/usr/bin/env python3
"""Cases for `capture_ci_row.py` — the instrument mutants of ADR-086 Engineering Protocol 2.

A producer that writes rows nobody checked is an instrument nobody calibrated, and the mutants this
protocol asks for are the ones that would corrupt the dataset silently: a publisher's name where a
model's belongs, a price-list figure wearing a measurement's name, a row filed under the wrong
inbox. Each is stated here as a case, and each was confirmed to fail when the rule it covers is
taken out of the assembly.

Every case drives `capture_ci_row.main(argv, fetcher)` with a fake host and a synthetic stream and
then reads what reached the inbox, rather than what the script said about it.

WHAT THIS SUITE ASSUMES, stated because it is written beside the implementation rather than after:

  * `capture_ci_row.main(argv, fetcher=None) -> int` — `argv` without the program name, `fetcher`
    the injected REST reader, a real `gh api` one when absent.
  * The fetcher is `get(path) -> object`: `path` is a `gh api` REST path with no leading slash, the
    return is the parsed body, and an absent resource is `{"status": "404"}` rather than an
    exception. Nothing else is called — porcelain is not a fetcher.
  * Without `--stream-commit` the script decides and assembles nothing; with it, it assembles,
    validates, and writes into `--inbox-root` when the row passes.

IT NEEDS THE ROW CONTRACT'S CHECKOUT, because the derivations are imported from it rather than
copied: `--execution-root`, `EXERIS_EXECUTION_ROOT`, or `execution/` beside the working directory.
A suite that quietly passed without it would be testing an import error.

Usage: capture_ci_row_suite.py [--execution-root DIR]
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "capture")
sys.path.insert(0, HERE)
import capture_ci_row as capture                                          # noqa: E402

CASES: list[tuple[str, object]] = []


def case(name):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


# ---------------------------------------------------------------------------------------------
# What the fixtures say. Every one of these is a value written into `scripts/fixtures/capture/`,
# repeated here so a case can name it; none is derived.

REPO = "exeris-systems/exeris-ai-execution"
PR = 7
RUN = 41000000001
ARTIFACT = 20000000001
ARTIFACT_NAME = "l2-execution-7"
RUN_ID = f"ci-{RUN}-{ARTIFACT}"
HEAD = "a1b2c3d4" * 5
STREAM_COMMIT = "b2c3d4e5" * 5
STARTED_AT = "2026-09-22T09:04:11Z"
DATE = "2026-09-22"
MODEL = "claude-sonnet-5"
CLIENT_VERSION = "2.1.274"
BUNDLE_VERSION = "2.1.0"
ROW_PATH = os.path.join("inbox", DATE, "runs", f"{RUN_ID}.json")
BRANCH = f"inbox/{REPO.replace('/', '--')}/{DATE}"
# The streams repository's own layout: `streams/<date>/<repo>/<workflow run>-<artefact>.json`,
# which is how every stream already there is named. The row's `run_id` is spelled differently and
# deliberately — the two are joined by `event_stream.ref` and by `index.json`, so nothing needs them
# to agree letter for letter, and a producer inventing a second file-naming convention would leave
# one tree carrying two.
STREAM_PATH = f"streams/{DATE}/exeris-ai-execution/{RUN}-{ARTIFACT}.json"

# The two components the producing job exports that a row carries verbatim, pinned at the values
# the row contract's own suite pins for its golden fixture — `tools/derive_ci_rows_suite.py` in
# `exeris-ai-execution`, where the derivation of each is written out above it. They are copied here
# rather than imported: this repository does not import that suite, and a value read from it at run
# time would agree with whatever it had become rather than with what it was pinned to.
#
# What the case below states is the CARRY-THROUGH: a component the producing job hashed reaches the
# row unchanged, so where the reconstruction computes these same two values the two producers'
# rows agree on them. That the reconstruction computes them is the other suite's case, and the
# component-by-component comparison of a live row against a reconstructed one is what retires the
# backfill fences.
SYSTEM_PROMPT_SHA256 = "318bdb6a65f08253784342a025fba7c27b399cb106f4d5eb1b454c92a981fc3d"
TOOL_SURFACE = "fdb5246cbad76771a888b04504b84ddb75b41e90430b020f3b56b63fe5aa2652"

# The ten values the producing job exports, as a caller that has adopted them passes them on.
EXPORTS = {
    "prompt-sha256": "1" * 64,
    "routine-sha256": "2" * 64,
    "routine-sha": "c" * 40,
    "agents-md-sha256": "3" * 64,
    "system-prompt-sha256": SYSTEM_PROMPT_SHA256,
    "tool-surface": TOOL_SURFACE,
    "bundle-version": BUNDLE_VERSION,
    "checkout-sha": HEAD,
    "head-sha": HEAD,
    "review-started-at": STARTED_AT,
}


def fixture(name: str) -> object:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


class FakeFetcher:
    """The canned REST bodies, and a record of what was asked for.

    Keyed by the path exactly as the producer spells it, because the producer is the file this
    suite is about: a fake that normalised the spelling would hide a path nobody serves.
    """

    def __init__(self) -> None:
        self.bodies: dict = dict(fixture("rest.json"))
        self.asked: list[str] = []
        self.missed: list[str] = []

    def set(self, path: str, body: object) -> None:
        self.bodies[path] = body

    def get(self, path: str) -> object:
        self.asked.append(path)
        if path in self.bodies:
            return self.bodies[path]
        self.missed.append(path)
        return {"status": "404"}


class World:
    """A tempdir holding the stream, an inbox checkout to write into, and the fake host."""

    def __init__(self, tmp: str, execution_root: str) -> None:
        self.tmp = tmp
        self.execution_root = execution_root
        self.log = os.path.join(tmp, "execution.json")
        self.inbox = os.path.join(tmp, "inbox-clone")
        self.decision_path = os.path.join(tmp, "capture-decision.json")
        self.row_path = os.path.join(tmp, "row.json")
        self.events = copy.deepcopy(fixture("stream.json"))
        self.rest = FakeFetcher()
        self.exports = dict(EXPORTS)
        # The producing job's eleventh export: the id the host gave the execution artefact, as its
        # upload step reported it. A case blanks it to state what a producer that cannot name the
        # artefact yields.
        self.artifact_id = str(ARTIFACT)

    def build(self) -> "World":
        os.makedirs(self.inbox, exist_ok=True)
        with open(self.log, "w", encoding="utf-8") as fh:
            json.dump(self.events, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        return self

    def run(self, *extra: str, commit: str | None = STREAM_COMMIT) -> tuple[int, dict]:
        argv = ["--execution-root", self.execution_root,
                "--log", self.log,
                "--repository", REPO,
                "--pull-request", str(PR),
                "--event-head-sha", HEAD,
                "--workflow-run-id", str(RUN),
                "--execution-artifact", ARTIFACT_NAME,
                "--artifact-id", self.artifact_id,
                "--verdict-source", "file",
                "--inbox-root", self.inbox,
                "--out", self.decision_path,
                "--row", self.row_path,
                "--commit-message", os.path.join(self.tmp, "message.txt"),
                "--pull-request-body", os.path.join(self.tmp, "body.md"),
                "--issue-body", os.path.join(self.tmp, "issue.md")]
        for key, value in self.exports.items():
            argv += [f"--{key}", value]
        if commit:
            argv += ["--stream-commit", commit]
        argv += list(extra)
        held, sys.stdout = sys.stdout, io.StringIO()
        try:
            code = capture.main(argv, fetcher=self.rest)
        finally:
            sys.stdout = held
        with open(self.decision_path, encoding="utf-8") as fh:
            return code, json.load(fh)

    def rows(self) -> dict[str, dict]:
        found = {}
        for here, _dirs, names in os.walk(self.inbox):
            if os.path.basename(here) != "runs":
                continue
            for name in sorted(names):
                if name.endswith(".json"):
                    path = os.path.join(here, name)
                    with open(path, encoding="utf-8") as fh:
                        found[os.path.relpath(path, self.inbox)] = json.load(fh)
        return found

    def row_bytes(self) -> str:
        with open(self.row_path, encoding="utf-8") as fh:
            return fh.read()


def world(execution_root: str):
    tmp = tempfile.mkdtemp(prefix="capture-ci-row-suite-")
    return World(tmp, execution_root).build(), tmp


# ---------------------------------------------------------------------------------------------
# The cases.


@case("a captured run becomes one row, validated before it is written")
def green(root, check):
    here, tmp = world(root)
    try:
        code, decision = here.run()
        check("the run is not failed by a capture", code, 0)
        check("no reason is recorded", decision["reason"], None)
        check("the row is new", decision["state"], "new")
        rows = here.rows()
        check("one row reached the inbox", sorted(rows), [ROW_PATH])
        row = rows[ROW_PATH]
        check("named by its run", row["run_id"], RUN_ID)
        check("dated by the review's own start", row["started_at"], STARTED_AT)
        check("the domain is the live review's", row["workload"]["domain"], "docs-review-live")
        check("the scope comes from the pull request's body", row["workload"]["scope"], "docs-only")
        check("the oracle has not judged yet", row["outcome"], "UNKNOWN")
        check("the calibration says which pass it waits for",
              row["oracle"]["calibration"]["status"], "not-run")
        check("the fence names the producer and the client",
              row["instrument"]["fence"], f"{DATE}-ci-live-cc-2-1-274")
        check("the stream is referenced at the commit that holds it",
              row["execution"]["event_stream"]["ref"],
              f"exeris-systems/exeris-ai-execution-streams/{STREAM_PATH}@{STREAM_COMMIT}")
        check("every count comes from the run's own record", row["execution"]["capture_level"],
              "full")
        check("the ledger is the credential's", row["accounting"]["mode"], "subscription")
        check("the snapshot is marked, not invented", row["agent"]["model_snapshot"],
              f"unresolved:{MODEL}")
        # THE WHOLE REST SURFACE, pinned. The job that runs this holds the two read scopes these
        # two calls need and nothing more, which is what keeps a caller's permission block from
        # growing — so a read added here that needs another permission is a caller-wide change, and
        # this is where it shows. The artefact list is deliberately absent: that endpoint is gated
        # on the Actions permission, which this job cannot hold and a caller would have to grant,
        # so the artefact's id is handed over by the producing job instead.
        check("it reads two things and nothing else", sorted(set(here.rest.asked)), [
            f"repos/{REPO}",
            f"repos/{REPO}/pulls/{PR}",
        ])
        # The index entry beside the file, and the two dates inside one record agreeing: the
        # directory a stream lands in is the day the entry itself records, so a reader of the index
        # and a reader of the tree resolve the same day.
        entry = decision["stream"]
        check("the entry names the file the row references", entry["path"], STREAM_PATH)
        check("the directory is the day the entry records",
              entry["path"].split("/")[1], entry["created_at"][:10])
        check("and the expiry is that day plus the upload's retention",
              entry["artifact_expires_at"], "2026-09-23T09:04:11Z")
        # `result_commits` is filled by a producer that owns the run's worktree and lists what the
        # run committed. This one reviews a tree it does not write, so the field is absent — and
        # never the empty array, which is the other producer's measurement that a run committed
        # nothing.
        check("what the run committed is not claimed",
              "result_commits" in row["execution"], False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("the stream names a publisher as the model — refused, and nothing is written")
def publisher_as_model(root, check):
    here, tmp = world(root)
    try:
        here.events[0]["model"] = "exeris-bot"
        here.events[1]["message"]["model"] = "exeris-bot"
        here.build()
        code, decision = here.run()
        check("the capture does not fail the run", code, 0)
        check("the reason names the mutant", decision["reason"], "publisher-as-agent")
        check("nothing reached the inbox", here.rows(), {})
        check("no row file was written", os.path.exists(here.row_path), False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a runtime's printed cost under a subscription reaches no field and no byte of the row")
def no_cost(root, check):
    here, tmp = world(root)
    try:
        code, decision = here.run()
        check("the row is written", decision["state"], "new")
        row = here.rows()[ROW_PATH]
        check("the ledger is the subscription's", row["accounting"]["mode"], "subscription")
        check("no reported cost", "provider_reported_cost" in row["accounting"], False)
        # The bytes, not the parsed object: a producer that kept the figure under another name
        # would satisfy a field test and fail this one.
        check("the word does not appear in the row at all", "cost" in here.row_bytes(), False)
        check("the stream did carry one", "total_cost_usd" in json.dumps(here.events), True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("`agent.harness.client` naming the pen is refused by the assembly itself")
def publisher_as_harness(root, check):
    ci_row, _report, _check = capture.tooling(root)
    # This producer fixes the client, so the mutant is stated against the assembly every producer
    # calls rather than against a flag this one does not have.
    refused = False
    try:
        ci_row.assemble(**dict(assembly_arguments(ci_row), harness_client="exeris-inbox[bot]"))
    except ci_row.PublisherAsAgent:
        refused = True
    check("the assembly refuses it", refused, True)


@case("`execution.principal` naming an App is accepted — the principal is where it belongs")
def principal_is_not_the_agent(root, check):
    ci_row, _report, _check = capture.tooling(root)
    row = ci_row.assemble(**assembly_arguments(ci_row))
    row["execution"]["principal"] = {"kind": "app", "login": "exeris-agent[bot]"}
    raised = False
    try:
        ci_row.refuse_publisher(row)
    except ci_row.PublisherAsAgent:
        raised = True
    check("the refusal reads `agent.*` and not the principal", raised, False)


@case("the exported components reach the row unchanged")
def components_carry_through(root, check):
    here, tmp = world(root)
    try:
        here.run()
        row = here.rows()[ROW_PATH]
        check("the system prompt hash is the one that was exported",
              row["agent"]["system_prompt_sha256"], SYSTEM_PROMPT_SHA256)
        check("the tool surface is the one that was exported",
              row["execution"]["tool_surface"], TOOL_SURFACE)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("one repository and one day are one branch, and one run is one file")
def one_branch_one_file(root, check):
    here, tmp = world(root)
    try:
        _code, first = here.run()
        _code, second = here.run()
        check("the branch is a function of the repository and the day", first["branch"], BRANCH)
        check("the second capture targets the same branch", second["branch"], first["branch"])
        check("the second capture recognises its own bytes", second["state"], "skip")
        check("the day holds one file for the run", sorted(here.rows()), [ROW_PATH])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a row already there in other bytes is refused, never overwritten")
def row_exists_differs(root, check):
    here, tmp = world(root)
    try:
        here.run()
        target = os.path.join(here.inbox, ROW_PATH)
        with open(target, encoding="utf-8") as fh:
            held = fh.read()
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(held.replace('"tool_calls": 1', '"tool_calls": 99'))
        _code, decision = here.run()
        check("the second answer is refused", decision["reason"], "row-exists-differs")
        with open(target, encoding="utf-8") as fh:
            check("what was there is still there", '"tool_calls": 99' in fh.read(), True)
        with open(os.path.join(here.tmp, "issue.md"), encoding="utf-8") as fh:
            issue = fh.read()
        check("the refusal is written up for the source repository",
              f"Key: `{REPO}#{PR}/capture`" in issue, True)
        check("and it names the human accountable for the pull request", "@a-person" in issue,
              True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("the publication's transport is recorded in the contract's vocabulary")
def verdict_route(root, check):
    here, tmp = world(root)
    try:
        here.run("--verdict-source", "execution log")
        check("spaces become hyphens through a table, not a replace",
              here.rows()[ROW_PATH]["execution"]["verdict_route"], "execution-log")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a transport the contract does not admit costs the row")
def verdict_route_unknown(root, check):
    here, tmp = world(root)
    try:
        _code, decision = here.run("--verdict-source", "a fifth transport")
        check("the reason names it", decision["reason"], "verdict-route-unknown")
        check("nothing reached the inbox", here.rows(), {})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a caller that exports nothing yields no row, with the reason named")
def inputs_absent(root, check):
    here, tmp = world(root)
    try:
        here.exports = {key: "" for key in EXPORTS}
        _code, decision = here.run()
        check("the reason is the caller's, not the run's", decision["reason"],
              "capture-inputs-absent")
        check("nothing reached the inbox", here.rows(), {})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a component the exports left empty costs the row")
def component_absent(root, check):
    here, tmp = world(root)
    try:
        here.exports["system-prompt-sha256"] = ""
        _code, decision = here.run()
        check("the reason names the components", decision["reason"], "components-absent")
        check("the detail names the field", "system_prompt_sha256" in decision["detail"], True)
        check("nothing reached the inbox", here.rows(), {})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("components read at a tree the row does not name cost the row")
def components_off_head(root, check):
    here, tmp = world(root)
    try:
        here.exports["checkout-sha"] = "f" * 40
        _code, decision = here.run()
        check("the reason names the disagreement", decision["reason"], "components-off-head")
        check("nothing reached the inbox", here.rows(), {})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a repository that is not public yields no row while that inbox does not exist")
def visibility_fail_closed(root, check):
    here, tmp = world(root)
    try:
        here.rest.set(f"repos/{REPO}", {"private": True, "visibility": "private"})
        _code, decision = here.run()
        check("the reason names the missing inbox", decision["reason"], "inbox-absent")
        check("the visibility is recorded fail-closed", decision["visibility"],
              "enterprise-private")
        check("nothing reached the public inbox", here.rows(), {})
        # The visibility question is asked FIRST, and this is the half of that which a comment
        # cannot hold: every other read this producer makes is a read of a public repository's
        # public data, so a repository that is not public is refused before one of them happens.
        check("and nothing else was asked of a repository that is not public",
              sorted(set(here.rest.asked)), [f"repos/{REPO}"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a visibility the host did not answer is not public either")
def visibility_unanswered(root, check):
    here, tmp = world(root)
    try:
        here.rest.set(f"repos/{REPO}", {"status": "404"})
        _code, decision = here.run()
        check("fail-closed runs one way", decision["visibility"], "enterprise-private")
        check("and costs the row", decision["reason"], "inbox-absent")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a pull request declaring no scope class this table admits costs the row")
def scope_unparsed(root, check):
    here, tmp = world(root)
    try:
        pull = dict(here.rest.bodies[f"repos/{REPO}/pulls/{PR}"])
        pull["body"] = pull["body"].replace("Scope class: docs-only", "Scope class: <one of>")
        here.rest.set(f"repos/{REPO}/pulls/{PR}", pull)
        _code, decision = here.run()
        check("the reason names the scope", decision["reason"], "scope-unparsed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a producing job that names no artefact id leaves the stream unnamed and the row unwritten")
def artifact_unresolved(root, check):
    here, tmp = world(root)
    try:
        here.artifact_id = ""
        _code, decision = here.run()
        check("the reason names the artefact", decision["reason"], "artifact-unresolved")
        check("no stream was named", decision["stream"], None)
        check("and the platform was not asked for it either",
              [p for p in here.rest.asked if "artifacts" in p], [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a head the producing job did not read costs the row")
def head_mismatch(root, check):
    here, tmp = world(root)
    try:
        here.exports["head-sha"] = "e" * 40
        here.exports["checkout-sha"] = "e" * 40
        _code, decision = here.run()
        check("the reason names the disagreement", decision["reason"], "head-sha-mismatch")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("without the stream's commit the script decides and assembles nothing")
def decide_only(root, check):
    here, tmp = world(root)
    try:
        _code, decision = here.run(commit=None)
        check("it got as far as deciding", decision["state"], "decided")
        check("the stream's own facts are stated", decision["stream"]["path"], STREAM_PATH)
        check("with the digest a row would carry", len(decision["stream"]["sha256"]), 64)
        check("and the event count beside it", decision["stream"]["event_count"],
              len(here.events))
        check("nothing was assembled", os.path.exists(here.row_path), False)
        check("and nothing reached the inbox", here.rows(), {})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a stream with no result event is not a run this producer can measure")
def result_absent(root, check):
    here, tmp = world(root)
    try:
        here.events = [e for e in here.events if e.get("type") != "result"]
        here.build()
        _code, decision = here.run()
        check("the reason names the stream", decision["reason"], "result-absent")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a credential class the stream does not establish costs the row")
def credential_ambiguous(root, check):
    here, tmp = world(root)
    try:
        here.events[0]["apiKeySource"] = "ANTHROPIC_API_KEY"
        here.build()
        _code, decision = here.run()
        check("the reason names the ledger", decision["reason"], "credential-ambiguous")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a row the inbox's own rules refuse is kept as an artefact and reported, never filed")
def validator_refuses(root, check):
    here, tmp = world(root)
    try:
        # THE FIXTURE ALONE MAKES THE ROW INVALID, with no hook into the script: the client version
        # reaches `instrument.fence` through the fence grammar, and a character the contract's
        # pattern for that field does not admit makes the assembled row fail the contract. The
        # producer is supposed to find that before the inbox does.
        here.events[0]["claude_code_version"] = "2.1.274+ci"
        here.build()
        _code, decision = here.run()
        check("the capture does not fail the run", _code, 0)
        check("the state is the refusal", decision["state"], "refused")
        check("and the reason names whose rules refused it", decision["reason"],
              "validator-refused")
        check("the refusals are recorded", len(decision["refusals"]) > 0, True)
        check("nothing reached the inbox", here.rows(), {})
        # The artefact: the row as it was assembled, so the defect can be read rather than guessed
        # at from a message. A row is repaired at the producer and never in the inbox.
        check("the row is kept where the workflow uploads it",
              os.path.exists(here.row_path), True)
        with open(os.path.join(here.tmp, "issue.md"), encoding="utf-8") as fh:
            issue = fh.read()
        check("one issue, keyed so a re-run files none",
              f"Key: `{REPO}#{PR}/capture`" in issue, True)
        check("naming the human accountable for the pull request", "@a-person" in issue, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@case("a refused row is recorded with the key its issue is found by")
def refusal_is_keyed(root, check):
    here, tmp = world(root)
    try:
        _code, decision = here.run()
        check("the key names the repository, the pull request and this step",
              decision["issue_key"], f"{REPO}#{PR}/capture")
        check("and the human accountable for it is named", decision["author"], "a-person")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def assembly_arguments(ci_row) -> dict:
    """One valid row's arguments, as the producer passes them — the base every mutant edits.

    Written out rather than captured from a run so that a mutant differs from a valid row in
    exactly the field it is about.
    """
    return {
        "run_id": RUN_ID,
        "started_at": STARTED_AT,
        "fingerprint": ci_row.fingerprint_ci(REPO, PR, HEAD),
        "domain": ci_row.REVIEW_LIVE_DOMAIN,
        "scope": "docs-only",
        "provider": "anthropic",
        "model_id": MODEL,
        "harness_client": "claude-code",
        "harness_version": CLIENT_VERSION,
        "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
        "repository": REPO,
        "visibility": "public",
        "commit": HEAD,
        "bundle_version": BUNDLE_VERSION,
        "turns": 3,
        "tool_calls": 1,
        "wall_time_ms": 123456,
        "event_stream_ref": f"exeris-systems/exeris-ai-execution-streams/{STREAM_PATH}@"
                            f"{STREAM_COMMIT}",
        "event_stream_sha256": "0" * 64,
        "event_count": 4,
        "accounting_mode": "subscription",
        "oracle": ci_row.REVIEW_DISPOSITION_ORACLE,
        "outcome": "UNKNOWN",
        "capture_version": "0.2.0",
        "fence": f"{DATE}-ci-live-cc-2-1-274",
    }


# What the checkout has to carry for these cases to mean anything: the derivations, the inbox's own
# rules, and the contract's version. Named as files rather than as directories, because a checkout
# that carries the directories and not these is the state a stacked change is in before the half it
# depends on has landed — and that state has to read as "the dependency is not there yet" rather
# than as twenty-two failing cases.
NEEDED = ("tools/ci_row.py", "tools/inbox_validate.py", "schemas/VERSION",
          "schemas/run-record.schema.json")


def execution_root(named: str | None) -> str:
    """Where the row contract's checkout is, or a refusal naming what is missing from it.

    The derivations are imported from that checkout by the script under test, so a suite that ran
    without it would report a pass for cases that never executed a derivation.
    """
    tried = []
    for candidate in (named, os.environ.get("EXERIS_EXECUTION_ROOT"), "execution"):
        if not candidate:
            continue
        missing = [one for one in NEEDED if not os.path.exists(os.path.join(candidate, one))]
        if not missing:
            return os.path.abspath(candidate)
        tried.append(f"{candidate} (no {', '.join(missing)})")
    print("::error title=capture_ci_row_suite::the row contract's checkout does not carry the "
          "derivations these cases import: " + ("; ".join(tried) or "nowhere to look") + ". Pass "
          "`--execution-root DIR`, set `EXERIS_EXECUTION_ROOT`, or check "
          "`exeris-systems/exeris-ai-execution` out into `execution/` — and note that the capture "
          "step itself reads the same files from that repository's default branch, so a branch "
          "that does not carry them yet is a capture that cannot assemble a row either.")
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execution-root", default="")
    root = execution_root(parser.parse_args().execution_root or None)

    failures, ran = 0, 0

    def check(name: str, got, want) -> None:
        nonlocal failures, ran
        ran += 1
        if got != want:
            failures += 1
            print(f"::error title=capture_ci_row_suite::{name}: expected {want!r}, got {got!r}")

    for name, run in CASES:
        try:
            run(root, check)
        except Exception as exc:                                  # a case that cannot run failed
            failures += 1
            print(f"::error title=capture_ci_row_suite::{name}: raised "
                  f"{type(exc).__name__}: {exc}")

    print(f"capture_ci_row_suite: ran {len(CASES)} case(s), {ran} assertion(s), "
          f"{failures} failure(s)")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## capture_ci_row_suite\n\nRan **{len(CASES)}** case(s), **{ran}** "
                     f"assertion(s) — **{failures} failure(s)**.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
