// Exeris commit conventions — ADR-085 §D, exeris-docs/standards/commit-conventions.md
// Applied to every PR commit and to the PR title (the squash-commit subject) by workflows/commit-lint.yml.
// Rule levels: 2 = error, 1 = warning, 0 = off.

const TYPES = ['feat', 'fix', 'docs', 'chore', 'refactor', 'test', 'build', 'ci', 'perf', 'release', 'report', 'research', 'revert'];
const MMR_TYPES = ['feat', 'fix', 'perf', 'refactor', 'release'];
const MMR_SECTIONS = ['Motivation:', 'Modification:', 'Result:'];

/** Squash-merge appends " (#123)" to the subject; strip it before measuring or parsing. */
const stripPrSuffix = (header) => header.replace(/\s\(#\d+\)$/, '');

module.exports = {
  extends: ['@commitlint/config-conventional'],
  parserPreset: {
    parserOpts: {
      // conventional parser, but tolerate the squash suffix and unicode scopes such as "entity-read-by-id"
      headerPattern: /^(\w+)(?:\(([\w.-]+)\))?(!)?: (.+?)(?:\s\(#\d+\))?$/,
      headerCorrespondence: ['type', 'scope', 'breaking', 'subject'],
    },
  },
  ignores: [
    (msg) => /^(Merge|Revert) /.test(msg),                 // merge/revert commits
    (msg) => /^(build|ci)\(deps.*\): bump /.test(msg),     // Dependabot
    (msg) => /^Fast-forward$/.test(msg),
  ],
  plugins: [
    {
      rules: {
        // commit-conventions.md rule 3: feat/fix/perf/refactor/release bodies carry Motivation / Modification / Result
        'exeris-mmr-sections': ({ type, body }) => {
          if (!MMR_TYPES.includes(type)) return [true];
          const text = body || '';
          const missing = MMR_SECTIONS.filter((s) => !new RegExp(`^${s}`, 'm').test(text));
          const ordered = MMR_SECTIONS.map((s) => text.indexOf(s)).every((v, i, a) => i === 0 || v > a[i - 1]);
          if (missing.length) return [false, `body of a '${type}' commit must contain: ${missing.join(' ')}`];
          if (!ordered) return [false, 'Motivation / Modification / Result must appear in that order'];
          return [true];
        },
        // commit-conventions.md rule 2: ≤ 100 chars after removing the squash suffix
        'exeris-header-length': ({ header }) => {
          const len = stripPrSuffix(header || '').length;
          return [len <= 100, `subject is ${len} characters; the limit is 100 (move the second clause into the body)`];
        },
        // commit-conventions.md rule 4: trailer grammar (only checked when present)
        'exeris-trailers': ({ body, footer }) => {
          const text = `${body || ''}\n${footer || ''}`;
          const bad = [];
          for (const line of text.split('\n')) {
            const s = line.trim();
            if (/^Refs:/.test(s) && !/^Refs: ADR-\d{3}(\s*,\s*ADR-\d{3})*$/.test(s)) bad.push(s);
            if (/^(Closes|Fixes) /.test(s) && !/^(Closes|Fixes) #\d+(\s*,\s*#\d+)*$/.test(s)) bad.push(s);
            if (/^Claim:/.test(s) && !/^Claim: [A-Z]-\d+$/.test(s)) bad.push(s);
          }
          return [bad.length === 0, `trailer(s) do not match the grammar: ${bad.join(' | ')}`];
        },
      },
    },
  ],
  rules: {
    'type-enum': [2, 'always', TYPES],
    'type-case': [2, 'always', 'lower-case'],
    'scope-case': [2, 'always', 'kebab-case'],
    'subject-case': [0],                        // house style capitalises identifiers freely
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],
    'header-max-length': [0],                   // replaced by exeris-header-length (squash-suffix aware)
    'exeris-header-length': [2, 'always'],
    'body-max-line-length': [1, 'always', 100],  // warning only: narrative bodies wrap where they wrap
    'footer-max-line-length': [0],
    'exeris-mmr-sections': [2, 'always'],
    'exeris-trailers': [2, 'always'],
  },
};
