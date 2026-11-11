"""Every script ends an unexpected exception with exactly one `::error::` line and exit 1; usage errors stay exit 2."""
from __future__ import annotations

import builtins
import os
import stat
import unittest

import caps_release_helpers as h
from caps_release_helpers import known_defect, pom
from readiness_support import Fixture, pom_xml
from test_pom_scripts import EFF_PLUGIN, dep, eff

WRAPPED = ["resolve_release", "check_drift", "check_pom_version", "check_release_profile", "check_auto_publish",
           "scan_snapshots", "check_release_readiness"]
ALL = WRAPPED + ["remove_signing_key", "check_dry_run_log", "check_secrets"]
NEWLINE_MESSAGE = "boom\n::error::forged\nsecond line"


class Injected(h.Case):
    """An exception raised where the script has no handler for it, injected through the module's own seam."""

    def run_with(self, name, seam, argv, exc=RuntimeError):
        module = h.load(name)
        original = getattr(module, seam)

        def boom(*_a, **_k):
            raise exc(NEWLINE_MESSAGE)
        setattr(module, seam, boom)
        try:
            return h.run_main(name, argv)
        finally:
            setattr(module, seam, original)

    ARGV = {
        "resolve_release": ["--target", "none", "--upload", "false", "--version", "1.2.3", "--generated-path", "g", "--ref-type", "branch"],
        "check_drift": ["--repo", ".", "--generated", "g"],
        "check_pom_version": ["--pom", "p", "--want", "1.0.0"],
        "check_release_profile": ["--pom", "p", "--target", "none"],
        "check_auto_publish": ["--effective-pom", "p"],
        "scan_snapshots": ["--effective-pom", "p", "--dependencies", "d", "--upload", "true"],
        "check_release_readiness": ["--target-dir", "t"],
    }

    def test_a_runtime_error_inside_the_script_is_one_error_line_and_exit_one(self):
        for name in WRAPPED:
            with self.subTest(name):
                res = self.run_with(name, "run", self.ARGV[name])
                self.assertEqual(res.rc, 1, res)
                self.assertEqual(len(res.errors()), 1, res)
                self.assertEqual(len(res.err.splitlines()), 1, "the message is flattened to one line")
                self.assertIn("unexpectedly", res.err)
                self.assertIn("RuntimeError", res.err)
                self.assertEqual(res.out, "")

    def test_keyboard_interrupt_and_system_exit_are_not_swallowed(self):
        for name in WRAPPED:
            for exc in (KeyboardInterrupt,):
                with self.subTest(name, exc=exc.__name__):
                    with self.assertRaises(exc):
                        self.run_with(name, "run", self.ARGV[name], exc)

    def test_key_removal_ends_an_unexpected_exception_with_one_line_and_cleans_up(self):
        secret, verify, key, env = (self.path(n) for n in ("secret", "verify", "key", "env"))
        os.makedirs(secret)
        os.makedirs(verify)
        for f in (key, env):
            with open(f, "w") as fh:
                fh.write("KEEP=1\n")
        res = self.run_with("remove_signing_key", "removal", ["--secret-home", secret, "--verify-home", verify, "--public-key", key,
                                                              "--env-file", env])
        self.assertEqual(res.rc, 1)
        self.assertEqual(len(res.errors()), 1)
        self.assertEqual(len(res.err.splitlines()), 1)
        for gone in (verify, key):
            self.assertFalse(os.path.exists(gone))
        with open(env) as fh:
            self.assertEqual(fh.read(), "KEEP=1\n")

    def test_the_dry_run_log_check_ends_an_unexpected_exception_with_one_line(self):
        log = self.write("log", "Skipping the upload of the bundle at user's request")
        module = h.load("check_dry_run_log")
        real = builtins.open

        def boom(path, *a, **k):
            if path == log:
                raise RuntimeError("boom")
            return real(path, *a, **k)
        module.open = boom
        try:
            res = h.run_main("check_dry_run_log", ["--log", log])
        finally:
            del module.open
        self.assertEqual((res.rc, len(res.errors())), (1, 1))

    def test_the_secrets_check_ends_an_unexpected_exception_with_one_line(self):
        module = h.load("check_secrets")

        class Env:
            def get(self, *_a):
                raise RuntimeError("boom")
        real = module.os
        fake = type("os", (), {"environ": Env()})
        module.os = fake
        try:
            res = h.run_main("check_secrets", ["--target", "central"])
        finally:
            module.os = real
        self.assertEqual((res.rc, len(res.errors())), (1, 1))


