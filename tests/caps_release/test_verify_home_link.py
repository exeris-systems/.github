"""remove_signing_key: a verify home that is a symbolic link is refused before anything is created, changed,
imported or written, however the link is spelled, and whatever the link names.

Every scenario snapshots the whole temporary root; the only paths allowed to differ afterwards are the ones the
script is meant to delete (the secret home, the exported key, the verify home itself) and the tool-call log.
"""
from __future__ import annotations

import os
import stat

import caps_release_helpers as h
from test_key_removal_finally import Root

S = "remove_signing_key"
SPELLINGS = ("{}", "{}/", "{}//", "{}/.", "{}/./")


def snapshot(root):
    """Mode and content of everything under root, links by their text; the root itself included."""
    out = {}
    for base, dirs, files in os.walk(root):
        for name in dirs + files + [""]:
            p = os.path.join(base, name) if name else base
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                out[p] = ("link", os.readlink(p))
            elif stat.S_ISDIR(st.st_mode):
                out[p] = ("dir", stat.S_IMODE(st.st_mode))
            else:
                with open(p, "rb") as fh:
                    out[p] = ("file", stat.S_IMODE(st.st_mode), fh.read())
    return out


class Linked(Root):
    def setUp(self):
        super().setUp()
        self.target = self.path("link-target")
        os.makedirs(self.target)
        with open(os.path.join(self.target, "sentinel"), "w") as fh:
            fh.write("target content")
        os.chmod(self.target, 0o755)
        self.link = self.path("L")

    def scenario(self, spelling="{}", env_content="KEEP=1\n", secret_link=None, link_to=None, run=True):
        """Build the state, run, and return the result after checking nothing outside the named paths changed."""
        for p in (self.link, self.secret, self.key, self.envfile):
            if os.path.islink(p) or os.path.isfile(p):
                os.remove(p)
        if os.path.isdir(self.secret):
            self.rmtree(self.secret)
        if env_content is not None:
            with open(self.envfile, "w") as fh:
                fh.write(env_content)
        if secret_link is None:
            self.make(self.secret, self.key)
        else:
            self.make(self.secret, self.key, secret_is_dir=False)
            os.symlink(secret_link, self.secret)
        os.symlink(self.target if link_to is None else link_to, self.link)
        self.before = snapshot(self.tmp)
        self.res = self.go(verify=spelling.format(self.link)) if run else None
        return self.res

    def assert_only_removals(self, allowed=()):
        after = snapshot(self.tmp)
        permitted = [self.secret, self.key, self.link, self.log, self.log + ".modes", self.tmpdir, *allowed]
        for p in set(self.before) | set(after):
            if self.before.get(p) != after.get(p):
                self.assertTrue(any(p == a or p.startswith(a + os.sep) for a in permitted), f"{p} changed: {self.before.get(p)} -> {after.get(p)}")

    def assert_nothing_imported(self):
        calls = self.calls()
        self.assertEqual([c for c in calls if "--import" in c["args"]], [])
        self.assertEqual([c for c in calls if c["tool"] == "gpg" and "--list-secret-keys" in c["args"]], [])

    def env_unchanged(self, env_content):
        if env_content is None:
            self.assertFalse(os.path.lexists(self.envfile), "the environment file is not created")
        else:
            with open(self.envfile) as fh:
                self.assertEqual(fh.read(), env_content)

    def assert_target_intact(self):
        self.assertEqual({p: v for p, v in snapshot(self.target).items()}, {p: v for p, v in self.before.items()
                         if p == self.target or p.startswith(self.target + os.sep)})
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o755)


