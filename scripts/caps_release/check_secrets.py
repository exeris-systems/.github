#!/usr/bin/env python3
"""Refuse an upload that lacks the signing secrets.

Reads booleans only. The caller evaluates `secrets.X != ''` in a workflow expression and hands over
the resulting `true` / `false`, so no secret value is ever in this process's environment.

Usage: check_secrets.py

Environment (each must be exactly `true` to count as present):
  HAVE_GPG_KEY, HAVE_GPG_PASSPHRASE                         both required

Exit status: 0 all present; 1 one or more missing (named on stderr), or the check failed unexpectedly; 2 usage error.
Output: stdout `ok - ...`.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the secrets check failed unexpectedly ({type(exc).__name__}: "
              f"{' '.join(str(exc).split())}).", file=sys.stderr)
        return 1


def run(argv: list[str] | None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.parse_args(argv)
    need = [("HAVE_GPG_KEY", "GPG_PRIVATE_KEY"), ("HAVE_GPG_PASSPHRASE", "GPG_PASSPHRASE")]
    missing = [secret for var, secret in need if os.environ.get(var) != "true"]
    if missing:
        print(f"::error::an upload needs secrets the caller did not pass: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    print("ok - the signing secrets were passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
