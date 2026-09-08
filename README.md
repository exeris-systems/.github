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
    tsdoc-gate.yml       reusable — TS doc comments + API-surface goldens (tsdoc-conventions.md)
  PULL_REQUEST_TEMPLATE.md
  CONTRIBUTING.md      standards links, DCO, and the maintainers list CODE_OF_CONDUCT/SECURITY refer to
CODE_OF_CONDUCT.md     Contributor Covenant 3.0 + reporting channel, enforcing party, AI-assisted-contribution line
SECURITY.md            org default: private reporting, 72 h / 7 d; exeris-kernel's own file wins there
SUPPORT.md             routing table behind the issue forms
scripts/
  _common.py             annotations + step summary + shared regexes
  frontmatter_check.py   docs-style-guide.md rules 2,3,5,6,7  (modes: ramp | strict)
  registry_check.py      adr-conventions.md rules 1–4         (consumer mode / registry mode)
  pr_body_check.py       pr-conventions.md rules 2–4
  agents_file_check.py   agents-md-schema.md rules 1, 2, 4, 5, 8  (+ machine-path, warning)
commitlint.config.js     commit-conventions.md rules 1–4 (custom rules: exeris-header-length, exeris-mmr-sections, exeris-trailers)
.markdownlint.yaml
vale/.vale.ini           + vale/styles/Quarkus (vendored, Apache-2.0) + vale/styles/Exeris (Terminology, RetractedFigures, DriftPatterns, Numbers, Absolutes)
lychee.toml
java/checkstyle-javadoc.xml        read from the checkout by javadoc-gate.yml — do not copy it into a repo
java/checkstyle-engine-pom.xml     the Checkstyle ENGINE, pinned beside the ruleset it runs
ts/eslint.tsdoc.mjs                shared flat-config fragment — the package imports it; the gate verifies it did
ts/tsdoc.json                      tag definitions for tsdoc/syntax — copy beside the package's tsconfig
ts/typedoc.base.json               port target for a library's typedoc.json (rule 1)
ts/api-extractor.base.json         port target for a library's api-extractor.json (rules 7-8)
ts/scripts/mcp-tool-surface.mjs    tools/list golden for an MCP server — the TS analogue of japicmp
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

   One optional input, `trivial-accessors`, is a policy and not a tuning knob. The default, `documented`, is `javadoc-conventions.md` rule 1 as written: every public member carries a doc comment. `exempt` drops that for a method whose body is a single line — what a fluent builder setter is — and a repository takes it only where something else carries the coverage, which for `exeris-sdk` is doclint plus its own completeness test. The gate writes which policy is in force into the step summary, because a green tick otherwise means two different things in two repositories and the result does not say which.

   It is named for the policy rather than for `minLineCount`, the Checkstyle property behind it. Line count is a poor proxy for triviality — `public Instant deadline() { return start.plus(ttl); }` is exempted along with the setters — and a better predicate should be able to replace it in this bundle without every caller changing a line of YAML.

4. TypeScript packages add the `tsdoc` job. Adoption is two devDependencies (`eslint-plugin-jsdoc`, `eslint-plugin-tsdoc`) and one import in the package's flat config:

   ```js
   import exerisTsdoc from "./.guardrails/ts/eslint.tsdoc.mjs";
   export default tseslint.config(..., ...exerisTsdoc({ gated: ["src/index.ts"] }));
   ```

   Locally, `.guardrails` has to be a **real directory** at that path — a symlink to a bundle checkout elsewhere does not work. Node resolves a module's realpath before searching for `node_modules`, so the fragment's `eslint-plugin-jsdoc` import is looked for beside the bundle instead of beside the package: `ERR_MODULE_NOT_FOUND`, zero files linted. Use a `git worktree` (or a copy) rather than `ln -s`, which also makes the local layout the same as the gate's — CI never hits this because it checks the bundle out.

   The gate checks this bundle out beside the package and **fails if that import is missing** — a flat config cannot be injected from outside, so a lint step that did not verify the reference would only be running the package's own rules.

   The rest is per package and opt-in: copy `ts/tsdoc.json` beside the package's `tsconfig.json`; a library that publishes adds `typedoc` (and `@microsoft/api-extractor`), ports `ts/typedoc.base.json` and `ts/api-extractor.base.json`, and sets `typedoc: true` with `api-report: api-extractor`; an MCP server sets `api-report: mcp-tool-surface`. Both stay off until the package commits the config and the golden they read — **the first golden lands in that build's own pull request, reviewed on its own**, because a golden reviewed alongside a feature is a golden nobody reads.
