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


def inputs_of(path: str) -> tuple[set[str], set[str]]:
    """The inputs a called workflow declares, and the subset it requires."""
    with open(path, encoding="utf-8") as fh:
        wf = yaml.safe_load(fh) or {}
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1), so both spellings are looked up.
    trigger = wf.get("on") or wf.get(True) or {}
    declared_inputs = ((trigger.get("workflow_call") or {}).get("inputs")) or {}
    required = {k for k, v in declared_inputs.items() if isinstance(v, dict) and v.get("required")}
    return set(declared_inputs), required


def check_with(path: str, job: str, spec: dict, called: str, bad: list) -> None:
    """Every `with:` key names an input the called workflow declares, and carries a value.

    `permissions` is not the only way one file here can invalidate another's. A `with:` key the
    called workflow does not declare is rejected as an invalid workflow, in the adopting repository,
    on the first push, with no logs — the same failure this script already exists to prevent, by the
    same mechanism, and it was not covered: a pull request in this repository once pasted an input
    DEFINITION into a `with:` block and every gate here passed it.
    """
    given = spec.get("with") or {}
    if not isinstance(given, dict):
        bad.append(f"{path}: job `{job}` has a `with:` that is a {type(given).__name__} rather than "
                   f"a mapping of input names to values")
        return
    declared, required = inputs_of(called)
    for key, value in given.items():
        if key not in declared:
            bad.append(f"{path}: job `{job}` passes `with: {key}`, which `{called}` does not "
                       f"declare as an input — GitHub rejects the whole file")
        if isinstance(value, (dict, list)):
            bad.append(f"{path}: job `{job}` passes `with: {key}` as a "
                       f"{type(value).__name__}; an input takes a scalar, and a mapping here is an "
                       f"input definition pasted where its value belongs")
    for key in sorted(required - set(given)):
        bad.append(f"{path}: job `{job}` omits `with: {key}`, which `{called}` declares required")


def nested_path(uses: str) -> str | None:
    """Where a `uses:` reference lands in THIS repository, or None when it points elsewhere."""
    if uses.startswith("./"):
        return uses[2:]
    if "exeris-systems/.github/" in uses:
        return os.path.join(WF_DIR, uses.split("/")[-1].split("@")[0])
    return None


def audit(path: str, wf: dict, bad: list) -> None:
    """One file's calls: the target exists, its `with:` is well formed, and the block is the union.

    The same three questions for `caller-example/guardrails.yml` and for a reusable workflow here
    that calls another. Asking them in two places asked them differently three times running — the
    second copy skipped a missing target, and neither copy checked this repository's own caller's
    permissions, which is the block that caps every nested call in it.
    """
    grants = wf.get("permissions") or {}
    need: dict[str, str] = {}
    for job, spec in (wf.get("jobs") or {}).items():
        called = nested_path((spec or {}).get("uses", ""))
        if called is None:
            continue
        if not os.path.exists(called):
            bad.append(f"{path}: job `{job}` calls `{called}`, which does not exist here")
            continue
        check_with(path, job, spec, called, bad)
        for key, value in declared(called).items():
            if RANK.get(value, 0) > RANK.get(need.get(key, "none"), 0):
                need[key] = value
    if not need:
        return
    for key, value in sorted(need.items()):
        if RANK.get(grants.get(key, "none"), 0) < RANK[value]:
            bad.append(f"{path}: grants `{key}: {grants.get(key, 'none')}` but a called "
                       f"workflow declares `{key}: {value}` — GitHub rejects the whole file")


def main() -> int:
    bad: list[str] = []
    for directory in ("caller-example", WF_DIR):
        for name in sorted(os.listdir(directory)):
            if not name.endswith((".yml", ".yaml")):
                continue
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8") as fh:
                audit(path, yaml.safe_load(fh) or {}, bad)

    for line in bad:
        print(f"::error::{line}")
    print(f"## caller_permissions_check\n\n{len(bad)} problem(s).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
