#!/bin/sh
# Does the pull request change the workflow file this run ENTERED THROUGH, or a workflow of the same
# repository that file calls?
#
# ADR-087's human-review override turns on the answer, so the question has to be the one the
# runner action actually asks. Its guard refuses to start when the workflow it was invoked from
# differs from the default branch's copy, and also when "a reusable workflow in this repository that
# the workflow calls (uses: ./.github/workflows/…)" does. A workflow called from ANOTHER repository
# (`uses: owner/repo/.github/workflows/…@ref`) is not part of that check, and neither is a workflow
# of this repository the entry does not call: a pull request changing either is reviewed normally.
#
# A file, not an inline snippet, because the step that used to hold it could not be exercised: it
# fetched the file list and decided in one breath, so nothing could drive the decision with a
# fixture. This half takes the list on stdin and prints `true` or `false`, and
# `entry_workflow_suite.py` drives it.
#
# The entry's own text, needed only when the diff changes some other workflow file, is read from
# <entry-file> when one is given, and otherwise from the ref the run entered through. A read that
# fails exits non-zero rather than answering: `false` would keep the override from a pull request
# the review cannot read, and `true` would hand it to one the review could.
#
# Usage: <changed paths on stdin> entry_workflow.sh "$GITHUB_WORKFLOW_REF" "$GITHUB_REPOSITORY" [<entry-file>]
set -eu

ref=${1:-}
repo=${2:-}
entry_file=${3:-}

# `owner/repo/.github/workflows/guardrails.yml@refs/pull/56/merge` → `.github/workflows/guardrails.yml`
entry=${ref%%@*}
case "$entry" in
  "$repo"/*) entry=${entry#"$repo"/} ;;
esac

# Fail closed. An empty or unrecognisable ref means the question was not answered, and answering
# `false` there would hand the override to a pull request nobody established it covers.
case "$entry" in
  .github/workflows/*) ;;
  *) echo "false"; exit 0 ;;
esac

changed=$(cat)

# `grep -qxF`: whole line, literal. A prefix match is what this file exists to stop being.
if printf '%s\n' "$changed" | grep -qxF "$entry"; then echo "true"; exit 0; fi

# No other workflow file in the diff: nothing the entry calls can have changed, and nothing is read.
others=$(printf '%s\n' "$changed" | grep -E '^\.github/workflows/[^/]+\.ya?ml$' || true)
if [ -z "$others" ]; then echo "false"; exit 0; fi

if [ -z "$entry_file" ]; then
  entry_file=$(mktemp)
  trap 'rm -f "$entry_file"' EXIT
  gh api -H "Accept: application/vnd.github.raw" \
    "repos/$repo/contents/$entry?ref=${ref#*@}" > "$entry_file"
fi

# The workflows the entry calls from its own repository: `uses: ./.github/workflows/<file>`, quoted
# or not. A call to another repository starts with its owner, not `./`, and is not matched.
called=$(sed -n "s|^[[:space:]]*uses:[[:space:]]*[\"']\{0,1\}\./\(\.github/workflows/[^\"'@#[:space:]]*\).*|\1|p" \
  "$entry_file")
for path in $called; do
  if printf '%s\n' "$others" | grep -qxF "$path"; then echo "true"; exit 0; fi
done
echo "false"
