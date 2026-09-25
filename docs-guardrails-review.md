---
title: Docs and Hygiene Review
type: reference
visibility: public
owning-repo: .github
status: active
last-verified: 2026-09-17
---

# Docs & Hygiene Review — Exeris Systems (L2 step, ADR-085 §J.33)

## Trigger
Every pull request in any Exeris repository, as **Step 1b of `pr-review.md`** — after the cross-repo impact check, before the repo-specific review. Runs on the substance the L1 gates cannot judge. Do not repeat what CI already reported; read the CI step summary first and reference it.

**One exception, and it is not a policy: a pull request that modifies THE WORKFLOW FILE THIS RUN ENTERED THROUGH is never reviewed by this routine.** The runner action refuses to start on one — *"the workflow file must exist and have identical content to the version on the repository's default branch"* — which is its own supply-chain guard and nothing a caller can configure away. A **reusable** workflow the run calls is not that file: a pull request changing one is reviewed like any other, and this routine has nothing to say against it.

This read "any file under `.github/workflows/`" until 2026-09-17, when the path filter that had always skipped the model first was lifted and the guard could finally be asked. Two runs, two shapes, both explained by the entry file and neither by the broader claim: `exeris-ai-execution#4` changes its own `guardrails.yml`, the file its run enters through, and the model step lasted five seconds and produced no verdict; `exeris-systems/.github#56` changes `docs-review.yml`, which that repository calls but does not enter through, and the model step ran six and a half minutes and produced a full verdict. The broader claim had never been tested because nothing had ever reached the guard. How loudly it fails depends on the caller. Where publication is off — `publish` defaults to `false`, which is every repository but this one — the job still reports success, so the absence of a review looks exactly like a clean one and the only tell is a model step that lasted four seconds. Where it is on, the publish step finds no verdict and the required check goes red with a comment saying so, which is the fail-closed path working: the review is still missing, but nobody mistakes it for a passing one. A change to CI reaches `main` carrying its L1 gates and nothing from this layer either way. Where that bites is a caller repository editing its own `guardrails.yml`; in `exeris-systems/.github` most pull requests change reusable workflows rather than the entry one, and those are reviewed. A person closes it by reviewing the change themselves and applying `human-reviewed`: the publication records who looked and at which commit, takes the label off, and greens the check on the strength of that record. The record is scoped and it ages — it counts only for the commit it names, so the next push leaves it behind and the check is red again.

**`human-reviewed` outranks this routine's verdict, and it does so everywhere, not only here.** The routine is an instrument; a person reading the diff is not, and a layer whose verdict outranks the person it reports to has stopped being a review. It used to decide nothing outside this exception, which had that backwards.

One condition, and it is not a limit on the person. Where a **BLOCKED** verdict stands against the same commit, the label greens it only once that person has said something on the pull request *after* the block — not approval, which the label already is, but an account: what the block got wrong, or what was done about it. A label event carries no text, so the text is a comment, and *after* is what makes it an answer rather than something written before there was anything to answer. The record quotes it. That a block is overridable at all is the cost, stated rather than hidden; what keeps it from being a bypass is that the record names the person, names the commit, quotes their account, and the next push leaves it behind.

**A pull request does not write the rules it is judged by, and is not judged on files it cannot show.** This routine is fetched from the organisation repository's default branch, so a change to it takes effect on the next review rather than its own. A repository's own extension is read at the pull request's base commit for the same reason: an extension is an ordinary file in the reviewed tree, and a rule added on a branch was measured being cited by the verdict on that branch — the direction that matters is the reverse, where a rule removed on a branch stops applying to it. The cost is the one the routine already pays: a pull request that changes the rules is reviewed under the old ones.

The reverse case is the checkout showing less than the branch. `.claude/agents/**` arrives at its base content whatever the pull request does to it, so its content is not the change and a finding about it describes the checkout. The paths are handed over per run in `restored-paths.txt` rather than left as a rule to remember, because a bundle bump — the one change touching both a vendor tree and the profiles that name it — otherwise earns a blocking finding true of nothing.

