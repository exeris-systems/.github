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

The secret home and the file named as the public key are removed in a `finally`, on every path out of
the script, WITHOUT regard to whether their paths passed the check below: removal uses literal path
operations (no shell, no pattern), never follows a symbolic link, and deletes a directory tree through
descriptor-relative calls. Every subprocess is bounded by a timeout; an expiry is a failure.

Every path argument is refused when it holds a control, format, separator or unassigned character
(a newline in a path would append a second `NAME=value` line to the environment file). A secret
home or verify home that is a symbolic link is reported and never followed or deleted through,
however it is spelled: trailing separators and `.` components are removed from the text before any
check, so `link/` and `link/.` name the link itself. The run still fails.

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
import stat
import subprocess
import sys
import tempfile
import unicodedata


SUBPROCESS_TIMEOUT = 120


def unusual(ch: str) -> bool:
    return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")


def literal(path: str) -> str:
    """PATH without trailing separators and trailing `.` components, computed on the text alone.

    The system resolves `link/` and `link/.` to the link's target, so a check made on such a spelling
    judges the target and not the link. The name that is checked and operated on is the last component
    itself. Nothing is resolved: no `realpath`, no lookup."""
    while True:
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/") or "/"
        elif path.endswith("/."):
            path = path[:-2] or "/"
        else:
            return path


def remove_tree(path: str) -> None:
    """Delete a directory tree; a symbolic link is removed as a link and never followed."""
    path = literal(path)
    if os.path.islink(path):
        os.unlink(path)
    elif os.path.lexists(path):
        shutil.rmtree(path, ignore_errors=True)


def remove_literally(path: str, tree: bool) -> None:
    """Delete PATH with literal path operations only (no shell, no pattern, no validation of its
    characters); a symbolic link is never followed and never deleted through. Best effort."""
    path = literal(path)
    try:
        if stat.S_ISDIR(os.lstat(path).st_mode):
            if tree:
                shutil.rmtree(path, ignore_errors=True)         # descriptor-relative, does not follow links
        elif not tree:
            os.unlink(path)
    except (OSError, ValueError):
        pass


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

    finished = False
    try:
        try:
            removal(a, fail, problems)
        except Exception as exc:
            fail(f"the key removal failed unexpectedly ({type(exc).__name__}: {' '.join(str(exc).split())}).")
        finished = True
    finally:
        # Whatever happened, and whether or not a path passed validation: nothing that holds, or may
        # hold, a secret key stays behind.
        remove_literally(a.secret_home, tree=True)
        remove_literally(a.public_key, tree=False)
        if problems or not finished:
            try:
                remove_tree(a.verify_home)
            except (OSError, ValueError):
                pass
    if problems:
        return 1
    print("ok - the private key is gone; the keyring holds the public key only")
    return 0


def removal(a: argparse.Namespace, fail, problems: list[str]) -> None:
    for flag in ("secret_home", "verify_home", "public_key", "env_file"):
        bad = [c for c in getattr(a, flag) if unusual(c)]
        if bad:
            fail(f"--{flag.replace('_', '-')} holds a control or unassigned character (U+{ord(bad[0]):04X}); "
                 "a path is one line of printable text.")
    if problems and any("--secret-home" in m for m in problems):
        return

    secret_home, verify_home = literal(a.secret_home), literal(a.verify_home)
    if os.path.islink(secret_home):
        fail("the private keyring still exists after removal: the secret home is a symbolic link, "
             "which is reported and not followed.")
    elif os.path.isdir(secret_home):
        try:
            subprocess.run([a.gpgconf, "--kill", "gpg-agent"], env={**os.environ, "GNUPGHOME": secret_home},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=SUBPROCESS_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            pass
        shutil.rmtree(secret_home, ignore_errors=True)
    if os.path.islink(verify_home):
        fail("the verify home is a symbolic link, which is reported and not followed: nothing is created, "
             "changed or imported through it.")
    if problems:
        return

    verify_env = {**os.environ, "GNUPGHOME": a.verify_home}
    if os.path.isfile(a.public_key) and os.path.getsize(a.public_key) > 0:
        inspect = tempfile.mkdtemp(prefix="gnupg-inspect-")
        try:
            shown = subprocess.run([a.gpg, "--batch", "--show-keys", "--with-colons", a.public_key],
                                   env={**os.environ, "GNUPGHOME": inspect}, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
        finally:
            shutil.rmtree(inspect, ignore_errors=True)
        if shown.returncode != 0:
            fail(f"the public key could not be imported: it could not be inspected: {shown.stderr.strip()}")
        elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):
            fail("the file named as the public key holds a secret key and was not imported; "
                 "a secret key is still on the runner in that file until it is deleted.")
        else:
            os.makedirs(verify_home, mode=0o700, exist_ok=True)
            os.chmod(verify_home, 0o700)
            done = subprocess.run([a.gpg, "--batch", "--import", a.public_key], env=verify_env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                  timeout=SUBPROCESS_TIMEOUT)
            if done.returncode != 0:
                fail(f"the public key could not be imported: {done.stderr.strip()}")
    try:
        os.remove(a.public_key)
    except FileNotFoundError:
        pass
    if problems:
        return

    os.makedirs(verify_home, mode=0o700, exist_ok=True)
    os.chmod(verify_home, 0o700)
    if os.path.lexists(secret_home):
        fail("the private keyring still exists after removal.")
    listed = subprocess.run([a.gpg, "--list-secret-keys", "--with-colons"], env=verify_env,
                            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    secret = [ln for ln in listed.stdout.splitlines() if ln.split(":", 1)[0] in ("sec", "ssb")]
    if listed.returncode not in (0, 2) or secret:
        fail("a secret key is still in the keyring after removal.")
    if problems:
        return

    with open(a.env_file, "a", encoding="utf-8") as fh:
        fh.write(f"GNUPGHOME={a.verify_home}\n")


if __name__ == "__main__":
    sys.exit(main())
