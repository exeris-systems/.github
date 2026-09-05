---
title: "exeris-systems/.github: the shared enforcement for the documentation standards"
type: reference
visibility: public
owning-repo: .github
status: active
last-verified: 2026-09-05
---

# exeris-systems/.github: the shared enforcement for the documentation standards

Guardrails for AI assistants working inside the organisation repository. The human-facing
description is in [`README.md`](README.md); this file states what an editing session must respect.

## Mission and scope

This repository holds the **enforcement**, never the rule. ADR-085 §C.11 gives it the organisation
default `CONTRIBUTING.md` and `PULL_REQUEST_TEMPLATE.md`, the reusable workflows (`docs-lint`,
`commit-lint`, `pr-body-check`, `javadoc-gate`), the Vale style package, the `markdownlint` and
`commitlint` configuration, and the validator scripts. The rules themselves live one repository
away, in
[`exeris-docs/standards/`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/README.md).

That split is the operating contract: **a gate here implements a rule stated there.** A check with
no standard behind it is a rule invented in CI, where nobody reviewed it and nobody can find it.

## Operating contract

**Every change here changes CI for every repository.** The workflows are called `@main` by each
repo's `.github/workflows/guardrails.yml`, so a merge to `main` is a deployment. There is no
staging. Run a checker locally against at least `exeris-docs` and one code repository before
proposing a change to it.

**Enforcement levels are a claim, and the claim is checkable.** A standard tags each rule `[L1: …]`
(CI, hard), `[L2]` (review) or `[L3]` (checklist). An `[L1]` marker naming a script, a workflow or a
config key asserts that the thing exists and fires. Two such markers have already been found inert —
`adr-conventions.md` rule 9 named a label nothing checked, and `docs-lint` was passed a path list
that omitted three of the five directories it was meant to cover. When you touch a rule, verify the
gate; when you touch a gate, verify the marker.

**What counts as documentation is defined once**, in
[`scripts/_common.py`](scripts/_common.py) — `SKIP_DIRS`, `SKIP_PATHS` and `LINK_SKIP_DIRS`. The
Python checkers import it. `vale/.vale.ini`, `lychee.toml` and `scripts/lint_globs.py` mirror it in
their own syntax and each says so. Change one and change all four, or the tools disagree silently.

**Do not weaken a gate to make a pull request pass.** A failing gate is either a real finding or a
defect in the gate. Both are worth fixing; suppressing the check is neither. `continue-on-error` and
`accept` lists are decisions with a comment explaining them — see the note on 429 in `lychee.toml`.

**Language.** English in every committed artefact.

## Layout

| Path | What it is |
|:--|:--|
| `.github/workflows/*.yml` | Reusable workflows (`workflow_call`), called by every repo |
| `.github/workflows/guardrails.yml` | This repository's own caller — it runs its gates on itself |
| `scripts/` | Validators: frontmatter, ADR registry, PR body, agent files; `_common.py` is shared |
| `vale/` | Exeris style plus the vendored Quarkus package (Apache-2.0, see `styles/Quarkus/NOTICE.md`) |
| `caller-example/guardrails.yml` | The file each repo copies — the whole per-repo footprint |
| `docs-guardrails-review.md`, `pr-review.patch.md` | The `[L2]` review routine and its router patch |

## When to stop and ask

- A change that would make an existing standard's `[L1]` marker false.
- A new check that no standard states — write the standard first, in `exeris-docs`.
- Anything touching `PRIVATE_REPOS` or the public/private link rules (ADR-020): a wrong entry either
  leaks a private path into a public page or blocks a legitimate one.