class VerifyHomeLink(Linked):
    def test_a_link_to_an_existing_directory_is_refused_in_every_spelling(self):
        for spelling in SPELLINGS:
            for env_content in (None, "KEEP=1\n"):
                with self.subTest(spelling=spelling, env=env_content):
                    res = self.scenario(spelling, env_content)
                    self.refused(res, "the verify home is a symbolic link")
                    self.assertEqual(len(res.errors()), 1, res)
                    self.assert_target_intact()
                    self.assert_nothing_imported()
                    self.env_unchanged(env_content)
                    self.assertFalse(os.path.lexists(self.secret), "the secret home is removed")
                    self.assertFalse(os.path.lexists(self.key), "the exported key is removed")
                    self.assert_only_removals()
                    self.assert_sentinels()

    def test_the_target_is_never_a_home_of_any_tool_call(self):
        self.scenario("{}/.")
        self.assertEqual([c for c in self.calls() if c["home"] in (self.target, self.link, self.link + "/.")], [])

    def test_a_dangling_link_is_refused_and_its_target_is_not_created(self):
        gone = self.path("not-there")
        for spelling in SPELLINGS:
            with self.subTest(spelling):
                res = self.scenario(spelling, link_to=gone)
                self.refused(res, "the verify home is a symbolic link")
                self.assertEqual(len(res.errors()), 1, res)
                self.assertFalse(os.path.lexists(gone), "nothing is created through a dangling link")
                self.assert_nothing_imported()
                self.env_unchanged("KEEP=1\n")
                self.assert_only_removals()

    def test_a_link_to_a_file_is_refused_and_the_file_is_untouched(self):
        for spelling in ("{}", "{}/", "{}/."):
            with self.subTest(spelling):
                res = self.scenario(spelling, link_to=os.path.join(self.target, "sentinel"))
                self.refused(res, "the verify home is a symbolic link")
                self.assertEqual(len(res.errors()), 1, res)
                self.assert_target_intact()
                self.assert_nothing_imported()
                self.env_unchanged("KEEP=1\n")
                self.assert_only_removals()

    def test_both_homes_being_links_is_two_errors_and_neither_target_is_touched(self):
        other = self.path("secret-target")
        os.makedirs(other)
        with open(os.path.join(other, "private-keys-v1.d"), "w") as fh:
            fh.write("PRIVATE")
        for spelling in SPELLINGS:
            with self.subTest(spelling):
                res = self.scenario(spelling, secret_link=other)
                self.assertEqual(res.rc, 1, res)
                self.assertEqual(len(res.errors()), 2, res)
                self.assertIn("secret home is a symbolic link", res.errors()[0])
                self.assertIn("the verify home is a symbolic link", res.errors()[1])
                self.assert_target_intact()
                self.assertEqual(os.listdir(other), ["private-keys-v1.d"], "the secret home's target is not followed")
                self.assert_nothing_imported()
                self.env_unchanged("KEEP=1\n")
                self.assertFalse(os.path.lexists(self.key))
                self.assert_only_removals(allowed=[other])
                self.assert_sentinels()

    def test_a_link_whose_target_is_the_secret_home_creates_nothing_where_the_secret_home_was(self):
        for spelling in SPELLINGS:
            with self.subTest(spelling):
                res = self.scenario(spelling, link_to=self.secret)
                self.refused(res, "the verify home is a symbolic link")
                self.assertEqual(len(res.errors()), 1, res)
                self.assertFalse(os.path.lexists(self.secret), "the secret home is removed and not recreated through the link")
                self.assertFalse(os.path.lexists(self.key))
                self.assert_nothing_imported()
                self.env_unchanged("KEEP=1\n")
                self.assert_only_removals()
                self.assert_sentinels()

    def test_the_refusal_is_the_same_in_a_calling_workflows_process(self):
        in_process = self.scenario("{}/")
        self.scenario("{}/", run=False)
        proc = h.run_proc(S, [f"--secret-home={self.secret}", f"--verify-home={self.link}/", f"--public-key={self.key}",
                              f"--env-file={self.envfile}", f"--gpg={self.gpg}", f"--gpgconf={self.gpgconf}"],
                          env=h.clean_env(FAKE_LOG=self.log))
        self.assertEqual((proc.rc, proc.errors()), (in_process.rc, in_process.errors()))
        self.assert_target_intact()
        self.assert_only_removals()


class RealVerifyHome(Linked):
    """The refusal does not touch the accepted cases."""

    def test_an_absent_or_empty_real_verify_home_still_succeeds(self):
        for label, prepare in (("absent", lambda: None), ("empty", lambda: os.makedirs(self.verify, mode=0o755))):
            with self.subTest(label):
                if os.path.isdir(self.verify):
                    self.rmtree(self.verify)
                with open(self.envfile, "w") as fh:
                    fh.write("KEEP=1\n")
                self.make(self.secret, self.key)
                prepare()
                before = snapshot(self.tmp)
                res = self.go(verify=self.verify)
                self.accepted(res)
                self.assertEqual(stat.S_IMODE(os.stat(self.verify).st_mode), 0o700)
                with open(self.envfile) as fh:
                    self.assertEqual(fh.read(), f"KEEP=1\nGNUPGHOME={self.verify}\n")
                self.assertFalse(os.path.lexists(self.secret))
                self.assertFalse(os.path.lexists(self.key))
                self.assertEqual({p for p in snapshot(self.target)}, {p for p in before if p == self.target or p.startswith(self.target + os.sep)})
                self.assert_sentinels()


if __name__ == "__main__":
    import unittest
    unittest.main()