class Seams(h.Case):
    """The real seams: an unwritable output, a summary that cannot be opened, an input nobody may read."""

    def test_an_unwritable_output_is_one_error_line_for_the_profile_check(self):
        f = self.write("pom.xml", pom("<profiles><profile><id>release</id></profile></profiles>"))
        for out in (self.tmp, self.path("absent", "out")):
            for run in (h.run_main, h.run_proc):
                with self.subTest(out, run=run.__name__):
                    res = run("check_release_profile", ["--pom", f, "--target", "none", "--output", out])
                    self.assertEqual((res.rc, len(res.errors())), (1, 1), res)
                    self.assertIn("failed unexpectedly", res.err)
                    self.assertNotIn("ok - this ref", res.out)

    def test_an_unwritable_summary_is_one_error_line_for_the_snapshot_scan(self):
        eff_f = self.write("eff.xml", eff(dep("1.0-SNAPSHOT")))
        deps = self.write("deps", "")
        for out in (self.tmp, self.path("absent", "summary.md")):
            for run in (h.run_main, h.run_proc):
                with self.subTest(out, run=run.__name__):
                    res = run("scan_snapshots", ["--effective-pom", eff_f, "--dependencies", deps, "--upload", "false", "--summary", out])
                    self.assertEqual((res.rc, len(res.errors())), (1, 1), res)
                    self.assertIn("failed unexpectedly", res.err)

    def test_an_unreadable_input_is_one_error_line_for_every_script_that_reads_one(self):
        cases = {
            "check_pom_version": ["--pom", self.path("absent"), "--want", "1.0.0"],
            "check_release_profile": ["--pom", self.path("absent"), "--target", "none"],
            "check_auto_publish": ["--effective-pom", self.path("absent")],
            "scan_snapshots": ["--effective-pom", self.path("absent"), "--dependencies", self.write("d", ""), "--upload", "true"],
            "check_dry_run_log": ["--log", self.path("absent")],
            "check_release_readiness": ["--target-dir", self.path("absent")],
            "check_drift": ["--repo", self.path("absent"), "--generated", "g"],
        }
        for name, argv in cases.items():
            for run in (h.run_main, h.run_proc):
                with self.subTest(name, run=run.__name__):
                    res = run(name, argv)
                    self.assertEqual((res.rc, len(res.errors())), (1, 1), res)

    def test_an_input_the_user_may_not_read_is_one_error_line(self):
        locked = self.write("locked.xml", pom("<version>1.0.0</version>"))
        os.chmod(locked, 0)
        if os.access(locked, os.R_OK):
            self.skipTest("permissions are not enforced for this user")
        for name, argv in (("check_pom_version", ["--pom", locked, "--want", "1.0.0"]),
                           ("check_release_profile", ["--pom", locked, "--target", "none"]),
                           ("check_auto_publish", ["--effective-pom", locked]),
                           ("scan_snapshots", ["--effective-pom", locked, "--dependencies", self.write("d", ""), "--upload", "true"]),
                           ("check_dry_run_log", ["--log", locked])):
            with self.subTest(name):
                res = h.run_proc(name, argv)
                self.assertEqual((res.rc, len(res.errors())), (1, 1), res)


class Readiness(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()

    def lock(self, name):
        path = os.path.join(self.target, name)
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        if os.access(path, os.R_OK):
            self.skipTest("permissions are not enforced for this user")

    def test_an_unreadable_javadoc_jar_is_one_error_line(self):
        self.lock("a-1.0.0-javadoc.jar")
        res = self.check()
        self.assertEqual((res.rc, len(res.errors())), (1, 1), res)
        self.assertIn("failed unexpectedly", res.err)

    def test_an_unreadable_pom_is_reported_as_a_pom_that_cannot_be_read(self):
        self.lock("a-1.0.0.pom")
        self.refused(self.check(), "cannot be read as a POM")

    def test_an_unreadable_bundle_is_one_error_line(self):
        self.write_bundle(self.bundle_entries())
        os.chmod(self.bundle_path, 0)
        self.addCleanup(os.chmod, self.bundle_path, 0o600)
        if os.access(self.bundle_path, os.R_OK):
            self.skipTest("permissions are not enforced for this user")
        res = self.check("--expect-bundle", "true")
        self.assertEqual((res.rc, len(res.errors())), (1, 1), res)

    def test_a_gpg_that_cannot_run_makes_every_signature_bad_and_stages_nothing_unchecked(self):
        res = self.check("--gpg", self.path("no-such-gpg"))
        self.refused(res, "is not a good signature")
        self.assertEqual(len([e for e in res.errors() if "not a good signature" in e]), 4)


class Usage(h.Case):
    def test_an_unknown_flag_is_a_usage_error_for_every_script_in_both_modes(self):
        for name in ALL:
            for run in (h.run_main, h.run_proc):
                with self.subTest(name, run=run.__name__):
                    self.assertEqual(run(name, ["--no-such-flag", "x"]).rc, 2)

    def test_missing_required_arguments_are_a_usage_error_wherever_one_is_required(self):
        for name in ALL:
            if name == "resolve_release":
                continue            # every flag defaults to empty and is then refused as a value
            for run in (h.run_main, h.run_proc):
                with self.subTest(name, run=run.__name__):
                    self.assertEqual(run(name, []).rc, 2)

    def test_a_value_outside_a_choice_is_a_usage_error(self):
        f = self.write("p", "")
        for name, argv in (("check_release_profile", ["--pom", f, "--target", "maven"]),
                           ("scan_snapshots", ["--effective-pom", f, "--dependencies", f, "--upload", "maybe"]),
                           ("check_release_readiness", ["--target-dir", f, "--expect-bundle", "maybe"]),
                           ("check_secrets", ["--target", "none"])):
            with self.subTest(name):
                self.assertEqual(h.run_main(name, argv).rc, 2)
                self.assertEqual(h.run_proc(name, argv).rc, 2)


if __name__ == "__main__":
    unittest.main()
