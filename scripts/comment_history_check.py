#!/usr/bin/env python3
"""A comment carries the contract, not the history — for the languages no other gate reads.

`comment-conventions.md` binds every comment in every language. Two gates enforce it: Checkstyle
over Java doc comments and ESLint over TypeScript ones. Neither reads Python, YAML or shell, so in
a repository written in those the rule binds and nothing checks it.

This is that check. It reads the tokens from `comment-history.json`, which is where they are
authored, and warns — never fails. Whether a sentence is archaeology or a statement about the
present is a reviewer's call, and a build that stops on the difference decides it wrongly in one
direction every time.

Only comments are read. A history token inside a string literal or an identifier is data, not a
claim about the code, and a check that cannot tell them apart is one people learn to ignore.

    python3 scripts/comment_history_check.py [--root .] [--exclude 'path path']
    python3 scripts/comment_history_check.py --emit-checkstyle   # the XML's `format`, regenerated
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import sys
import tokenize

sys.path.insert(0, os.path.dirname(__file__))
from _common import Report, SKIP_DIRS, SKIP_PATHS                      # noqa: E402

TOKENS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "comment-history.json")
# Java and TypeScript are owned by Checkstyle and ESLint, which read the same tokens from the same
# file. A third reader of the same sources would report each finding twice.
HASH_SUFFIXES = (".py", ".yml", ".yaml", ".sh", ".bash", ".toml", ".cfg", ".ini")
HASH_NAMES = ("Dockerfile", "Makefile")


def alternatives(path: str = TOKENS) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["alternatives"]


def pattern(path: str = TOKENS) -> re.Pattern:
    return re.compile("|".join(alternatives(path)), re.IGNORECASE)


def checkstyle_format(path: str = TOKENS) -> str:
    """The `format` attribute `java/checkstyle-javadoc.xml` must carry.

    Checkstyle reads no JSON, so the XML holds a copy. A copy nothing compares is a copy that
    drifts, which is what `comment_history_suite.py` asserts and what this prints.
    """
    return r"^\s*\*.*(" + "|".join(alternatives(path)) + ")"


def hash_comments(text: str) -> list[tuple[int, str]]:
    """`#` comments, with a `#` inside a quoted string left alone."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        quote, i = None, 0
        while i < len(line):
            ch = line[i]
            if quote:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                found.append((n, line[i + 1:]))
                break
            i += 1
    return found


def python_comments(text: str) -> list[tuple[int, str]]:
    """`#` comments and docstrings. A string that is not a docstring is data and is not read."""
    found = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                found.append((tok.start[0], tok.string.lstrip("#")))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        found.extend(hash_comments(text))
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                line = getattr(node.body[0], "lineno", 1) if node.body else 1
                found.extend((line + i, text_line)
                             for i, text_line in enumerate(doc.splitlines()))
    return found


def comments_of(path: str, text: str) -> list[tuple[int, str]]:
    name, suffix = os.path.basename(path), os.path.splitext(path)[1]
    if suffix == ".py":
        return python_comments(text)
    if suffix in HASH_SUFFIXES or name in HASH_NAMES:
        return hash_comments(text)
    return []


def walk(root: str, exclude: tuple[str, ...] = ()) -> list[str]:
    out = []
    for d, dirnames, filenames in os.walk(root):
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS and not x.startswith("_")]
        rel_dir = os.path.relpath(d, root)
        if any(rel_dir == p or rel_dir.startswith(p + os.sep) for p in SKIP_PATHS + exclude):
            continue
        for f in filenames:
            if os.path.splitext(f)[1] in HASH_SUFFIXES or f in HASH_NAMES:
                out.append(os.path.join(d, f))
    return sorted(out)


def check_text(path: str, text: str, rex: re.Pattern, rep: Report) -> None:
    rep.checked += 1
    for line, comment in comments_of(path, text):
        hit = rex.search(comment)
        if hit:
            rep.warning(path, f"comment narrates history ({hit.group(0).strip()!r}) — state the "
                              f"contract as it is today; what changed belongs in the commit or the "
                              f"changelog, what happened in an issue "
                              f"(comment-conventions.md rule 1)",
                        line=line, rule="history")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--emit-checkstyle", action="store_true")
    a = ap.parse_args(argv)
    if a.emit_checkstyle:
        print(checkstyle_format())
        return 0
    rex = pattern()
    rep = Report(name="comment_history_check")
    for path in walk(a.root, tuple(x for x in a.exclude.split() if x)):
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        check_text(os.path.relpath(path, a.root), text, rex, rep)
    return rep.emit()


if __name__ == "__main__":
    sys.exit(main())
