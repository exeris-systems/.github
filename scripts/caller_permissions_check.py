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
import subprocess
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


class _DuplicateKeyLoader(yaml.SafeLoader):
    """A loader that refuses what PyYAML silently forgives.

    On a duplicate mapping key PyYAML keeps the LAST value and says nothing. GitHub rejects the file
    outright — "'l1-results' is already defined" — and answers with a run carrying zero jobs, no
    logs and a conclusion of `failure`, which took every gate in this repository down with it. So the
    one tool that could have caught it was the one guaranteed not to: every check here parses with
    PyYAML, sees a well-formed mapping, and reports 0 problems.
    """

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"key {key!r} is defined more than once", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep)


_DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _DuplicateKeyLoader.construct_mapping)


def check_duplicate_keys(path: str, text: str, bad: list) -> None:
    """Every mapping in a workflow file defines each key once."""
    try:
        yaml.load(text, Loader=_DuplicateKeyLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        bad.append(f"{path}: {getattr(exc, 'problem', exc)}{where} — GitHub rejects the whole file, "
                   f"and PyYAML does not, so no other check here can see it")


def publishes(wf: dict) -> bool:
    """Whether this caller turns the publishing half on — the half that removes the review label."""
    for spec in (wf.get("jobs") or {}).values():
        spec = spec or {}
        if (spec.get("with") or {}).get("publish") is True:
            return True
        if "publish-verdict.yml" in str(spec.get("uses", "")):
            return True
    return False


def check_cancellation(path: str, wf: dict, bad: list) -> None:
    """A run the bot's own label removal starts must not cancel the run that removed the label.

    The publishing job removes the review label as one of its last steps. That removal is an
    `unlabeled` event, it starts a second run, and an unconditional `cancel-in-progress: true`
    points that run at the one still publishing. Measured on #35: the publishing run's last job
    completed at 07:06:26 and the cancelling run was created at 07:06:26 — every job came out
    `success` and the run was still recorded as `cancelled`. A slower review loses the
    `publish / verdict` job to the cancel, and a cancelled required check blocks a pull request for
    a reason no human can act on.

    Gating on the actor keeps the collapse where it earns its keep, on human pushes, and makes a
    bot-triggered run queue instead. Only a caller that both publishes and listens to label events
    can hit this; a caller with publication off removes no label and is left alone.
    """
    trigger = (wf.get("on") or wf.get(True) or {}).get("pull_request") or {}
    listens = sorted(set(trigger.get("types") or []) & {"labeled", "unlabeled"})
    if not listens or not publishes(wf):
        return
    if (wf.get("concurrency") or {}).get("cancel-in-progress") is True:
        bad.append(f"{path}: publishes and is triggered by {', '.join('`%s`' % t for t in listens)}, "
                   f"but sets `cancel-in-progress: true` — the run started by the bot removing the "
                   f"review label cancels the run that was still publishing it. Gate it on the "
                   f"actor: `cancel-in-progress: ${{{{ !endsWith(github.actor, '[bot]') }}}}`")


def nested_path(uses: str) -> str | None:
    """Where a `uses:` reference lands in THIS repository, or None when it points elsewhere."""
    if uses.startswith("./"):
        return uses[2:]
    if "exeris-systems/.github/" in uses:
        return os.path.join(WF_DIR, uses.split("/")[-1].split("@")[0])
    return None


def as_released(uses: str, path: str) -> dict | None:
    """The called workflow as the REF names it, not as this branch has it.

    A `uses:` pinned to `@main` is resolved by GitHub against `main`, while every check here reads
    the file beside it. So a pull request that adds an input to the called workflow and passes it in
    the same change looks consistent locally and is rejected by GitHub — the input does not exist on
    `main` yet. That is not a mistake anyone can see by reading one tree, and it cost a startup
    failure with zero jobs before it was understood.
    """
    ref = uses.split("@")[-1] if "@" in uses else ""
    if not ref or ref == "./" or uses.startswith("./"):
        return None
    out = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    try:
        return yaml.safe_load(out.stdout) or {}
    except yaml.YAMLError:
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
        released = as_released((spec or {}).get("uses", ""), called)
        if released is not None:
            trigger = released.get("on") or released.get(True) or {}
            # NOT `declared` — that is the module-level function used two lines down, and
            # shadowing it here made this check crash on its own first run.
            released_inputs = set(((trigger.get("workflow_call") or {}).get("inputs")) or {})
            ref = (spec or {}).get("uses", "").split("@")[-1]
            for key in sorted(set((spec.get("with") or {})) - released_inputs):
                bad.append(f"{path}: job `{job}` passes `with: {key}`, which `{called}` does not "
                           f"declare AT `{ref}` — GitHub resolves this call against `{ref}`, not "
                           f"against this branch, so the input must land there first")
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
                text = fh.read()
            check_duplicate_keys(path, text, bad)
            check_cancellation(path, yaml.safe_load(text) or {}, bad)
            audit(path, yaml.safe_load(text) or {}, bad)

    for line in bad:
        print(f"::error::{line}")
    print(f"## caller_permissions_check\n\n{len(bad)} problem(s).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
