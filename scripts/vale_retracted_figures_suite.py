#!/usr/bin/env python3
"""Cases for `Exeris.RetractedFigures` — the error-level rule that blocks a build on a retracted figure.

The rule is a token list, and a token list has no behaviour of its own to test: a token edited so it
no longer matches its figure, or widened so it matches a legitimate citation, changes what fails CI
in every repository and nothing here would notice. So the list is held to two corpora, run through
the same Vale version and the same `.vale.ini` the gate uses:

- `fixtures/vale/retracted-figures.alert.txt` — each non-blank line outside the leading HTML comment
  is one retracted figure in one of the forms it is written in, and must raise exactly one alert
  from this rule, on that line, and nothing else from it;
- `fixtures/vale/retracted-figures.pass.txt` — citations the Never quote alone rules admit, including an Axon arm
  next to its own numbers and the same digits in unrelated units, which must raise none.

The fixtures are `.txt` so the repository's own docs-lint does not read them: `.vale.ini` applies
styles to `*.md` only, and markdownlint and the link check are handed `**/*.md` globs. Here they are
fed to Vale on stdin with `--ext=.md`, so the `[*.md]` section applies to them as it does to a page.

Usage: vale_retracted_figures_suite.py [--vale PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(ROOT, "vale", ".vale.ini")
FIXTURES = os.path.join(HERE, "fixtures", "vale")
ALERT = os.path.join(FIXTURES, "retracted-figures.alert.txt")
PASS = os.path.join(FIXTURES, "retracted-figures.pass.txt")
DOCS_LINT = os.path.join(ROOT, ".github", "workflows", "docs-lint.yml")
RULE = "Exeris.RetractedFigures"
# The figure lines the alert corpus holds. Stated here as well as counted from the file, so a line
# removed from the corpus is a failing case rather than a smaller one.
FIGURE_LINES = 15

FAILED: list[str] = []
CASES: list[tuple[str, object]] = []
VALE = "vale"


def case(title):
    """Registers a case; `main` runs them once the Vale binary is known."""
    def wrap(fn):
        CASES.append((title, fn))
        return fn
    return wrap


def run(title, fn) -> None:
    try:
        fn()
        print(f"ok    {title}")
    except Exception as exc:                                # every class is reported, none hidden
        FAILED.append(title)
        print(f"::error title=vale_retracted_figures_suite::{title}: {type(exc).__name__}: {exc}")


def alerts(path: str) -> list[dict]:
    """Every alert Vale raises on `path` linted as Markdown under the gate's configuration."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    out = subprocess.run([VALE, f"--config={CONFIG}", "--output=JSON", "--ext=.md"],
                         input=text, capture_output=True, text=True)
    # Vale exits 1 when it raised an error-level alert, which the alert corpus always does.
    if out.returncode not in (0, 1):
        raise RuntimeError(f"vale exited {out.returncode}: {out.stderr.strip()}")
    return [a for found in json.loads(out.stdout or "{}").values() for a in found]


def figure_lines(path: str) -> list[int]:
    with open(path, encoding="utf-8") as fh:
        return [n for n, line in enumerate(fh, 1)
                if line.strip() and not line.lstrip().startswith("<!--")]


@case("the Vale running these cases is the version docs-lint pins")
def _():
    with open(DOCS_LINT, encoding="utf-8") as fh:
        pins = set(re.findall(r"^\s*version:\s*([0-9][0-9.]*)\s*$", fh.read(), re.M))
    assert len(pins) == 1, f"docs-lint.yml pins Vale as {sorted(pins)}, expected one version"
    out = subprocess.run([VALE, "--version"], capture_output=True, text=True, check=True).stdout
    got = out.split()[-1].lstrip("v")
    assert got == next(iter(pins)), f"{VALE} is {got}; docs-lint runs {next(iter(pins))}"


@case("every retracted figure raises exactly one error, on its own line")
def _():
    want = figure_lines(ALERT)
    assert len(want) == FIGURE_LINES, f"the corpus holds {len(want)} figure lines, not {FIGURE_LINES}"
    hits = [a for a in alerts(ALERT) if a["Check"] == RULE]
    by_line: dict[int, list[str]] = {}
    for a in hits:
        assert a["Severity"] == "error", f"line {a['Line']}: {a['Match']!r} is {a['Severity']}"
        by_line.setdefault(a["Line"], []).append(a["Match"])
    missed = [n for n in want if n not in by_line]
    doubled = {n: m for n, m in by_line.items() if len(m) > 1}
    stray = sorted(set(by_line) - set(want))
    assert not missed, f"no alert on line(s) {missed}"
    assert not doubled, f"more than one alert on {doubled}"
    assert not stray, f"alert(s) outside a figure line: {stray}"


@case("a citation the Never quote alone rules admit raises nothing from the rule")
def _():
    hits = [(a["Line"], a["Match"]) for a in alerts(PASS) if a["Check"] == RULE]
    assert not hits, f"alerted on {hits}"


@case("the corpora are outside the repository's own docs-lint")
def _():
    out = subprocess.run([VALE, f"--config={CONFIG}", "--output=JSON", ALERT, PASS],
                         capture_output=True, text=True)
    found = json.loads(out.stdout or "{}") if out.stdout.strip().startswith("{") else {}
    assert out.returncode == 0 and not any(found.values()), (
        f"Vale lints the fixtures as files (exit {out.returncode}): the alert corpus would turn "
        f"this repository's docs-lint red")


def main() -> int:
    global VALE
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vale", default="vale", help="Vale binary (default: vale on PATH)")
    VALE = ap.parse_args().vale
    for title, fn in CASES:
        run(title, fn)
    print(f"vale_retracted_figures_suite: {len(FAILED)} failed" if FAILED
          else "vale_retracted_figures_suite: all cases pass")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