5. Install the DCO GitHub App on the organisation with `.github/dco.yml` → `require: { members: false }` (org members exempt from the trailer, Spring's model).
6. Delete the repo's own `PULL_REQUEST_TEMPLATE.md` if it has one — the org default applies.
7. Community-health defaults (`CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`) reach every repository without one of its own, from this repository's root. They name two mailboxes and a private reporting channel, so before they are published: `conduct@exeris.eu` and `security@exeris.eu` must deliver, and organisation-level private vulnerability reporting must be on (*Settings → Code security*). A code of conduct whose reporting address bounces is worse than none. Delete a repo's own `SUPPORT.md` or `CODE_OF_CONDUCT.md` only where it says nothing the default does not; `exeris-kernel/SECURITY.md` says more and stays.

## Modes and the ramp

`frontmatter_check.py --mode ramp` fails only on files changed in the PR and downgrades everything else to warnings; `--mode strict` fails on every file. The rollout (ADR-085 Engineering Protocol 4) is: ramp for two weeks on `exeris-sdk` and `exeris-kernel`, then strict there, then fan out. `registry_check.py` and `pr_body_check.py` have no ramp — they check only what the PR introduces.

## Paths in agent files

`agents_file_check.py` warns when an agent file hard-codes a path under somebody's home directory —
`~/…`, `/home/<someone>/`, `/Users/<someone>/`, `C:\Users\…`. `/home/runner/` is exempt: that is the
Actions user, and describing what CI does is describing a shared machine.

It is a warning, and the message says what to do rather than what to delete. A reference to a sibling
repository is useful — it is how the reference-first discipline works — but a reader who cloned this
repository alone has no such directory, and the instruction does not fail for them: the grep finds
nothing and they conclude from the silence. Naming the repository is always true; the sibling path is
a convenience, so say it as one.

Generated adapters are skipped. `check_adapters` already ties them to their source, so the only
actionable copy is the one under `.agents/` and reporting both would double the worklist.

## What counts as generated

Two answers, and a repository should only have to give one. Directory names — `node_modules`, `target`, `build`, `dist` and the rest of `scripts/_common.py`'s taxonomy — cover output that lands where output usually lands. A committed report does not: `api/<pkg>.api.md` is generated, is meant to be in the diff, and is a Markdown file sitting in a directory with an ordinary name.

For those, the repository's own `.gitattributes` is the answer, which ADR-085 §F.21d already asks for: a tree marked `linguist-generated` is skipped by `frontmatter_check.py`, `frontmatter_backfill.py` and markdownlint. Both spellings work (`linguist-generated` and `linguist-generated=true`), and `-linguist-generated` on a path puts it back under the checks. The attribute is resolved by `git check-attr`, so nested files, negation and precedence behave the way GitHub's own diff collapsing does. Off a work tree — no git, no repository — the marker is simply not read, and the directory taxonomy stands on its own.

Vale and lychee still do not read it: both carry their own path lists, and a generated report is still checked for prose and links. Prose is warning-level; links are not, so a generated file full of URLs remains a reason to reach for `exclude`.

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

## What was verified on 2026-09-06 (TypeScript)

- `ts/eslint.tsdoc.mjs` spread into `exeris-ai-bridge`'s own type-aware config: 146 errors / 14 warnings (139 `require-jsdoc` on the gated `src/tools/**` — narrow the gated globs at kickoff; 6 `tsdoc/syntax`; 1 `check-tag-names`). On `exeris-codegen-ts` with a minimal typescript-eslint base: 248 errors / 113 warnings (113 `tsdoc/syntax`, 90 `check-tag-names` = 57 `{@code}` + 33 `@author`, 45 gated `require-jsdoc`; warnings 88 `require-jsdoc`, 15 `no-restricted-syntax` = 11 HTML markup + 4 history, 10 `multiline-blocks`). The history regex is the anchored list of ADR-085's 2026-09-05 amendment at warning level (the unanchored one produced 3 false positives on ai-bridge); `jsdoc/no-restricted-syntax` reports one context per comment, so the history contexts are listed first; `@author`/`@version` are errors through `tagNamePreference`.
- `ts/tsdoc.json`: `extends: ["typedoc/tsdoc.json"]` is required (`@since`, `@category` are typedoc's, not TSDoc core); the schema URL must be `tsdoc.schema.json`; `supportForTags` must not be used (it turns every unlisted core tag, `{@link}` included, into `tsdoc-unsupported-tag`).
- typedoc validation (`notDocumented`, `treatValidationWarningsAsErrors`): ai-bridge 36 warnings → exit 4; codegen-ts library modules 293 + 5 `notExported` → exit 4.
- api-extractor on `exeris-sdk-ui-kit`: report produced in one run; `ae-missing-release-tag` on both exports; CI mode exits 1 on a report diff after adding an export.
- `ts/scripts/mcp-tool-surface.mjs` on ai-bridge: 25 tools accepted; re-run "unchanged" exit 0; hand-edited golden → `- removed tool … (MAJOR)`, `~ changed tool …`, exit 2.

## What was verified on 2026-09-04

- `frontmatter_check.py` strict on `exeris-kernel/docs`: 89 files, 89 errors (all "missing frontmatter" — the expected baseline); on `exeris-docs/standards`: 14 files, 0 errors.
- `registry_check.py` on `exeris-docs` with siblings: 92 rows, 7 errors — six registry links to kernel ADRs that exist only on `development/0.12.0` (071, 073, 074, 077, 080, 083) and one relative link into the private `exeris-telemetry-spec` (ADR-018 stubs row). Consumer mode on `exeris-kernel`: 34 files, 0 errors; on `exeris-sdk`: 1 error (space-named `ADR-003 Entity-First Development Strategy.md`).
- `agents_file_check.py` replaced `claude_md_check.py` on 2026-09-05, when the schema moved from `CLAUDE.md` to `AGENTS.md`. It checks the entry file's presence and size, skill paths and metadata, manifest pinning, and whether provider directories carry generated markers — and nothing about wording, which the schema leaves to each repository
- `pr_body_check.py`: passes a conforming body; catches placeholders, unparseable classification, empty Verification, malformed `Refs:`, and a touched ADR without `Refs:`.
- `commitlint.config.js`: passes a conforming `fix` with Motivation/Modification/Result and the squash suffix; rejects a 117-char subject, a `fix` without the sections, `Refs: ADR-11`, and the type `destructive:`; passes `docs(adr): …` without a body and `report(entity-read-by-id): …` with a `Claim:` trailer.
<!-- vale Exeris.RetractedFigures = NO -->
- Vale on `exeris-kernel/docs/subsystems` (15 files): 0 errors, 352 warnings, 722 suggestions. On the public whitepapers at error level: **`exeris-kernel/docs/whitepaper.md` line 16 still asserts ">160GB" and line 136 still carries the retracted 459 MB / Axon saga table** — a live copy of retraction #23 on `main`. `b2b-technical-whitepaper.md` line 10 and `high-level-architecture.md` line 173 quote the figures inside withdrawal sentences (use the inline toggle).
<!-- vale Exeris.RetractedFigures = YES -->
