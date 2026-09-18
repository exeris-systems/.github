#!/usr/bin/env python3
"""Every door that asks "is a person doing this?" asks GitHub's own field — ADR-087 §A.3, §B.8.

Two labels decide things no routine may decide for itself. `needs-l2-review` starts a review;
`l2-human-reviewed` tells the required check that a person read a change the routine cannot. Both
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


def load(root: str, name: str) -> dict:
    with open(os.path.join(root, ".github", "workflows", name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def raw(root: str, name: str) -> str:
    with open(os.path.join(root, ".github", "workflows", name), encoding="utf-8") as fh:
        return fh.read()


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

    # 4. The planner's own half of the same rule, read from the file rather than imported: this
    # script runs where `jsonschema` may not be installed, and importing the planner would make a
    # missing dependency look like a broken rule.
    planner = os.path.join(root, "scripts", "publish_verdict.py")
    with open(planner, encoding="utf-8") as fh:
        code = fh.read()
    green_set = re.search(r"ABOUT_THE_PULL_REQUEST\s*=\s*frozenset\(\{([^}]*)\}\)", code)
    rule(green_set is not None and "bot-authored" not in green_set.group(1)
         and "draft-or-bot" not in green_set.group(1),
         "publish_verdict.py greens a skip on a pull request a bot opened — ADR-087 §B.8 names a "
         "passing verdict and the path-filter skip, and calls every other state red")
    rule("def human_principal(" in code,
         "publish_verdict.py no longer decides who is a person")
    rule("not human_principal(args.override_by, args.override_by_type)" in code,
         "publish_verdict.py does not ask `human_principal` about the override label")

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
