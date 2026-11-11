#!/usr/bin/env python3
"""Refuse an upload that lacks the secrets its target needs.

Reads booleans only. The caller evaluates `secrets.X != ''` in a workflow expression and hands over
the resulting `true` / `false`, so no secret value is ever in this process's environment.

Usage: check_secrets.py --target {central,github-packages}

Environment (each must be exactly `true` to count as present):
  HAVE_GPG_KEY, HAVE_GPG_PASSPHRASE                         required for every target
  HAVE_CENTRAL_USER, HAVE_CENTRAL_PASSWORD                  required for target `central` only

Exit status: 0 all present; 1 one or more missing (named on stderr); 2 usage error (including a
target of `none`, which uploads nothing and has no business here).
Output: stdout `ok - ...`.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", required=True, choices=["central", "github-packages"])
    a = p.parse_args(argv)
    need = [("HAVE_GPG_KEY", "GPG_PRIVATE_KEY"), ("HAVE_GPG_PASSPHRASE", "GPG_PASSPHRASE")]
    if a.target == "central":
        need += [("HAVE_CENTRAL_USER", "CENTRAL_TOKEN_USERNAME"), ("HAVE_CENTRAL_PASSWORD", "CENTRAL_TOKEN_PASSWORD")]
    missing = [secret for var, secret in need if os.environ.get(var) != "true"]
    if missing:
        print(f"::error::target '{a.target}' needs secrets the caller did not pass: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    print(f"ok - the secrets target '{a.target}' needs were passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
