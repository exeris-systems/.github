#!/usr/bin/env python3
"""Every door that asks "is a person doing this?" asks GitHub's own field — ADR-087 §A.3, §B.8.

Two labels decide things no routine may decide for itself. `needs-review` starts a review;
`human-reviewed` tells the required check that a person read a change the routine cannot. Both
are ordinary labels: anything holding `pull-requests: write` can apply either, `exeris-bot` among
them, and a second App in this organisation makes that an ordinary Tuesday rather than a thought
experiment. Applying them is the capability, and a gate that can hand itself that capability is not
a gate.

The rules live in workflow expressions, which no suite can execute: there is no runner here, no
event payload, no `github` context. What CAN be checked is that the expression SHIPPED still says
what it was written to say — the same shape as `gate_vocabulary_check.py`, which runs the mapping
this repository ships rather than a copy of it. Each rule below fails when the expression it reads
is edited back to the form it had, and each was confirmed to fail that way.

Usage: principal_check.py [--root .]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import yaml

# The payload field. `sender` is the principal that caused THIS event — the one who clicked, pushed
# or applied the label — and `type` is `User` or `Bot`. `actor` answers a different question, who
# started the run, and the two part company on a re-run.
SENDER_TYPE = "github.event.sender.type"
SENDER_LOGIN = "github.event.sender.login"
HUMAN = "'User'"
REVIEW_EVENT = "'pull_request_review'"


def load(root: str, name: str) -> dict:
    with open(os.path.join(root, ".github", "workflows", name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def raw(root: str, name: str) -> str:
    with open(os.path.join(root, ".github", "workflows", name), encoding="utf-8") as fh:
        return fh.read()


def condition(job: dict) -> str:
    """A job's `if:` with its whitespace folded, so a rule reads the expression and not its layout."""
    return " ".join(str((job or {}).get("if", "")).split())


