#!/usr/bin/env python3
"""`pr_body_check.check`'s owner-line fixture suite — ADR-085 §J.31, ai-provenance.md rule 3b.

The owner rule reads one thing this checker otherwise never looks at — who opened the pull
request — and branches on it: required-and-singular-and-well-formed for the execution identity,
forbidden for everyone else, and not judged at all when no author was given. Five branches, five
cases, plus the two ways "required" can still fail (absent, more than one) and the one way
"well-formed" can (no '@'). Each case calls `check()` directly against a body that already
satisfies every other rule the checker has, so a finding it reports can only be the owner rule.

Usage: pr_body_check_suite.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pr_body_check as pbc                                            # noqa: E402
from _common import Report                                             # noqa: E402

AGENT = "exeris-agent[bot]"
HUMAN = "arkstack-dev"

# Every other rule this checker enforces has to hold regardless, or a failure here would be
# indistinguishable from a break in the rule under test. Values are chosen straight out of
# `pr_body_check.FIELDS`, so the only findings any case below can produce carry `rule="owner"`.
TEMPLATE = """Motivation:
Explains why this change is needed.

Modification:
Explains what changed.

Result:
Explains the outcome.

## Classification
Scope class: docs-only
Wall impact: none
Generated files touched: no
TCK obligation: n/a
Compatibility impact: none
Cross-repo impact: none
ADRs referenced: none
Evidence state: n/a

## Verification
Ran the suite locally.
{owner}
"""

CASES: list[tuple[str, object]] = []


def case(name: str):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


def body(*owner_lines: str) -> str:
    return TEMPLATE.format(owner="\n".join(owner_lines))


def owner_errors(text: str, author) -> list:
    rep = Report("pr_body_check_suite")
    pbc.check(text, rep, author=author)
    return [f for f in rep.findings if f.rule == "owner"]


@case("app author, one well-formed Owner line — no error")
def _():
    errs = owner_errors(body("Owner: @arkstack-dev"), AGENT)
    assert errs == [], errs


@case("app author, no Owner line — reported absent")
def _():
    errs = owner_errors(body(), AGENT)
    assert len(errs) == 1, errs
    assert "no 'Owner: @<login>' line" in errs[0].msg, errs


@case("app author, two Owner lines — reported as more than one")
def _():
    errs = owner_errors(body("Owner: @arkstack-dev", "Owner: @someone-else"), AGENT)
    assert len(errs) == 1, errs
    assert "2 'Owner:' lines" in errs[0].msg, errs
    assert "exactly one is required" in errs[0].msg, errs


@case("app author, 'Owner: someone' with no '@' — reported malformed")
def _():
    errs = owner_errors(body("Owner: someone"), AGENT)
    assert len(errs) == 1, errs
    assert "does not match 'Owner: @<login>'" in errs[0].msg, errs


@case("human author, an Owner line — forbidden")
def _():
    errs = owner_errors(body("Owner: @arkstack-dev"), HUMAN)
    assert len(errs) == 1, errs
    assert "not exeris-agent[bot]" in errs[0].msg, errs


@case("human author, no Owner line — no error")
def _():
    errs = owner_errors(body(), HUMAN)
    assert errs == [], errs


@case("--body-file with no --author — the rule is not judged either way")
def _():
    assert owner_errors(body(), None) == []
    assert owner_errors(body("Owner: not-even-a-handle"), None) == []
    assert owner_errors(body("Owner: @a", "Owner: @b"), None) == []


def main() -> int:
    failures = 0
    for name, fn in CASES:
        try:
            fn()
        except AssertionError as exc:
            failures += 1
            print(f"::error title=pr_body_check_suite::{name}: {exc}")
        except Exception as exc:  # a case that cannot run is a case that did not pass
            failures += 1
            print(f"::error title=pr_body_check_suite::{name}: {type(exc).__name__}: {exc}")
    print(f"pr_body_check_suite: ran {len(CASES)} cases, {failures} failures")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## pr_body_check_suite\n\nRan **{len(CASES)}** cases — "
                     f"**{failures} failures**.\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
