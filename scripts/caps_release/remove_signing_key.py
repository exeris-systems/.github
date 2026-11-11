#!/usr/bin/env python3
"""Remove the private signing key from the runner and leave a keyring with the public key alone.

Stops the gpg-agent that may have cached the passphrase, deletes the keyring that held the private
key, builds a fresh keyring from the exported public key, deletes the exported file, and then
CHECKS the post-condition instead of assuming it: the private keyring is gone and the fresh keyring
lists no secret key. The later gates verify signatures with the public key only.

Usage: remove_signing_key.py --secret-home DIR --verify-home DIR --public-key FILE --env-file FILE
                             [--gpg PATH] [--gpgconf PATH]

  --secret-home  the GNUPGHOME that held the private key; removed (absent is fine: the import may
                 not have run)
  --verify-home  a GNUPGHOME to create (mode 700) for verification
  --public-key   the exported public key; imported when non-empty, always deleted
  --env-file     `GNUPGHOME=<verify-home>` is appended to it (GITHUB_ENV) so later steps verify there
  --gpg, --gpgconf  the executables (default `gpg`, `gpgconf`); a missing gpgconf is tolerated

Exit status: 0 key removed and post-condition holds; 1 the public key could not be imported, the
private keyring still exists, or a secret key is still listed; 2 usage error.
Output: stdout `ok - the private key is gone; the keyring holds the public key only`; failures on
stderr as `::error::`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--secret-home", required=True)
    p.add_argument("--verify-home", required=True)
    p.add_argument("--public-key", required=True)
    p.add_argument("--env-file", required=True)
    p.add_argument("--gpg", default="gpg")
    p.add_argument("--gpgconf", default="gpgconf")
    a = p.parse_args(argv)

    if os.path.isdir(a.secret_home):
        try:
            subprocess.run([a.gpgconf, "--kill", "gpg-agent"], env={**os.environ, "GNUPGHOME": a.secret_home},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        shutil.rmtree(a.secret_home, ignore_errors=True)

    os.makedirs(a.verify_home, mode=0o700, exist_ok=True)
    os.chmod(a.verify_home, 0o700)
    with open(a.env_file, "a", encoding="utf-8") as fh:
        fh.write(f"GNUPGHOME={a.verify_home}\n")
    env = {**os.environ, "GNUPGHOME": a.verify_home}

    failed = False
    if os.path.isfile(a.public_key) and os.path.getsize(a.public_key) > 0:
        done = subprocess.run([a.gpg, "--batch", "--import", a.public_key], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if done.returncode != 0:
            print(f"::error::the public key could not be imported: {done.stderr.strip()}", file=sys.stderr)
            failed = True
    try:
        os.remove(a.public_key)
    except FileNotFoundError:
        pass

    if os.path.exists(a.secret_home):
        print("::error::the private keyring still exists after removal.", file=sys.stderr)
        failed = True
    listed = subprocess.run([a.gpg, "--list-secret-keys", "--with-colons"], env=env,
                            capture_output=True, text=True)
    secret = [ln for ln in listed.stdout.splitlines() if ln.startswith("sec")]
    if listed.returncode not in (0, 2) or secret:
        print("::error::a secret key is still in the keyring after removal.", file=sys.stderr)
        failed = True
    if failed:
        return 1
    print("ok - the private key is gone; the keyring holds the public key only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