**A pull request opened by a bot is not reviewed, and it is not green either.** Those were one word, `draft-or-bot`, and one answer. Only the draft half earns it: GitHub refuses to merge a draft whatever this check says, so the colour decides nothing. A pull request an App opened *can* be merged, so greening it is a merge gate reporting a pass on a change nothing read — and ADR-087 §B.8 never granted that, naming a passing verdict and the path-filter skip and calling every other state red. The colour now comes from the standing verdict, which for a first pull request is red because none exists. Not spending a model on a dependency bump is a decision about cost and it stands; claiming a pass for one was never part of it.

**Both labels are checked for who applied them, and the check is GitHub's own field.** `needs-review` starts a review and `human-reviewed` tells the required check a person made one; both are ordinary labels, so every App installed on the organisation holds `pull-requests: write` and can apply either. Applying them *is* the capability, and a routine able to grant itself that capability is not a gate. The publication therefore reads `sender.type` from the event: a `Bot` applying `human-reviewed` records no review, has the label taken off, and gets a refusal written in its place naming it — the colour stays whatever the standing verdict already said, because a bot touching a label is not evidence about the change in either direction. A `Bot` triggering the readiness path does not start a review at all. What this cannot see is a **machine user** — an ordinary account a script holds a token for reports `User` exactly like a person, and telling those apart needs a list of people this does not have. The door it closes is the one an App walks through, which is the one that is open.

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
14a. A performance, footprint, throughput or cost figure inside an ADR or a `standards/` page → `[HARD BLOCK]` (`claims-and-evidence.md` rule 6, ADR-085 §G.26a). The figure is usually a real measurement; the page is the fault, so the fix is to cite the report rather than to defend the number. Two things are not this and are not findings: a threshold in a `Reversed by:` clause, which states what evidence would overturn the decision rather than a property of the system, and a figure in an RFC or a Research document, which is what those are for. Read before this rule existed, ADR-088 carried five such figures past four review rounds — each one caught under some other rule, one per round, because none of them was wrong about sourcing.
15. Any relative link into a private repo from a public file → `[HARD BLOCK]` (ADR-020).

## Step 4 — Javadoc changes (javadoc-conventions.md)
16. First sentence states the contract, not the name → else `[STYLE]`.
17. SPI type touching buffers/memory/threads without the three contract lines → `[CONTRACT]`.
18. `@implSpec` used for caller guidance or `@apiNote` for implementer requirements (swapped) → `[STYLE]`.
19. `@throws` on a method that can raise an `ExerisKernelException` without the EX-code → `[CONTRACT]`.
20. `<pre>{@code` examples added → `[STYLE]` (use `{@snippet}`).

20a. **A comment narrates history — in any language, and not only a doc comment.** "previously returned", "used to be", "fixed in 0.8.1", PR/issue numbers, why an earlier design was wrong → `[STYLE]` with the CHANGELOG/ADR destination named. Three gates catch the anchored list, all reading the same `comment-history.json`: Checkstyle over Java, ESLint over TypeScript, `comment_history_check.py` over Python, YAML and shell. This step catches what no token list can — "no longer" and a bare "used to" in a past-tense reading, and the comment that is true today yet exists only to explain a diff. `comment-conventions.md` is the rule; a comment that needs a story is a missing ADR link.

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

## Repository extension
A calling repository may add to this routine. It may not subtract from it. Two optional inputs carry the extension, and a repository that passes neither gets this routine and nothing else.

- **`repo-routine`** names a file in the calling repository, handed to you as `REPOSITORY EXTENSION`. Read it and the policies it names, and apply it **after** the steps above. It may add checks, raise a severity this routine assigns, or forbid something this routine permits. It may **not** lower a severity, skip a step, or change the output format, the severity tags or the verdict schema below. Those belong to this file: a review whose shape varies by repository is one no shared check can be gated on, and the point of the extension is to stop repositories keeping a whole review workflow of their own to get their rules applied.
- **`repo-checks`** is a command CI runs in the checked-out repository before you, its combined output and exit code left in the file named as `REPOSITORY CHECK OUTPUT`. **You do not run it.** This runner's harness denies `Bash`, and a routine that asks for what the harness refuses produces a review reporting its own checks as `not-run` — measured, and the reason the command moved into CI. Read the file, judge what it found, and list each script in `checks_run` with what it reported. A non-zero exit is evidence, not a verdict: most repo-local scripts locate candidates rather than decide, so report what was found and let the finding carry the severity, rather than failing the review on an exit code.