def caller_rules(root: str, rule) -> None:
    """Rules 5 and 5a, asked of this repository's own caller and of the one every repository copies.

    5a. AN APPROVAL IS AN EVENT THE VERDICT JOB MUST FOLLOW, and nothing else need. Listening to
    reviews is what lets a person's approval green the check without a second gesture; the review
    job must run on one for the same reason as rule 5, and the L1 gates must not, because a review
    changes no file they read.
    """
    for caller in ("guardrails.yml", "caller-example/guardrails.yml"):
        path = (os.path.join(root, ".github", "workflows", caller) if "/" not in caller
                else os.path.join(root, caller))
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            wf = yaml.safe_load(fh) or {}
        jobs = wf.get("jobs") or {}
        review = condition(jobs.get("docs-review"))
        rule(SENDER_TYPE not in review,
             f"{caller} skips the review job on a bot's event; the newest run then carries no "
             f"verdict and the required check waits on a status that never arrives")
        listens = (wf.get("on") or wf.get(True) or {}).get("pull_request_review") or {}
        rule({"submitted", "dismissed"} <= set(listens.get("types") or []),
             f"{caller} does not run on a review submitted or dismissed, so an approval greens "
             f"nothing until some other event follows it")
        rule(REVIEW_EVENT not in review,
             f"{caller} skips the review job on a review event, so an approval never reaches the "
             f"required check")
        # The gates run on a review event too, for the rule the review job obeys: a required check
        # is read from the newest run, and a gate called as a reusable workflow that is skipped
        # reports only its caller's job name, never `docs / docs-lint`, so the check it owes waits.
        for gate_job in ("docs", "commits", "pr-body"):
            rule(REVIEW_EVENT not in condition(jobs.get(gate_job)),
                 f"{caller}'s `{gate_job}` is skipped on a review event, so the newest run carries "
                 f"none of its checks and a required one waits on a status that never arrives")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    root = os.path.abspath(ap.parse_args().root)

    review = load(root, "docs-review.yml")
    publish = load(root, "publish-verdict.yml")
    produce = review["jobs"]["produce"]
    hands_over = review["jobs"]["publish"]["with"]
    bad: list[str] = []
    # Counted where they run, not counted by a reader. A number in a pull request body that no tool
    # prints is a number somebody arrived at, and on #62 that number was wrong by four — asserted as
    # "eight rules" against a file carrying twelve. `claims-and-evidence.md` rule 1 asks for the
    # report a figure came from; the cheapest way to have one is for the tool to say it.
    checked = [0]

    def rule(ok: bool, said: str) -> None:
        checked[0] += 1
        if not ok:
            bad.append(said)

    # 1. THE REVIEW RUNS BECAUSE A PERSON ASKED. Opening, reopening, marking ready and applying the
    # request label are all read as "a person says this is ready", so all four have to come from a
    # person. Without this the label alone starts a run, and the publication applies labels.
    gate = " ".join(str(produce.get("if", "")).split())
    rule(f"{SENDER_TYPE} == {HUMAN}" in gate,
         f"the produce job's `if:` does not require {SENDER_TYPE} == {HUMAN}, so a bot applying "
         f"the request label starts a review the runner will refuse")

    # 1a. A REVIEW IS NOT A READINESS EVENT. The callers listen to reviews so that an approval
    # reaches the required check, and while the request label stands every other clause of the
    # produce job's condition admits one — a review would run the model again on a tree it has read.
    rule("github.event_name == 'pull_request'" in gate,
         "the produce job's `if:` does not require github.event_name == 'pull_request', so a "
         "review submitted while the request label stands runs the model again")

    # 2. A BOT EVENT IS NOT A READINESS EVENT. `skip-kind` is an ordered chain of `||`, so the first
    # alternative that is truthy wins. `ready` before `bot-event` classified the publication's own
    # label change as a review that was asked for and produced nothing.
    kind = " ".join(str(hands_over.get("skip-kind", "")).split())
    rule("bot-event" in kind and "'ready'" in kind
         and kind.index("bot-event") < kind.index("'ready'"),
         "`skip-kind` does not reach `bot-event` before `ready`, so a bot's label change on a pull "
         "request still carrying the request label is classified as a review that produced nothing")
    rule(SENDER_TYPE in kind,
         f"`skip-kind` does not decide `bot-event` from {SENDER_TYPE}")

    # 2a. A PULL REQUEST A BOT OPENED CAN BE MERGED, so it is its own kind. `draft-or-bot` was one
    # word for two situations and one green for both; only the draft half earns it, because GitHub
    # refuses to merge a draft whatever this check says. This reads the shipped expression because
    # no Python suite can execute it, and the planner's own half is read below.
    rule("'draft'" in kind and "'bot-authored'" in kind and "draft-or-bot" not in kind,
         "`skip-kind` does not name `draft` and `bot-authored` as separate kinds — merged, a pull "
         "request a bot opened takes the draft's green and merges having been read by nothing")

    # 2b. A REVIEW EVENT IS ITS OWN KIND, and it is reached before `ready`: otherwise a review on a
    # pull request carrying the request label reads as a review that was asked for and produced
    # nothing, where what it carries is whether a person's approval now covers the head.
    rule("'review-event'" in kind and "'ready'" in kind
         and kind.index("'review-event'") < kind.index("'ready'"),
         "`skip-kind` does not reach `review-event` before `ready`, so an approval is classified as "
         "a review that was asked for and produced nothing")

    reason = " ".join(str(hands_over.get("skip-reason", "")).split())
    rule(SENDER_TYPE in reason,
         f"`skip-reason` does not name {SENDER_TYPE}, so the reason and the classification can "
         f"disagree about why the job was skipped")

    # 3. THE OVERRIDE NAMES THE LABELLER AND ITS TYPE, AND DECIDES NEITHER HERE. The planner decides,
    # because the planner has cases. What this file must not do is filter the login and drop the
    # override silently: that left the label on the pull request, claiming a review nobody made.
    plan_step = None
    for step in publish["jobs"]["verdict"]["steps"]:
        if str(step.get("name", "")).startswith("Plan the publication"):
            plan_step = step
    if plan_step is None:
        bad.append("publish-verdict.yml has no `Plan the publication` step to read")
    else:
        env = plan_step.get("env") or {}
        by = " ".join(str(env.get("OVERRIDE_BY", "")).split())
        rule(SENDER_LOGIN in by,
             f"OVERRIDE_BY is not read from {SENDER_LOGIN}")
        rule("[bot]" not in by,
             "OVERRIDE_BY still filters the login here. Refusing in an expression drops the "
             "override and leaves the label standing — the planner refuses, removes and records")
        rule(SENDER_TYPE in " ".join(str(env.get("OVERRIDE_BY_TYPE", "")).split()),
             f"OVERRIDE_BY_TYPE is not read from {SENDER_TYPE}")
        rule("--override-by-type" in str(plan_step.get("run", "")),
             "the planner is not given --override-by-type, so it decides on an empty type")
        rule("--reviews reviews.json" in str(plan_step.get("run", "")),
             "the planner is not given --reviews, so a person's approval is never read as a "
             "human review")

    # 3a. AN APPROVAL IS A DOOR TOO, and it carries its principal's TYPE across. The reviews listing
    # is reduced before the planner reads it; a reduction that dropped `user.type` would hand the
    # planner an empty type on every review, which it reads as not a person — safe, and a door that
    # never opens.
    fetch = [step for step in publish["jobs"]["verdict"]["steps"]
             if str(step.get("name", "")).startswith("The approvals on this pull request")]
    rule(bool(fetch) and "type: .user.type" in str(fetch[0].get("run", "")),
         "publish-verdict.yml does not carry each review's `user.type` to the planner, so no "
         "approval can be told apart from an App's")

    # 4. The planner's own half of the same rule, read from the file rather than imported: this
    # script runs where `jsonschema` may not be installed, and importing the planner would make a
    # missing dependency look like a broken rule.
    planner = os.path.join(root, "scripts", "publish_verdict.py")
    with open(planner, encoding="utf-8") as fh:
        code = fh.read()
    # 5. EVERY EVENT CARRIES THE VERDICT JOB, A BOT'S INCLUDED. A required check is read from the
    # newest run of the caller on the head commit, so a run in which the review job is skipped
    # leaves the pull request waiting on a status nothing will report. The publisher's own label
    # changes are events, so a caller that skips the job on a bot's event strands every pull request
    # whose last event was the publisher's. Rule 1 is what keeps the model asleep on such an event;
    # the caller only decides whether the verdict job exists, and it must always exist. The example
    # is what every adopting repository copies, so the two are held to the same rule.
    caller_rules(root, rule)

    green_set = re.search(r"ABOUT_THE_PULL_REQUEST\s*=\s*frozenset\(\{([^}]*)\}\)", code)
    rule(green_set is not None and "bot-authored" not in green_set.group(1)
         and "draft-or-bot" not in green_set.group(1),
         "publish_verdict.py greens a skip on a pull request a bot opened — ADR-087 §B.8 names a "
         "passing verdict and the path-filter skip, and calls every other state red")
    rule("def human_principal(" in code,
         "publish_verdict.py no longer decides who is a person")
    rule("not human_principal(args.override_by, args.override_by_type)" in code,
         "publish_verdict.py does not ask `human_principal` about the override label")
    rule("if not human_principal(login, kind):" in code,
         "publish_verdict.py does not ask `human_principal` about an approving review, so an App's "
         "approval reads as a person's")

    for said in bad:
        print(f"::error::principal_check: {said}")
    if bad:
        print(f"principal_check: {len(bad)} of {checked[0]} rule(s) broken")
        return 1
    print(f"principal_check: {checked[0]} rule(s) checked — every door that asks for a person "
          f"asks GitHub what it is looking at")
    return 0


if __name__ == "__main__":
    sys.exit(main())
