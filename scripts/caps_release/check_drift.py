#!/usr/bin/env python3
"""The committed generated tree must be what the build produced.

`exeris:generate` writes into the source tree and that tree is committed, so a build whose output
differs from the committed copy means the declaration and the manifest a consumer reads disagree.
`git status --porcelain --untracked-files=all` over the path catches a modified file, a deleted one
and a file the build added.

Usage: check_drift.py --repo DIR --generated PATH [--uploaded]

  --repo       the working tree; `git` runs there
  --generated  repository-relative path of the generated tree; empty is refused
  --uploaded   the run has already uploaded: the refusal also tells the reader to drop the deployment

Exit status: 0 no difference; 1 a difference, an empty path, or `git` failing (a tree that cannot be
asked is not a clean one); 2 usage error.
Output: on a difference, the porcelain status and the diff on stdout, the refusal on stderr.
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", required=True)
    p.add_argument("--generated", required=True)
    p.add_argument("--uploaded", action="store_true")
    a = p.parse_args(argv)
    if not a.generated:
        print("::error::the generated path is empty.", file=sys.stderr)
        return 1
    status = git(a.repo, "status", "--porcelain", "--untracked-files=all", "--", a.generated)
    if status.returncode != 0:
        print(f"::error::git could not report on {a.generated}: {status.stderr.strip()}", file=sys.stderr)
        return 1
    if status.stdout.strip():
        print(status.stdout.rstrip())
        print(git(a.repo, "diff", "--", a.generated).stdout.rstrip())
        tail = " If a deployment was uploaded, DROP it." if a.uploaded else \
            " Run the two-pass build and commit the result."
        print(f"::error::{a.generated} does not match what this build produced.{tail}", file=sys.stderr)
        return 1
    print(f"ok - {a.generated} is what this build produces")
    return 0


if __name__ == "__main__":
    sys.exit(main())
