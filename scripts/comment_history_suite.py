#!/usr/bin/env python3
"""`comment_history_check.py`'s fixture suite, and the drift check over its two sibling gates.

The token list is authored once in `comment-history.json` and read by three consumers. Two of them
can read it — this checker and `ts/eslint.tsdoc.mjs`; Checkstyle cannot, so `java/checkstyle-javadoc.xml`
carries a regenerated copy, and a copy nothing compares is a copy that drifts. The last two cases
are that comparison.

One case is about `_common.Report` rather than this checker. This suite already drives `Report`, and
it runs in both CI and `repo-checks`, so it is where the report's own output contract is held: a
passing check writes its summary to stdout even where a step summary exists.

Usage: comment_history_suite.py
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _common import Report                                             # noqa: E402
import comment_history_check as chk                                    # noqa: E402

# (name, filename, source, how many findings)
CASES = [
    ("a hash comment that narrates", "a.py", "# It used to return null\nx = 1\n", 1),
    ("a docstring that narrates", "a.py", '"""Fixed in v0.8.1."""\n', 1),
    ("a function docstring that narrates", "a.py",
     'def f():\n    """This used to take a path."""\n    return 1\n', 1),
    ("a string literal is data, not a claim", "a.py", 'MSG = "it used to be null"\n', 0),
    ("an identifier is data", "a.py", "used_to_be = 1\n", 0),
    ("a present-tense sentence about now", "a.py",
     "# The buffer is no longer valid after close()\n", 0),
    ("a bare 'previously'", "a.py", "# previously agreed with the caller\n", 0),
    ("YAML", "a.yml", "# used to be a matrix job\njobs: {}\n", 1),
    ("a hash inside a YAML string", "a.yml", 'url: "https://x/y#it-used-to-be"\n', 0),
    ("shell", "a.sh", "# formerly two scripts\necho hi\n", 1),
    ("a word boundary: 'port' inside 'report'", "a.py",
     "# since the error is itself reported\n", 0),
    ("a word boundary: a real port", "a.py", "# after the io_uring port\n", 1),
    ("an issue number", "a.py", "# workaround for bug #412\n", 1),
    ("Java is Checkstyle's, not this gate's", "A.java", "/** It used to be null. */\n", 0),
    ("TypeScript is ESLint's", "a.ts", "/** It used to be null. */\n", 0),
]


def run_cases(rep: Report) -> int:
    rex = chk.pattern()
    failures = 0
    for name, filename, source, want in CASES:
        r = Report(name="case")
        chk.check_text(filename, source, rex, r)
        got = len(r.findings)
        if got != want:
            failures += 1
            print(f"::error title=comment_history_suite::{name}: expected {want} finding(s), "
                  f"got {got}")
    return failures


def run_drift(rep: Report) -> int:
    """Every consumer carries the authored list, or names the one that does."""
    failures = 0
    alts = chk.alternatives()
    for alt in alts:
        try:
            re.compile(alt)
        except re.error as exc:
            failures += 1
            print(f"::error title=comment_history_suite::{alt!r} is not a regex ({exc})")

    xml = open(os.path.join(ROOT, "java", "checkstyle-javadoc.xml"), encoding="utf-8").read()
    if chk.checkstyle_format() not in xml:
        failures += 1
        print("::error title=comment_history_suite::java/checkstyle-javadoc.xml does not carry the "
              "authored token list. Checkstyle reads no JSON, so the XML holds a copy: regenerate "
              "it with `python3 scripts/comment_history_check.py --emit-checkstyle`.")

    mjs = open(os.path.join(ROOT, "ts", "eslint.tsdoc.mjs"), encoding="utf-8").read()
    if "comment-history.json" not in mjs:
        failures += 1
        print("::error title=comment_history_suite::ts/eslint.tsdoc.mjs does not read "
              "comment-history.json. It can read the list; a copy there is a second list.")
    if re.search(r'const HISTORY = "\(?\\\\b\(previously', mjs):
        failures += 1
        print("::error title=comment_history_suite::ts/eslint.tsdoc.mjs carries a literal token "
              "list again — it reads comment-history.json instead.")
    return failures


def run_emit() -> int:
    """A passing report is on stdout whether or not a step summary is set, and in the summary too."""
    import contextlib
    import io
    import tempfile
    failures = 0
    held = os.environ.get("GITHUB_STEP_SUMMARY")
    with tempfile.TemporaryDirectory() as tmp:
        for summary in (None, os.path.join(tmp, "summary.md")):
            if summary:
                os.environ["GITHUB_STEP_SUMMARY"] = summary
            else:
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
            r = Report(name="emit_case")
            r.checked = 1
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = r.emit()
            where = "with a step summary" if summary else "without a step summary"
            if code != 0 or "## emit_case" not in out.getvalue():
                failures += 1
                print(f"::error title=comment_history_suite::Report.emit {where}: a passing report "
                      f"is not on stdout, so `repo-checks.out` would show the check as never run")
            if summary and "## emit_case" not in open(summary, encoding="utf-8").read():
                failures += 1
                print("::error title=comment_history_suite::Report.emit no longer writes the step "
                      "summary")
    if held is None:
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
    else:
        os.environ["GITHUB_STEP_SUMMARY"] = held
    return failures


def main() -> int:
    rep = Report(name="comment_history_suite")
    failures = run_cases(rep) + run_drift(rep) + run_emit()
    total = len(CASES) + len(chk.alternatives()) + 3 + 2
    print(f"comment_history_suite: ran {total} cases, {failures} failures")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## comment_history_suite\n\nRan **{total}** cases — "
                     f"**{failures} failures**.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
