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
