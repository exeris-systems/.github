#!/usr/bin/env python3
"""The dry-run upload guard: a build that must stay local shows the plugin's own proof that it did.

Reads the Maven log of the dry-run deploy. Success needs the Central plugin's statement that it
skipped the upload (`Skipping the upload of the bundle at user's request`), and any line saying it
began one (`Going to upload`) is a failure whatever else the log holds. The dry run holds no
credential, so an upload cannot have succeeded; this makes a plugin that tried visible, and makes a
log that proves nothing a failure rather than a pass.

Usage: check_dry_run_log.py --log FILE

Exit status: 0 skip stated and no upload begun; 1 an upload began, or the skip is not stated, or
the log is unreadable; 2 usage error.
Output: stdout `ok - ...`; the refusal on stderr as `::error::`.
"""
from __future__ import annotations

import argparse
import sys

BEGAN = "Going to upload"
SKIPPED = "Skipping the upload of the bundle at user's request"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--log", required=True)
    a = p.parse_args(argv)
    try:
        with open(a.log, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"::error::the dry-run log cannot be read ({exc}).", file=sys.stderr)
        return 1
    if BEGAN in text:
        print("::error::the dry run began an upload to Central. It holds no credential, so it cannot have "
              "succeeded; treat this as a failure of the dry-run guard.", file=sys.stderr)
        return 1
    if SKIPPED not in text:
        print("::error::the Central plugin did not report that it skipped the upload; the dry run cannot be "
              "shown to have stayed local.", file=sys.stderr)
        return 1
    print("ok - the plugin reported that it skipped the upload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
