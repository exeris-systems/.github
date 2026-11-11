#!/usr/bin/env python3
"""Run the tests of `scripts/caps_release/`, and fail when there are none.

`python -m unittest discover` over a directory with no tests exits 0 on Python before 3.12 and
reports "NO TESTS RAN" only on later ones. A suite that collects nothing proves nothing, so this
counts first: zero collected tests is a failure, as is a test module that cannot be imported
(discovery turns that into a failing test).

Usage: run_caps_release_tests.py [--root .]

Exit status: 0 every collected test passed; 1 a test failed, or none was collected.
"""
from __future__ import annotations

import argparse
import os
import sys
import unittest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    start = os.path.join(ap.parse_args().root, "tests", "caps_release")
    suite = unittest.defaultTestLoader.discover(start, pattern="test*.py")
    n = suite.countTestCases()
    if n == 0:
        print(f"::error::no test was collected from {start}. The scripts that decide what is signed "
              "and uploaded are not tested.", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