Where the extension and this routine disagree about severity, the higher one stands.

## Output format

```
DOCS & HYGIENE — <repo> — <PR title>

[HARD BLOCK] <file>:<line> — <standard> rule <n>: <finding> → <fix>
[CONTRACT]   …
[CROSS-REPO] …
[DOC DEBT]   <file> — <what is missing>; tracked as: <issue or backlog entry>
[STYLE]      …

CI already reported: <one line per L1 gate result — do not restate>
SUMMARY: <verdict — PASS | CONDITIONAL | BLOCKED>
```

`[DOC DEBT]` is a sibling of `[TCK DEBT]`: it never blocks a dev PR on its own, always names a concrete backlog item, and is counted and aged by the monthly `docs-guardrails-audit.md`. A PR is never approved with a `[HARD BLOCK]` finding.

## Verdict

The review also emits one JSON object valid against the composed verdict schema this repository ships, [`.agents/schemas/verdict.schema.json`](.agents/schemas/verdict.schema.json). `docs-review.yml` checks this repository out into `.guardrails/`, so at run time inside a caller that file is `.guardrails/.agents/schemas/verdict.schema.json`; only when `.github` reviews itself is it the path the link names. Read it from the checkout of *this* repository either way — a caller's own `.agents/schemas/verdict.schema.json` is that repository's schema, narrowed to that repository's roles, and is a different contract that does not know this routine's role or its `tag`.

Write the object to `verdict.json` in the root of the checkout under review, and repeat it as a fenced `json` block at the end of the review you write. The file is what the publication step reads, and the block is a fallback (ADR-087 §B.10). Both are consumed today: the split of Engineering Protocol 2 has landed, and a third source sits between them — the runner's own execution log, which is where the verdict actually arrives from, because this runner's harness denies the `Write` call the file needs and the comment needs a write scope the produce job does not hold. Write the object anyway: a runner that can write a file is the case §B.10 prefers, and the log is the one that works now.

`SUMMARY` above is `decision`, and the three words are the same three words, so nothing maps. `PASS with DOC DEBT` was never a third state: a `[DOC DEBT]` finding does not block on its own, so that run is `PASS` with a finding tagged `DOC DEBT`, and the label the publication step applies carries the rest. `CONDITIONAL` is for findings that have to be addressed before the merge and do not, on their own, refuse it.

The bracketed severity in front of each line above is that finding's `tag`, one per finding: a run reporting a `[HARD BLOCK]` and a `[DOC DEBT]` writes two findings carrying two tags, not one severity for the verdict. `agent` is `exeris-org-docs-reviewer`, the role that runs this routine rather than this file. `checks_run` names every L1 gate this routine was to read, the ones that had not reported included. Three of them are **mandatory** — `docs-lint`, `commit-lint` and `pr-body-check` — and a verdict that reports any of the three as `not-run` leaves the required check red whatever its `decision` says: a review resting on a gate nobody performed has not been performed either (ADR-087 §B.8). `javadoc-gate` and `tsdoc-gate` are not in that set, because a repository without a gated module runs neither, and a caller whose own gates must also be mandatory names them in `docs-review.yml`'s `mandatory-gates` input.

Two things the publication step deliberately does not do with `checks_run`, written here because they are decisions rather than omissions. A gate reported `fail` does not by itself make the required check red: §B.8 names the absent and the unrun, and a gate that ran and failed is already red in its own right, on the same pull request, where its author will look. But a `PASS` resting on one is a review disagreeing with a gate without saying so, and that is a `[CONTRACT]` finding for a human, not a state this step infers. And the labels the step compares against are the pull request's as of the moment the job was triggered, not the moment it writes: with `always()` and a queued concurrency group those can be minutes apart, so a label a human added in between is not seen, and none is removed that the map does not own. A finding in the prose and not in `findings`, or the reverse, is two reviews rather than one.
