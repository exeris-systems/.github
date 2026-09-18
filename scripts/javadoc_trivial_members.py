#!/usr/bin/env python3
"""Rule 1's trivial-member exemption, decided by BODY SHAPE rather than by line count.

`javadoc-conventions.md` rule 1 requires a doc comment on every public member of a
gated module, with one exemption for a member that is purely mechanical -- a getter
that returns a field, a setter that assigns one. Checkstyle cannot express that: its
only predicate is `MissingJavadocMethod.minLineCount`, the number of lines in the
body, which measures brevity and not triviality.

Measured 2026-09-18 on corpora stripped of doc comments, so the exempt set is visible:

    corpus                    public  exempted by  of which  short but   actually
                              methods  line count  NO BODY   contractful mechanical
    exeris-kernel-spi            938    689 (73%)      377       259         52
    exeris-kernel-tck            259     55 (21%)       10        35         10
    exeris-sdk-source-model      447    393 (88%)        2       186        205

An abstract method has no body, so its body is zero lines, so `minLineCount=1`
releases it: on `exeris-kernel-spi` that predicate releases 377 abstract contract
methods -- the surface a driver implementor reads -- against 29 getters. The released
set resembles accessors only on a record-and-builder corpus.

So the predicate lives here and Checkstyle stays strict. Checkstyle parses the Java,
resolves the scopes and decides who needs a comment; this filter answers one question
about a member it has already flagged: is the body one of the shapes below, exactly?

    return <field>;                        a getter, no parameters
    return this.<field>;
    <field> = <param>;                     a setter, exactly one parameter
    this.<field> = <param>;
    <field> = <param>; return this;        a fluent setter
    this.<field> = <param>; return this;

That is the whole set, enumerated rather than described, so that what is exempt can
be read rather than judged. Anything else survives: a method with no body, a
constant return, a delegation, a computation, a setter that validates, a getter that
copies. `public Instant deadline() { return start.plus(ttl); }` survives here and is
under any line-count threshold.

THE FILTER FAILS CLOSED. Every path that cannot reach a confident answer -- a file
that will not read, a declaration whose body cannot be found, a body that does not
match a shape exactly -- keeps the finding. A member is exempted only by a rule that
fired, never by a check that gave up.

Usage:
    checkstyle ... > report.txt || true
    python3 scripts/javadoc_trivial_members.py --policy exempt --report report.txt

Exit status is 0 when nothing survives and 1 when something does, with the count
printed rather than returned. `com.puppycrawl.tools.checkstyle.Main` returns the
count, and a process exit status is eight bits: 909 surviving findings on
`exeris-kernel-spi` arrive as 141, and exactly 256 arrive as 0 and read as clean. The
gate asks only whether the step failed, so nothing is lost by keeping the number out
of the byte.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# `[ERROR] /abs/path/Thing.java:23:5: Missing a Javadoc comment. [MissingJavadocMethod]`
FINDING = re.compile(r"^\[(?P<severity>[A-Z]+)\]\s+(?P<path>.+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s+(?P<message>.*?)\s*\[(?P<check>\w+)\]\s*$")

# The only check this filter may touch. A finding from any other check passes through
# untouched even under `exempt`: this is rule 1's exemption, not a general silencer.
FILTERED_CHECK = "MissingJavadocMethod"

IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
SHAPES = (
    ("GETTER", 0, re.compile(rf"^return\s+(?:this\.)?(?P<field>{IDENT})\s*;$")),
    ("FLUENT_SETTER", 1, re.compile(rf"^(?:this\.)?(?P<field>{IDENT})\s*=\s*(?P<value>{IDENT})\s*;\s*return\s+this\s*;$")),
    ("SETTER", 1, re.compile(rf"^(?:this\.)?(?P<field>{IDENT})\s*=\s*(?P<value>{IDENT})\s*;$")),
)


def _strip_literals_and_comments(text: str) -> str:
    """Blank out comments and literals, preserving length so offsets stay usable.

    Crude on purpose and safe by direction: a construct this mis-reads yields a body
    that matches no shape, and an unmatched body keeps its finding.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif two == "/*":
            while i < n and text[i:i + 2] != "*/":
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            for _ in range(2):
                if i < n:
                    out[i] = " "
                    i += 1
        elif text[i:i + 3] == '"""':
            for _ in range(3):
                out[i] = " "
                i += 1
            while i < n and text[i:i + 3] != '"""':
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            for _ in range(3):
                if i < n:
                    out[i] = " "
                    i += 1
        elif text[i] in ('"', "'"):
            quote = text[i]
            out[i] = " "
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\":
                    out[i] = " "
                    i += 1
                    if i < n:
                        out[i] = " "
                        i += 1
                    continue
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def member_at(path: Path, line: int) -> tuple[str, str | None, str | None]:
    """Return (kind, parameter list, body) for the member declared at `line`.

    `kind` is BODY, NO_BODY or UNREADABLE. Checkstyle reports the member's first
    modifier or annotation, so the declaration is scanned forward from there: the
    first `{` or `;` outside parentheses ends it. Parenthesis depth is what keeps an
    annotation's own braces -- `@Foo({1, 2})` -- from being read as a body.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ("UNREADABLE", None, None)
    lines = raw.splitlines(keepends=True)
    if not 1 <= line <= len(lines):
        return ("UNREADABLE", None, None)

    start = sum(len(l) for l in lines[: line - 1])
    masked = _strip_literals_and_comments(raw)

    paren = 0
    params: str | None = None
    param_start = -1
    i = start
    n = len(masked)
    while i < n:
        ch = masked[i]
        if ch == "(":
            if paren == 0:
                param_start = i + 1
            paren += 1
        elif ch == ")":
            paren -= 1
            if paren == 0 and param_start >= 0:
                # Overwrite rather than keep the first: an annotation carrying arguments
                # opens a depth-0 group of its own before the signature does, and the
                # group that counts is the last one before the body.
                params = raw[param_start:i]
        elif paren == 0:
            if ch == ";":
                return ("NO_BODY", params, None)
            if ch == "{":
                depth = 0
                j = i
                while j < n:
                    if masked[j] == "{":
                        depth += 1
                    elif masked[j] == "}":
                        depth -= 1
                        if depth == 0:
                            return ("BODY", params, raw[i + 1 : j])
                    j += 1
                return ("UNREADABLE", params, None)
        i += 1
    return ("UNREADABLE", params, None)


def parameter_names(params: str | None) -> list[str] | None:
    """Names of the declared parameters, or None when the list cannot be read."""
    if params is None:
        return None
    text = _strip_literals_and_comments(params).strip()
    if not text:
        return []
    out = []
    depth = 0
    current = []
    for ch in text:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
    out.append("".join(current))
    names = []
    for part in out:
        words = re.findall(IDENT, part.replace("...", " "))
        if not words:
            return None
        names.append(words[-1])
    return names


def classify(path: Path, line: int) -> str | None:
    """Name the mechanical shape of the member at `line`, or None to keep the finding."""
    kind, params, body = member_at(path, line)
    if kind != "BODY" or body is None:
        return None
    names = parameter_names(params)
    if names is None:
        return None
    normalised = re.sub(r"\s+", " ", _strip_literals_and_comments(body)).strip()
    if _strip_literals_and_comments(body).strip() != body.strip():
        # A comment or a literal inside the body says something the shape does not, and a
        # member that needs a note inside is not one that needs none outside.
        return None
    for name, arity, pattern in SHAPES:
        match = pattern.match(normalised)
        if not match:
            continue
        if len(names) != arity:
            continue
        if arity == 1 and match.group("value") != names[0]:
            continue
        if arity == 1 and match.group("field") == names[0] and "this." not in normalised:
            continue  # `x = x;` without `this.` assigns the parameter to itself
        return name
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", required=True, choices=("documented", "exempt"))
    ap.add_argument("--report", required=True, type=Path, help="Checkstyle plain-text output")
    ap.add_argument("--summary", type=Path, default=None, help="append a step-summary block here")
    args = ap.parse_args(argv)

    try:
        report = args.report.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"::error::cannot read the Checkstyle report: {exc}", file=sys.stderr)
        return 1

    kept: list[str] = []
    dropped = Counter()
    for raw_line in report.splitlines():
        match = FINDING.match(raw_line)
        if match is None:
            kept.append(raw_line)
            continue
        if args.policy == "documented" or match["check"] != FILTERED_CHECK or match["severity"] != "ERROR":
            kept.append(raw_line)
            continue
        shape = classify(Path(match["path"]), int(match["line"]))
        if shape is None:
            kept.append(raw_line)
        else:
            dropped[shape] += 1

    for line in kept:
        print(line)

    surviving = sum(1 for line in kept if (m := FINDING.match(line)) and m["severity"] == "ERROR")
    if surviving:
        print(f"javadoc-gate: {surviving} Javadoc finding(s) -- javadoc-conventions.md rule 1")
    if dropped:
        total = sum(dropped.values())
        detail = ", ".join(f"{count} {shape.lower().replace('_', ' ')}" for shape, count in sorted(dropped.items()))
        print(f"javadoc-gate: {total} finding(s) exempted as mechanical members ({detail}) -- javadoc-conventions.md rule 1")
        if args.summary:
            with args.summary.open("a", encoding="utf-8") as fh:
                fh.write(f"- Rule 1 exemption applied to **{total}** member(s): {detail}.\n")
    return 1 if surviving else 0


if __name__ == "__main__":
    sys.exit(main())
