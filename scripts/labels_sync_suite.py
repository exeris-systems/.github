#!/usr/bin/env python3
"""Cases for `labels_sync.py` — what the sync asks of a repository's labels, planned without a network.

`plan()` decides every request the sync sends, so each rule it applies is checkable here: an old
name is renamed in place rather than duplicated, a new name already present leaves the old one for a
person, and nothing is ever deleted. The last case reads `labels.yml` itself, because a
`renamed-from` naming the label it sits on would rename a label onto itself.

Usage: labels_sync_suite.py
"""
from __future__ import annotations

import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from labels_sync import plan  # noqa: E402

SPEC = {"name": "needs-review", "color": "c5def5", "description": "A review is asked for",
        "renamed-from": ["needs-l2-review"]}
CURRENT = {"name": "needs-review", "color": "c5def5", "description": "A review is asked for"}
FAILED = []


def case(title):
    def wrap(fn):
        try:
            fn()
            print(f"ok    {title}")
        except AssertionError as exc:
            FAILED.append(title)
            print(f"FAIL  {title}: {exc}")
        return fn
    return wrap


def kinds(actions):
    return [(k, n) for k, n, _, _ in actions]


@case("an old name with no new one is renamed in place, not created beside")
def _():
    a = plan([SPEC], {"needs-l2-review": {"name": "needs-l2-review", "color": "c5def5"}})
    assert kinds(a) == [("rename", "needs-l2-review")], a
    assert a[0][2]["new_name"] == "needs-review", a


@case("the rename carries the taxonomy's colour and description")
def _():
    a = plan([SPEC], {"needs-l2-review": {"name": "needs-l2-review", "color": "000000",
                                          "description": "old"}})
    assert a[0][2] == {"new_name": "needs-review", "color": "c5def5",
                       "description": "A review is asked for"}, a


@case("neither name present: the label is created")
def _():
    assert kinds(plan([SPEC], {})) == [("create", "needs-review")]


@case("both names present: the new one stands, the old one is reported and not touched")
def _():
    a = plan([SPEC], {"needs-review": CURRENT, "needs-l2-review": {"name": "needs-l2-review"}})
    assert kinds(a) == [("ok", "needs-review"), ("left", "needs-l2-review")], a
    assert a[1][2] is None, a


@case("the new name present and drifted: corrected, and the old one still left")
def _():
    a = plan([SPEC], {"needs-review": dict(CURRENT, color="ffffff"),
                      "needs-l2-review": {"name": "needs-l2-review"}})
    assert kinds(a) == [("correct", "needs-review"), ("left", "needs-l2-review")], a


@case("two old names present: one is renamed, the other left")
def _():
    spec = dict(SPEC, **{"renamed-from": ["needs-l2-review", "l2-review"]})
    a = plan([spec], {"needs-l2-review": {}, "l2-review": {}})
    assert kinds(a) == [("rename", "needs-l2-review"), ("left", "l2-review")], a


@case("no action deletes a label")
def _():
    a = plan([SPEC], {"needs-review": CURRENT, "needs-l2-review": {}, "area: x": {}})
    assert all(k in ("create", "rename", "correct", "ok", "left") for k, *_ in a), a
    assert not any(n == "area: x" for _, n, _, _ in a), a


@case("labels.yml: every `renamed-from` names another label, and no label the taxonomy still defines")
def _():
    with open(os.path.join(HERE, "..", "labels.yml"), encoding="utf-8") as fh:
        want = yaml.safe_load(fh)
    names = {s["name"] for s in want}
    for s in want:
        for old in s.get("renamed-from", []):
            assert old != s["name"], f"{s['name']} is renamed from itself"
            assert old not in names, f"{old} is both defined and renamed into {s['name']}"


if __name__ == "__main__":
    print(f"{len(FAILED)} failed" if FAILED else "all cases pass")
    sys.exit(1 if FAILED else 0)
