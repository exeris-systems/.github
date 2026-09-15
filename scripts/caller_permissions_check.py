#!/usr/bin/env python3
"""Check that caller-example/*.yml grants the union of what its called workflows declare.

A called workflow can only narrow the caller's permissions. Grant less than one of them declares
and GitHub does not run that job with less — it rejects the whole file as an invalid workflow,
before any gate runs. The failure therefore arrives in the adopting repository, on the first push,
as a red X with no logs, which is the worst place for it to arrive.

This is the same shape as every other check in this bundle: a file here asserts something about
another file here, so the assertion is testable. Run by the organisation repository's own guardrails.
"""
import os
import sys

import yaml

RANK = {"none": 0, "read": 1, "write": 2}
WF_DIR = os.path.join(".github", "workflows")


def declared(path: str, seen: set[str] | None = None) -> dict:
    """The permissions a called workflow needs, ITS OWN NESTED CALLS INCLUDED.

    A reusable workflow may call another, and the caller's block still has to be the union of
    everything down the chain — GitHub rejects the file at the top, in the adopting repository, with
    no logs. Reading one level was right while no workflow here nested; `docs-review.yml` now calls
    `publish-verdict.yml`, and a checker that stops at the first level answers "0 problems" to the
    question it exists to ask. The union happens to hold today, which is exactly when a gate quietly
    stops covering its subject.
    """
    seen = seen if seen is not None else set()
    real = os.path.realpath(path)
    if real in seen:
        return {}
    seen.add(real)
    with open(path, encoding="utf-8") as fh:
        wf = yaml.safe_load(fh) or {}
    need = dict(wf.get("permissions") or {})
    for spec in (wf.get("jobs") or {}).values():
        uses = (spec or {}).get("uses", "")
        if not uses:
            continue
        nested = nested_path(uses)
        if nested is None:
            continue
        if not os.path.exists(nested):
            continue
        for key, value in declared(nested, seen).items():
            if RANK.get(value, 0) > RANK.get(need.get(key, "none"), 0):
                need[key] = value
    return need


def nested_path(uses: str) -> str | None:
    """Where a `uses:` reference lands in THIS repository, or None when it points elsewhere."""
    if uses.startswith("./"):
        return uses[2:]
    if "exeris-systems/.github/" in uses:
        return os.path.join(WF_DIR, uses.split("/")[-1].split("@")[0])
    return None


def main() -> int:
    bad = []
    for name in sorted(os.listdir("caller-example")):
        if not name.endswith((".yml", ".yaml")):
            continue
        path = os.path.join("caller-example", name)
        with open(path, encoding="utf-8") as fh:
            caller = yaml.safe_load(fh)
        grants = caller.get("permissions") or {}
        need: dict[str, str] = {}
        for job, spec in (caller.get("jobs") or {}).items():
            uses = spec.get("uses", "")
            if "exeris-systems/.github/" not in uses:
                continue
            called = os.path.join(WF_DIR, uses.split("/")[-1].split("@")[0])
            if not os.path.exists(called):
                bad.append(f"{path}: job `{job}` calls `{called}`, which does not exist here")
                continue
            for key, value in declared(called).items():
                if RANK.get(value, 0) > RANK.get(need.get(key, "none"), 0):
                    need[key] = value
        for key, value in sorted(need.items()):
            if RANK.get(grants.get(key, "none"), 0) < RANK[value]:
                bad.append(f"{path}: grants `{key}: {grants.get(key, 'none')}` but a called "
                           f"workflow declares `{key}: {value}` — GitHub rejects the whole file")
    for line in bad:
        print(f"::error::{line}")
    print(f"## caller_permissions_check\n\n{len(bad)} problem(s).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
