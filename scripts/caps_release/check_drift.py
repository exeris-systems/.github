#!/usr/bin/env python3
"""The committed generated tree must be what the build produced.

`exeris:generate` writes into the source tree and that tree is committed, so a build whose output
differs from the committed copy means the declaration and the manifest a consumer reads disagree.
`git status --porcelain --untracked-files=all` over the path catches a modified file, a deleted one
and a file the build added.

The path is a directory, not a pathspec. It is resolved through symbolic links and must then be an
existing directory inside the repository that holds at least one tracked file; a path that names
nothing, that leaves the repository, or that holds no tracked file would otherwise check nothing and
report the tree clean. git receives the resolved, repository-relative path literally
(`--literal-pathspecs`), so a pathspec magic prefix (`:(exclude)`) or a glob character in it is a file
name and not an instruction.

Usage: check_drift.py --repo DIR --generated PATH [--uploaded]

  --repo       the working tree; `git` runs there
  --generated  repository-relative path of the generated tree; empty is refused
  --uploaded   the run has already uploaded: the refusal also tells the reader to drop the deployment

Exit status: 0 no difference; 1 a difference, an empty or unusable path, or `git` failing (a tree that
cannot be asked is not a clean one); 2 usage error.
Output: on a difference, the porcelain status and the diff on stdout, the refusal on stderr.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


GIT_TIMEOUT = 300


def git(repo: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1"}
    try:
        return subprocess.run(["git", "--literal-pathspecs", "-C", repo, *args], capture_output=True, text=True, env=env,
                              timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", f"git timed out after {GIT_TIMEOUT} seconds")


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the drift check failed unexpectedly ({type(exc).__name__}: {' '.join(str(exc).split())}).",
              file=sys.stderr)
        return 1


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", required=True)
    p.add_argument("--generated", required=True)
    p.add_argument("--uploaded", action="store_true")
    a = p.parse_args(argv)
    if not a.generated:
        print("::error::the generated path is empty.", file=sys.stderr)
        return 1
    shown = a.generated.encode("unicode_escape").decode("ascii")

    inside = git(a.repo, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0:
        print(f"::error::git could not report on {shown}: {' '.join(inside.stderr.split())}", file=sys.stderr)
        return 1

    root = os.path.realpath(a.repo)
    resolved = os.path.realpath(os.path.join(root, a.generated))
    if os.path.commonpath([root, resolved]) != root:
        print(f"::error::{shown} leaves the repository (it resolves to {resolved.encode('unicode_escape').decode('ascii')}).",
              file=sys.stderr)
        return 1
    if not os.path.isdir(resolved):
        print(f"::error::{shown} is not a directory in the repository; a path that names nothing checks nothing.",
              file=sys.stderr)
        return 1
    rel = os.path.relpath(resolved, root)

    tracked = git(a.repo, "ls-files", "-z", "--", rel)
    if tracked.returncode != 0:
        print(f"::error::git could not report on {shown}: {' '.join(tracked.stderr.split())}", file=sys.stderr)
        return 1
    if not tracked.stdout:
        print(f"::error::{shown} holds no tracked file; a generated tree that is not committed cannot be compared.",
              file=sys.stderr)
        return 1

    status = git(a.repo, "status", "--porcelain", "--untracked-files=all", "--", rel)
    if status.returncode != 0:
        print(f"::error::git could not report on {shown}: {' '.join(status.stderr.split())}", file=sys.stderr)
        return 1
    if status.stdout.strip():
        print(status.stdout.rstrip())
        print(git(a.repo, "diff", "--", rel).stdout.rstrip())
        tail = " If a deployment was uploaded, DROP it." if a.uploaded else \
            " Run the two-pass build and commit the result."
        print(f"::error::{shown} does not match what this build produced.{tail}", file=sys.stderr)
        return 1
    print(f"ok - {a.generated} is what this build produces")
    return 0


if __name__ == "__main__":
    sys.exit(main())
