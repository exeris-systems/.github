"""Plumbing shared by the tests of `staged_manifest.py` and of the jobs that use it.

Nothing here reads the script under test: the expected manifest, the parse of a `GITHUB_OUTPUT` file
and the sample directories are made independently, so a test compares the script with them and not
with itself.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import random
import signal
import stat

SCRIPT = "staged_manifest"
FINAL = "::error::the staged files are not what the gate staged"
SUFFIXES = (".jar", "-sources.jar", "-javadoc.jar", ".pom")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def coordinate_names(base: str) -> list[str]:
    """The eight names of a coordinate: four files and a detached signature of each."""
    return [f"{base}{s}{e}" for s in SUFFIXES for e in ("", ".asc")]


def put(directory: str, name: str, data: bytes | str | None = None) -> str:
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else (data if data is not None else f"content of {name}\n").encode())
    return path


def make_coordinate(directory: str, base: str = "a-1.0.0") -> list[str]:
    os.makedirs(directory, exist_ok=True)
    names = coordinate_names(base)
    for n in names:
        put(directory, n)
    return names


def manifest_of(directory: str) -> str:
    """The manifest text of the regular files of DIRECTORY, made without the script."""
    lines = []
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), "rb") as fh:
            lines.append(f"{sha(fh.read())}  {name}\n")
    return "".join(lines)


def parse_github_output(text: str) -> dict[str, str]:
    """A `GITHUB_OUTPUT` file as the runner reads it: `key=value`, or `key<<DELIMITER` up to a line that is the delimiter.

    Strict: a line that is neither (outside a value) is an error, so a name that smuggled a line into the file shows.
    """
    out: dict[str, str] = {}
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line.split("=", 1)[0]:
            key, delimiter = line.split("<<", 1)
            i += 1
            body = []
            while i < len(lines) and lines[i] != delimiter:
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise ValueError(f"the value of {key!r} is never closed by {delimiter!r}")
            out[key] = "\n".join(body) + ("\n" if body else "")
        elif "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
        else:
            raise ValueError(f"line {i + 1} is neither a key=value nor a delimiter: {line!r}")
        i += 1
    return out


class Timeout(Exception):
    pass


@contextlib.contextmanager
def bounded(seconds: float = 20.0):
    """Fail instead of hanging: the body must finish inside SECONDS (the main thread, SIGALRM)."""
    def fire(*_):
        raise Timeout(f"did not finish in {seconds} seconds")
    old = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def random_sets(seed: int, count: int):
    """A seeded sample of directory contents: lists of (name, bytes) for one to three whole coordinates."""
    rng = random.Random(seed)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    for _ in range(count):
        files, used = [], []
        for _ in range(rng.randint(1, 3)):
            while True:
                artifact = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12)))
                base = f"{artifact}-{rng.randint(0, 9)}.{rng.randint(0, 9)}.{rng.randint(0, 99)}"
                if not any(base.startswith(u) or u.startswith(base) for u in used):
                    used.append(base)
                    break
            for n in coordinate_names(base):
                size = (1 << 20) + 17 if rng.random() < 0.02 else rng.choice([0, 1, 100, 4096, rng.randint(0, 5000)])
                files.append((n, rng.randbytes(size)))
        yield files


def is_regular(path: str) -> bool:
    return stat.S_ISREG(os.lstat(path).st_mode)
