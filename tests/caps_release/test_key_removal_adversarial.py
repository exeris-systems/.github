"""remove_signing_key against a secret key handed in as the public one, hostile paths and failing tools."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import caps_release_helpers as h
from caps_release_helpers import known_defect
from test_remove_signing_key import Doubles, RealBase

S = "remove_signing_key"

DOUBLE = """#!/bin/sh
tool="$(basename "$0")"
printf '%s\\t%s\\t%s\\t%s\\n' "$tool" "$*" "$GNUPGHOME" "$([ -d "${GNUPGHOME:-/nonexistent}" ] && echo yes || echo no)" >> "$FAKE_LOG"
printf '%s\\t%s\\n' "$*" "$(stat -c %a "${GNUPGHOME:-/nonexistent}" 2>/dev/null)" >> "$FAKE_LOG.modes"
case " $* " in
  *" --show-keys "*) printf '%s' "$FAKE_SHOW_OUT"; printf '%s' "$FAKE_SHOW_ERR" >&2; exit "${FAKE_SHOW_RC:-0}" ;;
  *" --import "*) printf '%s' "$FAKE_IMPORT_ERR" >&2; exit "${FAKE_IMPORT_RC:-0}" ;;
  *" --list-secret-keys "*) printf '%s' "$FAKE_LIST_OUT"; exit "${FAKE_LIST_RC:-0}" ;;
