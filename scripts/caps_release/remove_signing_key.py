#!/usr/bin/env python3
"""Remove the private signing key from the runner and leave a keyring with the public key alone.

Stops the gpg-agent that may have cached the passphrase, deletes the keyring that held the private
key, builds a fresh keyring from the exported public key, deletes the exported file, and then
CHECKS the post-condition instead of assuming it: the private keyring is gone and the fresh keyring
lists no secret key. The later gates verify signatures with the public key only.

The file named as the public key is inspected BEFORE it is imported (`gpg --show-keys --with-colons`
in a throwaway home): a `sec` or `ssb` record means it is a secret-key export, and it is refused
without being imported. The environment file is written only after the post-condition holds, so no
failure leaves `GNUPGHOME` pointing at a keyring. On ANY failure the verify home is deleted, the
exported file is deleted, and the secret home is deleted again if it came back.

Every path argument is refused when it holds a control, format, separator or unassigned character
(a newline in a path would append a second `NAME=value` line to the environment file). A secret
home that is a symbolic link is reported and never followed or deleted through; the run still fails.

Usage: remove_signing_key.py --secret-home DIR --verify-home DIR --public-key FILE --env-file FILE
                             [--gpg PATH] [--gpgconf PATH]

  --secret-home  the GNUPGHOME that held the private key; removed (absent is fine: the import may
                 not have run)
  --verify-home  a GNUPGHOME to create (mode 700) for verification
  --public-key   the exported public key; imported when non-empty, always deleted
  --env-file     `GNUPGHOME=<verify-home>` is appended to it (GITHUB_ENV) so later steps verify there,
                 on success only
  --gpg, --gpgconf  the executables (default `gpg`, `gpgconf`); a missing gpgconf is tolerated

Exit status: 0 key removed and post-condition holds; 1 a path argument is unusable, the public key
could not be inspected or imported or holds a secret key, the private keyring still exists, or a
secret key is still listed; 2 usage error.
Output: stdout `ok - the private key is gone; the keyring holds the public key only`; failures on
stderr as `::error::`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata


def unusual(ch: str) -> bool:
    return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")


def remove_tree(path: str) -> None:
    """Delete a directory tree; a symbolic link is removed as a link and never followed."""
    if os.path.islink(path):
        os.unlink(path)
    elif os.path.lexists(path):
        shutil.rmtree(path, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--secret-home", required=True)
    p.add_argument("--verify-home", required=True)
    p.add_argument("--public-key", required=True)
    p.add_argument("--env-file", required=True)
    p.add_argument("--gpg", default="gpg")
    p.add_argument("--gpgconf", default="gpgconf")
    a = p.parse_args(argv)

    problems: list[str] = []

    def fail(msg: str) -> None:
        problems.append(msg)
        print(f"::error::{msg}", file=sys.stderr)

    try:
        removal(a, fail, problems)
    except Exception as exc:
        fail(f"the key removal failed unexpectedly ({type(exc).__name__}: {' '.join(str(exc).split())}).")
    if problems:
        cleanup(a)
        return 1
    print("ok - the private key is gone; the keyring holds the public key only")
    return 0


def cleanup(a: argparse.Namespace) -> None:
    """Failure: nothing that holds, or may hold, a secret key stays behind."""
    for path in (a.verify_home, a.public_key):
        if not any(unusual(c) for c in path):
            try:
                if path == a.public_key:
                    os.remove(path)
                else:
                    remove_tree(path)
            except OSError:
                pass
    if not any(unusual(c) for c in a.secret_home) and not os.path.islink(a.secret_home):
        shutil.rmtree(a.secret_home, ignore_errors=True)


def removal(a: argparse.Namespace, fail, problems: list[str]) -> None:
    for flag in ("secret_home", "verify_home", "public_key", "env_file"):
        bad = [c for c in getattr(a, flag) if unusual(c)]
        if bad:
            fail(f"--{flag.replace('_', '-')} holds a control or unassigned character (U+{ord(bad[0]):04X}); "
                 "a path is one line of printable text.")
    if problems and any("--secret-home" in m for m in problems):
        return

    if os.path.islink(a.secret_home):
        fail("the private keyring still exists after removal: the secret home is a symbolic link, "
             "which is reported and not followed.")
    elif os.path.isdir(a.secret_home):
        try:
            subprocess.run([a.gpgconf, "--kill", "gpg-agent"], env={**os.environ, "GNUPGHOME": a.secret_home},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        shutil.rmtree(a.secret_home, ignore_errors=True)
    if problems:
        return

    verify_env = {**os.environ, "GNUPGHOME": a.verify_home}
    if os.path.isfile(a.public_key) and os.path.getsize(a.public_key) > 0:
        inspect = tempfile.mkdtemp(prefix="gnupg-inspect-")
        try:
            shown = subprocess.run([a.gpg, "--batch", "--show-keys", "--with-colons", a.public_key],
                                   env={**os.environ, "GNUPGHOME": inspect}, capture_output=True, text=True)
        finally:
            shutil.rmtree(inspect, ignore_errors=True)
        if shown.returncode != 0:
            fail(f"the public key could not be imported: it could not be inspected: {shown.stderr.strip()}")
        elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):
            fail("the file named as the public key holds a secret key and was not imported; "
                 "a secret key is still on the runner in that file until it is deleted.")
        else:
            os.makedirs(a.verify_home, mode=0o700, exist_ok=True)
            os.chmod(a.verify_home, 0o700)
            done = subprocess.run([a.gpg, "--batch", "--import", a.public_key], env=verify_env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if done.returncode != 0:
                fail(f"the public key could not be imported: {done.stderr.strip()}")
    try:
        os.remove(a.public_key)
    except FileNotFoundError:
        pass
    if problems:
        return

    os.makedirs(a.verify_home, mode=0o700, exist_ok=True)
    os.chmod(a.verify_home, 0o700)
    if os.path.lexists(a.secret_home):
        fail("the private keyring still exists after removal.")
    listed = subprocess.run([a.gpg, "--list-secret-keys", "--with-colons"], env=verify_env,
                            capture_output=True, text=True)
    secret = [ln for ln in listed.stdout.splitlines() if ln.split(":", 1)[0] in ("sec", "ssb")]
    if listed.returncode not in (0, 2) or secret:
        fail("a secret key is still in the keyring after removal.")
    if problems:
        return

    with open(a.env_file, "a", encoding="utf-8") as fh:
        fh.write(f"GNUPGHOME={a.verify_home}\n")


if __name__ == "__main__":
    sys.exit(main())
