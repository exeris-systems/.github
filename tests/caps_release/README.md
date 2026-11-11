---
title: "Tests of the capability release scripts"
type: reference
visibility: public
owning-repo: .github
status: active
last-verified: 2026-11-11
---

# Tests of the capability release scripts

This directory holds the tests of `scripts/caps_release/`, the scripts that
`.github/workflows/caps-release.yml` runs to decide what is signed and uploaded. A test here runs a
script on plain files in a temporary directory, with no GitHub environment and no network, and
asserts on its exit status and output.

What the suite covers, per script, on the accepting path and on every refusing path:

- `resolve_release.py`: target, upload and version validation; every C0, DEL and C1 control
  character refused in every input; tag shape; tag and version agreement; containment of a tag in
  the default branch with the comparison replaced; the dispatch upload rule.
- `check_release_profile.py`: the release profile, a root `<modules>`, the Central plugin and
  publishing server id.
- `check_pom_version.py`: a tagged POM that does and does not say the tagged version.
- `scan_snapshots.py`: hard and soft SNAPSHOT classes, a property and a comment ignored, the
  upload and dry-run difference.
- `check_auto_publish.py`: `autoPublish` and `waitUntil` values in an effective POM.
- `check_dry_run_log.py`: a log that states the skip, one that begins an upload, one that proves
  nothing.
- `check_drift.py`: a clean, a modified, a deleted and an added file in the generated tree.
- `check_release_readiness.py`: missing artifacts, javadoc without `index.html`, absent and bad
  signatures, a stray file in a Central bundle.
- `check_secrets.py`: the secrets each target needs.
- `remove_signing_key.py`: the private keyring removed and the post-condition checked.

`python scripts/run_caps_release_tests.py` discovers `test*.py` here and fails when it collects no
test, so an empty suite cannot pass.

## How the suite is built

- Every script is run twice, in this process through `main(argv)` and as the workflow runs it
  (`python3 -I -B <script>`); `caps_release_helpers.Case.both` asserts that the two agree on the exit
  status, the `::error::` lines and what is written to `--output`.
- `mutation_table.py` lists the mutants: one `(old -> new)` source change each, which must match
  exactly once. `test_mutations.py` copies the script, applies the change and runs the selected tests
  against the copy, in forked workers with a time limit (a mutant that hangs counts as noticed). A mutant
  no test notices fails the suite and is listed. `mutation_killers.json` records which test killed each
  mutant, so that test runs first; regenerate it after editing the table with
  `python3 -B tests/caps_release/test_mutations.py --record`.
- `workflow_invariants.py` reads `caps-release.yml` as data (secrets only in `publish`, the id token
  only in `attest`, the gate staging what both uploads and the attestation take, key removal directly after the deploy, the scripts' digest re-verified after
  project code, pinned actions, safe defaults). `test_workflow.py` mutates the workflow text once per
  invariant to prove each can fail.
- A test marked `known_defect` states the correct behaviour of a script that does not have it yet. It
  is reported as an expected failure and becomes an unexpected success, which fails the run, when the
  script is fixed; the decorator is then removed.
- Tests that need `gpg` generate a throwaway key in a temporary keyring and skip when `gpg` is absent.

