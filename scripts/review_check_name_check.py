#!/usr/bin/env python3
"""The required check's name is a contract between files, so it is derived from the files and compared.

A check run is named `<caller job> / <job>`, one segment for each reusable workflow the run passes
through. That makes the name a function of three things that live in three places: the job id in a
repository's `guardrails.yml`, the layout of the workflow it calls, and the string a ruleset
requires. A required check whose name no run produces never reports, and a pull request waiting on
one cannot merge, so a drift between any two of them is found here and not by a pull request that
waits for ever.

What is asserted:

1. `review.yml` holds the steps of `verdict` itself, so a caller whose job is `review` reports
   `review / verdict`. A `verdict` that is a call to another workflow would add a segment.
2. `docs-review.yml` is a one-job wrapper whose job is `publish`, so a caller whose job is
   `docs-review` still reports `docs-review / publish / verdict`, and the wrapper declares what
   `review.yml` declares and hands every input and secret over unchanged.
3. `publish-verdict.yml`, kept for callers that pin an old `docs-review.yml` by commit, carries the
   same `verdict` and `capture` jobs as `review.yml` once the one substitution between them is made.
4. The caller in this repository and the caller example call `review.yml` from a job called `review`.
5. Each ruleset names a check some caller can produce, and no repository sits in two of them.

Usage: review_check_name_check.py [--root .]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

import yaml

NEW_NAME = "review / verdict"
OLD_NAME = "docs-review / publish / verdict"
INTEGRATION = 15368  # GitHub Actions
HANDOVER = "needs.handover.outputs."


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def trigger(wf: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1), so both spellings are looked up.
    return (wf.get("on") or wf.get(True) or {}).get("workflow_call") or {}


def names(workflows: str, caller_job: str, called: str, seen: tuple = ()) -> set[str]:
    """Every check name a caller job produces by calling `called`, nested calls followed."""
    if called in seen:
        return set()
    path = os.path.join(workflows, called)
    if not os.path.exists(path):
        return set()
    out: set[str] = set()
    for job_id, spec in (load(path).get("jobs") or {}).items():
        spec = spec or {}
        label = spec.get("name") if isinstance(spec.get("name"), str) \
            and "${{" not in spec["name"] else job_id
        uses = str(spec.get("uses", ""))
        if uses:
            nested = uses.split("@")[0].rsplit("/", 1)[-1]
            out |= names(workflows, f"{caller_job} / {label}", nested, seen + (called,))
        else:
            out.add(f"{caller_job} / {label}")
    return out


def flat(value) -> str:
    return " ".join(str(value).split())


def declared(wf: dict) -> tuple[dict, dict]:
    t = trigger(wf)
    return t.get("inputs") or {}, t.get("secrets") or {}


def normalise(job: dict) -> dict:
    """`review.yml`'s job as `publish-verdict.yml` would spell it: the hand-over read as inputs."""
    text = json.dumps(job).replace(HANDOVER, "inputs.")
    out = json.loads(text)
    for key in ("needs", "if", "permissions"):
        out.pop(key, None)
    return out


