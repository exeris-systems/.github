# exeris-systems/.github — shared guardrails

Organisation-level defaults and the reusable CI gates that enforce ADR-085. Every Exeris repository gets the community files here by default (GitHub applies `CONTRIBUTING.md` and `PULL_REQUEST_TEMPLATE.md` org-wide) and opts into the gates with a 10-line workflow caller.

## Layout

```
.github/
  workflows/
    docs-lint.yml        reusable — frontmatter/filenames/registry/private-link checks (error), markdownlint + Vale (warning; retracted figures error), lychee
    commit-lint.yml      reusable — commitlint on PR commits and on the PR title
    pr-body-check.yml    reusable — template headings + classification grammar + trailers
    javadoc-gate.yml     reusable — Javadoc gate: whole-module on `modules`, changed-files on `diff-modules`
  PULL_REQUEST_TEMPLATE.md
  CONTRIBUTING.md
scripts/
  _common.py             annotations + step summary + shared regexes
  frontmatter_check.py   docs-style-guide.md rules 2,3,5,6,7  (modes: ramp | strict)
  registry_check.py      adr-conventions.md rules 1–4         (consumer mode / registry mode)
  pr_body_check.py       pr-conventions.md rules 2–4
  agents_file_check.py   agents-md-schema.md rules 1, 2, 4, 5, 8
commitlint.config.js     commit-conventions.md rules 1–4 (custom rules: exeris-header-length, exeris-mmr-sections, exeris-trailers)
.markdownlint.yaml
vale/.vale.ini           + vale/styles/Quarkus (vendored, Apache-2.0) + vale/styles/Exeris (Terminology, RetractedFigures, DriftPatterns, Numbers, Absolutes)
lychee.toml
java/checkstyle-javadoc.xml        read from the checkout by javadoc-gate.yml — do not copy it into a repo
java/checkstyle-engine-pom.xml     the Checkstyle ENGINE, pinned beside the ruleset it runs
java/javadoc-plugin-block.xml      port target for gated modules' pom.xml
caller-example/guardrails.yml      copy into each repo's .github/workflows/
```

## Installing in a repo

1. Copy `caller-example/guardrails.yml` to `.github/workflows/guardrails.yml`. Keep `mode: ramp` until the frontmatter backfill has landed; keep `section-check: false` until subsystem/module pages carry the required sections.
2. `exeris-docs` passes `extra-paths: "adr rfc *.md"` because its records live at the repo root.
3. JVM repos with a gated module add the `javadoc` job. It takes two module lists, because `javadoc-conventions.md` rule 11 asks two different questions:

   - `modules` — gated in full. Port `java/javadoc-plugin-block.xml` into each of these modules' own `pom.xml` (not the parent: `-am` would gate their dependencies too).
   - `diff-modules` — gated on the pull request's changed files only, which is what rule 11 says for Kernel Core, Community and tooling. **No pom change**: this half invokes `javadoc` directly with the flags the profile would have set, so a module can be put under the gate without being made clean first.
   - `build-modules` — built, never audited. An annotation processor or generator a gated module needs is not reachable by `-am`: `<annotationProcessorPaths>` is not a reactor edge, and without naming it the install step dies on a missing artifact.

   That is the whole adoption cost: the gate checks this bundle out and reads `java/checkstyle-javadoc.xml` from there, and it uses `./mvnw` only if the repo has one.
4. Install the DCO GitHub App on the organisation with `.github/dco.yml` → `require: { members: false }` (org members exempt from the trailer, Spring's model).
5. Delete the repo's own `PULL_REQUEST_TEMPLATE.md` if it has one — the org default applies.

## Modes and the ramp

`frontmatter_check.py --mode ramp` fails only on files changed in the PR and downgrades everything else to warnings; `--mode strict` fails on every file. The rollout (ADR-085 Engineering Protocol 4) is: ramp for two weeks on `exeris-sdk` and `exeris-kernel`, then strict there, then fan out. `registry_check.py` and `pr_body_check.py` have no ramp — they check only what the PR introduces.

## Running locally

```
pip install pyyaml && pip install vale        # or brew install vale
python scripts/frontmatter_check.py --root docs --mode strict
python scripts/registry_check.py --index ../exeris-docs/adr-index.md
python scripts/agents_file_check.py
npx --package @commitlint/cli --package @commitlint/config-conventional commitlint --config commitlint.config.js --from origin/main
vale --config vale/.vale.ini docs/
```

Vale inline toggles are the sanctioned way to quote a retracted figure on purpose (a withdrawal note, a retraction register):

```
<!-- vale Exeris.RetractedFigures = NO -->
… earlier revisions asserted ">160 GB on a 4 GB payload"; no campaign supports it …
<!-- vale Exeris.RetractedFigures = YES -->
```

## What was verified on 2026-09-04

- `frontmatter_check.py` strict on `exeris-kernel/docs`: 89 files, 89 errors (all "missing frontmatter" — the expected baseline); on `exeris-docs/standards`: 14 files, 0 errors.
- `registry_check.py` on `exeris-docs` with siblings: 92 rows, 7 errors — six registry links to kernel ADRs that exist only on `development/0.12.0` (071, 073, 074, 077, 080, 083) and one relative link into the private `exeris-telemetry-spec` (ADR-018 stubs row). Consumer mode on `exeris-kernel`: 34 files, 0 errors; on `exeris-sdk`: 1 error (space-named `ADR-003 Entity-First Development Strategy.md`).
- `agents_file_check.py` replaced `claude_md_check.py` on 2026-09-05, when the schema moved from `CLAUDE.md` to `AGENTS.md`. It checks the entry file's presence and size, skill paths and metadata, manifest pinning, and whether provider directories carry generated markers — and nothing about wording, which the schema leaves to each repository
- `pr_body_check.py`: passes a conforming body; catches placeholders, unparseable classification, empty Verification, malformed `Refs:`, and a touched ADR without `Refs:`.
- `commitlint.config.js`: passes a conforming `fix` with Motivation/Modification/Result and the squash suffix; rejects a 117-char subject, a `fix` without the sections, `Refs: ADR-11`, and the type `destructive:`; passes `docs(adr): …` without a body and `report(entity-read-by-id): …` with a `Claim:` trailer.
<!-- vale Exeris.RetractedFigures = NO -->
- Vale on `exeris-kernel/docs/subsystems` (15 files): 0 errors, 352 warnings, 722 suggestions. On the public whitepapers at error level: **`exeris-kernel/docs/whitepaper.md` line 16 still asserts ">160GB" and line 136 still carries the retracted 459 MB / Axon saga table** — a live copy of retraction #23 on `main`. `b2b-technical-whitepaper.md` line 10 and `high-level-architecture.md` line 173 quote the figures inside withdrawal sentences (use the inline toggle).
<!-- vale Exeris.RetractedFigures = YES -->
