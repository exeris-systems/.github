# Getting help

Organisation-wide default for every `exeris-systems` repository. Where to take what, so that a question does not become an issue and a bug does not vanish into a discussion.

| You have… | Go to | Because |
|:--|:--|:--|
| a question — how do I, why does it, is this the right way | [GitHub Discussions](https://github.com/orgs/exeris-systems/discussions) | Questions are answered where the next person can find them; architectural ones belong under `exeris-docs`. |
| a bug — observed behaviour contradicts a stated contract, with a reproducer | the repository's *Bug* issue form | Issues are for work, and the form asks for what the work needs ([`issue-conventions.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/issue-conventions.md)). |
| a change you want — feature, API addition, behaviour change | the *Change request* form, or a Discussion first if the shape is unclear | A change request becomes a pull request; an RFC-shaped topic starts as a Discussion. |
| a number that surprised you — throughput, allocation, latency | the *Performance finding* form, with the report path | Performance claims without evidence close after 14 days ([`claims-and-evidence.md`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/claims-and-evidence.md)). |
| a documentation problem — stale, missing, wrong | the *Documentation* form | Documentation debt is tracked like code debt (`[DOC DEBT]`). |
| a suspected vulnerability | **private** reporting only — see [`SECURITY.md`](SECURITY.md) | Never a public issue. |
| a conduct concern | <conduct@exeris.eu> — see [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | Handled privately. |
| a licensing or legal question | <legal@exeris.eu> | Each repository's `LICENSE` states its terms; the kernel's tiers are described in its README. |
| an Enterprise-tier question | the channel in your commercial agreement | Enterprise support is contractual and is not provided through public issues. |

## What to expect

Exeris is maintained by a very small team. Discussions and issues are read regularly, but there is no service level on public channels: a bug with a reproducer and a clear contract violation is picked up before a bug without one, and a change request with a concrete consumer before a speculative one. Reading [`CONTRIBUTING.md`](.github/CONTRIBUTING.md) first, and the standards it links, is the fastest way to a useful answer — most questions about *how things are done here* are answered there.

## Before you ask

Check the repository's `docs/` (and `docs.exeris.eu` once that is live — it has no DNS record yet, so this is deliberately not a link), the ADR registry in `exeris-docs/adr-index.md` for decisions already taken, and the open Discussions for the same question. If you found the answer in a place that was hard to find, a *Documentation* issue saying where you looked first is a contribution.
