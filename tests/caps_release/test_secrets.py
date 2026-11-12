"""check_secrets: no arguments, only the literal `true` counts, and the missing secrets are named without a value."""
from __future__ import annotations

import unittest

import caps_release_helpers as h

SECRETS = "check_secrets"
MESSAGE = "boom\n::error::forged\nsecond line"
FULL = {"HAVE_GPG_KEY": "true", "HAVE_GPG_PASSPHRASE": "true"}


class Counting(h.Case):
    def test_both_secrets_present_is_accepted(self):
        res = self.both(SECRETS, [], env=h.clean_env(**FULL))
        self.accepted(res)
        self.assertIn("ok - the signing secrets were passed", res.out)

    def test_only_the_exact_word_true_counts_for_each_secret(self):
        for var, secret in (("HAVE_GPG_KEY", "GPG_PRIVATE_KEY"), ("HAVE_GPG_PASSPHRASE", "GPG_PASSPHRASE")):
            for value in ("True", "TRUE", "1", "yes", "false", "", " true", "true ", "true\n", "tru", "truee"):
                with self.subTest(var, value=repr(value)):
                    res = self.both(SECRETS, [], env=h.clean_env(**{**FULL, var: value}))
                    self.refused(res, secret)
                    self.assertEqual(len(res.errors()), 1)
                    other = "GPG_PASSPHRASE" if secret == "GPG_PRIVATE_KEY" else "GPG_PRIVATE_KEY"
                    self.assertNotIn(other, res.err, "only the missing secret is named")

    def test_an_unset_variable_is_missing(self):
        for env, named in ((h.clean_env(), "GPG_PRIVATE_KEY, GPG_PASSPHRASE"),
                           (h.clean_env(HAVE_GPG_KEY="true"), "GPG_PASSPHRASE"),
                           (h.clean_env(HAVE_GPG_PASSPHRASE="true"), "GPG_PRIVATE_KEY")):
            with self.subTest(named):
                res = self.both(SECRETS, [], env=env)
                self.refused(res, f"an upload needs secrets the caller did not pass: {named}")
                self.assertEqual(len(res.errors()), 1)

    def test_a_variable_of_another_target_is_neither_needed_nor_counted(self):
        res = self.both(SECRETS, [], env=h.clean_env(HAVE_CENTRAL_USER="true", HAVE_CENTRAL_PASSWORD="true"))
        self.refused(res, "GPG_PRIVATE_KEY, GPG_PASSPHRASE")
        self.accepted(self.both(SECRETS, [], env=h.clean_env(**FULL, HAVE_CENTRAL_USER="false")))

    def test_no_secret_value_is_ever_printed(self):
        env = h.clean_env(HAVE_GPG_KEY="s3cr3t-value", HAVE_GPG_PASSPHRASE="true", GPG_PRIVATE_KEY="s3cr3t-key",
                          GPG_PASSPHRASE="s3cr3t-pass", GITHUB_TOKEN="s3cr3t-token")
        res = self.both(SECRETS, [], env=env)
        self.refused(res, "GPG_PRIVATE_KEY")
        for value in ("s3cr3t-value", "s3cr3t-key", "s3cr3t-pass", "s3cr3t-token"):
            self.assertNotIn(value, res.out + res.err)
        res = self.both(SECRETS, [], env=h.clean_env(**FULL, GPG_PRIVATE_KEY="s3cr3t-key", GPG_PASSPHRASE="s3cr3t-pass"))
        self.accepted(res)
        self.assertNotIn("s3cr3t", res.out + res.err)


class Misuse(h.Case):
    def test_the_script_takes_no_argument(self):
        for argv in (["--target", "github-packages"], ["--target", "none"], ["--target", "central"], ["--target"], ["x"],
                     ["--expect-bundle", "true"], ["--no-such-flag"]):
            for run in (h.run_main, h.run_proc):
                with self.subTest(argv, run=run.__name__):
                    res = run(SECRETS, argv, env=h.clean_env(**FULL))
                    self.assertEqual(res.rc, 2, res)
                    self.assertEqual(res.errors(), [])
                    self.assertNotIn("Traceback", res.err)

    def test_help_exits_zero_and_names_the_exit_statuses(self):
        res = h.run_main(SECRETS, ["--help"])
        self.assertEqual(res.rc, 0)
        self.assertIn("usage", res.out.lower())
        doc = h.load(SECRETS).__doc__
        for fragment in ("Exit status", "2 usage error", "unexpectedly", "HAVE_GPG_KEY", "HAVE_GPG_PASSPHRASE"):
            self.assertIn(fragment, doc)

    def test_a_failure_inside_the_script_is_one_error_line_and_exit_one(self):
        module = h.load(SECRETS)
        for exc in (RuntimeError, ValueError, KeyError, OSError, AttributeError, ZeroDivisionError, UnicodeError, MemoryError):
            with self.subTest(exc.__name__):
                original = module.run

                def boom(*_a, _exc=exc, **_k):
                    raise _exc(MESSAGE)
                module.run = boom
                try:
                    res = h.run_main(SECRETS, [])
                finally:
                    module.run = original
                self.assertEqual(res.rc, 1, res)
                self.assertEqual(len(res.err.splitlines()), 1, "a newline in the message cannot start a second line")
                self.assertEqual(len(res.errors()), 1)
                self.assertIn(f"failed unexpectedly ({exc.__name__}", res.err)
                self.assertNotIn("\n::error::forged", res.err)
                self.assertEqual(res.out, "")

    def test_an_exception_while_reading_the_environment_is_one_line(self):
        module = h.load(SECRETS)

        class Env:
            def get(self, *_a):
                raise RuntimeError("boom")
        real = module.os
        module.os = type("os", (), {"environ": Env()})
        try:
            res = h.run_main(SECRETS, [])
        finally:
            module.os = real
        self.assertEqual((res.rc, len(res.errors())), (1, 1), res)

    def test_a_system_exit_and_a_keyboard_interrupt_are_not_swallowed(self):
        module = h.load(SECRETS)
        original = module.run

        def interrupt(*_a):
            raise KeyboardInterrupt()
        module.run = interrupt
        try:
            with self.assertRaises(KeyboardInterrupt):
                module.main([])
        finally:
            module.run = original


if __name__ == "__main__":
    unittest.main()
