"""Shared plumbing of the capability release suite.

Every script is exercised twice: in this process through its `main(argv)`, loaded by path, and in a
child process exactly as a calling workflow runs it (`python3 -I -B <script>`). `both` runs the two and
asserts they agree on exit status and on the `::error::` lines, so a script cannot behave one way
under test and another way under a calling workflow.

The directory the scripts are read from can be redirected (`SCRIPT_DIR_OVERRIDE`); the mutation
tests use that to run this suite against a deliberately broken copy of a script.
"""
from __future__ import annotations

import contextlib
import functools
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT_DIR = os.path.join(REPO, "scripts", "caps_release")
WORKFLOW = os.path.join(REPO, ".github", "workflows", "caps-release.yml")
RUNNER = os.path.join(REPO, "scripts", "run_caps_release_tests.py")

SCRIPT_DIR_OVERRIDE: str | None = None


def script_path(name: str) -> str:
    return os.path.join(SCRIPT_DIR_OVERRIDE or SCRIPT_DIR, name + ".py")


_LOADED: dict = {}


def runner_path() -> str:
    copy = os.path.join(SCRIPT_DIR_OVERRIDE or "", "run_caps_release_tests.py")
    return copy if SCRIPT_DIR_OVERRIDE and os.path.exists(copy) else RUNNER


def load(name: str):
    """Import a script by path. Keyed by path and modification time, so a mutated copy never leaks."""
    path = script_path(name)
    key = (path, os.stat(path).st_mtime_ns)
    if key not in _LOADED:
        spec = importlib.util.spec_from_file_location(f"caps_release_under_test_{abs(hash(key))}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOADED[key] = module
    return _LOADED[key]


class Result:
    def __init__(self, rc, out, err):
        self.rc, self.out, self.err = rc, out, err

    def errors(self) -> list[str]:
        return [ln for ln in self.err.splitlines() if ln.startswith("::error::")]

    def __repr__(self):
        return f"Result(rc={self.rc!r}, out={self.out!r}, err={self.err!r})"


def run_main(name: str, argv: list[str], env: dict | None = None, **kwargs) -> Result:
    module = load(name)
    out, err = io.StringIO(), io.StringIO()
    saved = os.environ.copy()
    if env is None:
        env = {**os.environ, "LC_ALL": "C.UTF-8", "LANGUAGE": "C"}
    os.environ.clear()
    os.environ.update(env)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = module.main(argv, **kwargs)
            except SystemExit as exc:           # argparse usage error
                rc = exc.code if isinstance(exc.code, int) else 1
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return Result(rc, out.getvalue(), err.getvalue())


def run_proc(name: str, argv: list, env: dict | None = None, timeout: float = 60) -> Result:
    if SCRIPT_DIR_OVERRIDE:                     # a mutant is judged in-process, for speed
        return run_main(name, [a.decode("utf-8", "surrogateescape") if isinstance(a, bytes) else a for a in argv], env=env)
    if env is None:
        env = clean_env()
    proc = subprocess.run([sys.executable, "-I", "-B", script_path(name), *argv], capture_output=True,
                          env=env, timeout=timeout)
    return Result(proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))


def clean_env(**extra) -> dict:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C.UTF-8", "LANGUAGE": "C"}
    if "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    env.update(extra)
    return env


class Case(unittest.TestCase):
    """Base class: a temporary directory per test and the `both` runner."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="caps-release-test-")
        self.addCleanup(self.rmtree, self.tmp)

    @staticmethod
    def rmtree(path):
        for root, dirs, _ in os.walk(path):
            for d in dirs:
                with contextlib.suppress(OSError):
                    os.chmod(os.path.join(root, d), 0o700)
        shutil.rmtree(path, ignore_errors=True)

    def path(self, *parts) -> str:
        return os.path.join(self.tmp, *parts)

    def write(self, name: str, content="", mode="w") -> str:
        path = self.path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
            fh.write(content)
        return path

    def both(self, name: str, argv: list[str], env: dict | None = None, **kwargs) -> Result:
        """Run in-process and as a calling workflow does; they must agree. Returns the in-process result."""
        sink = argv[argv.index("--output") + 1] if "--output" in argv else None
        before = _read(sink)
        a = run_main(name, argv, env=env, **kwargs)
        after_main = _read(sink)
        if kwargs or SCRIPT_DIR_OVERRIDE:       # a replaced collaborator cannot cross a process boundary;
            return a                            # and a mutant is judged on its in-process behaviour, for speed
        if sink is not None:
            _restore(sink, before)
        b = run_proc(name, argv, env=env)
        self.assertEqual(a.rc, b.rc, f"main() and the subprocess disagree on the exit status: {a} / {b}")
        self.assertEqual(a.errors(), b.errors(), "main() and the subprocess disagree on the ::error:: lines")
        self.assertEqual(after_main, _read(sink), "main() and the subprocess disagree on what they wrote")
        return a

    def refused(self, res: Result, fragment: str | None = None):
        self.assertEqual(res.rc, 1, res)
        self.assertTrue(res.errors(), f"a refusal must print ::error:: on stderr: {res}")
        if fragment is not None:
            self.assertIn(fragment, "\n".join(res.errors()), res)

    def accepted(self, res: Result):
        self.assertEqual(res.rc, 0, res)
        self.assertEqual(res.errors(), [], res)


def _read(path):
    if path is None:
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return b""


def _restore(path, content):
    if content is None:
        return
    if content == b"" and not os.path.exists(path):
        return
    with open(path, "wb") as fh:
        fh.write(content)


def known_defect(ident: str, why: str):
    """Mark a test that states the CORRECT behaviour of a script that does not have it yet.

    The test fails today and is reported as an expected failure. It turns into an unexpected success
    (which fails the run) the moment the script is fixed, at which point the decorator is removed.
    Against a mutated copy of a script it is skipped: a mutant is judged by assertions that hold.
    """
    def wrap(fn):
        @functools.wraps(fn)
        def inner(self, *args, **kwargs):
            if SCRIPT_DIR_OVERRIDE:
                self.skipTest("known-defect tests are not mutation targets")
            return fn(self, *args, **kwargs)
        inner.__doc__ = f"[{ident}] {why}"
        return unittest.expectedFailure(inner)
    return wrap


def have_gpg() -> bool:
    return shutil.which("gpg") is not None and shutil.which("gpgconf") is not None


def pom(body: str, ns: str = "") -> str:
    attr = f' xmlns="{ns}"' if ns else ""
    return f'<?xml version="1.0"?>\n<project{attr}>\n{body}\n</project>\n'
