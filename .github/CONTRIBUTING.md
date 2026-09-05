# Contributing to Exeris

This is the organisation-wide default. A repo's own `CONTRIBUTING.md` (build, native prerequisites, subsystem rules) takes precedence for anything it states; the standards below apply everywhere.

## Standards

All conventions live in one place and are linked, not copied:

- Commits — [`commit-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/commit-conventions.md)
- Pull requests — [`pr-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/pr-conventions.md)
- Javadoc — [`javadoc-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/javadoc-conventions.md)
- Documentation — [`docs-style-guide.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/docs-style-guide.md)
- Issues — [`issue-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/issue-conventions.md)
- ADRs / RFCs — [`adr-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/adr-conventions.md)
- Changelog and compatibility — [`changelog-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/changelog-conventions.md)
- Numbers in docs — [`claims-and-evidence.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/claims-and-evidence.md)
- Agent-facing files — [`agents-md-schema.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/agents-md-schema.md)
- AI assistance — [`ai-provenance.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/ai-provenance.md)

The CI gates that enforce them are reusable workflows in this repository (`.github/workflows/`); your PR will tell you which one failed and why.

## Licence and sign-off

Each repository states its licence at its root — a `LICENSE` file, and where a repository publishes more than one tier, a per-tier licence file beside it. By contributing you offer your contribution under the licence that repository publishes for the module you are changing. If a repository asks for anything beyond that, its own `CONTRIBUTING.md` says so; this file does not decide it.

External contributions carry a **Developer Certificate of Origin** sign-off on every commit:

```
git commit -s          # appends: Signed-off-by: Your Name <you@example.com>
```

The sign-off certifies the [DCO 1.1](https://developercertificate.org/) statements — that you wrote the change, or have the right to submit it under that licence. It certifies origin and grants nothing further. The [DCO app](https://github.com/apps/dco) checks every commit in the pull request; `.github/dco.yml` in this repository allow-lists organisation members, who are exempt from the trailer and not from the accountability rule in [`ai-provenance.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/ai-provenance.md).

If you contribute in the course of employment or on behalf of an organisation, link a short written authorisation from that organisation on your first pull request — a personal sign-off does not bind an employer.

A commit that missed the trailer is fixed with `git commit --amend -s` (or `git rebase --signoff <base>` for several) and a force-push; there is nothing to re-sign elsewhere.

## Getting help

Open a GitHub Discussion in the repo concerned; architectural questions go to `exeris-docs`. Bug reports, change requests, performance findings and documentation problems are issues, not discussions — the forms are in this repository and blank issues are disabled, so the tracker records work and Discussions hold the questions.
