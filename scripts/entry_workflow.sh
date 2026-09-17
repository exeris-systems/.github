#!/bin/sh
# Is the workflow file this run ENTERED THROUGH among the paths changed by the pull request?
#
# ADR-087's human-review override turns on the answer, so the question has to be the one the
# runner action actually asks. Its guard is about the workflow it was invoked from — "the workflow
# file must exist and have identical content to the version on the repository's default branch" —
# and a REUSABLE workflow that run calls is not that file. Measured 2026-09-17: a pull request
# changing its repository's own `guardrails.yml` was refused in five seconds with no verdict; one
# changing a called `docs-review.yml` was reviewed for six and a half minutes.
#
# A file, not an inline snippet, because the step that used to hold it could not be exercised: it
# fetched the file list and decided in one breath, so nothing could drive the decision with a
# fixture. This half takes the list on stdin and prints `true` or `false`, and
# `entry_workflow_suite.py` drives it.
#
# Usage: <changed paths on stdin> entry_workflow.sh "$GITHUB_WORKFLOW_REF" "$GITHUB_REPOSITORY"
set -eu

ref=${1:-}
repo=${2:-}

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

# `grep -qxF`: whole line, literal. A prefix match is what this file exists to stop being.
if grep -qxF "$entry"; then echo "true"; else echo "false"; fi
