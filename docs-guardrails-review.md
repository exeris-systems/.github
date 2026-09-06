---
title: Docs and Hygiene Review
type: reference
visibility: public
owning-repo: .github
status: active
last-verified: 2026-09-05
---

# Docs & Hygiene Review — Exeris Systems (L2 step, ADR-085 §J.33)

## Trigger
Every pull request in any Exeris repository, as **Step 1b of `pr-review.md`** — after the cross-repo impact check, before the repo-specific review. Runs on the substance the L1 gates cannot judge. Do not repeat what CI already reported; read the CI step summary first and reference it.

## Inputs
- The PR body (template per `pr-conventions.md`) and the squash-commit subject.
- The diff, restricted to: `docs/**`, `*.md`, `CLAUDE.md`, `.github/**`, `CHANGELOG.md`, `MIGRATION*.md`, `adr-index.md`, Java files whose diff touches `/** … */` blocks.
- The standards: `exeris-docs/standards/*.md`. Cite rule numbers in findings (`docs-style-guide.md rule 5`).

## Step 1 — PR body substance (pr-conventions.md)
1. Does *Motivation* name a constraint, failure or measurement? "Improve", "clean up", "align" without a cause → `[STYLE]`.
2. Does *Result* say what is **not** covered? Absent → `[STYLE]`.
3. Does the *Classification* block match the diff? A `docs-only` scope class with Java changes, `Wall impact: none` with a new cross-module import, `Compatibility impact: none` with a japicmp-reported change → `[HARD BLOCK]` (the classification is what routes review; a wrong one is worse than none).
4. Do the *Verification* commands prove the claim (tagged tests for kernel changes, `-Pparanoid` for off-heap, `javadoc:javadoc` for gated modules)? A default build cited for a hot-path change → `[STYLE]`, with the missing command named.
5. Numbers in the body without a report path and state → `[STYLE]` on dev PRs, `[HARD BLOCK]` on release-gate PRs and on any change to `whitepaper`, `high-level-architecture`, README (claims-and-evidence.md rule 1).

## Step 2 — Documentation changes (docs-style-guide.md)
6. Type discipline: is each changed page one Diátaxis/record type? A how-to that explains, an explanation with steps → `[STYLE]` with the split proposed.
7. Boundary and trade-off: does a new or rewritten page say where it does not apply and name one cost? Missing → `[STYLE]`.
8. `last-verified` bumped on a page whose text changed but whose subject code did not → ask; bumped without checking the code → `[STYLE]`. Not bumped on a page whose subject code changed in this PR → `[DOC DEBT]`.
9. Terminology: Vale warnings the author dismissed — spot-check three; a dismissed warning that is correct → `[STYLE]`.
10. Subsystem/module pages touched: do `## Contract / Hot path / Failure modes / Owning ADRs` exist or is the page on the backfill list? Missing and not listed → `[DOC DEBT]`.

## Step 3 — Records (adr-conventions.md)
11. New ADR: registry row exists on `main` (not only on the PR branch) → else `[HARD BLOCK]`. Filename regex, `slug`, `status` consistent between header table and frontmatter.
12. `Non-Goals` and `Risks and Assumptions` present and non-trivial ("Reversed by:" names evidence) → else `[STYLE]`.
13. Amended ADR: `## Amendments` entry dated, original text preserved, registry status `upd.` → else `[HARD BLOCK]` (silent rewrite of an accepted decision).
14. Cross-repo ADR: stubs present or listed as pending in the same PR → else `[CROSS-REPO]`.
15. Any relative link into a private repo from a public file → `[HARD BLOCK]` (ADR-020).

## Step 4 — Javadoc changes (javadoc-conventions.md)
16. First sentence states the contract, not the name → else `[STYLE]`.
17. SPI type touching buffers/memory/threads without the three contract lines → `[CONTRACT]`.
18. `@implSpec` used for caller guidance or `@apiNote` for implementer requirements (swapped) → `[STYLE]`.
19. `@throws` on a method that can raise an `ExerisKernelException` without the EX-code → `[CONTRACT]`.
20. `<pre>{@code` examples added → `[STYLE]` (use `{@snippet}`).

20a. Doc comment (Java or TS) narrates history — "previously", "used to be", "fixed in", PR/issue numbers, why an earlier design was wrong → `[STYLE]` with the CHANGELOG/ADR destination named; CI catches the precision-first list, this step catches the rest ("no longer", bare "used to" in a past-tense reading).

## Step 4-TS — TypeScript doc comments and goldens (tsdoc-conventions.md)
20b. Javadoc markup in a `.ts` doc comment (`<p>`, `{@code}`, `@author`, `{type}` in a tag, `@param name desc` without the hyphen) → `[STYLE]`.
20c. Export added to a published package without a release tag (`@public/@beta/@alpha/@internal`) → `[CONTRACT]`.
20d. `api/*.api.md` or `api/tools.api.json` changed: a `-` line (removed tool/export/`required` input) with *Compatibility impact* `none` → `[HARD BLOCK]`; an added line with `none` → `[STYLE]` (should say `additive`). Golden changed without the `api-surface` label → `[STYLE]`.
20e. Tool `description` string in `src/tools/**` changed → treat as 20d: it is the public documentation the model reads, and the golden diff must show it.
20f. Emitter header string changed, or a new emitter with its own header text instead of the shared helper → `[CATEGORY-B]`; a file under `src/app/generated/**` edited without a generator run in the same PR → `[CATEGORY-B]`.

## Step 5 — Commits and agent files
21. Subject over 100 characters or `feat/fix/perf/refactor` body without Motivation/Modification/Result — CI catches it; if CI was skipped (draft merged, bot), report as `[STYLE]`.
22. `CLAUDE.md` changed: does it restate a rule a standard or a CI gate already enforces → `[STYLE]` (link instead); does it weaken an ADR → `[HARD BLOCK]`.
23. New `copilot-instructions.md` / `.cursorrules` / `AGENTS.md` content beyond a pointer → `[DOC DEBT]`.

## Step 6 — Changelog and compatibility (changelog-conventions.md)
24. Release PR: `### Breaking` present and consistent with the japicmp report (Java) or the golden diff (TS); `accepted-api-changes.json` justified; `MIGRATION.md` section for non-empty Breaking → else `[HARD BLOCK]`.
25. Non-release PR with a `Compatibility impact: breaking (ADR-NNN)` line: is the ADR accepted and does `accepted-api-changes.json` gain the entry in this PR → else `[CONTRACT]`.

## Output format

```
DOCS & HYGIENE — <repo> — <PR title>

[HARD BLOCK] <file>:<line> — <standard> rule <n>: <finding> → <fix>
[CONTRACT]   …
[CROSS-REPO] …
[DOC DEBT]   <file> — <what is missing>; tracked as: <issue or backlog entry>
[STYLE]      …

CI already reported: <one line per L1 gate result — do not restate>
SUMMARY: <verdict — PASS | PASS with DOC DEBT | BLOCK>
```

`[DOC DEBT]` is a sibling of `[TCK DEBT]`: it never blocks a dev PR on its own, always names a concrete backlog item, and is counted and aged by the monthly `docs-guardrails-audit.md`. A PR is never approved with a `[HARD BLOCK]` finding.
