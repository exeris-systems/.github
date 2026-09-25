#!/usr/bin/env python3
"""Cases for `review_surface.py` — the produce job exports what it hashed, ADR-087 §C.14.

A run record states which instructions the repository put in front of the model, as one hash over
three components: the prompt as passed, the review routine at the checked-out `.github` commit, and
the caller's agent file. Nothing in a run's own event stream carries the prompt, so either the job
that renders it also exports the hash, or the hash is reconstructed afterwards from what the host
still holds. The reconstruction is a fence with a stated verification, and this export is the other
half of that verification: the two producers must land on the same digest over the same text, or
the fence comes down.

That is why the golden case below is pinned to a constant computed in the other producer rather
than to one computed here. A suite that recomputed the hash the way the code computes it would
agree with the code and with nothing else; this one agrees, or fails, with `exeris-ai-execution`.

WHAT THIS SUITE ASSUMES OF THE IMPLEMENTATION, stated here because it is written beside it rather
than after it:

  * `scripts/review_surface.py` is a command line taking file paths and strings:
    `--prompt`, `--routine`, `--agents-md`, `--settings`, `--manifest` (paths, each of which may
    name a file that does not exist), `--allowed-tools` (the allow-list as `ALLOWED_TOOLS` spells
    it, the option absent where the launch passed none), `--routine-sha`, `--checkout-sha`,
    `--head-sha`, `--review-started-at` (strings), and `--print`.
  * It writes `key=value` lines to the file `GITHUB_OUTPUT` names, and with `--print` writes the
    same pairs to stdout, where no `GITHUB_OUTPUT` need be set.
  * It is importable, and `EXPORTED` is the module-level tuple naming the ten exports in the order
    they are written. The last case reads that tuple rather than restating it, because a list
    restated in a suite is a fourth copy of the thing the case exists to hold to three.
  * It carries its own copy of the canonicalisations, so nothing but this suite holds it to the
    other producer's. Two copies of one canonicalisation agree until one of them is edited, and
    the constants below are where that edit is caught.

Usage: review_surface_suite.py
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(HERE, "review_surface.py")
sys.path.insert(0, HERE)
import review_surface                                                            # noqa: E402

# The step whose outputs the produce job's own outputs are built from, and the prefix the
# publishing half takes them under. Both are written once here for the same reason `EXPORTED` is
# written once in the script: a name spelt twice is a name that can differ.
SURFACE_STEP = "surface"
CAPTURE_PREFIX = "capture-"

CASES: list[tuple[str, object]] = []


def case(name: str):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


# ---------------------------------------------------------------------------------------------
# The fixture, copied from the producer suite of `exeris-ai-execution` so that the two agree on
# bytes rather than on a description of them. Every string here is a file that suite writes and
# every constant is one it pins; nothing below is derived.

ALLOWED_TOOLS = ("Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*),"
                 "Bash(git status:*)")

# The prompt as the action was handed it: the template's block scalar, dedented, with its five
# expressions substituted and exactly one trailing newline.
GOLDEN_PROMPT = (
    "Review pull request 7 in\n"
    "exeris-systems/exeris-ai-execution against the routine in\n"
    "`.guardrails/docs-guardrails-review.md`.\n"
    "\n"
    "L1 GATE RESULTS, already in the shape `checks_run` takes:\n"
    "\n"
    '[{"check":"docs-lint","result":"pass"},{"check":"commit-lint","result":"pass"},'
    '{"check":"pr-body-check","result":"fail"}]\n'
    "\n"
    "REPOSITORY EXTENSION: docs/repo-review-rules.md\n"
    "REPOSITORY CHECK OUTPUT: repo-checks.out\n"
)

ROUTINE = (
    "---\n"
    'title: "Documentation and hygiene review routine (fixture excerpt)"\n'
    "type: reference\n"
    "---\n"
    "\n"
    "# Docs and hygiene review\n"
    "\n"
    "Step 1. x\n"
    "\n"
    "Step 5. x\n"
    "\n"
    "## Verdict\n"
    "\n"
    "x\n"
)

AGENTS_MD = "# AGENTS.md (fixture excerpt)\n\nx\n"

SETTINGS = (
    "{\n"
    '  "permissions": {\n'
    '    "allow": [\n'
    '      "Read(//home/runner/work/**)"\n'
    "    ],\n"
    '    "deny": [\n'
    '      "Bash(rm:*)"\n'
    "    ]\n"
    "  }\n"
    "}\n"
)

MANIFEST = (
    "version: 2\n"
    "repository: exeris-ai-execution\n"
    "\n"
    "imports:\n"
    "  - bundle: exeris-agents\n"
    "    version: 2.1.0\n"
    "    ref: 0000000000000000000000000000000000000000\n"
    "    sha256: sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
)
BUNDLE_VERSION = "2.1.0"

# SHA-256 over the three components in §C.14's order — the prompt, the routine, the agent file —
# each stripped of one trailing newline and given exactly one. Pinned by the producer suite of
# `exeris-ai-execution`; a change to either producer's canonicalisation moves it, and moving it is
# what `instrument.fence` exists to mark.
SYSTEM_PROMPT_SHA256 = "318bdb6a65f08253784342a025fba7c27b399cb106f4d5eb1b454c92a981fc3d"

# The same hash with the third component empty. A repository with no agent file contributes exactly
# one newline, not a skipped concatenation, so it still has a hash and it is not the hash of a
# repository whose agent file is an empty file. Also pinned by that suite.
SYSTEM_PROMPT_SHA256_NO_AGENTS = "961b9a5268a6d3c2f7909f473d53112e5fe79260fd52cd4e0c8908e2318dfcf9"

# Tool-surface canonicalisation v1 (ADR-086 §C.14a) over the allow-list above, split at bracket
# depth zero, stripped, deduplicated and sorted, together with the permission rules the fixture's
# `.claude/settings.json` declares. Pinned by the producer suite of `exeris-ai-execution`.
TOOL_SURFACE = "fdb5246cbad76771a888b04504b84ddb75b41e90430b020f3b56b63fe5aa2652"

# The same canonicalisation with the allow-list recorded as `null`. A launch that passes no
# allow-list is a run whose powers are known and unrestricted: a state written into the hashed
# text, never an absent field, because no digest would have meant "unrestricted".
TOOL_SURFACE_NO_ALLOW = "f72eeff2f44753af758e66f6d93a2cee3f52ea4af4e4b6906f8fc719726b11b6"

# The commits and the clock reading the job hands over rather than derives. Their shapes are the
# export's business; their values are not.
ROUTINE_SHA = "e5f60718" * 5
CHECKOUT_SHA = "b2c3d4e5" * 5
HEAD_SHA = "a1b2c3d4" * 5
STARTED_AT = "2026-09-17T09:15:42Z"

# A word no derivation could produce, carried by one case's prompt. The export is hashes and
# commits; a job output is readable by anyone who can read the run, so the prompt's own text
# leaking into one is the export saying more than it was asked for.
SENTINEL = "jacaranda-7741"


# ---------------------------------------------------------------------------------------------
# What a job output may be. The keys are the ten the produce job declares, each with the one shape
# its value can take — a stronger statement than "one of the four shapes", and the same statement
# where it matters: nothing here is prose, a path, or a name.

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

KEYS = {
    "prompt-sha256": HEX64,
    "routine-sha256": HEX64,
    "routine-sha": SHA40,
    "agents-md-sha256": HEX64,
    "system-prompt-sha256": HEX64,
    "tool-surface": HEX64,
    "bundle-version": SEMVER,
    "checkout-sha": SHA40,
    "head-sha": SHA40,
    "review-started-at": RFC3339,
}

# A job output line is at most this long. The limit is not a formatting preference: it is the width
# at which anything that is not a digest, a commit, a version or a timestamp stops fitting.
LINE_LIMIT = 128

PAIR = re.compile(r"^([a-z0-9][a-z0-9-]*)=(.*)$")


def component(text: str) -> str:
    """One component's hash: the text with one trailing newline stripped and exactly one added.

    Written from §C.14's sentence rather than taken from the producer, because the empty component
    is the state where the two spellings part company and the case below is about exactly that.
    """
    body = (text[:-1] if text.endswith("\n") else text) + "\n"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build(root: str, *, prompt: str | None = GOLDEN_PROMPT, routine: str | None = ROUTINE,
          agents_md: str | None = AGENTS_MD, settings: str | None = SETTINGS,
          manifest: str | None = MANIFEST) -> None:
    """The checkout the produce job hashes. `None` is a file the repository does not carry."""
    files = {
        "prompt.txt": prompt,
        "docs-guardrails-review.md": routine,
        "AGENTS.md": agents_md,
        os.path.join(".claude", "settings.json"): settings,
        os.path.join(".agents", "manifest.yaml"): manifest,
    }
    for name, text in files.items():
        if text is None:
            continue
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


class Result:
    def __init__(self, code: int, stdout: str, stderr: str, text: str):
        self.code, self.stdout, self.stderr, self.text = code, stdout, stderr, text

    @property
    def output(self) -> str:
        return self.stdout + self.stderr

    def values(self, *, strict: bool) -> dict:
        """The pairs the export wrote. `strict` where every line has to be one."""
        found = {}
        for line in self.text.splitlines():
            if not line.strip():
                continue
            pair = PAIR.match(line)
            if pair:
                found[pair.group(1)] = pair.group(2)
            elif strict:
                raise AssertionError(f"not a key=value line: {line!r}")
        return found


def run(root: str, *, allowed_tools: str | None = ALLOWED_TOOLS, printed: bool = False) -> Result:
    """Run the export over one checkout and return what it wrote."""
    out_path = os.path.join(root, "github-output.txt")
    argv = [sys.executable, SCRIPT,
            "--prompt", os.path.join(root, "prompt.txt"),
            "--routine", os.path.join(root, "docs-guardrails-review.md"),
            "--routine-sha", ROUTINE_SHA,
            "--agents-md", os.path.join(root, "AGENTS.md"),
            "--settings", os.path.join(root, ".claude", "settings.json"),
            "--manifest", os.path.join(root, ".agents", "manifest.yaml"),
            "--checkout-sha", CHECKOUT_SHA,
            "--head-sha", HEAD_SHA,
            "--review-started-at", STARTED_AT]
    if allowed_tools is not None:
        argv += ["--allowed-tools", allowed_tools]
    if printed:
        argv.append("--print")

    env = dict(os.environ)
    env.pop("GITHUB_OUTPUT", None)
    if not printed:
        env["GITHUB_OUTPUT"] = out_path

    proc = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=root)
    if printed:
        text = proc.stdout
    elif os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = ""
    return Result(proc.returncode, proc.stdout, proc.stderr, text)


# ---------------------------------------------------------------------------------------------
# 1 — the golden. One prompt, one routine, one agent file, and the digest the other producer pins.


@case("the same three components hash to the digest the deriver pins")
def _(root):
    build(root)
    got = run(root)
    assert got.code == 0, got.output
    values = got.values(strict=True)
    assert values["system-prompt-sha256"] == SYSTEM_PROMPT_SHA256, values
    # Component by component, which is what makes a disagreement locatable rather than only
    # visible: the reconstruction and the live export are compared per component, so each
    # component's digest is over the normalised text and not over the file as it sat on disk.
    assert values["prompt-sha256"] == component(GOLDEN_PROMPT), values
    assert values["routine-sha256"] == component(ROUTINE), values
    assert values["agents-md-sha256"] == component(AGENTS_MD), values


# 2 — the tool surface: what the run was permitted, from the launch and from the checkout.


@case("the allow-list and the checkout's permissions hash to the surface the deriver pins")
def _(root):
    build(root)
    got = run(root)
    assert got.code == 0, got.output
    surface = got.values(strict=True)["tool-surface"]
    assert surface == TOOL_SURFACE, surface


# 3 — no agent file. The empty component is a written state, so a repository carrying none still
# exports a digest, and it is the digest of one newline rather than of nothing.


@case("an absent agent file is the empty component, not a missing one")
def _(root):
    build(root, agents_md=None)
    got = run(root)
    assert got.code == 0, got.output
    values = got.values(strict=True)
    assert values["agents-md-sha256"] == component(""), values
    want = hashlib.sha256(
        (GOLDEN_PROMPT.rstrip("\n") + "\n" + ROUTINE.rstrip("\n") + "\n" + "\n").encode("utf-8")
    ).hexdigest()
    assert values["system-prompt-sha256"] == want, values
    assert want == SYSTEM_PROMPT_SHA256_NO_AGENTS, want
    assert values["system-prompt-sha256"] != SYSTEM_PROMPT_SHA256, values


# 4 — no allow-list. A launch that passes none is not a launch permitted nothing, and neither is
# the same surface as one that names seven tools.


@case("no allow-list is a recorded state and a different surface")
def _(root):
    build(root)
    got = run(root, allowed_tools=None)
    assert got.code == 0, got.output
    surface = got.values(strict=True)["tool-surface"]
    assert surface == TOOL_SURFACE_NO_ALLOW, surface
    assert surface != TOOL_SURFACE, surface


# 5 — what reaches the job output. Ten keys, each a digest, a commit, a version or a clock reading;
# a job output crosses into the publishing half and is readable by anyone who can read the run.


@case("the export is ten keys, and every value is a digest, a commit, a version or a timestamp")
def _(root):
    leaky = GOLDEN_PROMPT + f"INTERNAL NOTE: sentinel-{SENTINEL}\n"
    build(root, prompt=leaky)
    got = run(root)
    assert got.code == 0, got.output

    values = got.values(strict=True)
    assert set(values) == set(KEYS), sorted(set(values) ^ set(KEYS))
    for key, shape in KEYS.items():
        assert shape.match(values[key]), f"{key}={values[key]!r}"

    # Shape is not identity: three of these are forty hex characters and a transposed pair would
    # satisfy every pattern above while naming the wrong tree. What was handed over comes back as
    # handed over, and the version is the one the manifest pins rather than any well-formed one.
    assert values["routine-sha"] == ROUTINE_SHA, values
    assert values["checkout-sha"] == CHECKOUT_SHA, values
    assert values["head-sha"] == HEAD_SHA, values
    assert values["review-started-at"] == STARTED_AT, values
    assert values["bundle-version"] == BUNDLE_VERSION, values

    for line in got.text.splitlines():
        assert len(line) <= LINE_LIMIT, f"{len(line)} characters: {line[:60]!r}…"

    # Not one word of the text that was hashed. The sentinel is the word nothing but the prompt
    # could have put there; the routine's own filename is the word a well-meaning label would.
    assert SENTINEL not in got.text, got.text
    assert "docs-guardrails-review" not in got.text, got.text
    assert "Review pull request" not in got.text, got.text


# 6 — the same ten pairs without a job to write them into, which is how anyone reproduces the
# export by hand against a run that already happened.


@case("--print says the same thing to stdout as the job output holds")
def _(root):
    build(root)
    from_file = run(root).values(strict=True)
    printed = run(root, printed=True)
    assert printed.code == 0, printed.output
    assert printed.values(strict=False) == from_file, (printed.text, from_file)


# 7 — the same list in the four places that spell it. `EXPORTED` is the script's; the produce leg's
# identity step reads each from the surface step and writes it into the artefact the capture job
# reads per part; the capture job's run step reads each back out; and `publish-verdict.yml`'s
# `capture-*` inputs are the one-run path a producer without parts still hands over. Nothing in
# GitHub compares them: a key renamed or added in one resolves to the empty string in silence —
# and an empty value is how this export says "this component was not measured". A component that
# WAS measured, reported as one that was not, is the single confusion the design exists to avoid.


@case("the script, the leg's identity, the capture and the one-run inputs name one list")
def _(_root):
    def workflow(name: str) -> dict:
        with open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    produce = (workflow("docs-review.yml").get("jobs") or {}).get("produce") or {}
    steps = produce.get("steps") or []
    assert any(str(step.get("id") or "") == SURFACE_STEP for step in steps), \
        f"the produce job carries no step with `id: {SURFACE_STEP}`, so every value below is empty"

    identity = next((st for st in steps if st.get("id") == "identity"), None)
    assert identity, "the produce job carries no `identity` step, so no leg leaves its surface"
    env = " ".join(str(v) for v in (identity.get("env") or {}).values())
    run = str(identity.get("run") or "")
    for key in review_surface.EXPORTED:
        want = "steps.%s.outputs.%s" % (SURFACE_STEP, key)
        assert want in env, f"the identity step does not read `{want}`"
        assert f'"{key}"' in run, f"the identity step writes no `{key}` into the artefact"

    publish = workflow("publish-verdict.yml")
    capture = ((publish.get("jobs") or {}).get("capture") or {}).get("steps") or []
    reader = next((st for st in capture if st.get("id") == "run"), None)
    assert reader, "the capture job carries no `run` step, so no part's surface is read"
    text = str(reader.get("run") or "")
    unread = [key for key in review_surface.EXPORTED if key not in text]
    assert not unread, f"the capture job reads no {unread} out of a part's surface"

    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1), so both spellings are looked
    # up — the same accommodation every other reader of these files makes.
    trigger = publish.get("on") or publish.get(True) or {}
    inputs = ((trigger.get("workflow_call") or {}).get("inputs")) or {}
    missing = [CAPTURE_PREFIX + key for key in review_surface.EXPORTED
               if CAPTURE_PREFIX + key not in inputs]
    assert not missing, f"`publish-verdict.yml` declares no input for {missing}"
    # Optional, every one of them, which is a compatibility statement rather than a preference: a
    # caller tracks that file at its default branch and passes inputs by name, so a required input
    # there stops the caller's whole workflow parsing before any gate in it runs.
    demanded = sorted(CAPTURE_PREFIX + key for key in review_surface.EXPORTED
                      if (inputs.get(CAPTURE_PREFIX + key) or {}).get("required"))
    assert not demanded, f"{demanded} are required inputs, which a pinned caller cannot satisfy"


def main() -> int:
    failures = 0
    for name, fn in CASES:
        with tempfile.TemporaryDirectory() as root:
            try:
                fn(root)
            except AssertionError as exc:
                failures += 1
                print(f"::error title=review_surface_suite::{name}: {exc}")
            except Exception as exc:  # a case that cannot run is a case that did not pass
                failures += 1
                print(f"::error title=review_surface_suite::{name}: "
                      f"{type(exc).__name__}: {exc}")
    print(f"review_surface_suite: ran {len(CASES)} cases, {failures} failures")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## review_surface_suite\n\nRan **{len(CASES)}** cases — "
                     f"**{failures} failures**.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
