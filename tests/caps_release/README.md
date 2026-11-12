---
title: "Tests of the capability release scripts"
type: reference
visibility: public
owning-repo: .github
status: active
last-verified: 2026-11-12
---

# Tests of the capability release scripts

This directory holds the tests of `scripts/caps_release/`, the scripts that decide what is signed and
uploaded. They are written to be called by a reusable capability release workflow, `caps-release.yml`,
which this repository does not hold yet; elsewhere on this page "the calling workflow" is that
workflow. A test here runs a script on plain files in a temporary directory, with no GitHub environment and no network, and
asserts on its exit status and output.

What the suite covers, per script, on the accepting path and on every refusing path:

- `resolve_release.py`: the two targets (`none` and `github-packages`; any other value, padded or in another case, is one
  `::error::` line), upload and version validation; every C0, DEL and C1 control character refused in every input; tag shape; tag and
  version agreement; containment of a tag in the default branch with the comparison replaced; `publish` only for an upload to
  `github-packages`, a warning for an upload with `none`, and the dispatch upload rule.
- `check_release_profile.py --pom P`: the `release` profile, a `<modules>` anywhere, the signing, sources and javadoc plugins in the
  release profile's `<build><plugins>`, and the Central publishing plugin refused there. The scope of the check (what it does not read)
  is stated in `test_release_profile.py`.
- `check_pom_version.py`: a tagged POM that does and does not say the tagged version.
- `scan_snapshots.py`: hard and soft SNAPSHOT classes, a property and a comment ignored, the upload and dry-run difference.
- `check_drift.py`: a clean, a modified, a deleted and an added file in the generated tree; the refusal names the fix and no deployment.
- `check_release_readiness.py --target-dir D [--gpg G] [--stage S]`: the closed file set of each coordinate (main, sources and javadoc
  jars, pom, and a detached signature of each) and everything else refused; non-regular files; signatures checked with the given
  `gpg` on the gate's private copies; the javadoc `index.html`; the coordinate read from the pom; the read-once private copies and the
  staging that must equal what was verified; the XML and subprocess bounds.
- `check_secrets.py`: no arguments; only the literal `true` of the two signing-secret booleans counts; the missing secrets are named and
  no value is printed.
- `remove_signing_key.py`: the private keyring removed and the post-condition checked; the secret home and the exported key removed by
  literal path operations on every way out.
- An unexpected failure in any script is one `::error::` line; usage errors are exit 2.
- ASCII-only versions in `resolve_release.py`, `scan_snapshots.py` and the gate; the XML size and depth bounds of the four POM readers.

`test_upload_command.py` runs the workflow's own upload command against a `file://` repository, on files staged by the real gate, and
asserts the repository layout. It needs `mvn` and the deploy plugin in the local Maven repository, and is skipped, never passed,
without them.

`python scripts/run_caps_release_tests.py` discovers `test*.py` here and fails when it collects no
test, so an empty suite cannot pass.

## How the suite is built

- Every script is run twice, in this process through `main(argv)` and as the calling workflow runs it
  (`python3 -I -B <script>`); `caps_release_helpers.Case.both` asserts that the two agree on the exit
  status, the `::error::` lines and what is written to `--output`.
- `mutation_table.py` lists the mutants: one `(old -> new)` source change each, which must match
  exactly once. `test_mutations.py` copies the script, applies the change and runs the selected tests
  against the copy, in forked workers with a time limit (a mutant that hangs counts as noticed). A mutant
  no test notices fails the suite and is listed. `mutation_killers.json` records which test killed each
  mutant, so that test runs first; regenerate it after editing the table with
  `CAPS_MUTANT_TIMEOUT=240 python3 -B tests/caps_release/test_mutations.py --record` (a pass with no recorded killer runs every
  selected test against a surviving mutant, which takes longer than the 25 seconds a normal run allows). A mutant that no input can
  tell from the script is listed with its reason in `EQUIVALENT` instead of in the table.
- `workflow_invariants.py` reads `caps-release.yml` as data (the two targets and no other repository or bundle, secrets only in
  `publish`, the upload token in the upload step alone and the passphrase in the signing step alone, the id token only in `attest`,
  the order sign, remove the key, gate, upload, the upload run from the staging directory to one URL without a profile, the gate staging
  what both uploads and the attestation take, the scripts' digest re-verified after project code, pinned actions, safe defaults).
  `test_workflow.py` mutates the workflow text once per invariant to prove each can fail.
- A test marked `known_defect` states the correct behaviour of a script that does not have it yet. It
  is reported as an expected failure and becomes an unexpected success, which fails the run, when the
  script is fixed; the decorator is then removed.
- A subprocess bound is a module constant. The tests assert its value, assert that the call passes it
  to `subprocess.run`, and lower the constant to a fraction of a second against a double that sleeps.
- Tests that need `gpg` generate a throwaway key in a temporary keyring and skip when `gpg` is absent.


## What the suite does not cover, and what it costs

- It runs the scripts, not the calling workflow: nothing here executes on GitHub, so the passing of inputs, secrets and
  permissions from the calling workflow to the scripts is not exercised.
- `gpg` is a double in all but the tests that name the real one; a signature is judged by the double's rule there.
- The mutation run is most of the suite's time: one fork per mutant, each bounded by 25 seconds (240 when recording the killers).
