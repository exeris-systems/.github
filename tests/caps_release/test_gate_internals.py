"""The readiness gate's own seams: every check is made on the private read, descriptors are not leaked, staging is exclusive.

These call the module's functions directly where the whole program cannot reach a branch, and patch one function of the
module where a file has to change at an exact point between two steps.
"""
from __future__ import annotations

import os
import shutil
import zipfile

import caps_release_helpers as h
from readiness_support import GROUP, Fixture, pom_xml
from test_staging_binding import Staged, patched

S = "check_release_readiness"
NAMES = ["a-1.0.0.jar", "a-1.0.0-sources.jar", "a-1.0.0-javadoc.jar", "a-1.0.0.pom", "a-1.0.0.jar.asc", "a-1.0.0-sources.jar.asc",
         "a-1.0.0-javadoc.jar.asc", "a-1.0.0.pom.asc"]


class Descriptors(Staged):
    def open_descriptors(self):
        return len(os.listdir("/proc/self/fd"))

    def test_a_refused_read_does_not_leak_a_descriptor(self):
        os.mkfifo(self.path("fifo.jar"))
        os.mkdir(self.path("dir.jar"))
        os.symlink(self.live("a-1.0.0.jar"), self.path("link.jar"))
        before = self.open_descriptors()
        for _ in range(40):
            for name in ("fifo.jar", "dir.jar", "link.jar", "absent.jar"):
                with self.assertRaises(OSError):
                    self.mod.take(self.path(name), self.tmpdir)
        self.assertEqual(self.open_descriptors(), before)

    def test_the_private_directory_of_the_gate_is_closed_to_others(self):
        self.use_py_gpg()
        with self.private_tmp():
            res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(PYGPG_LOG=self.log))
        self.accepted(res)
        scratches = {c["scratch_modes"][0] for c in self.gpg_calls()}
        self.assertEqual(scratches, {0o700})


class ChecksOnThePrivateRead(Staged):
    """A file that changes after it was read changes nothing about what was judged."""

    def gate_with_swap(self, name, swap, *extra):
        original = self.mod.take

        def take(src, scratch, limit=None):
            out = original(src, scratch, limit) if limit is not None else original(src, scratch)
            if os.path.basename(src) == name:
                swap()
            return out
        argv = ["--target-dir", self.target, "--gpg", self.gpg, *extra]
        with self.private_tmp(), patched(self.mod, take=take):
            return h.run_main(S, argv)

    def test_the_javadoc_jar_is_judged_on_the_copy(self):
        def swap():
            zipfile.ZipFile(self.live("a-1.0.0-javadoc.jar"), "w").close()
        self.accepted(self.gate_with_swap("a-1.0.0-javadoc.jar", swap))

    def test_the_pom_is_judged_on_the_copy(self):
        def swap():
            with open(self.live("a-1.0.0.pom"), "w") as fh:
                fh.write(pom_xml(GROUP, "evil", "9.9.9"))
        self.accepted(self.gate_with_swap("a-1.0.0.pom", swap))

    def test_a_signature_is_checked_with_the_copies_of_both_files(self):
        self.use_py_gpg()
        seen = []
        original = self.mod.take

        def take(src, scratch, limit=None):
            out = original(src, scratch) if limit is None else original(src, scratch, limit)
            seen.append(out[0])
            return out
        with self.private_tmp(), patched(self.mod, take=take):
            h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(PYGPG_LOG=self.log))
        handed = {p for c in self.gpg_calls() for p in c["argv"][1:]}
        self.assertEqual(handed, set(seen))


class Staging(Staged):
    def plant_links_after_the_first_copy(self, victim):
        original = self.mod.copy_gated
        state = {"planted": False}

        def copy_gated(src, dst, gated):
            if not state["planted"]:
                state["planted"] = True
                for name in NAMES:
                    link = os.path.join(os.path.dirname(dst), name)
                    if link != dst and not os.path.lexists(link):
                        os.symlink(victim, link)
            return original(src, dst, gated)
        return copy_gated

    def test_a_link_planted_in_the_stage_is_never_written_through(self):
        victim = self.path("victim.bin")
        with open(victim, "wb") as fh:
            fh.write(b"keep")
        res = self.run_gate(copy_gated=self.plant_links_after_the_first_copy(victim))
        self.assertEqual(res.rc, 1, res)
        with open(victim, "rb") as fh:
            self.assertEqual(fh.read(), b"keep")
        self.assertFalse(os.path.lexists(self.stage))
        self.assertIn("File exists", "\n".join(res.errors()))

    def test_staging_without_a_record_copies_the_live_file_without_following_a_link_or_writing_over_one(self):
        dest = self.path("direct")
        errors = []
        victim = self.path("victim.bin")
        with open(victim, "wb") as fh:
            fh.write(b"keep")
        os.makedirs(dest)
        self.assertTrue(self.mod.stage(dest, self.target, ["a-1.0.0.jar"], errors.append, None) in (True, False))
        self.assertEqual(errors, [])
        with open(os.path.join(dest, "a-1.0.0.jar"), "rb") as fh:
            self.assertEqual(fh.read(), self.read_target("a-1.0.0.jar"))
        shutil.rmtree(dest)
        os.makedirs(dest)
        os.symlink(victim, os.path.join(dest, "a-1.0.0.jar"))
        with self.assertRaises(FileExistsError):
            self.mod.copy_gated(self.live("a-1.0.0.jar"), os.path.join(dest, "a-1.0.0.jar"), None)
        with open(victim, "rb") as fh:
            self.assertEqual(fh.read(), b"keep")
        os.remove(self.live("a-1.0.0.jar"))
        os.symlink(victim, self.live("a-1.0.0.jar"))
        errors.clear()
        shutil.rmtree(dest)
        self.mod.stage(dest, self.target, ["a-1.0.0.jar"], errors.append, None)
        self.assertEqual(len(errors), 1)
        self.assertIn("cannot be staged", errors[0])

    def test_a_copy_that_does_not_match_its_digest_is_not_left_behind(self):
        private, digest = self.mod.take(self.live("a-1.0.0.jar"), self.tmpdir)
        dst = self.path("out.jar")
        with self.assertRaisesRegex(OSError, "not the file that was verified"):
            self.mod.copy_gated(self.live("a-1.0.0.jar"), dst, (private, "0" * 64))
        self.assertFalse(os.path.lexists(dst))
        with open(private, "r+b") as fh:
            fh.write(b"\xff")                                   # the live file is as it was; the private copy is not
        with self.assertRaisesRegex(OSError, "the verified copy changed"):
            self.mod.copy_gated(self.live("a-1.0.0.jar"), dst, (private, digest))
        self.assertFalse(os.path.lexists(dst), "the copy that failed its digest is unlinked")

class Reporting(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()

    def test_a_pom_that_cannot_be_read_is_one_finding_and_not_also_a_missing_coordinate(self):
        for text in ("<project", "not xml", "", "<a></b>"):
            with self.subTest(text):
                shutil_target = self.target
                for n in os.listdir(shutil_target):
                    os.remove(os.path.join(shutil_target, n))
                self.coordinate("a-1.0.0", pom_text=text)
                res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg])
                self.refused(res, "a-1.0.0.pom cannot be read as a POM")
                self.assertEqual(len(res.errors()), 2, res.errors())
                self.assertNotIn("does not yield", res.err)
                self.assertNotIn("unexpectedly", res.err)


if __name__ == "__main__":
    import unittest
    unittest.main()
