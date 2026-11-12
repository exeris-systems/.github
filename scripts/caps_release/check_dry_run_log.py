#!/usr/bin/env python3
"""The dry-run upload guard: a build that must stay local shows the plugin's own proof that it did.

Reads the Maven log of the dry-run deploy (a regular file, opened without following a link, of at most
MAX_LOG_BYTES). Success needs the Central plugin's statement that it
skipped the upload (`Skipping the upload of the bundle at user's request`), and any line saying it
began one (`Going to upload`) is a failure whatever else the log holds. The dry run holds no
credential, so an upload cannot have succeeded; this makes a plugin that tried visible, and makes a
log that proves nothing a failure rather than a pass.

Usage: check_dry_run_log.py --log FILE

Exit status: 0 skip stated and no upload begun; 1 an upload began, or the skip is not stated, or
the log is unreadable, or the check failed unexpectedly (one `::error::` line); 2 usage error.
Output: stdout `ok - ...`; the refusal on stderr as `::error::`.
"""
from __future__ import annotations

import argparse
import os
import stat
import sys

BEGAN = "Going to upload"
MAX_LOG_BYTES = 64 * 1024 * 1024
SKIPPED = "Skipping the upload of the bundle at user's request"


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the dry-run log check failed unexpectedly ({type(exc).__name__}: "
              f"{' '.join(str(exc).split())}).", file=sys.stderr)
        return 1


def read_log(path: str) -> str:
    """The text of the log at PATH: opened without following a link or blocking, required to be a regular
    file, and read only up to MAX_LOG_BYTES (a larger log is an error, not a prefix)."""
    def opener(name, flags):
        return os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)

    with open(path, "rb", opener=opener) as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise OSError("not a regular file")
        data = fh.read(MAX_LOG_BYTES + 1)
    if len(data) > MAX_LOG_BYTES:
        raise OSError(f"larger than {MAX_LOG_BYTES} bytes")
    return data.decode("utf-8", errors="replace")


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--log", required=True)
    a = p.parse_args(argv)
    try:
        text = read_log(a.log)
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
