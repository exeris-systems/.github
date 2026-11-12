"""Every subprocess the release scripts start is bounded, and an expiry is a refusal with one error line and nothing left behind.

The bound is a module constant (`SUBPROCESS_TIMEOUT`, `GH_TIMEOUT`, `GIT_TIMEOUT`); the tests assert its value, assert that
the call passes it to `subprocess.run`, and then lower it to a fraction of a second against a double that sleeps, so no test
waits for the real bound.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import time
import unittest

import caps_release_helpers as h
from readiness_support import Fixture
from test_remove_signing_key import Doubles
from test_resolve_release import TAG, argv
from test_staging_binding import bounded, patched

READY = "check_release_readiness"
RESOLVE = "resolve_release"
DRIFT = "check_drift"
REMOVE = "remove_signing_key"


@contextlib.contextmanager
def spying_on_run():
    """Record the timeout of every subprocess.run call made while the block runs."""
    real = subprocess.run
    seen = []

    def run(cmd, *a, **k):
        seen.append((list(cmd) if not isinstance(cmd, str) else cmd, k.get("timeout")))
        return real(cmd, *a, **k)
    subprocess.run = run
    try:
        yield seen
    finally:
        subprocess.run = real


class Bounds(Fixture):
    """The stated bounds, read off the calls themselves."""

    def test_the_constants_state_the_documented_bounds(self):
        self.assertEqual(h.load(READY).SUBPROCESS_TIMEOUT, 120)
        self.assertEqual(h.load(RESOLVE).GH_TIMEOUT, 120)
        self.assertEqual(h.load(DRIFT).GIT_TIMEOUT, 300)
        self.assertEqual(h.load(REMOVE).SUBPROCESS_TIMEOUT, 120)

    def test_every_gpg_verification_is_started_with_the_bound(self):
        self.real_coordinate()
        with spying_on_run() as seen:
            res = h.run_main(READY, ["--target-dir", self.target, "--gpg", self.gpg])
        self.accepted(res)
        verifies = [(c, t) for c, t in seen if "--verify" in c]
        self.assertEqual(len(verifies), 4)
        self.assertEqual({t for _, t in verifies}, {120})

    def test_the_gh_call_is_started_with_the_bound(self):
        with spying_on_run() as seen:
            try:
                h.load(RESOLVE).compare_status("o/r", "a" * 40, "main")
            except (OSError, subprocess.CalledProcessError):
                pass
        calls = [(c, t) for c, t in seen if c and c[0] == "gh"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 120)

    def test_every_git_call_of_the_drift_check_is_started_with_the_bound(self):
        repo = self.path("repo")
        os.makedirs(os.path.join(repo, "gen"))
        subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
        with spying_on_run() as seen:
            h.load(DRIFT).git(repo, "rev-parse", "--is-inside-work-tree")
        git = [(c, t) for c, t in seen if c and c[0] == "git"]
        self.assertEqual([t for _, t in git], [300])


class KeyBounds(Doubles):
    def test_every_tool_of_the_key_removal_is_started_with_the_bound(self):
        self.prepare()
        with spying_on_run() as seen:
            res = self.invoke()
        self.accepted(res)
        tools = [(c, t) for c, t in seen if c and os.path.basename(c[0]) in ("gpg", "gpgconf")]
        self.assertGreaterEqual(len(tools), 4, tools)
        self.assertEqual({t for _, t in tools}, {120}, tools)


class GateGpg(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()
        self.mod = h.load(READY)
        self.tmpdir = self.path("tmp")
        os.mkdir(self.tmpdir)

    def test_a_gpg_that_never_answers_makes_every_signature_bad_and_leaves_nothing(self):
        self.use_py_gpg()
        stage = self.path("gated-files")
        saved = tempfile.tempdir
        tempfile.tempdir = self.tmpdir
        start = time.monotonic()
        try:
            with patched(self.mod, SUBPROCESS_TIMEOUT=0.3), bounded(60):
                res = h.run_main(READY, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", stage],
                                 env=h.clean_env(PYGPG_SLEEP="30"))
        finally:
            tempfile.tempdir = saved
        self.assertLess(time.monotonic() - start, 20, "the expiry, not the sleep, ends each call")
        self.refused(res, "is not a good signature")
        self.assertEqual(len([e for e in res.errors() if "is not a good signature" in e]), 4)
        self.assertEqual(len(res.errors()), 5, "one line per signature and the closing line, no traceback")
        self.assertFalse(os.path.lexists(stage))
        self.assertEqual(os.listdir(self.tmpdir), [])

    def test_the_same_for_the_signatures_inside_a_bundle(self):
        self.use_py_gpg()
        self.write_bundle(self.bundle_entries())
        saved = tempfile.tempdir
        tempfile.tempdir = self.tmpdir
        try:
            with patched(self.mod, SUBPROCESS_TIMEOUT=0.3), bounded(60):
                res = h.run_main(READY, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"],
                                 env=h.clean_env(PYGPG_SLEEP="30"))
        finally:
            tempfile.tempdir = saved
        self.refused(res, "is not a good signature")
        self.assertEqual(len([e for e in res.errors() if "of the bundle's own file" in e]), 4)
        self.assertEqual(os.listdir(self.tmpdir), [])

    def test_a_gpg_that_answers_within_the_bound_is_not_cut_short(self):
        self.use_py_gpg()
        with patched(self.mod, SUBPROCESS_TIMEOUT=5):
            res = h.run_main(READY, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(PYGPG_SLEEP="0.05"))
        self.accepted(res)


class Gh(h.Case):
    def test_a_gh_that_never_answers_is_a_refused_comparison_with_one_line(self):
        bin_dir = self.path("bin")
        os.makedirs(bin_dir)
        self.write("bin/gh", "#!/bin/sh\nexec sleep 30\n")
        os.chmod(os.path.join(bin_dir, "gh"), 0o755)
        env = h.clean_env(PATH=bin_dir + os.pathsep + os.environ.get("PATH", "/usr/bin"))
        start = time.monotonic()
        with patched(h.load(RESOLVE), GH_TIMEOUT=0.3), bounded(60):
            res = h.run_main(RESOLVE, argv(TAG, compare_status="", sha="a" * 40), env=env)
        self.assertLess(time.monotonic() - start, 20)
        self.refused(res, "the comparison with main failed")
        self.assertEqual(len(res.errors()), 1, res)
        self.assertIn("timed out", res.err)


class Git(h.Case):
    def test_a_git_that_never_answers_ends_the_drift_check_with_one_line(self):
        real_git = shutil.which("git")
        bin_dir = self.path("bin")
        os.makedirs(bin_dir)
        self.write("bin/git", f"#!/bin/sh\ncase \" $* \" in *\" status \"*) exec sleep 30 ;; esac\nexec {real_git} \"$@\"\n")
        os.chmod(os.path.join(bin_dir, "git"), 0o755)
        repo = self.path("repo")
        os.makedirs(os.path.join(repo, "gen"))
        subprocess.run([real_git, "init", "-q", "-b", "main", repo], check=True, capture_output=True)
        with open(os.path.join(repo, "gen", "a.txt"), "w") as fh:
            fh.write("a\n")
        subprocess.run([real_git, "-C", repo, "add", "-A"], check=True, capture_output=True)
        subprocess.run([real_git, "-C", repo, "-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false",
                        "commit", "-q", "-m", "x"], check=True, capture_output=True)
        env = h.clean_env(PATH=bin_dir + os.pathsep + os.environ.get("PATH", "/usr/bin"))
        start = time.monotonic()
        with patched(h.load(DRIFT), GIT_TIMEOUT=0.3), bounded(60):
            res = h.run_main(DRIFT, ["--repo", repo, "--generated=gen"], env=env)
        self.assertLess(time.monotonic() - start, 20)
        self.refused(res, "git timed out after 0.3 seconds")
        self.assertEqual(len(res.errors()), 1, res)


SLEEPING_DOUBLE = """#!/bin/sh
tool="$(basename "$0")"
printf '%s\\t%s\\t%s\\t%s\\n' "$tool" "$*" "$GNUPGHOME" "$([ -d "${GNUPGHOME:-/nonexistent}" ] && echo yes || echo no)" >> "$FAKE_LOG"
case "$tool $*" in *"$FAKE_SLEEP_ON"*) exec sleep 30 ;; esac
case " $* " in
  *" --show-keys "*) exit 0 ;;
  *" --list-secret-keys "*) exit 0 ;;
