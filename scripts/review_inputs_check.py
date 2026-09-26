#!/usr/bin/env python3
"""What a review may read from the branch under review — ADR-087 §A.3, §C.14a.

A pull request must not write the rules it is judged by. The shared routine holds that by being
fetched from the organisation repository's default branch. A repository's own extension is an
ordinary file in the reviewed tree, so holding it needs a step: the routine reads the file at the
base commit and hands the reviewer that copy.

And the reverse case, where the checkout shows LESS than the branch: the runner restores the paths
it reads itself from the base branch whatever the pull request does to them, so a finding about
their content in the checkout describes the checkout rather than the change. The paths are named per
run, because a model given a list has a fact and a model given a rule has something to remember, and
the prompt sends it to the copy of what the pull request wrote, which the runner keeps under
`.claude-pr/`.

Both are one fact spread over two places -- a step that derives it and a prompt that spends it --
and either half alone reads as correct.

Usage: review_inputs_check.py [--root .]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import yaml

BASE_COPY = "repo-routine.base.md"
RESTORED = "restored-paths.txt"
SNAPSHOT = ".claude-pr/"
# `SENSITIVE_PATHS` in claude-code-action's `src/github/operations/restore-config.ts`: the paths the
# runner restores from the base branch before it starts, each from the root of the checkout and
# whole. The workflow names them in `RESTORED_BY_RUNNER`; this copy is what it is compared with.
RUNNER_RESTORES = (".claude", ".mcp.json", ".claude.json", ".gitmodules", ".ripgreprc",
                   "CLAUDE.md", "CLAUDE.local.md", ".husky")
RESTORE_STEP_ENV = "RESTORED_BY_RUNNER"
GENERATED = "generated-paths.txt"
GENERATED_SCRIPT = "generated_paths.py"
# ADR-087 §C.14a: the instruction files an agent reads that the runner does not restore for itself.
# The workflow names them in `RESTORED_BY_ORGANISATION` and puts each back to the base branch's
# content; this copy is what the list is compared with.
ORGANISATION_RESTORES = ("AGENTS.md", ".agents", "GEMINI.md", ".gemini", ".codex", ".cursor",
                         ".cursorrules", ".clinerules", ".windsurfrules",
                         ".github/copilot-instructions.md")
ORGANISATION_ENV = "RESTORED_BY_ORGANISATION"
ORGANISATION_SNAPSHOT = ".exeris-pr/"
RUNNER_ACTION = "anthropics/claude-code-action"
# The step that renders the prompt, by id. The prompt is hashed as rendered, so it is written once
# into a step rather than inline on the action; what a reviewer is handed therefore lives in a
# `run:` and no longer only in a `with:`. A rule that read one place would pass on a prompt that
# says nothing it requires.
PROMPT_STEP = "prompt"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    root = os.path.abspath(ap.parse_args().root)
    with open(os.path.join(root, ".github", "workflows", "docs-review.yml"), encoding="utf-8") as fh:
        routine = yaml.safe_load(fh)
    steps = (routine.get("jobs", {}).get("produce", {}).get("steps") or [])
    renders = [s for s in steps if str(s.get("id") or "") == PROMPT_STEP]
    # Line continuations joined first: a command split over two lines is one command, and a rule
    # that matches per line would accept a mention where it needs a write. The rendering step is
    # left out: its `run:` is the prompt, not a command the job performs on the checkout.
    shell = re.sub(r"\\\n\s*", " ",
                   "\n".join(str(s.get("run") or "") for s in steps if s not in renders))
    prompt = "\n".join([str((s.get("with") or {}).get("prompt") or "") for s in steps]
                       + [str(s.get("run") or "") for s in renders])
    bad: list[str] = []

    def rule(ok: bool, said: str) -> None:
        if not ok:
            bad.append(said)

    # THE EXTENSION IS NOT READ FROM THE BRANCH. Measured rather than assumed: a rule added on a
    # branch was cited by the verdict on that same branch, so the reviewer applied a rule the pull
    # request wrote. What the prompt names decides this, and the step is what makes the name exist.
    # The WRITE, not the mention. A rule satisfied by the name appearing anywhere passes while a
    # cleanup line is the only thing carrying it.
    rule(re.search(r"git show [^\n]*>\s*" + re.escape(BASE_COPY), shell) is not None,
         f"no step writes `{BASE_COPY}` from the base commit, so the repository extension the "
         f"reviewer reads is the branch's own copy and a pull request can be judged under rules "
         f"it wrote")
    rule(BASE_COPY in prompt,
         f"the prompt does not hand the reviewer `{BASE_COPY}`")
    rule("inputs.repo-routine != '' && 'repo-routine.base.md'" in " ".join(prompt.split())
         or f"'{BASE_COPY}'" in prompt,
         "the prompt still names `inputs.repo-routine` as the file to read, which is the path in "
         "the branch checkout rather than the copy taken at the base")

    # AND THE PATHS THE CHECKOUT CANNOT SHOW. Naming them is the cheap half; a reviewer told only
    # "some files may be stale" has nothing to act on.
    named = [str((s.get("env") or {}).get(RESTORE_STEP_ENV) or "") for s in steps]
    listed = next((n.split() for n in named if n), [])
    rule(sorted(listed) == sorted(RUNNER_RESTORES),
         f"`{RESTORE_STEP_ENV}` names {sorted(listed)}, and the runner restores "
         f"{sorted(RUNNER_RESTORES)} — a path it restores and the list omits is judged at base "
         f"content as though it were the change")
    rule(re.search(re.escape("$" + RESTORE_STEP_ENV) + r".*?>\s*" + re.escape(RESTORED), shell,
                   re.S) is not None,
         f"no step derives `{RESTORED}` from `{RESTORE_STEP_ENV}`")
    rule(RESTORED in prompt, f"the prompt does not name `{RESTORED}`")
    rule(SNAPSHOT in prompt,
         f"the prompt does not send the reviewer to `{SNAPSHOT}`, where the runner keeps what the "
         f"pull request wrote to a restored path")

    organisation_rules(steps, prompt, rule)

    # AND THE FILES NOBODY AUTHORED. A renderer's copy judged as written text reports its source's
    # wording once per copy, in a pull request that may not carry the source at all.
    rule(re.search(re.escape(GENERATED_SCRIPT) + r".*?>?\s*" + re.escape(GENERATED), shell, re.S)
         is not None,
         f"no step runs `{GENERATED_SCRIPT}` to write `{GENERATED}`")
    rule(GENERATED in prompt,
         f"the prompt does not name `{GENERATED}`, so a generated copy is judged as authored text")

    for said in bad:
        print(f"::error::review_inputs_check: {said}")
    if bad:
        return 1
    print("review_inputs_check: the extension comes from the base, and the paths the checkout "
          "cannot show are named")
    return 0


def organisation_rules(steps: list, prompt: str, rule) -> None:
    """§C.14a: the instructions an agent reads are put back to the base before the runner starts."""
    found = [i for i, s in enumerate(steps) if ORGANISATION_ENV in (s.get("env") or {})]
    rule(len(found) == 1, f"no single step names `{ORGANISATION_ENV}`, so `AGENTS.md` and "
                          f"`.agents/**` are read as the pull request wrote them")
    if len(found) != 1:
        return
    step = steps[found[0]]
    listed = str(step["env"][ORGANISATION_ENV]).split()
    rule(sorted(listed) == sorted(ORGANISATION_RESTORES),
         f"`{ORGANISATION_ENV}` names {sorted(listed)}, and §C.14a restores "
         f"{sorted(ORGANISATION_RESTORES)}")
    run = re.sub(r"\\\n\s*", " ", str(step.get("run") or ""))
    rule('git checkout -q "$base" --' in run,
         "the step does not put the instruction files back to the base branch's content")
    rule(re.search(r">>\s*" + re.escape(RESTORED), run) is not None,
         f"the step does not add the paths it restored to `{RESTORED}`")
    rule(ORGANISATION_SNAPSHOT in run,
         f"the step keeps no copy of what the pull request wrote under `{ORGANISATION_SNAPSHOT}`")
    runner = [i for i, s in enumerate(steps) if str(s.get("uses") or "").startswith(RUNNER_ACTION)]
    rule(bool(runner) and found[0] < min(runner),
         "the instruction files are restored after the runner has started, or no runner step "
         "was found to order them before")
    rule(ORGANISATION_SNAPSHOT in prompt,
         f"the prompt does not send the reviewer to `{ORGANISATION_SNAPSHOT}`, where the "
         f"pull request's own instruction files are kept")


if __name__ == "__main__":
    sys.exit(main())
