#!/usr/bin/env python3
"""Which parts of `docs-guardrails-review.md` a pull request's review runs — ADR-087.

The routine is grouped into parts, and a part judges only the files its `## Part` heading names.
Where a pull request has none of them the part would find nothing and say nothing, so it is not run
at all: the plan names it as skipped and says why, and the aggregated verdict carries that sentence
where a reader looks for the part. `pr` is never skipped, because its subject is the pull request
itself; `repo` runs whenever the calling repository passes an extension, for the same reason.

A skipped part is a statement, never an absence. A part the plan runs and that then produces no
verdict is `missing`, and the aggregate is incomplete: this file decides what is expected, and it
is the aggregate's job to hold the runs to it.

The scopes below and the routine's headings are two copies of one list. The suite compares them.

Usage: review_plan.py --files FILE [--repo-routine PATH] [--out plan.json]
  FILE holds one changed path per line, as the pull request's files list names them. With
  GITHUB_OUTPUT set, `parts` (a JSON array, the matrix) and `skipped` (a JSON object) are written
  there as well.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import sys

# The order is the order the aggregate reports parts in: the pull request first, then what it
# changed, then the repository's own rules.
PARTS = ("pr", "docs", "records", "code-docs", "code", "repo")

CODE_SUFFIXES = (".java", ".ts", ".py", ".yml", ".yaml", ".sh")

# What `code` judges is behaviour, so it reaches further than the comments do: every language a
# build runs, and the build files that decide what consumers receive.
SOURCE_SUFFIXES = (".java", ".kt", ".ts", ".tsx", ".js", ".mjs", ".py", ".sh", ".yml", ".yaml")
BUILD_FILES = ("pom.xml", "package.json", "build.gradle", "build.gradle.kts",
               "settings.gradle", "settings.gradle.kts")


def in_docs(path: str) -> bool:
    """Every Markdown page, records included, and the one agent file that is not Markdown."""
    return path.endswith(".md") or posixpath.basename(path) == ".cursorrules"


def in_records(path: str) -> bool:
    """ADRs, the registry, the stubs that point at an ADR elsewhere, and the standards."""
    dirs, base = path.split("/")[:-1], posixpath.basename(path)
    return (base == "adr-index.md" or base.endswith(".link.md")
            or "adr" in dirs or "standards" in dirs)


def in_code_docs(path: str) -> bool:
    """Files whose comments or doc comments the routine judges, and the API goldens."""
    dirs = path.split("/")[:-1]
    return (path.endswith(CODE_SUFFIXES) or "api" in dirs
            or "/src/tools/" in "/" + path or "generated" in dirs)


def in_code(path: str) -> bool:
    """Source, scripts, workflows and build files, and not generated output: a generated file
    changes because its generator did, and the generator is the code under review."""
    dirs, base = path.split("/")[:-1], posixpath.basename(path)
    return (path.endswith(SOURCE_SUFFIXES) or base in BUILD_FILES) and "generated" not in dirs


# A bundle vendored whole at a pinned digest. Its content is the bundle repository's to judge, and a
# pull request carrying it cannot fix a finding about it, so it counts for no part.
VENDORED = ".agents/vendor/"


SCOPES = {
    "docs": (in_docs, "no `*.md` and no `.cursorrules` in the diff"),
    "records": (in_records, "no ADR, `adr-index.md`, `*.link.md` or `standards/` file in the diff"),
    "code-docs": (in_code_docs, "no Java, TypeScript, Python, YAML or shell file, API golden or "
                                "generated output in the diff"),
    "code": (in_code, "no source, script, workflow or build file outside generated output in the "
                      "diff"),
}


def plan(files: list[str], repo_routine: str) -> dict:
    """`{"parts": [...], "skipped": {part: reason}}`, every part in exactly one of the two."""
    paths = [f.strip().removeprefix("./") for f in files if f.strip()]
    vendored = [p for p in paths if p.startswith(VENDORED)]
    paths = [p for p in paths if not p.startswith(VENDORED)]
    run, skipped = [], {}
    for part in PARTS:
        if part == "pr":
            run.append(part)
        elif part == "repo":
            if repo_routine.strip():
                run.append(part)
            else:
                skipped[part] = "the repository passes no `repo-routine`"
        else:
            applies, reason = SCOPES[part]
            if any(applies(p) for p in paths):
                run.append(part)
            elif vendored:
                skipped[part] = (f"{reason}; the {len(vendored)} vendored file(s) under "
                                 f"`{VENDORED}` are the bundle's, and no part judges them")
            else:
                skipped[part] = reason
    return {"parts": run, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", required=True)
    ap.add_argument("--repo-routine", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    with open(a.files, encoding="utf-8") as fh:
        result = plan(fh.read().splitlines(), a.repo_routine)
    text = json.dumps(result, indent=2) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"parts={json.dumps(result['parts'])}\n")
            fh.write(f"skipped={json.dumps(result['skipped'])}\n")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
