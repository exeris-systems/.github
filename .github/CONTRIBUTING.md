# Contributing to Exeris

This is the organisation-wide default. A repo's own `CONTRIBUTING.md` (build, native prerequisites, subsystem rules) takes precedence for anything it states; the standards below apply everywhere.

## Standards

All conventions live in one place and are linked, not copied:

- Commits — [`commit-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/commit-conventions.md)
- Pull requests — [`pr-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/pr-conventions.md)
- Javadoc — [`javadoc-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/javadoc-conventions.md)
- Documentation — [`docs-style-guide.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/docs-style-guide.md)
- ADRs / RFCs — [`adr-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/adr-conventions.md)
- AI assistance — [`ai-provenance.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/ai-provenance.md)

The CI gates that enforce them are reusable workflows in this repository (`.github/workflows/`); your PR will tell you which one failed and why.

## Licence and sign-off

Each repository states its licence at its root (`LICENSE`, and for `exeris-kernel` the per-tier `LICENSE-COMMUNITY` / `LICENSE-ENTERPRISE`). By contributing you offer your contribution under the licence of the module you are changing.

External contributions require a Developer Certificate of Origin sign-off on every commit (`git commit -s`, producing `Signed-off-by: Name <email>`); the DCO check on the PR enforces it. Members of the `exeris-systems` organisation are exempt from the trailer, not from the accountability rule in `ai-provenance.md`. No CLA is required.

## Getting help

Open a GitHub Discussion in the repo concerned; architectural questions go to `exeris-docs`.
