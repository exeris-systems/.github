#!/usr/bin/env python3
"""Emit the Markdown globs for tools that take a glob list rather than a walk root.

`walk_md` in _common.py is the single definition of what counts as documentation; the Python
checkers get it for free. markdownlint takes globs instead, so this prints the same taxonomy in
its form. Vale and lychee carry their own configuration files, which mirror the same lists by
hand — each says so, and each names this module.

Usage: lint_globs.py [--root .] [--exclude 'dir another/dir']
"""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import SKIP_DIRS, SKIP_PATHS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--exclude", default="", help="space-separated extra paths to skip")
    a = ap.parse_args()
    root = a.root.rstrip("/") or "."
    prefix = "" if root == "." else f"{root}/"
    out = [f"{prefix}**/*.md"]
    for d in SKIP_DIRS:
        out.append(f"!{prefix}**/{d}/**")
    for pth in SKIP_PATHS:
        out.append(f"!{prefix}{pth}/**")
    # "_"-prefixed working directories are local-only by convention (see _common.walk_md).
    out.append(f"!{prefix}**/_*/**")
    for extra in a.exclude.split():
        out.append(f"!{extra.rstrip('/')}/**")
    print("\n".join(out))


if __name__ == "__main__":
    main()
