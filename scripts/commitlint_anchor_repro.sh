#!/usr/bin/env bash
# The report behind the numbers in the pull request that added this repository's `package.json`.
#
# A caller checks this repository out as `.guardrails/` inside its own workspace. Without a
# `package.json` here, Node and npm both walk UP looking for a project root and find the CALLER's.
# This builds the caller layout twice -- once without the anchor and once with it -- runs the exact
# commands `commit-lint.yml` runs, and prints what differs.
#
# Needs network: it installs `@commitlint/cli@19` in each state, as the workflow does. That is why
# it is a reproduction to run rather than a gate to wire in.
#
# Usage: scripts/commitlint_anchor_repro.sh [workdir]        (default: a fresh mktemp -d)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${1:-$(mktemp -d)}"
CONFIG="$HERE/commitlint.config.js"
ANCHOR="$HERE/package.json"

[ -f "$CONFIG" ] || { echo "no commitlint.config.js beside this script" >&2; exit 2; }

# One conforming message. Green here means the config loaded AND its rules ran.
MSG=$'fix(x): a subject\n\nMotivation:\na\n\nModification:\nb\n\nResult:\nc\n'
# One that must fail, so a "pass" cannot come from a config that loaded empty.
BAD=$'fix(x): a subject\n\nno sections here\n'

state() {
  local name="$1"
  local anchored="$2"
  local dir="$WORK/$name"
  rm -rf "$dir"; mkdir -p "$dir/.guardrails"
  printf '{\n  "name": "caller",\n  "type": "module",\n  "private": true\n}\n' > "$dir/package.json"
  local before; before=$(sha256sum < "$dir/package.json" | cut -d' ' -f1)
  cp "$CONFIG" "$dir/.guardrails/"
  [ "$anchored" = yes ] && cp "$ANCHOR" "$dir/.guardrails/"

  ( cd "$dir/.guardrails" && npm install --no-audit --no-fund --silent \
      @commitlint/cli@19 @commitlint/config-conventional@19 >/dev/null 2>&1 ) || true

  local after; after=$(sha256sum < "$dir/package.json" | cut -d' ' -f1)
  local where="neither"
  [ -d "$dir/node_modules" ] && where="caller root"
  [ -d "$dir/.guardrails/node_modules" ] && where=".guardrails/"

  local load rules
  if ( cd "$dir" && printf '%s' "$MSG" | npx --prefix .guardrails commitlint \
        --config .guardrails/commitlint.config.js >/dev/null 2>&1 ); then load="loads"; else load="FAILS"; fi
  if ( cd "$dir" && printf '%s' "$BAD" | npx --prefix .guardrails commitlint \
        --config .guardrails/commitlint.config.js >/dev/null 2>&1 ); then load="$load (but a bad message passed)"; fi
  rules=$(cd "$dir" && node -e \
    "try{const c=require('./.guardrails/commitlint.config.js');console.log(Object.keys(c.rules).length+' rules, '+(c.plugins||[]).length+' plugin(s)')}catch(e){console.log('-')}" 2>/dev/null || echo -)

  printf '%-14s | %-30s | %-14s | %s\n' "$name" "$load" "$where" \
    "$([ "$before" = "$after" ] && echo 'manifest unchanged' || echo 'MANIFEST REWRITTEN')"
  printf '%-14s | %s\n' "" "$rules"
}

echo "node $(node --version), npm $(npm --version)"
printf '%-14s | %-30s | %-14s | %s\n' "state" "conforming message" "node_modules" "caller package.json"
printf -- '---------------+--------------------------------+----------------+--------------------\n'
state "no-anchor" no
state "anchored" yes
echo
echo "workdir: $WORK"
