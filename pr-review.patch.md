# Patch for `pr-review.md` (Project routine) — ADR-085 §J.33

> **2026-09-05.** Edit 1 below is now also implemented in CI, as
> `.github/workflows/docs-review.yml` in this repository. §J.33 placed the step inside `pr-review.md`,
> a Project document outside git, which meant the L2 layer ran only in Cowork sessions and never on a
> pull request. The workflow is the enforcement; this patch remains the Project-side half, so a review
> conducted in a session applies the same routine. Both read the same
> [`docs-guardrails-review.md`](docs-guardrails-review.md).

Apply two edits:

## 1. New Step 1b (insert after "Step 1 — Cross-repo impact check")

```
## Step 1b — Docs & hygiene review (ALL PRs)

Apply **docs-guardrails-review.md**. Read the CI step summary first (docs-lint, commit-lint, pr-body-check,
javadoc-gate) and do not restate what it reported; review the substance those gates cannot judge: PR body vs
diff, doc type discipline, boundary and trade-off, record integrity, Javadoc contract prose, changelog consistency.
```

## 2. Severity framework — add one line after `[TCK DEBT]`

```
**[DOC DEBT]**  — Missing or stale documentation, frontmatter, contract lines, changelog entry (track, never a block on its own; counted monthly)
```

Also add to `routine-schedule.md`:

| Routine | File | Scope |
|:--|:--|:--|
| Docs guardrails audit (monthly, first Monday) | `docs-guardrails-audit.md` | all repos — re-run `standards/_inventory/inventory.py`, diff against the previous run, report `[DOC DEBT]` count and age, list Vale error-level hits on `whitepaper` / `high-level-architecture` / README |
