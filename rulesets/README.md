---
title: Organisation rulesets — the branch rules that bind the execution identity
type: reference
visibility: public
owning-repo: .github
status: active
last-verified: 2026-10-15
---

# Organisation rulesets

Two rulesets, applied at organisation level, versioned here because a rule that exists only in a
settings page is a rule nobody reviews (ADR-085 §C.11: shared enforcement lives in this
repository). They are the "capability absence" half of RFC-2026-09-17 Q6: what the `exeris-agent`
App structurally cannot do is decided by these files and by the App's permission set, not by a
sentence in `AGENTS.md`.

| File | Targets | What it says |
|:--|:--|:--|
| `exeris-code-base.json` | every repository's default branch, except the three data repositories: the two inboxes (`exeris-ai-execution`, `-enterprise`), which carry ADR-086 §G.33's validator as their own required check, and `exeris-ai-execution-streams`, whose `main` the pen commits streams to directly (ADR-087 §A.1, §C.13) | no deletion, no force-push, **every change through a pull request**, **no bypass actors — the founder included**, stale approvals dismissed on push; approval of the most recent push by someone other than its pusher is one of the three switches below |
| `exeris-code-verdict.json` | the default branch and every `development/**` branch of the repositories whose `guardrails.yml` calls `review.yml` from a job `review`: `.github` today. `development/**` is where a repository that integrates a release on a development branch, such as `exeris-kernel`, takes its pull requests | the required check `review / verdict` (ADR-087 §B.8), pinned to the GitHub Actions integration so another App cannot report a check by that name |

`exeris-code-verdict` is the only source of the required review check, for every publishing
repository: no per-repository branch protection and no repository ruleset carries it.

Why `include` is a list and not `~ALL`: a required status check that no workflow reports leaves a
pull request unable to merge forever. Publication is opt-in per repository
(`caller-example/guardrails.yml`), so the check exists only where it is switched on, and only once
the repository's caller job is `review`. **`include` lists only repositories whose `guardrails.yml`
calls `review.yml` from a job `review`.** The end state is every repository whose `guardrails.yml`
sets `publish: true`. Until a repository is listed it has no required review check; one that is
listed while its caller still reports `docs-review / publish / verdict` could never merge.

### Moving a repository to `review / verdict`

The check is named `<caller job> / <job>`, so the name follows the caller's job id: a job called
`review` calling `review.yml` reports `review / verdict`, and a job called `docs-review` calling
`docs-review.yml` reports `docs-review / publish / verdict`. For each repository, in this order:

1. Open the caller change (`README.md`, step 5). Its own checks report `review / verdict`, because
   the run that decides a pull request is the one its branch carries.
2. Merge it. A pull request still open in that repository carries the old job id until it takes the
   merge, so it reports the old name: update its branch from the base.
3. Confirm the name against the run on the caller pull request's last head, as below. The review
   runs on pull requests, not on the push to the default branch, so the merge commit has no such run.
4. Add the repository to `include` in `exeris-code-verdict.json` and apply the file (`PUT`, below).
   Only now do its pull requests require the name its caller reports.

`.github` is the first repository: its caller is in this repository, so the pull request that
introduces the job `review` also lists `.github` in the file, and the owner applies the file after
that merge, once the run on that pull request's last head reported `review / verdict`.

When the last repository has moved, `docs-review.yml` and `publish-verdict.yml` are deleted.
`scripts/review_check_name_check.py` fails when the ruleset requires anything but exactly
`review / verdict` from the Actions integration, when `.github` is not in `include`, and when a
repository in `include` that the checkout can see (`.github` itself) does not call `review.yml` from
a job `review`.

To list the repositories that publish, and the job id each one's review job carries, fetch each
`guardrails.yml` and read it; a code search finds the candidates and nothing in it is the answer,
because a commented-out `publish: true` matches too:

```sh
gh api 'search/code?q=org:exeris-systems+%22publish:+true%22+path:.github/workflows+filename:guardrails.yml' \
  --jq '.items[].repository.name'
```

A caller that pins `docs-review.yml` by commit is still served by the file it pinned, and that
copy reaches `publish-verdict.yml` at `@main`: neither file is removed while one exists.

## The three switches for the second maintainer

All three live in `exeris-code-base.json`, all three are off while the organisation has one member
who can review, and flipping them is the whole of what changes on the day there is a second
(RFC-2026-09-17, *Independent* levels; `review-policy.json` in the harness carries the level):

- `required_approving_review_count`: `0` → `1`
- `require_code_owner_review`: `false` → `true` once `CODEOWNERS` has more than one row
- `require_last_push_approval`: `false` → `true`. It is not free of an approval count: applied with
  the count at `0`, it refuses every merge with "new changes require approval from someone other
  than the last pusher", which in a one-member organisation is every pull request. RFC-2026-09-17's
  S1.e expected it on from day one; the measurement says it belongs with the other two.

Until then the human-verification rule for App-authored pull requests lives in the required check
(`scripts/publish_verdict.py`, author-conditional), which is where a rule that depends on the
author can live and a ruleset cannot. Either of two gestures satisfies it, and both are the same
record: an approving review by a `User` principal on the head commit, or `human-reviewed` — the
only one open to a person on a pull request of their own, which GitHub does not let them approve.
An approval by a `Bot` principal never counts, and a push leaves either behind.

## Apply

```sh
# first time
gh api -X POST orgs/exeris-systems/rulesets --input rulesets/exeris-code-base.json
gh api -X POST orgs/exeris-systems/rulesets --input rulesets/exeris-code-verdict.json

# afterwards: find the id, then PUT the file
gh api orgs/exeris-systems/rulesets --jq '.[] | "\(.id)\t\(.name)"'
gh api -X PUT orgs/exeris-systems/rulesets/<id> --input rulesets/exeris-code-verdict.json
```

Confirm the check name against a real run before a repository is added to the verdict ruleset:

```sh
gh api repos/exeris-systems/<repo>/commits/<head-sha>/check-runs --jq '.check_runs[].name'
```

## Things this file does not decide

- Whether an App's approving review counts toward `required_approving_review_count` (RFC-2026-09-17
  Q7, S1.a). Expected not; it is measured on a throwaway repository under these same files.
- A repository that still receives direct pushes to its default branch goes red on the next push
  under `exeris-code-base.json`. That is the rule working; the remedy is a pull request, not an
  exclusion — an exclusion is a bypass under another name. The three data repositories are not that
  case: none of them holds code, each is written by one App identity under ADR-087 §A.1 and read by
  a person before anything depends on it, and each carries its own required check in place of this
  file's — the inbox validator on the two inboxes (ADR-086 §G.33), the index-digest verification on
  the streams repository. A stream is committed to `main` directly because a pull request would
  leave the row's reference to it dangling until merged (ADR-087 §C.13); that is the sanctioned shape
  of the pen, and it is the only one.
