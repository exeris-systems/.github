---
title: "Review rules for exeris-systems/.github"
type: reference
visibility: public
owning-repo: .github
status: active
last-verified: 2026-09-17
---

# Review rules for `exeris-systems/.github`

The `repo-routine` extension of [`docs-guardrails-review.md`](docs-guardrails-review.md), applied
**after** its steps and under its severity tags, output format and verdict schema. It adds checks and
raises severities; it lowers nothing and skips nothing. One review, one verdict, one publisher.

## What this repository is answerable for

Every gate every other repository runs. Its substance is not prose: it is Python that decides
required checks, YAML that decides what runs, JSON and YAML that decide what a verdict means, and a
routine file that decides what a reviewer looks for. The shared routine judges this repository's pull
request bodies and its Markdown. Without these rules nobody judges the part that can turn a gate off
everywhere at once — and a change here reaches every repository the moment it is merged, without any
of them opening a pull request.

## Step R — rules of this repository

R1. **A required check may not go green without a stated reason.** Any change that lets
    `publish_verdict.py` conclude `green` on a path where no verdict was read → `[HARD BLOCK]`
    unless the pull request names the §B.8 clause that permits it. Green is stated, never inferred,
    and this is the file where a green that nobody stated is written. Measured 2026-09-17: a pull
    request changing only `scripts/*.py` took `docs-review / publish / verdict` to **pass** with no
    review and no comment — the deterministic path filter answered "nothing to read" and the check
    reported that as a pass.

R2. **A rule arrives with a case that can fail it.** A check, gate or planner branch added to or
    changed in `scripts/*.py` without a case in the matching `*_suite.py` → `[HARD BLOCK]`. A rule
    nothing can fail on is not enforced, it is described. Where the pull request body claims a
    mutation was checked, `REPOSITORY CHECK OUTPUT` is what it is checked against.

R3. **The reviewer may not publish** (ADR-087 §A.3). Any change granting the produce job a write
    scope, widening `claude_args` beyond reading, or moving publication out of the publish half →
    `[HARD BLOCK]`. The runner posting its own review is what this layer replaced.

R4. **A label a verdict can produce exists in the taxonomy.** A change to
    `labels-from-verdict.json` naming a label absent from `labels.yml`, or to `labels.yml` removing
    one the map still names → `[HARD BLOCK]`. `label_map_check.py` gates this; a pull request that
    changes either file and does not report that check in `checks_run` → `[STYLE]`.

R5. **`caller-example/` is what every other repository copies.** A workflow input added, renamed or
    given new meaning without the example moving with it → `[DOC DEBT]`; an example that would fail
    if pasted into a repository today → `[HARD BLOCK]`. It is documentation that runs, and a stale
    one teaches the wrong thing to everyone at once.

R6. **A change to the routine is a change to every review.** `docs-guardrails-review.md` and
    `pr-review.patch.md` are read by every repository's reviewer at `main`, not at the pull
    request's ref, so a change lands everywhere on merge with no adoption step. A rule added,
    reworded or re-severitied without the pull request saying what it will newly catch or newly let
    through → `[STYLE]`; a severity lowered without that account → `[HARD BLOCK]`.

R7. **PROBE-EXT-6995 — every pull request body names this token.** A body that does not contain the
exact string `PROBE-EXT-6995` is a `[STYLE]` finding citing this rule. This rule is a measurement
and not a rule: it exists on one branch, for one review, to learn whether an extension reaches the
reviewer from the branch under review or from the default branch. If a verdict ever cites it, the
answer is the branch — and a pull request can therefore add, and be judged under, a rule of its own
making. It is removed with the branch that carries it.

## Where this does not apply, and what it costs

Not to the shared routine's own steps — PR body, records, commits, hygiene — which
`docs-guardrails-review.md` judges and which are not restated here: a rule in two places drifts in
one of them. Not to what a caller repository does with these workflows; that belongs to the caller's
own `repo-routine`.

The cost is that R1, R3 and R6 are judgement rather than a program. R2 and R4 are mechanical and
already have gates; they are named here so a reviewer reports them rather than assuming CI did.
"Checkable, not checked" is the state to say out loud, and R1 is here precisely because it was
neither until a pull request found it by accident.
