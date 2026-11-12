"""check_dry_run_log and check_secrets: an exception nobody planned for is one `::error::` line and exit 1; misuse is exit 2."""
from __future__ import annotations

import os
import unittest

import caps_release_helpers as h

LOG = "check_dry_run_log"
SECRETS = "check_secrets"
SKIPPED = "Skipping the upload of the bundle at user's request"
MESSAGE = "boom\n::error::forged\nsecond line"


class Unexpected(h.Case):
    def inject(self, name, seam, argv, exc=RuntimeError, env=None):
        module = h.load(name)
        original = getattr(module, seam)

        def boom(*_a, **_k):
            raise exc(MESSAGE)
        setattr(module, seam, boom)
        try:
            return h.run_main(name, argv, env=env)
        finally:
            setattr(module, seam, original)

    def test_a_failure_inside_either_script_is_one_error_line_and_exit_one(self):
        log = self.write("log", SKIPPED)
        cases = {LOG: ["--log", log], SECRETS: ["--target", "central"]}
        for name, argv in cases.items():
            for exc in (RuntimeError, ValueError, KeyError, OSError, AttributeError, ZeroDivisionError, UnicodeError, MemoryError):
                with self.subTest(name, exc=exc.__name__):
                    res = self.inject(name, "run", argv, exc)
                    self.assertEqual(res.rc, 1, res)
                    self.assertEqual(len(res.err.splitlines()), 1, "a newline in the message cannot start a second line")
                    self.assertEqual(len(res.errors()), 1)
                    self.assertIn(f"failed unexpectedly ({exc.__name__}", res.err)
                    self.assertNotIn("\n::error::forged", res.err)
                    self.assertEqual(res.out, "")

    def test_a_refusal_of_the_program_is_one_line_and_never_a_traceback(self):
        """A traceback would end with exit 1 too; the difference is the single line."""
        log = self.write("log", SKIPPED)
        for name, argv, env in ((LOG, ["--log", self.tmp], None), (SECRETS, ["--target", "central"], None)):
            res = h.run_proc(name, argv, env=env)
            self.assertEqual(res.rc, 1, res)
            self.assertNotIn("Traceback", res.err)
            self.assertEqual(len(res.errors()), 1, res)
        self.assertEqual(h.run_proc(LOG, ["--log", log]).rc, 0)

    def test_a_usage_error_is_exit_two_without_an_error_line_and_is_not_turned_into_one(self):
        for name, argv in ((LOG, []), (LOG, ["--log"]), (LOG, ["--log", "x", "--extra"]), (SECRETS, []),
                           (SECRETS, ["--target", "none"]), (SECRETS, ["--target", "Central"]), (SECRETS, ["--target"])):
            for run in (h.run_main, h.run_proc):
                with self.subTest(name, argv=argv, run=run.__name__):
                    res = run(name, argv)
                    self.assertEqual(res.rc, 2, res)
                    self.assertEqual(res.errors(), [])
                    self.assertNotIn("Traceback", res.err)

    def test_a_system_exit_from_the_arguments_passes_through_the_wrapper(self):
        res = h.run_main(SECRETS, ["--help"])
        self.assertEqual(res.rc, 0)
        self.assertIn("usage", res.out.lower())

    def test_help_names_the_exit_statuses(self):
        for name in (LOG, SECRETS):
            doc = h.load(name).__doc__
            self.assertIn("Exit status", doc)
            self.assertIn("2 usage error", doc)
            self.assertIn("unexpectedly", doc)


class Reading(h.Case):
    def test_an_unreadable_or_odd_log_is_one_line(self):
        d = self.path("dir")
        os.mkdir(d)
        for label, path in (("directory", d), ("absent", self.path("absent"))):
            with self.subTest(label):
                res = self.both(LOG, ["--log", path])
                self.refused(res, "cannot be read")
                self.assertEqual(len(res.errors()), 1)

    def test_bytes_that_are_not_text_do_not_hide_the_statement(self):
        f = self.write("log", b"\xff\xfe\x00" + SKIPPED.encode() + b"\x80", mode="wb")
        self.accepted(self.both(LOG, ["--log", f]))
        started = self.write("log2", b"\xff Going to upload \x80" + SKIPPED.encode(), mode="wb")
        self.refused(self.both(LOG, ["--log", started]), "began an upload")


class Secrets(h.Case):
    def test_only_the_exact_word_true_counts(self):
        full = {"HAVE_GPG_KEY": "true", "HAVE_GPG_PASSPHRASE": "true", "HAVE_CENTRAL_USER": "true", "HAVE_CENTRAL_PASSWORD": "true"}
        self.accepted(self.both(SECRETS, ["--target", "central"], env=h.clean_env(**full)))
        for value in ("True", "TRUE", "1", "yes", "false", "", " true", "true ", "true\n"):
            with self.subTest(repr(value)):
                env = h.clean_env(**{**full, "HAVE_GPG_KEY": value})
                res = self.both(SECRETS, ["--target", "central"], env=env)
                self.refused(res, "GPG_PRIVATE_KEY")
                self.assertEqual(len(res.errors()), 1)

    def test_github_packages_does_not_need_the_central_secrets(self):
        env = h.clean_env(HAVE_GPG_KEY="true", HAVE_GPG_PASSPHRASE="true")
        self.accepted(self.both(SECRETS, ["--target", "github-packages"], env=env))
        self.refused(self.both(SECRETS, ["--target", "central"], env=env), "CENTRAL_TOKEN_USERNAME, CENTRAL_TOKEN_PASSWORD")

    def test_no_secret_value_is_ever_printed(self):
        env = h.clean_env(HAVE_GPG_KEY="s3cr3t-value", HAVE_GPG_PASSPHRASE="true")
        res = self.both(SECRETS, ["--target", "github-packages"], env=env)
        self.assertNotIn("s3cr3t-value", res.out + res.err)


if __name__ == "__main__":
    unittest.main()
