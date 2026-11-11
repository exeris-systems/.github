"""remove_signing_key: whatever the paths hold and however the run ends, the secret home and the exported key are
removed by literal path operations, a link is never followed, and nothing outside the given paths is deleted.

Every scenario runs inside a temporary root that holds sentinels beside, above and below the paths it names; the
sentinels must all be present afterwards.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import types
import unittest

import caps_release_helpers as h
from caps_release_helpers import known_defect
from test_remove_signing_key import Doubles
from test_staging_binding import bounded, patched

S = "remove_signing_key"


class Root(Doubles):
    """Doubles, plus a victim directory and sentinel files that must survive every scenario."""

    def setUp(self):
        super().setUp()
        self.work = self.path("work")
        os.makedirs(self.work)
        self.victim = self.path("victim")
        os.makedirs(os.path.join(self.victim, "deep"))
        self.sentinels = [self.path("above.txt"), os.path.join(self.victim, "sentinel"), os.path.join(self.victim, "deep", "sentinel"),
                          os.path.join(self.work, "bystander"), self.path("pub.asc.bak"), self.path("secret-sibling", "sentinel")]
        for s in self.sentinels:
            os.makedirs(os.path.dirname(s), exist_ok=True)
            with open(s, "w") as fh:
                fh.write("keep")
        self.tmpdir = self.path("tmp")
        os.mkdir(self.tmpdir)

    def assert_sentinels(self):
        for s in self.sentinels:
            self.assertTrue(os.path.isfile(s), f"{s} must survive")

    def make(self, secret, key=None, verify=None, secret_is_dir=True):
        if secret_is_dir:
            os.makedirs(secret, exist_ok=True)
            with open(os.path.join(secret, "private-keys-v1.d"), "w") as fh:
                fh.write("PRIVATE")
        if key is not None:
            with open(key, "w") as fh:
                fh.write("PUBLIC KEY\n")

    def go(self, secret=None, key=None, verify=None, extra=(), env=(), cwd=None, **patches):
        secret = secret if secret is not None else self.secret
        key = key if key is not None else self.key
        verify = verify if verify is not None else self.verify
        argv = [f"--secret-home={secret}", f"--verify-home={verify}", f"--public-key={key}", f"--env-file={self.envfile}",
                f"--gpg={self.gpg}", f"--gpgconf={self.gpgconf}", *extra]
        saved = tempfile.tempdir
        tempfile.tempdir = self.tmpdir
        try:
            with patched(h.load(S), **patches), (contextlib.chdir(cwd) if cwd else contextlib.nullcontext()):
                return h.run_main(S, argv, env=h.clean_env(FAKE_LOG=self.log, **dict(env)))
        finally:
            tempfile.tempdir = saved


class PathCharacters(Root):
    def setUp(self):
        super().setUp()
        with open(self.envfile, "w") as fh:
            fh.write("KEEP=1\n")

    def test_the_paths_are_removed_whatever_characters_they_hold(self):
        names = {"newline": "sec\nret", "zero width": "sec​ret", "right-to-left override": "sec‮ret",
                 "carriage return": "sec\rret", "nul-free unusual": "sec\x1bret", "unassigned": "sec͸ret",
                 "line separator": "sec ret", "space": "sec ret", "trailing space": "secret ", "glob": "sec*[a-z]?",
                 "shell": "$(touch pwned);`x`", "quote": "se'cr\"et", "accent": "sécret", "tilde": "~secret",
                 "dollar home": "$HOME", "percent": "%s%n", "backslash": "sec\\ret", "leading dot": ".secret", "double dot name": "..secret"}
        for label, name in names.items():
            with self.subTest(label):
                with open(self.envfile, "w") as fh:
                    fh.write("KEEP=1\n")
                secret = os.path.join(self.work, name)
                key = os.path.join(self.work, "key-" + name)
                verify = os.path.join(self.work, "verify-" + name)
                sibling = os.path.join(self.work, "sec-A-ret")           # a name a glob in the path would also match
                os.makedirs(sibling, exist_ok=True)
                open(os.path.join(sibling, "f"), "w").close()
                self.make(secret, key)
                res = self.go(secret, key, verify)
                self.assertFalse(os.path.lexists(secret), "the secret home is gone whatever its name")
                self.assertFalse(os.path.lexists(key), "the exported key is gone whatever its name")
                self.assertFalse(os.path.lexists(os.path.join(os.getcwd(), "pwned")))
                self.assertTrue(os.path.isfile(os.path.join(sibling, "f")), "a pattern in a path is never expanded")
                self.assert_sentinels()
                if any(ord(c) < 0x20 or c in "​‮ ͸" for c in name):
                    self.refused(res, "holds a control or unassigned character")
                    self.assertFalse(os.path.lexists(verify), "a refused run leaves no verify home")
                else:
                    self.accepted(res)
                with open(self.envfile) as fh:
                    text = fh.read()
                self.assertEqual(text.count("\n"), 1 if res.rc else 2, "no second NAME=value line can be appended")

    def test_a_path_that_starts_with_a_dash_is_a_path_and_not_an_option(self):
        with contextlib.chdir(self.work):
            self.make("-secret", "-key")
            res = self.go("-secret", "-key", "-verify", cwd=self.work)
            self.accepted(res)
            self.assertFalse(os.path.lexists(os.path.join(self.work, "-secret")))
            self.assertFalse(os.path.lexists(os.path.join(self.work, "-key")))
            self.assertTrue(os.path.isdir(os.path.join(self.work, "-verify")))
        self.assert_sentinels()

    def test_dot_and_dot_dot_components_resolve_as_the_system_resolves_them_and_delete_only_that(self):
        decoy = os.path.join(self.work, "decoy")
        os.makedirs(decoy)
        open(os.path.join(decoy, "f"), "w").close()
        real = os.path.join(self.work, "secret")
        for label, form in (("dot component", "{s}/./"), ("dot dot", "{w}/decoy/../secret"), ("dot", "{w}/./secret"),
                            ("trailing slash", "{s}/"), ("doubled slash", "{w}//secret")):
            with self.subTest(label):
                self.make(real, self.key)
                self.go(form.format(s=real, w=self.work), self.key, self.verify)
                self.assertFalse(os.path.lexists(os.path.join(real, "private-keys-v1.d")), "the key material is gone")
                if os.path.isdir(real):               # `secret/./` cannot be rmdir'd: the emptied directory is left and the run fails
                    self.assertEqual(os.listdir(real), [])
                    os.rmdir(real)
                self.assertTrue(os.path.isfile(os.path.join(decoy, "f")), "a sibling named on the way is not touched")
                shutil.rmtree(self.verify, ignore_errors=True)
        self.assert_sentinels()

    def test_a_key_path_that_is_not_a_regular_file_is_never_followed_and_never_blocks(self):
        os.makedirs(self.work, exist_ok=True)
        os.mkfifo(self.key)
        self.make(self.secret)
        with bounded(30):
            res = self.go()
        self.accepted(res)
        self.assertFalse(os.path.lexists(self.key), "the fifo is unlinked")
        self.assert_sentinels()

    def test_a_key_path_that_is_a_directory_is_left_alone_and_the_failure_is_one_line(self):
        os.makedirs(os.path.join(self.key, "inner"))
        with open(os.path.join(self.key, "inner", "f"), "w") as fh:
            fh.write("keep")
        self.make(self.secret)
        res = self.go()
        self.refused(res, "failed unexpectedly")
        self.assertEqual(len(res.errors()), 1, res)
        self.assertTrue(os.path.isfile(os.path.join(self.key, "inner", "f")), "a directory is not deleted as a key file")
        self.assertFalse(os.path.lexists(self.secret), "the secret home is removed all the same")
        self.assertFalse(os.path.lexists(self.verify))
        self.assert_sentinels()

    def test_a_key_path_that_is_a_symbolic_link_is_removed_as_a_link_and_the_target_survives(self):
        target = self.sentinels[1]
        os.symlink(target, self.key)
        self.make(self.secret)
        res = self.go()
        self.accepted(res)
        self.assertFalse(os.path.lexists(self.key))
        self.assert_sentinels()
        os.symlink(self.victim, self.key)
        self.go()
        self.assertFalse(os.path.lexists(self.key))
        self.assert_sentinels()


class Links(Root):
    def test_a_secret_home_that_is_a_symbolic_link_is_reported_and_its_target_untouched(self):
        link = os.path.join(self.work, "secret-link")
        os.symlink(self.victim, link)
        self.make(self.secret, self.key) if False else self.make(self.path("unused"), self.key, secret_is_dir=False)
        res = self.go(link)
        self.refused(res, "the secret home is a symbolic link")
        self.assertEqual(sorted(os.listdir(self.victim)), ["deep", "sentinel"])
        self.assert_sentinels()
        self.assertFalse(os.path.lexists(self.key), "the exported key is removed even then")
        self.assertFalse(os.path.lexists(self.verify))
        self.assertEqual([c for c in self.calls() if c["tool"] == "gpgconf"], [], "no agent is stopped through the link")

    @known_defect("trailing-slash-follows-link", "a secret home or verify home given as a symbolic link plus a trailing slash (or "
                  "`/.`) is followed: os.path.islink and os.lstat resolve `link/`, so shutil.rmtree empties the link's target; "
                  "remove_signing_key.py:129 and :138 (removal), :72 and :74 (remove_literally), :62 and :65 (remove_tree)")
    def test_a_symbolic_link_written_with_a_trailing_slash_is_not_followed(self):
        for suffix in ("/", "/."):
            with self.subTest(f"secret home {suffix!r}"):
                link = os.path.join(self.work, "secret-link")
                if os.path.lexists(link):
                    os.remove(link)
                os.symlink(self.victim, link)
                self.make(self.path("unused"), self.key, secret_is_dir=False)
                self.go(link + suffix)
                self.assert_sentinels()
        for suffix in ("/", "/."):
            with self.subTest(f"verify home {suffix!r}"):
                link = os.path.join(self.work, "verify-link")
                if os.path.lexists(link):
                    os.remove(link)
                os.symlink(self.victim, link)
                self.make(self.secret, self.key)
                self.go(verify=link + suffix, env={"FAKE_IMPORT_RC": "2"})
                self.assert_sentinels()

    def test_a_verify_home_that_is_a_symbolic_link_is_removed_as_a_link_on_failure(self):
        link = os.path.join(self.work, "verify-link")
        os.symlink(self.victim, link)
        self.make(self.secret, self.key)
        res = self.go(verify=link, env={"FAKE_IMPORT_RC": "2"})
        self.assertEqual(res.rc, 1)
        self.assertFalse(os.path.lexists(link), "the link itself is removed")
        self.assert_sentinels()

    def test_a_secret_home_replaced_by_a_link_during_the_removal_is_not_followed(self):
        def boom(*_a, **_k):
            raise RuntimeError("boom")
        for label, patches in (("inside removal()", {}), ("inside the finally", {"removal": boom})):
            with self.subTest(label):
                self.make(self.secret, self.key)
                count = []
                real = shutil.rmtree

                def rmtree(path, *a, **k):
                    if path == self.secret:
                        count.append(path)
                        if len(count) == 1:
                            os.rename(path, path + ".moved")
                            os.symlink(self.victim, path)
                    return real(path, *a, **k)
                res = self.go(shutil=types.SimpleNamespace(rmtree=rmtree), **patches)
                self.assertEqual(len(count), 1 if patches else 1, "the swap happened at the first removal")
                self.assertEqual(res.rc, 1)
                self.assert_sentinels()
                self.assertEqual(sorted(os.listdir(self.victim)), ["deep", "sentinel"], "nothing in the link's target was removed")
                os.remove(self.secret)
                shutil.rmtree(self.secret + ".moved", ignore_errors=True)

    def test_a_link_inside_the_secret_home_is_removed_as_a_link(self):
        self.make(self.secret, self.key)
        os.symlink(self.victim, os.path.join(self.secret, "inner-link"))
        os.symlink(self.sentinels[0], os.path.join(self.secret, "file-link"))
        res = self.go()
        self.accepted(res)
        self.assertFalse(os.path.lexists(self.secret))
        self.assert_sentinels()


class Endings(Root):
    def setUp(self):
        super().setUp()
        with open(self.envfile, "w") as fh:
            fh.write("KEEP=1\n")

    def test_an_interrupt_still_removes_the_secret_home_the_key_and_the_verify_home(self):
        self.make(self.secret, self.key)
        os.makedirs(self.verify)
        open(os.path.join(self.verify, "pubring.kbx"), "w").close()

        def interrupt(*_a, **_k):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.go(removal=interrupt)
        self.assertFalse(os.path.lexists(self.secret))
        self.assertFalse(os.path.lexists(self.key))
        self.assertFalse(os.path.lexists(self.verify), "an interrupted run leaves no half-built verify home")
        self.assert_sentinels()
        with open(self.envfile) as fh:
            self.assertEqual(fh.read(), "KEEP=1\n")

    def test_an_interrupt_in_the_middle_of_a_gpg_call_is_the_same(self):
        self.make(self.secret, self.key)
        real = __import__("subprocess").run

        def run(cmd, *a, **k):
            if "--import" in cmd:
                raise KeyboardInterrupt()
            return real(cmd, *a, **k)
        mod = h.load(S)
        with patched(mod.subprocess, run=run):
            with self.assertRaises(KeyboardInterrupt):
                self.go()
        self.assertFalse(os.path.lexists(self.secret))
        self.assertFalse(os.path.lexists(self.key))
        self.assertFalse(os.path.lexists(self.verify))
        self.assertEqual(os.listdir(self.tmpdir), [])

    def test_a_removal_that_raises_is_one_line_and_everything_is_still_removed(self):
        self.make(self.secret, self.key)
        os.makedirs(self.verify)

        def boom(*_a, **_k):
            raise RuntimeError("boom\n::error::forged")
        res = self.go(removal=boom)
        self.refused(res, "the key removal failed unexpectedly (RuntimeError")
        self.assertEqual(len(res.err.splitlines()), 1)
        self.assertFalse(os.path.lexists(self.secret))
        self.assertFalse(os.path.lexists(self.key))
        self.assertFalse(os.path.lexists(self.verify))
        self.assert_sentinels()

    def test_a_finally_that_cannot_delete_does_not_hide_the_outcome(self):
        self.make(self.secret, self.key)

        def refuse(*_a, **_k):
            raise PermissionError("denied")
        proxy = types.SimpleNamespace(rmtree=refuse)
        res = self.go(shutil=proxy)
        self.assertIn(res.rc, (0, 1))
        self.assertNotIn("Traceback", res.err)

    def test_nothing_outside_the_given_paths_is_deleted_in_any_scenario(self):
        scenarios = {
            "success": {}, "import fails": {"env": {"FAKE_IMPORT_RC": "2"}},
            "a secret listed": {"env": {"FAKE_LIST_OUT": "sec:u:255:22:ABCDEF:1:::::\n"}},
            "a bad character": {"verify": os.path.join(self.work, "ver\nify")},
        }
        for label, kw in scenarios.items():
            with self.subTest(label):
                self.make(self.secret, self.key)
                self.go(**kw)
                self.assert_sentinels()
                self.assertFalse(os.path.lexists(self.secret))
                self.assertFalse(os.path.lexists(self.key))
                shutil.rmtree(self.verify, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
