"""Shared fixtures of the readiness-gate tests: a target/ directory and a gpg double.

The gpg double accepts a detached signature only when it is `SIG:<sha256 of the file>`, so a signature
made for one file never verifies another and the gate's pairing of file and signature is observable
without a keyring. `Fixture.coordinate` and `Fixture.real_coordinate` write the four files of a coordinate and a signature of each by
that rule.
"""
from __future__ import annotations

import hashlib
import os
import zipfile

import caps_release_helpers as h

FAKE_GPG = """#!/bin/sh
if [ -n "$FAKE_GPG_LOG" ]; then printf '%s\\t%s\\t%s\\t%s\\n' "$1" "$2" "$3" "$(sha256sum "$3" | cut -d' ' -f1)" >> "$FAKE_GPG_LOG"; fi
[ $# -eq 3 ] && [ "$1" = "--verify" ] || exit 2
want="SIG:$(sha256sum "$3" | cut -d' ' -f1)"
[ "$(cat "$2")" = "$want" ]
"""

SUFFIXES = (".jar", "-sources.jar", "-javadoc.jar", ".pom")
GROUP = "eu.exeris.caps"


def sig_of(path):
    with open(path, "rb") as fh:
        return "SIG:" + hashlib.sha256(fh.read()).hexdigest() + "\n"


def make_zip(path, names, payload=b"x"):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, payload)


def pom_xml(group=GROUP, artifact="a", version="1.0.0", parent_group=None, extra=""):
    parent = f"<parent><groupId>{parent_group}</groupId><artifactId>p</artifactId><version>{version}</version></parent>" \
        if parent_group else ""
    g = f"<groupId>{group}</groupId>" if group else ""
    return f"<project>{parent}{g}<artifactId>{artifact}</artifactId><version>{version}</version>{extra}</project>"


def default_pom(base):
    """A POM that names the coordinate a file base name `<artifactId>-<version>` stands for, so the gate can bind
    it; a base that is not of that shape gets a POM that yields no coordinate."""
    artifact, sep, version = base.rpartition("-")
    if base.count("-") >= 1 and version[:1].isdigit() and artifact:
        return pom_xml(GROUP, artifact, version)
    return f"<project>{base}</project>"


class Fixture(h.Case):
    """A target/ directory and a gpg double that accepts a signature only of the file it is handed."""

    def setUp(self):
        super().setUp()
        self.target = self.path("target")
        os.makedirs(self.target)
        self.gpg = self.write("fake-gpg", FAKE_GPG)
        os.chmod(self.gpg, 0o755)
        self.log = self.path("gpg.log")

    def use_py_gpg(self):
        """Replace the gpg double by one that logs its argument vector as JSON, so a name with a newline or a leading dash
        can be seen intact; returns the log path."""
        import sys
        with open(self.gpg, "w") as fh:
            fh.write(PY_GPG.format(python=sys.executable))
        os.chmod(self.gpg, 0o755)
        return self.log

    def gpg_calls(self):
        import json
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [json.loads(ln) for ln in fh]

    def coordinate(self, base="a-1.0.0", sign=True, skip=(), javadoc_names=("index.html", "a/B.html"), pom_text=None):
        t = self.target
        make_zip(os.path.join(t, f"{base}.jar"), ["a/B.class"])
        make_zip(os.path.join(t, f"{base}-sources.jar"), ["a/B.java"])
        make_zip(os.path.join(t, f"{base}-javadoc.jar"), list(javadoc_names))
        with open(os.path.join(t, f"{base}.pom"), "w") as fh:
            fh.write(pom_text if pom_text is not None else default_pom(base))
        for suffix in SUFFIXES:
            f = os.path.join(t, base + suffix)
            if suffix in skip:
                os.remove(f)
            elif sign:
                with open(f + ".asc", "w") as fh:
                    fh.write(sig_of(f))
        return base

    def real_coordinate(self, group=GROUP, artifact="a", version="1.0.0", **kw):
        """A coordinate whose POM names its group, artifactId and version."""
        return self.coordinate(f"{artifact}-{version}", pom_text=pom_xml(group, artifact, version), **kw)

    def read_target(self, name) -> bytes:
        with open(os.path.join(self.target, name), "rb") as fh:
            return fh.read()

    def check(self, *extra):
        return self.both("check_release_readiness", ["--target-dir", self.target, "--gpg", self.gpg, *extra])

    def tree(self):
        """Every path under the temporary root, for a 'nothing was written' comparison."""
        out = set()
        for root, dirs, files in os.walk(self.tmp):
            out.update(os.path.join(root, n) for n in dirs + files)
        return out


PY_GPG = """#!{python}
import hashlib, json, os, stat, sys, time
args = sys.argv[1:]
log = os.environ.get("PYGPG_LOG")
sleep = os.environ.get("PYGPG_SLEEP")


def mode(path):
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return None


if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({{"argv": args, "dir_modes": [mode(os.path.dirname(a)) for a in args[1:]],
                             "scratch_modes": [mode(os.path.dirname(os.path.dirname(a))) for a in args[1:]]}}) + "\\n")
if sleep:
    time.sleep(float(sleep))
if len(args) != 3 or args[0] != "--verify":
    sys.exit(2)
with open(args[2], "rb") as fh:
    want = "SIG:" + hashlib.sha256(fh.read()).hexdigest()
with open(args[1], "r") as fh:
    sys.exit(0 if fh.read().strip() == want else 1)
"""
