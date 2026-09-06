// exeris-systems/.github — shared ESLint fragment for TS doc comments.
// Enforces tsdoc-conventions.md rules 1-6 and 12 (L1). Spread it into the repo's flat config
// AFTER the type-aware block:
//
//   import exerisTsdoc from "./.guardrails/ts/eslint.tsdoc.mjs";
//   export default tseslint.config(..., ...exerisTsdoc({ gated: ["src/index.ts", "src/public/**/*.ts"] }));
//
// The path is `.guardrails/ts/` — where workflows/tsdoc-gate.yml checks this bundle out — and the
// same string works locally, because every repository carries a `.guardrails` symlink to the local
// bundle checkout. The package must install `eslint-plugin-jsdoc` and `eslint-plugin-tsdoc`
// itself: this file imports them, and Node resolves them from the repository's node_modules.
// That import IS the adoption; the gate cannot inject a flat config from outside, so it verifies
// the reference instead of assuming it.
//
// `gated` = files whose exports are the published surface (rule 1 → error);
// everything else gets rule 1 as a warning so the diff-aware gate can ramp.
import jsdoc from "eslint-plugin-jsdoc";
import tsdoc from "eslint-plugin-tsdoc";

// Rule 12 regex, anchored by measurement (ADR-085 amendment 2026-09-05): each token is tied
// to the verb that makes it past-referential. Unanchored, "no longer", bare "used to" and bare
// "previously" are mostly correct present-tense English ("is used to validate", "deletes any it
// no longer emits"), so they are left to L2. The rule WARNS — archaeology vs. contract is a
// reviewer's call — and mirrors java/checkstyle-javadoc.xml.
const HISTORY = "\\b(previously (returned|threw|was|were|did|had|used|required|allowed|emitted|read|took|lived)|historically|fixed in \\d|used to (be|have|read|emit|export|produce|write|generate|return|take|live|sit|do|call|throw|accept|require|default)|after the .{0,40}(refactor|rewrite|migration)|(PR|issue|bug) #\\d+|workaround for|because of a bug|earlier (version|revision|design|implementation)s?)\\b";

const base = {
  plugins: { jsdoc, tsdoc },
  settings: { jsdoc: { mode: "typescript", tagNamePreference: { author: { message: "@author is banned — Git is the author record (tsdoc-conventions.md rule 5)." }, version: { message: "@version is banned (tsdoc-conventions.md rule 5)." }, return: "returns" } } },
  rules: {
    // rule 2 — syntax is TSDoc, not JSDoc-with-types
    "tsdoc/syntax": "error",
    // rule 2 — summary stands alone; rule 3 — every param/return described
    "jsdoc/require-description": ["error", { descriptionStyle: "body", contexts: ["ExportNamedDeclaration"] }],
    "jsdoc/require-param": ["error", { checkDestructured: false, contexts: ["ExportNamedDeclaration"] }],
    "jsdoc/require-param-description": "error",
    "jsdoc/require-returns": ["error", { contexts: ["ExportNamedDeclaration"], forceReturnsWithAsync: false }],
    "jsdoc/require-returns-description": "error",
    "jsdoc/require-returns-check": "error",
    // rule 3 — TS carries the types; a {type} in a tag is a Java habit
    "jsdoc/no-types": "error",
    "jsdoc/require-param-type": "off",
    "jsdoc/require-returns-type": "off",
    // rule 4 — tag vocabulary is TSDoc core/extended + typedoc's organisational tags; @author/@version banned (rule 5)
    "jsdoc/check-tag-names": ["error", { typed: false, definedTags: ["generated", "public", "beta", "alpha", "internal", "since", "remarks", "example", "defaultValue", "typeParam", "throws", "see", "deprecated", "returns", "param", "link", "linkcode", "inheritDoc", "packageDocumentation", "privateRemarks", "category", "group", "module", "hidden", "sealed", "virtual", "override", "readonly", "eventProperty", "label"] }],
    "jsdoc/check-param-names": "error",
    "jsdoc/check-alignment": "warn",
    "jsdoc/multiline-blocks": "warn",
    "jsdoc/no-restricted-syntax": ["warn", { contexts: [
      // rule 12 — no history in doc comments
      { comment: `JsdocBlock:has(JsdocDescriptionLine[description=/${HISTORY}/i])`, context: "any", message: "Doc comment narrates history — state the contract as it is today; the past belongs in CHANGELOG/ADR (tsdoc-conventions.md rule 12)." },
      { comment: `JsdocBlock:has(JsdocTag[description=/${HISTORY}/i])`, context: "any", message: "Doc comment narrates history — state the contract as it is today; the past belongs in CHANGELOG/ADR (tsdoc-conventions.md rule 12)." },
      // rule 6 — HTML markup does not render in TSDoc/typedoc ({@code} is an error via check-tag-names)
      { comment: "JsdocBlock:has(JsdocDescriptionLine[description=/<p>|\\{@code |<b>|<pre>/])", context: "any", message: "Javadoc markup in a TS doc comment — use Markdown and backticks (tsdoc-conventions.md rule 6)." },
    ]}],
  },
};

export default function exerisTsdoc({ gated = [], files = ["src/**/*.ts"], tests = ["**/*.test.ts", "**/*.spec.ts", "test/**", "tests/**"] } = {}) {
  return [
    { files, ignores: tests, ...base,
      rules: { ...base.rules, "jsdoc/require-jsdoc": ["warn", { publicOnly: true, require: { FunctionDeclaration: true, ClassDeclaration: true, MethodDefinition: false }, contexts: ["TSInterfaceDeclaration", "TSTypeAliasDeclaration", "TSEnumDeclaration", "ExportNamedDeclaration > VariableDeclaration"] }] } },
    ...(gated.length ? [{ files: gated, rules: { "jsdoc/require-jsdoc": ["error", { publicOnly: true, require: { FunctionDeclaration: true, ClassDeclaration: true, MethodDefinition: true }, contexts: ["TSInterfaceDeclaration", "TSTypeAliasDeclaration", "TSEnumDeclaration", "TSPropertySignature", "TSMethodSignature", "ExportNamedDeclaration > VariableDeclaration"] }] } }] : []),
    { files: tests, rules: { "jsdoc/require-jsdoc": "off", "jsdoc/require-description": "off", "jsdoc/require-param": "off", "jsdoc/require-returns": "off" } },
  ];
}
