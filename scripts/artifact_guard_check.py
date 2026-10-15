#!/usr/bin/env python3
"""A guard whose condition cannot fail is not a guard — ADR-087 §B.10.

The `verdict` job of `review.yml` fetches each artefact behind
`if: needs.handover.outputs.<name>-artifact != ''`, which says the `handover` job leaves the name
empty when there is nothing to fetch. That is a contract between two files, and
only one of them can keep it: if the caller builds the name from the pull-request number alone, the
input is never empty, the step always runs, and a skipped producing job leaves it fetching an
artefact that was never uploaded.

Neither job is wrong by itself. The pair is. So this reads both: every `*-artifact` output the
`handover` job carries must be conditional on something the producing job reports, and every one the
publishing jobs consume must be guarded on being non-empty.

Usage: artifact_guard_check.py [--root .]
"""
from __future__ import annotations

import argparse
import os
import sys

import yaml

ROUTINE = "review.yml"
# The publishing jobs are jobs of the routine's own file: `verdict` must be one, for the required
# check to be named `review / verdict`. `publish_twin_check.py` holds `publish-verdict.yml` to them.
PUBLISH = "review.yml"
HANDOVER = "needs.handover.outputs"


def load(root: str, name: str) -> dict:
    with open(os.path.join(root, ".github", "workflows", name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def flat(value) -> str:
    return " ".join(str(value).split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    root = os.path.abspath(ap.parse_args().root)
    routine, publish = load(root, ROUTINE), load(root, PUBLISH)
    bad: list[str] = []

    handed = (routine.get("jobs", {}).get("handover", {}).get("outputs") or {})
    names = sorted(k for k in handed if k.endswith("-artifact"))
    if not names:
        print("::error::artifact_guard_check: the `handover` job carries no artefact names, so "
              "there is nothing to compare — it moved, and a check that cannot find what it "
              "checks is not a check")
        return 1

    produced = set((routine.get("jobs", {}).get("produce", {}).get("outputs") or {}))
    for key in names:
        expr = flat(handed[key])
        if "needs.produce.outputs." not in expr:
            bad.append(f"`{key}` is handed over unconditionally, so the publish half's "
                       f"`{HANDOVER}.{key} != ''` can never be false and a skipped producing job "
                       f"leaves it fetching an artefact nobody uploaded")
            continue
        named = [o for o in produced if f"needs.produce.outputs.{o}" in expr]
        if not named:
            bad.append(f"`{key}` is conditional on a produce output the produce job does not "
                       f"declare; it will read as empty and the artefact is never fetched")

    # The other half of the same contract: a name the routine may leave empty must be consumed
    # behind a guard, or the empty string is passed to `download-artifact` as a name.
    #
    # EVERY JOB IN THE FILE, not the publishing one alone. A second job fetching the same artefact
    # is a second place the guard has to hold, and a checker that read one job would answer "0
    # problems" about a file it had covered half of.
    steps = [step
             for job in (publish.get("jobs") or {}).values()
             for step in ((job or {}).get("steps") or [])]
    for key in names:
        ref = f"{HANDOVER}.{key}"
        users = [s for s in steps if ref in flat(s.get("with") or {})]
        for step in users:
            if ref not in flat(step.get("if") or ""):
                bad.append(f"`{PUBLISH}` step {step.get('name')!r} uses `{ref}` without guarding "
                           f"on it being non-empty")

    for said in bad:
        print(f"::error::artifact_guard_check: {said}")
    if bad:
        return 1
    print(f"artifact_guard_check: {len(names)} artefact name(s), each conditional where it is "
          f"handed over and guarded where it is read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
