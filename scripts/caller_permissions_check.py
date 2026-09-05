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


def declared(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh).get("permissions") or {}


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
