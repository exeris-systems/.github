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
in `.github/workflows/`; elsewhere on this page "the calling workflow" is that
workflow. A test here runs a script on plain files in a temporary directory, with no GitHub environment and no network, and
asserts on its exit status and output.

What the suite covers, per script, on the accepting path and on every refusing path:

- `resolve_release.py`: the two targets (`none` and `github-packages`; any other value, padded or in another case, is one
  `::error::` line), upload and version validation; the JDK distribution (`temurin`, `graalvm`) and version (`NN`, `NN.x`, `NN.N.N`) when given; every C0, DEL and C1 control character refused in every input; tag shape; tag and
  version agreement; containment of a tag in the default branch with the comparison replaced; `publish` only for an upload to
  `github-packages`, a warning for an upload with `none`, and the dispatch upload rule.
- `check_release_profile.py --pom P`: the `release` profile, a `<modules>` anywhere, the signing, sources and javadoc plugins in the
  release profile's `<build><plugins>`, and the Central publishing plugin refused there. The scope of the check (what it does not read)
  is stated in `test_release_profile.py`.
- `check_pom_version.py`: a tagged POM that does and does not say the tagged version.
- `scan_snapshots.py`: hard and soft SNAPSHOT classes, a property and a comment ignored, the upload and dry-run difference.
- `check_drift.py`: a clean, a modified, a deleted and an added file in the generated tree; the refusal names the fix and no deployment.
- `check_release_readiness.py --target-dir D [--gpg G] [--stage S]`: the closed file set of each coordinate (main, sources and javadoc
  jars, pom, and a detached signature of each) and everything else refused; a base that is not `<artifactId>-<MAJOR.MINOR.PATCH>` (artifactId
  `[A-Za-z0-9_.-]`, at most 200 characters in all) and names that collide under case folding refused; non-regular files; signatures checked with the given
  `gpg` on the gate's private copies; the javadoc `index.html`; the coordinate read from the pom; the read-once private copies and the
  staging that must equal what was verified; the XML and subprocess bounds.
- `check_secrets.py`: no arguments; only the literal `true` of the two signing-secret booleans counts; the missing secrets are named and
  no value is printed.
- `remove_signing_key.py`: the private keyring removed and the post-condition checked; the secret home and the exported key removed by
  literal path operations on every way out.
- `staged_manifest.py`: `create` (sorted `<sha256>  <name>` lines, an output heredoc whose delimiter occurs in no line, `-digest` and `-id`,
  illegal names and non-regular entries refused with nothing written) and `verify` (a directory equal to the manifest in the environment,
  every difference one finding, the closed set of a coordinate, a `pom.xml` or `.mvn` or `settings.xml` refused, every malformed manifest
  text, a blank line included, refused; every refusal of `verify` ends with the same final line; the same base rule as the gate; names that
  collide under case folding or normalisation refused; `--dir` judged as written, `link/` as `link`); each file opened once without following links; the closed set it accepts against the set the real gate stages
  (`test_manifest_gate_agreement.py`).
- An unexpected failure in any script is one `::error::` line; usage errors are exit 2.
- ASCII-only versions in `resolve_release.py`, `scan_snapshots.py` and the gate; the XML size and depth bounds of the four POM readers.

`test_base_rule.py` holds one table of base names (`base_rule_support.py`, with an independent statement of the rule) to the readiness gate,
`create` and `verify`, runs a seeded sample of 20 000 names over a hostile alphabet through the three, and runs the workflow's own upload step with a
`mvn` that records its arguments to show that the files it names are exactly the files of each accepted base. `test_manifest_refusals.py` covers the
literal reading of `--dir`, a file that vanishes, the final line of every refusal of `verify`, the `--name` pattern and the top-level handler.

`test_upload_command.py` runs the `upload` job of the workflow against a `file://` repository: the real gate stages a fixture build, the
manifest is made of the staged directory, the directory is copied to a fresh download directory, and the job's own comparison, settings and
upload steps run from it. It needs `mvn`, `/usr/bin/python3` and the deploy plugin in the local Maven repository, and is skipped, never
passed, without them.

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
- `workflow_invariants.py` reads `caps-release.yml` as data and states the four-job split as invariants: the permissions of each job
  (`packages: write` in `upload` alone, `build` and `publish` read-only, `attest` with the id token and attestations and nothing else);
  where the job token and the signing secrets may appear (the token in the last step of `upload` and the read-only resolve step of `build`,
  in any spelling; the key in the import step and the passphrase in the signing step of `publish`); that `upload` and `attest` check out
  only this repository's scripts, restore no cache, run no file from the download directory, interpolate nothing into shell text and take
  only the manifest and the artifact name from `publish`; the order of the steps of `upload` and of `publish`; that the manifest travels as
  a job output and is compared before anything is uploaded or attested; that both JDK inputs reach the resolver through the environment of the resolve step
  and nowhere else, `build` publishes what it wrote, and every `setup-java` step reads those outputs and never an input; the pins, the defaults and the scripts' digest.
  `test_workflow.py` mutates the workflow text (and moves steps) at least once per identifier the checker can report.
- A test marked `known_defect` states the correct behaviour of a script that does not have it yet. It
  is reported as an expected failure and becomes an unexpected success, which fails the run, when the
  script is fixed; the decorator is then removed.
- A subprocess bound is a module constant. The tests assert its value, assert that the call passes it
  to `subprocess.run`, and lower the constant to a fraction of a second against a double that sleeps.
- Tests that need `gpg` generate a throwaway key in a temporary keyring and skip when `gpg` is absent.


## What the suite does not cover, and what it costs

- It runs the scripts, not the calling workflow: nothing here executes on GitHub, so the passing of inputs, secrets and
  permissions from the calling workflow to the scripts is not exercised.
- The reusable workflow is read as data and its upload command is run against a `file://` repository; the workflow itself is not
  run, and `test_upload_command.py` is skipped without `mvn` and the deploy plugin in the local Maven repository.
- `gpg` is a double in all but the tests that name the real one; a signature is judged by the double's rule there.
- The mutation run is most of the suite's time: one fork per mutant, each bounded by 25 seconds (240 when recording the killers).
