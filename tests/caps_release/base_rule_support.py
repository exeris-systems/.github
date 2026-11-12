"""The rule for a releasable base name, stated once for the tests, independently of the scripts.

A base is `<artifactId>-<MAJOR.MINOR.PATCH>`: the artifactId made of `[A-Za-z0-9_.-]` and starting with a letter, a digit or `_`,
each number of the version `0` or without a leading zero and of at most nine ASCII digits, the whole base at most 200 characters.
`rule` below is that sentence written as code that shares nothing with the regular expressions of the scripts (it cuts at the last
`-` and inspects characters), so a test compares a script with it and not with itself.

`ACCEPTED` and `REFUSED` are the table every consumer is held to: the readiness gate, `staged_manifest.py create` and `verify`.
"""
from __future__ import annotations

import random

ID_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
ID_REST = ID_START | frozenset(".-")
DIGITS = frozenset("0123456789")
MAX = 200


def rule(base: str) -> bool:
    if not 0 < len(base) <= MAX:
        return False
    artifact, dash, version = base.rpartition("-")
    if not dash or not artifact or artifact[0] not in ID_START or any(c not in ID_REST for c in artifact):
        return False
    numbers = version.split(".")
    if len(numbers) != 3:
        return False
    for n in numbers:
        if not 1 <= len(n) <= 9 or any(c not in DIGITS for c in n) or (n != "0" and n[0] == "0"):
            return False
    return True


def padded(length: int) -> str:
    """A base of exactly LENGTH characters whose artifactId is one letter repeated."""
    tail = "-1.0.0"
    return "a" * (length - len(tail)) + tail


ACCEPTED = [
    "a-1.0.0", "a_b.c-0.0.0", "A.b-c_d-10.20.30", padded(200), "_a-1.0.0", "0a-1.0.0", "a-999999999.999999999.999999999",
    "a--1.0.0", "a.-1.0.0", "a-1.0.0-1.0.0", "a-b-c-d-1.2.3", "Z-0.0.0", "a..b-1.0.0", "a--keyring-1.0.0", "x.pom-1.0.0",
]
SPECIALS = list(',"$\';`*?[]{}()<>|&!#~%^=+@:/\\') + [" ", "\t", "\n", "\x00", "é", "٢", "​", "\x7f", "\x1b"]
REFUSED = [
    padded(201), ".a-1.0.0", "-a-1.0.0", "-1.0.0", "a-01.0.0", "a-1.00.0", "a-1.0.00", "a-1.0", "a-1", "a-1.0.0-rc1", "a-1.0.0.0",
    "a-1234567890.0.0", "a-1.1234567890.0", "a-1.0.1234567890", "", "a", "a-", "a-1.0.0-", "a-1.0.0-SNAPSHOT", "a-SNAPSHOT",
    "a-1.0.0\n", "a-1.0.0 ", " a-1.0.0", "a-1.x.0", "a-v1.0.0", "a-1.0.0+1", "a-1..0", "a-.1.0", "a-1.0.",
    "a-１.0.0", "a-1.０.0", "a-１.０.０", "a-1.0.0٣", "é-1.0.0", "aé-1.0.0", ".-1.0.0",
] + [f"a{c}b-1.0.0" for c in SPECIALS] + [f"{c}a-1.0.0" for c in SPECIALS if c not in "\x00/"] + [f"a-1.0.0{c}" for c in SPECIALS]
# A file name cannot hold these, so a consumer that reads a directory cannot be shown them; the rule is asked about them directly.
NOT_A_FILE_NAME = ("/", "\x00")


def storable(base: str) -> bool:
    return not any(c in base for c in NOT_A_FILE_NAME)


HOSTILE = (list("abcxyzAZ019_.-") * 4 + list(",\"$';`*?[]{}()<>|&!#~%^=+@:/\\ \t\n\x00") + ["é", "٢", "１", "​", "K", "ſ"])
NUMBERS = ["0", "1", "7", "10", "99", "007", "01", "123456789", "1234567890", "", "x", "１"]


def sample(seed: int, count: int):
    """A seeded stream of names over a hostile alphabet, half of them one edit away from a name the rule accepts."""
    rng = random.Random(seed)
    for _ in range(count):
        roll = rng.random()
        if roll < 0.55:
            artifact = "".join(rng.choice("abcXYZ019_.-") for _ in range(rng.randint(1, 10)))
            base = f"{artifact}-" + ".".join(rng.choice(NUMBERS[:9]) for _ in range(3))
            for _ in range(rng.choice([0, 0, 1, 2])):
                at = rng.randint(0, len(base))
                edit = rng.random()
                if edit < 0.5:
                    base = base[:at] + rng.choice(HOSTILE) + base[at:]
                elif edit < 0.8 and base:
                    base = base[:at] + base[at + 1:]
                else:
                    base = base[:at] + base[at:at + 1] * 2 + base[at:]
        elif roll < 0.62:
            base = padded(rng.randint(196, 204))
        else:
            base = "".join(rng.choice(HOSTILE) for _ in range(rng.randint(0, 14)))
        yield base