esac
exit 0
"""


class KeyRemoval(Doubles):
    def setUp(self):
        super().setUp()
        with open(self.fake, "w") as fh:
            fh.write(SLEEPING_DOUBLE)
        self.tmpdir = self.path("tmp")
        os.mkdir(self.tmpdir)
        self.mod = h.load(REMOVE)

    def run_sleeping(self, on):
        self.prepare(env_content="KEEP=1\n")
        saved = tempfile.tempdir
        tempfile.tempdir = self.tmpdir
        start = time.monotonic()
        try:
            with patched(self.mod, SUBPROCESS_TIMEOUT=0.3), bounded(60):
                res = self.invoke(FAKE_SLEEP_ON=on)
        finally:
            tempfile.tempdir = saved
        self.assertLess(time.monotonic() - start, 20)
        return res

    def assert_cleaned_up(self):
        self.assertFalse(os.path.lexists(self.secret), "the secret home is removed")
        self.assertFalse(os.path.lexists(self.key), "the exported key is removed")
        self.assertFalse(os.path.lexists(self.verify), "the verify home is removed")
        self.assertEqual(os.listdir(self.tmpdir), [], "the inspection home is removed")
        with open(self.envfile) as fh:
            self.assertEqual(fh.read(), "KEEP=1\n", "the environment file is not extended by a failed removal")

    def test_a_gpgconf_that_never_answers_does_not_stop_the_removal(self):
        res = self.run_sleeping("gpgconf")
        self.accepted(res)
        self.assertFalse(os.path.lexists(self.secret))

    def test_each_gpg_call_that_never_answers_is_one_failure_line_and_everything_is_removed(self):
        for on in ("--show-keys", "--import", "--list-secret-keys"):
            with self.subTest(on):
                shutil.rmtree(self.verify, ignore_errors=True)
                res = self.run_sleeping(on)
                self.refused(res, "failed unexpectedly (TimeoutExpired")
                self.assertEqual(len(res.errors()), 1, res)
                self.assert_cleaned_up()


if __name__ == "__main__":
    unittest.main()
