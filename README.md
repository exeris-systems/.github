# exeris-systems/.github — the organisation's enforcement

This repository holds **the enforcement, never the rule**. The rules live one repository away, in
[`exeris-docs/standards/`](https://github.com/exeris-systems/exeris-docs/blob/main/standards/README.md);
what is here is what makes them fire. A check with no standard behind it is a rule invented in CI,
where nobody reviewed it and nobody can find it.

It does three things.

**Community defaults, org-wide.** GitHub applies this repository's `CONTRIBUTING.md`,
`PULL_REQUEST_TEMPLATE.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` and `SUPPORT.md` to every repository
that has none of its own. No adoption step; they are simply in force.

**Reusable L1 gates**, which a repository opts into with one 10-line caller
(`caller-example/guardrails.yml`): documentation lint, commit lint, pull-request body, Javadoc and
TSDoc. These are mechanical and they run in the adopting repository's CI.

**The L2 review and its publication** (ADR-087). `docs-guardrails-review.md` is the organisation's
review routine — one copy, checked out and handed to a model verbatim, so changing it changes every
repository at once. What the review produces is a `verdict`: a JSON object this repository defines a
schema for, composed over the `exeris-agents` bundle vendored under `.agents/`. `docs-review.yml`
produces it and `publish-verdict.yml` publishes it under the `exeris-bot` identity — posting the
review, applying the labels of `labels-from-verdict.json`, and being the required check that is red
when the verdict is absent, invalid, `BLOCKED`, or resting on a gate that did not run.

**Every change here changes CI for every repository.** The workflows are called `@main`, so a merge
to `main` is a deployment and there is no staging. The gates in this repository's own
`.github/workflows/guardrails.yml` run on this repository, including the L2 review: a gate its owner
does not run is a gate nobody has tested.

## Layout

```text
.github/
  workflows/
    docs-lint.yml        reusable — frontmatter/filenames/registry/private-link checks (error), markdownlint + Vale (warning; retracted figures error), lychee
    commit-lint.yml      reusable — commitlint on PR commits and on the PR title
    pr-body-check.yml    reusable — template headings + classification grammar + trailers
    javadoc-gate.yml     reusable — Javadoc gate: whole-module on `modules`, changed-files on `diff-modules`
    tsdoc-gate.yml       reusable — TS doc comments + API-surface goldens (tsdoc-conventions.md)
    docs-review.yml      reusable — the L2 review: a `produce` job runs the routine, a `publish`
                         job (opt-in, `publish: true`) posts and gates. ADR-087 §B.5
    publish-verdict.yml  reusable — the publishing half on its own, so more than one producer can
                         reach it. Posts as `exeris-bot`, labels, and is the required check
    guardrails.yml       this repository's OWN caller — it runs its gates, and the L2 review, on itself
    labels-sync.yml      applies labels.yml across the organisation
    issue-hygiene.yml    ages `needs-reproducer` / `needs-evidence`
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
  caller_permissions_check.py  a caller's permission block is the union of every workflow it calls,
                         nested calls included, and each `with:` key is an input that workflow
                         declares. GitHub rejects the whole file otherwise — in the adopting
                         repository, on the first push, with no logs
  publish_verdict.py     the publish step's decision half: it plans and never writes. Reads the
                         verdict, validates it, and writes the labels, the comment and the
                         conclusion the workflow then applies and gates on
  publish_verdict_suite.py  one case per red path ADR-087 §B.8 names, run in this repository's CI
  bundle_pin_check.py    the vendored bundle is the ref docs-lint.yml resolves
  commitlint_anchor_repro.sh  the report behind `package.json`: builds the caller layout twice,
                         with the anchor and without, and prints what differs. Needs network, so it
                         is run rather than wired in
  label_map_check.py     labels-from-verdict.json names only tags in the schema and labels in labels.yml
  caller_bundle_check.py the reviewed repository's bundle pin against this one's (§B.6a)
  (the agent-layer tooling is NOT here — the bundle owns it. docs-lint.yml checks exeris-agents out
   into .agents-tools/ and runs it from there; `.agents/` below is this repository's vendored copy)
package.json             anchors this checkout as its own Node project — see commit-lint.yml for what walks up without it
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
docs-guardrails-review.md          the [L2] review routine — one copy, read by every repository
pr-review.patch.md                 the router patch that places the routine inside pr-review.md
labels.yml                         the organisation label taxonomy (issue-conventions.md rule 3)
labels-from-verdict.json           which verdict field applies which label from labels.yml (§B.7)
.agents/
  manifest.yaml                    the exeris-agents pin: bundle, version, ref, sha256
  vendor/exeris-agents-<version>/  the verified vendored copy the schema composes over
  schemas/verdict.schema.json      the organisation's composed verdict — its role, its scope classes,
                                   its `tag` on a finding, and the four objects it closes
docs/adr/ADR-087.link.md           link stub for the ADR this enforcement implements
```

## Installing in a repo

1. Copy `caller-example/guardrails.yml` to `.github/workflows/guardrails.yml`. Keep `mode: ramp` until the frontmatter backfill has landed; keep `section-check: false` until subsystem/module pages carry the required sections.
2. `exeris-docs` passes `extra-paths: "adr rfc *.md"` because its records live at the repo root.
3. JVM repos with a gated module add the `javadoc` job. It takes two module lists, because `javadoc-conventions.md` rule 11 asks two different questions:

   - `modules` — gated in full. Port `java/javadoc-plugin-block.xml` into each of these modules' own `pom.xml` (not the parent: `-am` would gate their dependencies too).
   - `diff-modules` — gated on the pull request's changed files only, which is what rule 11 says for Kernel Core, Community and tooling. **No pom change**: this half invokes `javadoc` directly with the flags the profile would have set, so a module can be put under the gate without being made clean first.
   - `build-modules` — built, never audited. An annotation processor or generator a gated module needs is not reachable by `-am`: `<annotationProcessorPaths>` is not a reactor edge, and without naming it the install step dies on a missing artifact.

   That is the whole adoption cost: the gate checks this bundle out and reads `java/checkstyle-javadoc.xml` from there, and it uses `./mvnw` only if the repo has one.

   One optional input, `trivial-accessors`, is a policy and not a tuning knob. The default, `documented`, is `javadoc-conventions.md` rule 1 as written: every public member carries a doc comment. `exempt` drops that for a method whose BODY SHAPE is mechanical — `return <field>;`, `<field> = <param>;`, either with `return this;` — and a repository takes it only where something else carries the coverage, which for `exeris-sdk` is its own completeness test. It moves both halves: Checkstyle skips those methods and javadoc runs `-Xdoclint:all,-missing`. Doclint does **not** carry the exemption's coverage, it is the half being relaxed — `missing` is the only group that reports an undocumented accessor, so the exemption costs the whole group, and the ruleset buys back what that group was carrying alone (missing docs above private visibility, and on fields and enum constants). A gated module whose pom hardcodes `<doclint>` cannot receive the flag; the gate warns and that module keeps the strict policy. The shape predicate lives in `scripts/javadoc_trivial_members.py`, which filters `MissingJavadocMethod` findings and nothing else: Checkstyle has no property for a body shape, and the one it does have — `minLineCount` — counts a body an abstract method does not have, so it releases 377 abstract contract methods on `exeris-kernel-spi` against 29 getters. The gate writes which policy is in force into the step summary, because a green tick otherwise means two different things in two repositories and the result does not say which.

   It is named for the policy rather than for `minLineCount`, the Checkstyle property behind it. Line count is a poor proxy for triviality — `public Instant deadline() { return start.plus(ttl); }` is exempted along with the setters — and a better predicate should be able to replace it in this bundle without every caller changing a line of YAML.

4. TypeScript packages add the `tsdoc` job. Adoption is two devDependencies (`eslint-plugin-jsdoc`, `eslint-plugin-tsdoc`) and one import in the package's flat config:

   ```js
   import exerisTsdoc from "./.guardrails/ts/eslint.tsdoc.mjs";
   export default tseslint.config(..., ...exerisTsdoc({ gated: ["src/index.ts"] }));
   ```

   Locally, `.guardrails` has to be a **real directory** at that path — a symlink to a bundle checkout elsewhere does not work. Node resolves a module's realpath before searching for `node_modules`, so the fragment's `eslint-plugin-jsdoc` import is looked for beside the bundle instead of beside the package: `ERR_MODULE_NOT_FOUND`, zero files linted. Use a `git worktree` (or a copy) rather than `ln -s`, which also makes the local layout the same as the gate's — CI never hits this because it checks the bundle out.

   The gate checks this bundle out beside the package and **fails if that import is missing** — a flat config cannot be injected from outside, so a lint step that did not verify the reference would only be running the package's own rules.

   The rest is per package and opt-in: copy `ts/tsdoc.json` beside the package's `tsconfig.json`; a library that publishes adds `typedoc` (and `@microsoft/api-extractor`), ports `ts/typedoc.base.json` and `ts/api-extractor.base.json`, and sets `typedoc: true` with `api-report: api-extractor`; an MCP server sets `api-report: mcp-tool-surface`. Both stay off until the package commits the config and the golden they read — **the first golden lands in that build's own pull request, reviewed on its own**, because a golden reviewed alongside a feature is a golden nobody reads.
5. The L2 review comes with the caller's `docs-review` job and needs nothing else to run: it
   produces a review and posts it, as it did before the split. **Publication is opt-in.** Adding
   `publish: true` turns on the second job, which posts the verdict under the organisation's
   identity, applies the labels of `labels-from-verdict.json`, and becomes a check that is red when
   the verdict is absent, invalid, `BLOCKED`, or rests on a mandatory gate that did not run.

   Leave it off until `exeris-systems/.github` has answered ADR-087 Engineering Protocol 4 on its
   own pull requests — whether the runner writes a verdict file, and what identity it posts under.
   When you do turn it on, the check to protect is `docs-review / publish / verdict`, and **confirm
   that name against a real run first**: a required check whose name does not exist never reports,
   and a pull request waiting on one can never merge.

   Two organisation secrets carry the publication, `EXERIS_BOT_APP_ID` and
   `EXERIS_BOT_PRIVATE_KEY`. They are optional — without them the review still runs and the check
   still decides, it is simply not published under the organisation's byline. No permission is added
   either way: every write goes through the App's installation token, so neither job's own
   `GITHUB_TOKEN` holds one.
6. Install the DCO GitHub App on the organisation with `.github/dco.yml` → `require: { members: false }` (org members exempt from the trailer, Spring's model).
7. Delete the repo's own `PULL_REQUEST_TEMPLATE.md` if it has one — the org default applies.
8. Community-health defaults (`CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`) reach every repository without one of its own, from this repository's root. They name two mailboxes and a private reporting channel, so before they are published: `conduct@exeris.eu` and `security@exeris.eu` must deliver, and organisation-level private vulnerability reporting must be on (*Settings → Code security*). A code of conduct whose reporting address bounces is worse than none. Delete a repo's own `SUPPORT.md` or `CODE_OF_CONDUCT.md` only where it says nothing the default does not; `exeris-kernel/SECURITY.md` says more and stays.

## Modes and the ramp

`frontmatter_check.py --mode ramp` fails only on files changed in the PR and downgrades everything else to warnings; `--mode strict` fails on every file. The rollout (ADR-085 Engineering Protocol 4) is: ramp for two weeks on `exeris-sdk` and `exeris-kernel`, then strict there, then fan out. `registry_check.py` and `pr_body_check.py` have no ramp — they check only what the PR introduces.

## Paths in agent files

The agent-file checker (now in `exeris-agents`) warns when an agent file hard-codes a path under somebody's home directory —
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

```bash
pip install pyyaml && pip install vale        # or brew install vale
python scripts/frontmatter_check.py --root docs --mode strict
python scripts/registry_check.py --index ../exeris-docs/adr-index.md
python scripts/caller_permissions_check.py           # the caller blocks and every `with:` key
python scripts/bundle_pin_check.py                   # the vendored bundle is the ref docs-lint uses
python scripts/label_map_check.py                    # the label map names only what exists
python scripts/publish_verdict_suite.py --root .     # the publish step's rules, no network, no token
# agent layer: from the bundle, not from here
git clone https://github.com/exeris-systems/exeris-agents ../exeris-agents
python ../exeris-agents/tools/agents_file_check.py --root .
python ../exeris-agents/tools/agents_render.py --root . --check
npx --package @commitlint/cli --package @commitlint/config-conventional commitlint --config commitlint.config.js --from origin/main
vale --config vale/.vale.ini docs/
```

Vale inline toggles are the sanctioned way to quote a retracted figure on purpose (a withdrawal note, a retraction register):

```markdown
<!-- vale Exeris.RetractedFigures = NO -->
… earlier revisions asserted ">160 GB on a 4 GB payload"; no campaign supports it …
<!-- vale Exeris.RetractedFigures = YES -->
```
