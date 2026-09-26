#!/usr/bin/env python3
"""Changed files that say they are generated, and what they are generated from — ADR-087.

A renderer writes a copy and marks it: `DO NOT EDIT. Generated from <source> by <tool>`, in a
comment near the top. Nobody authors the copy, so a finding about its content is a finding about the
source. Where the source is in the same pull request that is where it belongs; where the source
lives elsewhere, in a bundle or in another repository, the pull request carrying the copy cannot fix
it. A reviewer who is not told which files are copies reports the source's text once per copy, as
though each were written here.

The copy is read from the pull request's own commit, not the working tree: some of these paths are
restored to the base before the reviewer starts, and what the pull request wrote is the question.

Usage: generated_paths.py --pr pull-request.json [--rev HEAD] [--out generated-paths.txt]
  Writes one line per generated file, `<path>\\t<source>`.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

# Only a marker in a comment counts: a page explaining generated files may quote the phrase, and
# that page is authored. The source is the first token after "Generated from".
MARKER = re.compile(r"^\s*(?:#|//|<!--|/\*|\*)\s*DO NOT EDIT\.\s+Generated from\s+(\S+)")

# How far down the marker may sit. Far enough to clear a frontmatter block, which a rendered
# adapter carries above it; near enough that a marker quoted deep in a file is not read as its own.
HEAD_LINES = 40


def source_of(text: str) -> str | None:
    """The source a file's header names, or None when it names none."""
    for line in text.splitlines()[:HEAD_LINES]:
        found = MARKER.match(line)
        if found:
            return found.group(1)
    return None


def read_at(rev: str, path: str) -> str | None:
    """The file as `rev` has it; None when `rev` does not have it, which is a deletion."""
    shown = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True)
    if shown.returncode != 0:
        return None
    return shown.stdout.decode("utf-8", errors="replace")


def generated(paths: list[str], rev: str) -> list[tuple[str, str]]:
    out = []
    for path in paths:
        text = read_at(rev, path)
        source = source_of(text) if text is not None else None
        if source:
            out.append((path, source))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", required=True)
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--out", default="generated-paths.txt")
    a = ap.parse_args(argv)
    with open(a.pr, encoding="utf-8") as fh:
        paths = [f["path"] for f in json.load(fh).get("files") or []]
    found = generated(paths, a.rev)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.writelines(f"{path}\t{source}\n" for path, source in found)
    print(f"generated_paths: {len(found)} of {len(paths)} changed file(s) are generated copies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