def twin_problems(review: dict, publish: dict) -> list[str]:
    bad: list[str] = []
    r_jobs, p_jobs = review.get("jobs") or {}, publish.get("jobs") or {}
    workflow_permissions = publish.get("permissions") or {}
    for job in ("verdict", "capture"):
        if job not in r_jobs or job not in p_jobs:
            bad.append(f"`{job}` is missing from review.yml or publish-verdict.yml, so the two cannot "
                       f"be compared")
            continue
        a, b = normalise(r_jobs[job]), normalise(p_jobs[job])
        if a != b:
            keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            steps = [s.get("name") or s.get("uses") or s.get("run", "")[:40]
                     for s, t in zip(a.get("steps") or [], b.get("steps") or []) if s != t]
            where = f" (step {steps[0]!r})" if steps else ""
            bad.append(f"review.yml's `{job}` differs from publish-verdict.yml's in {keys}{where} — "
                       f"a change made to one of the two copies and not the other, and the callers "
                       f"pinned to an old docs-review.yml run the second")
    perms = (r_jobs.get("verdict") or {}).get("permissions") or {}
    if perms != workflow_permissions:
        bad.append(f"review.yml's `verdict` job grants {perms}, where publish-verdict.yml's workflow "
                   f"grants {workflow_permissions}; the publishing job has never held `id-token`")
    cap = ((r_jobs.get("capture") or {}).get("permissions"), (p_jobs.get("capture") or {}).get("permissions"))
    if cap[0] != cap[1]:
        bad.append(f"the `capture` job's permissions differ: {cap[0]} in review.yml, {cap[1]} in "
                   f"publish-verdict.yml")
    cond = flat((r_jobs.get("capture") or {}).get("if", ""))
    if cond != "${{ !cancelled() && needs.handover.outputs.capture == 'true' }}":
        bad.append("review.yml's `capture` job no longer runs only when the hand-over says `true`; a "
                   "job output is a string, and `'false'` is truthy")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    root = os.path.abspath(ap.parse_args().root)
    workflows = os.path.join(root, ".github", "workflows")
    bad: list[str] = []
    checked = [0]

    def rule(ok: bool, said: str) -> None:
        checked[0] += 1
        if not ok:
            bad.append(said)

    review = load(os.path.join(workflows, "review.yml"))

    # 1. The steps of `verdict` are in review.yml.
    verdict = (review.get("jobs") or {}).get("verdict") or {}
    rule(bool(verdict.get("steps")) and "uses" not in verdict,
         "review.yml's `verdict` is not a job with steps of its own; a call would put a third "
         f"segment in the name and a caller's job `review` would no longer report `{NEW_NAME}`")
    rule(NEW_NAME in names(workflows, "review", "review.yml"),
         f"a caller job `review` calling review.yml does not produce `{NEW_NAME}`")

    # 2. The wrapper keeps the old name, and says what review.yml says.
    wrapper_path = os.path.join(workflows, "docs-review.yml")
    if os.path.exists(wrapper_path):
        wrapper = load(wrapper_path)
        jobs = wrapper.get("jobs") or {}
        rule(list(jobs) == ["publish"] and str(jobs["publish"].get("uses", "")).split("@")[0]
             .endswith("/.github/workflows/review.yml"),
             "docs-review.yml is not a single job `publish` calling review.yml; the callers that "
             f"have not moved require `{OLD_NAME}`")
        rule(OLD_NAME in names(workflows, "docs-review", "docs-review.yml"),
             f"a caller job `docs-review` calling docs-review.yml does not produce `{OLD_NAME}`")
        r_in, r_sec = declared(review)
        w_in, w_sec = declared(wrapper)
        rule(set(r_in) == set(w_in),
             f"docs-review.yml and review.yml declare different inputs: "
             f"{sorted(set(r_in) ^ set(w_in))}")
        for key in sorted(set(r_in) & set(w_in)):
            for field in ("type", "default", "required"):
                rule((r_in[key] or {}).get(field) == (w_in[key] or {}).get(field),
                     f"input `{key}` differs in `{field}` between docs-review.yml and review.yml, so "
                     f"the same caller behaves differently through the two")
        # Messages about secrets carry counts, not names: the names are in both files, and a
        # check's log is no place to print anything read from a `secrets` block.
        rule(set(r_sec) == set(w_sec),
             f"docs-review.yml and review.yml declare different secrets "
             f"({len(set(r_sec) ^ set(w_sec))} declared in only one)")
        unequal = [k for k in set(r_sec) & set(w_sec)
                   if bool((r_sec[k] or {}).get("required")) != bool((w_sec[k] or {}).get("required"))]
        rule(not unequal,
             f"{len(unequal)} secret(s) required in one of docs-review.yml and review.yml and not the other")
        given = (jobs.get("publish") or {}).get("with") or {}
        handed = (jobs.get("publish") or {}).get("secrets") or {}
        for key in sorted(r_in):
            rule(flat(given.get(key, "")) == "${{ inputs." + key + " }}",
                 f"docs-review.yml does not hand input `{key}` to review.yml unchanged")
        altered = [k for k in r_sec if flat(handed.get(k, "")) != "${{ secrets." + k + " }}"]
        rule(not altered, f"docs-review.yml does not hand {len(altered)} secret(s) to review.yml unchanged")

    # 3. The frozen copy stays the same text.
    twin = os.path.join(workflows, "publish-verdict.yml")
    if os.path.exists(twin):
        problems = twin_problems(review, load(twin))
        checked[0] += 4
        bad.extend(problems)

    # 4. The callers in this repository.
    own = load(os.path.join(workflows, "guardrails.yml"))
    rule(str(((own.get("jobs") or {}).get("review") or {}).get("uses", ""))
         == "./.github/workflows/review.yml",
         "this repository's guardrails.yml has no job `review` calling ./.github/workflows/review.yml, "
         f"so the check it reports is not `{NEW_NAME}`")
    example = os.path.join(root, "caller-example", "guardrails.yml")
    if os.path.exists(example):
        ex_job = ((load(example).get("jobs") or {}).get("review") or {})
        rule(str(ex_job.get("uses", "")).endswith("/.github/workflows/review.yml@main"),
             "caller-example/guardrails.yml has no job `review` calling review.yml@main; every "
             "repository copies it, and its job id is the first segment of the check")

    # 5. The rulesets.
    produced = {"exeris-code-review.json": NEW_NAME, "exeris-code-verdict.json": OLD_NAME}
    includes: dict[str, set[str]] = {}
    for path in sorted(glob.glob(os.path.join(root, "rulesets", "exeris-code-*.json"))):
        base = os.path.basename(path)
        if base not in produced:
            continue
        with open(path, encoding="utf-8") as fh:
            ruleset = json.load(fh)
        contexts = [(c["context"], c.get("integration_id"))
                    for r in ruleset["rules"] if r["type"] == "required_status_checks"
                    for c in r["parameters"]["required_status_checks"]]
        rule(contexts == [(produced[base], INTEGRATION)],
             f"{base} requires {contexts}, not `{produced[base]}` from the Actions integration "
             f"({INTEGRATION}); a repository requires one name, never both")
        includes[base] = set(ruleset["conditions"]["repository_name"]["include"])
    if len(includes) == 2:
        both = sorted(includes["exeris-code-review.json"] & includes["exeris-code-verdict.json"])
        rule(not both, f"{both} sit in both rulesets, so each requires both names and one never reports")
        rule(".github" in includes["exeris-code-review.json"]
             and ".github" not in includes["exeris-code-verdict.json"],
             "`.github` calls review.yml from a job `review`, so it belongs to exeris-code-review.json "
             "and not to exeris-code-verdict.json")

    for said in bad:
        print(f"::error::review_check_name_check: {said}")
    if bad:
        print(f"review_check_name_check: {len(bad)} of {checked[0]} rule(s) broken")
        return 1
    print(f"review_check_name_check: {checked[0]} rule(s) checked — `{NEW_NAME}` for a caller job "
          f"`review`, `{OLD_NAME}` for a caller job `docs-review`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
