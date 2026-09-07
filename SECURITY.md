# Security Policy

Organisation-wide default for every `exeris-systems` repository. A repository with its own `SECURITY.md` — today `exeris-kernel`, whose policy also defines the security model, the vulnerability classes and the severity guidance — takes precedence for that repository; this file states what is the same everywhere.

## Reporting a vulnerability

Report suspected vulnerabilities **privately**, through GitHub private vulnerability reporting on the repository concerned (*Security → Report a vulnerability*). If you cannot use GitHub, email <security@exeris.eu>. Do not open a public issue, discussion or pull request for a suspected vulnerability; the issue forms route security to the private channel for that reason.

Include the minimum needed to reproduce and understand the issue: affected repository and version or commit, the input or configuration that triggers it, what you observed, and what you expected. If your research accidentally reaches secrets, tenant data or other sensitive runtime material, stop and report with only the minimum necessary detail.

## What happens next

The maintainers aim to acknowledge receipt within 72 hours and to give an initial triage result or follow-up questions within 7 days — the same terms as `exeris-kernel/SECURITY.md`. After that: validate against the module's contracts and TCK obligations, assess which branches, tags and published artefacts are affected, prepare a fix with test coverage, and coordinate disclosure once a mitigation is available. Fixed vulnerabilities are recorded in the repository's `CHANGELOG.md` under `Security` and, where a published artefact is affected, in a GitHub security advisory with a CVE requested through GitHub.

## Supported versions

Security fixes go to the default branch and to the latest published release of each artefact (Maven Central, npm, GitHub Packages). Earlier releases, stale branches, forks and experimental branches are not supported unless a release line is explicitly announced as supported in the repository's own `SECURITY.md`. Enterprise-tier artefacts follow the support terms of their commercial licence.

## Scope

In scope: every repository under `exeris-systems`, the artefacts they publish, the `docs.exeris.eu` site, and the CI workflows in this repository. Third-party dependency vulnerabilities are in scope when Exeris code makes them reachable; otherwise report them upstream and open a dependency-update pull request here. Out of scope: infrastructure you do not own or have permission to test, and social-engineering of maintainers.

## Safe harbour

Good-faith research that avoids data destruction, persistence, lateral movement, access to third-party secrets and public disclosure before coordination is welcome, and we will not pursue it. This statement is not legal advice and does not authorise testing against third-party systems, production tenants or infrastructure you do not own.

## Coordinated disclosure

Please hold public disclosure until a mitigation has been released. If your organisation requires a disclosure deadline, say so in the initial report so it can be planned for. If a vulnerability lands in a public issue by accident, the maintainers may limit the thread, remove sensitive details and move coordination to the private channel; please do not continue exploit discussion in public once that has happened.