esac
exit 0
"""


def inspection_homes():
    return {n for n in os.listdir(tempfile.gettempdir()) if n.startswith("gnupg-inspect-")}


class Scripted(Doubles):
    """The gpg double also answers `--show-keys`, which is how the key file is inspected before it is imported."""

    def setUp(self):
        super().setUp()
        with open(self.fake, "w") as fh:
            fh.write(DOUBLE)
        self.before = inspection_homes()

    def run_removal(self, argv=None, **env):
        res = self.invoke(argv, **env)
        self.assertEqual(inspection_homes() - self.before, set(), "the throwaway inspection home is removed on every path")
        return res

    def assert_refused_cleanly(self, res, fragment, secret_gone=True):
        self.refused(res, fragment)
        self.assertEqual(self.env_bytes, self.read_env(), "the environment file is byte-identical to what it was")
        self.assertFalse(os.path.exists(self.verify), "the verify home is gone")
        self.assertFalse(os.path.exists(self.key), "the exported key file is gone")
        if secret_gone:
            self.assertFalse(os.path.exists(self.secret), "the secret home is gone")

    def read_env(self):
        with open(self.envfile, "rb") as fh:
            return fh.read()

    def prepare(self, **kw):
        kw.setdefault("env_content", "KEEP=1\n")
        super().prepare(**kw)
        self.env_bytes = self.read_env()


class Inspection(Scripted):
    def test_the_key_file_is_inspected_before_anything_is_imported_and_in_a_home_of_its_own(self):
        self.prepare()
        self.accepted(self.run_removal(FAKE_SHOW_OUT="pub:u:255:22:ABC\nuid:::::\n"))
        calls = self.calls()
        show = [c for c in calls if "--show-keys" in c["args"]]
        imp = [c for c in calls if "--import" in c["args"]]
        self.assertEqual(len(show), 1)
        self.assertEqual(show[0]["args"], ["--batch", "--show-keys", "--with-colons", self.key])
        self.assertNotIn(show[0]["home"], (self.secret, self.verify), "the inspection runs in a home that holds nothing else")
        self.assertTrue(show[0]["home_exists"])
        self.assertLess(calls.index(show[0]), calls.index(imp[0]))
        self.assertFalse(os.path.exists(show[0]["home"]), "and that home is removed")

    def modes(self):
        with open(self.log + ".modes") as fh:
            return [ln.rstrip("\n").split("\t") for ln in fh]

    def test_a_loose_verify_home_is_tightened_before_the_import_and_before_the_listing(self):
        self.prepare()
        os.makedirs(self.verify, mode=0o755)
        os.chmod(self.verify, 0o755)
        self.accepted(self.run_removal())
        for args, mode in self.modes():
            if "--import" in args or "--list-secret-keys" in args:
                self.assertEqual(mode, "700", args)

    def test_a_loose_verify_home_is_tightened_when_there_is_no_key_to_import(self):
        self.prepare(key=None)
        os.makedirs(self.verify, mode=0o755)
        os.chmod(self.verify, 0o755)
        self.accepted(self.run_removal())
        listing = [mode for args, mode in self.modes() if "--list-secret-keys" in args]
        self.assertEqual(listing, ["700"])

    def test_a_secret_subkey_listed_after_the_import_is_a_refusal(self):
        self.prepare()
        self.refused(self.run_removal(FAKE_LIST_OUT="pub:u\nssb:u:255\n"), "secret key is still")

    def test_a_verify_home_inside_the_secret_home_leaves_neither_behind(self):
        self.prepare()
        inside = os.path.join(self.secret, "v")
        self.refused(self.run_removal(self.argv(verify_home=inside)), "private keyring still exists")
        self.assertFalse(os.path.exists(self.secret))
        self.assertFalse(os.path.exists(inside))

    def test_a_secret_key_record_in_the_inspected_file_is_refused_unimported(self):
        for label, out in (("sec", "sec:u:255:22:ABC:1:::::\n"), ("ssb alone", "pub:u:255:22:ABC\nssb:u:255:18:DEF\n"),
                           ("sec after pub", "pub:u:255:22:ABC\nsec:u:255:22:XYZ\n"), ("sec last, no newline", "pub:u\nsec:u")):
            with self.subTest(label):
                shutil.rmtree(self.verify, ignore_errors=True)
                shutil.rmtree(self.secret, ignore_errors=True)
                open(self.log, "w").close()
                self.prepare()
                res = self.run_removal(FAKE_SHOW_OUT=out)
                self.assert_refused_cleanly(res, "holds a secret key and was not imported")
                self.assertEqual([c for c in self.calls() if "--import" in c["args"]], [], "nothing was imported anywhere")
                self.assertEqual([c for c in self.calls() if c["home"] == self.verify], [])
                self.assertEqual(len(res.errors()), 1)

    def test_records_that_only_start_with_the_letters_are_not_secret_keys(self):
        self.prepare()
        self.accepted(self.run_removal(FAKE_SHOW_OUT="pub:u\nsecret:x\nssbx:y\nuid:::sec:::\nfpr:::sec\n"))

    def test_a_failing_inspection_is_a_refusal_and_imports_nothing(self):
        self.prepare()
        res = self.run_removal(FAKE_SHOW_RC="2", FAKE_SHOW_ERR="gpg: no valid OpenPGP data found.")
        self.assert_refused_cleanly(res, "it could not be inspected: gpg: no valid OpenPGP data")
        self.assertEqual([c for c in self.calls() if "--import" in c["args"]], [])
        self.assertEqual(len(res.errors()), 1)

    def test_the_inspection_exit_status_is_what_decides(self):
        for rc in (1, 2, 3, 127):
            with self.subTest(rc):
                shutil.rmtree(self.verify, ignore_errors=True)
                self.prepare()
                self.refused(self.run_removal(FAKE_SHOW_RC=str(rc)), "could not be inspected")

    def test_an_empty_or_missing_key_file_is_not_inspected(self):
        for key in ("", None):
            with self.subTest(repr(key)):
                shutil.rmtree(self.verify, ignore_errors=True)
                open(self.log, "w").close()
                self.prepare(key=key)
                self.accepted(self.run_removal())
                self.assertEqual([c for c in self.calls() if "--show-keys" in c["args"]], [])

    def test_a_gpg_that_cannot_run_ends_in_one_error_line_with_the_secret_home_deleted(self):
        for label, key in (("with a key file", "PUBLIC KEY\n"), ("without", None)):
            with self.subTest(label):
                shutil.rmtree(self.verify, ignore_errors=True)
                self.prepare(key=key)
                res = self.run_removal(self.argv(gpg=self.path("bin", "no-such-gpg")))
                self.assert_refused_cleanly(res, "failed unexpectedly (FileNotFoundError")
                self.assertEqual(len(res.errors()), 1)
                self.assertNotIn(f"GNUPGHOME={self.verify}", self.read_env().decode())

    def test_the_subprocess_agrees_for_a_gpg_that_cannot_run(self):
        self.prepare()
        res = h.run_proc(S, self.argv(gpg=self.path("bin", "no-such-gpg")), env=h.clean_env(FAKE_LOG=self.log))
        self.assertEqual(res.rc, 1)
        self.assertEqual(len(res.errors()), 1)
        self.assertEqual(self.env_bytes, self.read_env())
        self.assertFalse(os.path.exists(self.secret))

    def test_an_environment_file_that_cannot_be_written_ends_in_one_error_line_and_removes_the_verify_home(self):
        self.prepare()
        res = self.run_removal(self.argv(env_file=self.path("no-such-dir", "env")))
        self.refused(res, "failed unexpectedly")
        self.assertEqual(len(res.errors()), 1)
        self.assertFalse(os.path.exists(self.verify))
        self.assertFalse(os.path.exists(self.secret))
        self.assertFalse(os.path.exists(self.key))

    def test_the_environment_file_is_written_once_and_only_on_success(self):
        self.prepare()
        self.accepted(self.run_removal())
        self.assertEqual(self.read_env(), self.env_bytes + f"GNUPGHOME={self.verify}\n".encode())
        failures = {"inspection": dict(FAKE_SHOW_RC="2"), "secret export": dict(FAKE_SHOW_OUT="sec:u\n"),
                    "import": dict(FAKE_IMPORT_RC="2"), "listing": dict(FAKE_LIST_OUT="sec:u\n"), "listing status": dict(FAKE_LIST_RC="3")}
        for label, env in failures.items():
            with self.subTest(label):
                shutil.rmtree(self.verify, ignore_errors=True)
                self.prepare()
                self.refused(self.run_removal(**env))
                self.assertEqual(self.read_env(), self.env_bytes)

    def test_a_symlinked_secret_home_is_not_followed_and_the_run_fails_with_one_line(self):
        real = self.path("real-secret")
        os.makedirs(real)
        with open(os.path.join(real, "private-keys"), "w") as fh:
            fh.write("PRIVATE")
        os.symlink(real, self.secret)
        self.prepare(secret=False)
        res = self.run_removal()
        self.refused(res, "the secret home is a symbolic link")
        self.assertEqual(len(res.errors()), 1)
        self.assertTrue(os.path.islink(self.secret))
        self.assertTrue(os.path.isfile(os.path.join(real, "private-keys")))
        self.assertEqual(self.env_bytes, self.read_env())
        self.assertEqual([c for c in self.calls() if c["tool"] == "gpgconf"], [], "no agent is stopped through the link")

    def test_a_verify_home_that_is_a_symlink_is_removed_as_a_link_on_failure(self):
        real = self.path("somewhere")
        os.makedirs(real)
        with open(os.path.join(real, "keep"), "w") as fh:
            fh.write("data")
        os.symlink(real, self.verify)
        self.prepare()
        self.refused(self.run_removal(FAKE_LIST_OUT="sec:u\n"))
        self.assertFalse(os.path.lexists(self.verify))
        self.assertTrue(os.path.isfile(os.path.join(real, "keep")), "the target of the link is untouched")


class HostilePaths(Scripted):
    BAD = {"newline": "\n", "carriage return": "\r", "escape": "\x1b", "line separator": " ", "paragraph separator": " ",
           "zero width space": "​", "bidi override": "‮", "byte order mark": "﻿", "unassigned": "͸",
           "delete": "\x7f", "c1 control": "\x85", "lone surrogate": "\udc80"}

    def test_every_unusual_character_in_each_of_the_four_paths_is_refused_and_writes_nothing(self):
        for flag in ("secret_home", "verify_home", "public_key", "env_file"):
            for label, ch in self.BAD.items():
                with self.subTest(flag=flag, char=label):
                    for d in (self.secret, self.verify):
                        shutil.rmtree(d, ignore_errors=True)
                    open(self.log, "w").close()
                    self.prepare()
                    argv = self.argv(**{flag: getattr(self, {"secret_home": "secret", "verify_home": "verify",
                                                             "public_key": "key", "env_file": "envfile"}[flag]) + ch + "EVIL=1"})
                    res = self.run_removal(argv)
                    flagname = "--" + flag.replace("_", "-")
                    self.refused(res, f"{flagname} holds a control or unassigned character")
                    self.assertNotIn("EVIL=1\n", self.read_env().decode() if flag != "env_file" else "")
                    self.assertEqual(self.read_env() if flag != "env_file" else self.env_bytes, self.env_bytes)
                    self.assertEqual([c for c in self.calls() if "--import" in c["args"] or "--show-keys" in c["args"]], [],
                                     "no key is inspected or imported under a hostile path")

    def test_a_hostile_path_cannot_append_a_second_line_to_the_environment_file(self):
        self.prepare()
        evil = self.verify + "\nGITHUB_OUTPUT=/x"
        self.refused(self.run_removal(self.argv(verify_home=evil)))
        self.assertEqual(self.read_env(), self.env_bytes)

    def test_no_tool_is_run_under_a_hostile_secret_home_path(self):
        evil = self.secret + "\u200b"
        os.makedirs(evil)
        self.prepare(secret=False)
        try:
            self.refused(self.run_removal(self.argv(secret_home=evil)))
            self.assertEqual([c for c in self.calls() if c["home"] == evil or c["tool"] == "gpgconf"], [])
        finally:
            shutil.rmtree(evil, ignore_errors=True)

    def test_a_hostile_verify_home_does_not_stop_the_private_keyring_from_being_removed(self):
        self.prepare()
        self.refused(self.run_removal(self.argv(verify_home=self.verify + "​")))
        self.assertFalse(os.path.exists(self.secret))

    def test_a_hostile_public_key_path_does_not_stop_the_private_keyring_from_being_removed(self):
        self.prepare()
        self.refused(self.run_removal(self.argv(public_key=self.key + " ")))
        self.assertFalse(os.path.exists(self.secret))

    def test_a_hostile_secret_home_path_must_still_remove_the_private_keyring(self):
        evil = self.secret + "​"
        os.makedirs(evil)
        with open(os.path.join(evil, "private-keys"), "w") as fh:
            fh.write("PRIVATE")
        self.prepare(secret=False)
        try:
            self.refused(self.run_removal(self.argv(secret_home=evil)))
            self.assertFalse(os.path.exists(evil))
        finally:
            shutil.rmtree(evil, ignore_errors=True)

    def test_a_hostile_key_file_path_must_still_be_deleted(self):
        evil = self.key + "​"
        with open(evil, "w") as fh:
            fh.write("PRIVATE KEY EXPORT")
        self.prepare(key=None)
        try:
            self.refused(self.run_removal(self.argv(public_key=evil)))
            self.assertFalse(os.path.exists(evil))
        finally:
            if os.path.exists(evil):
                os.remove(evil)


class Real(RealBase):
    """Real gpg: a secret export handed in as the public key, and a stale verify home."""

    def setUp(self):
        super().setUp()
        with open(self.envfile, "w") as fh:
            fh.write("KEEP=1\n")
        self.env_bytes = b"KEEP=1\n"
        self.before = inspection_homes()

    def secret_export_run(self, runner):
        self.export(secret=True)
        with open(self.key) as fh:
            self.assertIn("PRIVATE KEY", fh.read())
        res = runner(S, self.argv(), env=self.env)
        self.refused(res, "holds a secret key and was not imported")
        self.assertEqual(len(res.errors()), 1)
        self.assertFalse(os.path.exists(self.secret), "the secret home is gone")
        self.assertFalse(os.path.exists(self.verify), "no verify home exists, so nothing was imported anywhere that survives")
        self.assertFalse(os.path.exists(self.key), "the export is deleted")
        with open(self.envfile, "rb") as fh:
            self.assertEqual(fh.read(), self.env_bytes, "the environment file is untouched")
        self.assertEqual(inspection_homes() - self.before, set(), "the inspection home is removed")

    def test_a_secret_export_handed_in_as_the_public_key_is_refused_in_process(self):
        self.secret_export_run(h.run_main)

    def test_a_secret_export_handed_in_as_the_public_key_is_refused_as_a_subprocess(self):
        self.secret_export_run(h.run_proc)

    def test_a_secret_export_leaves_no_secret_key_in_any_directory_of_the_run(self):
        self.export(secret=True)
        h.run_main(S, self.argv(), env=self.env)
        for home in (self.secret, self.verify):
            self.assertEqual(self.secret_keys(home) if os.path.exists(home) else [], [])
        left = [n for n in os.listdir(self.base)]
        self.assertEqual(sorted(left), ["env"], "only the environment file is left in the working directory")

    def test_a_stale_verify_home_holding_a_secret_key_is_refused_and_removed(self):
        os.mkdir(self.verify, 0o700)
        self.gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key", "Stale <s@invalid>", "ed25519", "sign", "1d",
                 home=self.verify)
        self.assertEqual(len(self.secret_keys(self.verify)), 1)
        self.export()
        res = h.run_main(S, self.argv(), env=self.env)
        self.refused(res, "secret key is still")
        self.assertFalse(os.path.exists(self.secret))
        self.assertFalse(os.path.exists(self.verify), "the stale home that held a secret key is deleted")
        with open(self.envfile, "rb") as fh:
            self.assertEqual(fh.read(), self.env_bytes)

    def test_a_key_file_that_is_not_a_key_is_refused_without_a_verify_home(self):
        with open(self.key, "w") as fh:
            fh.write("not a key")
        res = h.run_main(S, self.argv(), env=self.env)
        self.refused(res, "it could not be inspected")
        self.assertFalse(os.path.exists(self.verify))
        self.assertFalse(os.path.exists(self.secret))
        self.assertEqual(inspection_homes() - self.before, set())

    def test_a_missing_gpg_binary_is_one_error_line_with_the_secret_home_deleted(self):
        self.export()
        res = h.run_main(S, self.argv() + ["--gpg", self.path("no-gpg")], env=self.env)
        self.refused(res, "failed unexpectedly")
        self.assertEqual(len(res.errors()), 1)
        self.assertFalse(os.path.exists(self.secret))
        with open(self.envfile, "rb") as fh:
            self.assertEqual(fh.read(), self.env_bytes)

    def test_a_symlinked_secret_home_is_untouched_and_exit_is_one(self):
        real = os.path.join(self.base, "real")
        os.rename(self.secret, real)
        os.symlink(real, self.secret)
        out = self.gpg("--armor", "--export", home=real).stdout
        with open(self.key, "w") as fh:
            fh.write(out)
        res = h.run_main(S, self.argv(), env=self.env)
        self.refused(res, "symbolic link")
        self.assertTrue(os.path.islink(self.secret))
        self.assertEqual(len(self.secret_keys(real)), 1, "the private key behind the link is untouched")
        with open(self.envfile, "rb") as fh:
            self.assertEqual(fh.read(), self.env_bytes)


if __name__ == "__main__":
    unittest.main()
