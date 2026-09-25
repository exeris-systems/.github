#!/usr/bin/env python3
"""Cases for `status_capture_check.py` — a status read under `bash -e` is a status of 0.

The first case runs bash itself, so the premise the check rests on is measured here rather than
assumed. The rest name a step's shell and script and whether the capture in it is reached.

Usage: status_capture_check_suite.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import status_capture_check as sc  # noqa: E402

FAILED: list[str] = []


def case(title):
    def wrap(fn):
        try:
            fn()
            print(f"ok    {title}")
        except Exception as exc:                            # every class is reported, none hidden
            FAILED.append(title)
            print(f"::error title=status_capture_check_suite::{title}: {type(exc).__name__}: {exc}")
        return fn
    return wrap


CAPTURE = "tool > out.txt 2>&1\nstatus=$?\necho \"$status\"\n"


@case("under `bash -e` a failing command ends the script before the line that reads its status")
def _():
    script = "set -uo pipefail\n(exit 3) > /dev/null\nstatus=$?\necho \"reached $status\"\n"
    under_e = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True)
    assert under_e.returncode == 3 and "reached" not in under_e.stdout, under_e
    plus_e = subprocess.run(["bash", "-e", "-c", "set +e\n" + script], capture_output=True,
                            text=True)
    assert "reached 3" in plus_e.stdout, plus_e


@case("no shell, and plain `bash`, run under `-e`")
def _():
    assert sc.findings(CAPTURE, None) == [2]
    assert sc.findings(CAPTURE, "bash") == [2]
    assert sc.findings(CAPTURE, "bash -e {0}") == [2]
    assert sc.findings(CAPTURE, "bash -eo pipefail {0}") == [2]


@case("a shell given without `-e` reaches the capture")
def _():
    assert sc.findings(CAPTURE, "bash {0}") == []
    assert sc.findings(CAPTURE, "bash --noprofile --norc {0}") == []
    assert sc.findings(CAPTURE, "bash -x {0}") == []
    assert sc.findings(CAPTURE, "pwsh") == []


@case("`set +e` earlier in the step turns `-e` off, and a later `set -e` turns it back on")
def _():
    assert sc.findings("set +e\n" + CAPTURE, None) == []
    assert sc.findings("set +e -uo pipefail\n" + CAPTURE, None) == []
    assert sc.findings("set +e\nset -euo pipefail\n" + CAPTURE, None) == [4]
    # `set -uo pipefail` leaves `-e` where the shell put it.
    assert sc.findings("set -uo pipefail\n" + CAPTURE, None) == [3]
    assert sc.findings("set -uo pipefail\n" + CAPTURE, "bash {0}") == []


@case("`cmd || status=$?` is not a capture on a line of its own")
def _():
    assert sc.findings("tool > out.txt || status=$?\n", None) == []
    assert sc.findings("status=0\n", None) == []
    assert sc.findings("  status=$?  # read below\n", None) == [1]


@case("the step's shell outranks the job's default, which outranks the workflow's")
def _():
    wf = {"defaults": {"run": {"shell": "bash {0}"}}}
    job = {"defaults": {"run": {"shell": "bash -e {0}"}}}
    assert sc.shell_of({}, {}, wf) == "bash {0}"
    assert sc.shell_of({}, job, wf) == "bash -e {0}"
    assert sc.shell_of({"shell": "bash"}, job, wf) == "bash"
    assert sc.shell_of({}, {}, {}) is None


@case("the command line reads every workflow and names the step")
def _():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, ".github", "workflows"))
        with open(os.path.join(tmp, ".github", "workflows", "w.yml"), "w", encoding="utf-8") as fh:
            fh.write("on: push\njobs:\n  j:\n    runs-on: x\n    steps:\n"
                     "      - name: counts findings\n        run: |\n"
                     "          tool\n          n=$?\n")
        got = subprocess.run([sys.executable, os.path.join(HERE, "status_capture_check.py"),
                              "--root", tmp], capture_output=True, text=True)
        assert got.returncode == 1 and "`counts findings`, line 2" in got.stdout, got.stdout


@case("this repository's workflows capture no status under `-e`")
def _():
    assert sc.check(ROOT) == [], sc.check(ROOT)


if __name__ == "__main__":
    total = sum(1 for line in open(__file__, encoding="utf-8") if line.startswith("@case("))
    print(f"status_capture_check_suite: ran {total} cases, {len(FAILED)} failures")
    sys.exit(1 if FAILED else 0)
