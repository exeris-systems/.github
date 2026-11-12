"""The readiness gate's own seams: every check is made on the private read, descriptors are not leaked, staging is exclusive.

These call the module's functions directly where the whole program cannot reach a branch, and patch one function of the
module where a file has to change at an exact point between two steps.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import tempfile
import unicodedata
import zipfile

import caps_release_helpers as h
from caps_release_helpers import known_defect
from readiness_support import GROUP, Fixture, pom_xml, sig_of, write_zip
from test_staging_binding import Staged, bounded, patched
from zip_support import Entry, build, compress

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

    def test_the_size_limit_is_inclusive(self):
        size = os.path.getsize(self.live("a-1.0.0.jar"))
        private, _ = self.mod.take(self.live("a-1.0.0.jar"), self.tmpdir, size)
        self.assertEqual(os.path.getsize(private), size)
        with self.assertRaisesRegex(OSError, f"larger than {size - 1} bytes"):
            self.mod.take(self.live("a-1.0.0.jar"), self.tmpdir, size - 1)

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

    def test_the_bundle_is_judged_on_the_copy(self):
        self.write_bundle(self.bundle_entries())

        def swap():
            with open(self.bundle_path, "wb") as fh:
                fh.write(b"not a zip")
        self.accepted(self.gate_with_swap("central-bundle.zip", swap, "--expect-bundle", "true"))

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
        self.assertTrue(self.mod.stage(dest, self.target, ["a-1.0.0.jar"], None, errors.append, None) in (True, False))
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
        self.mod.stage(dest, self.target, ["a-1.0.0.jar"], None, errors.append, None)
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

    def test_the_bundle_check_alone_leaves_no_directory_behind(self):
        self.write_bundle(self.bundle_entries())
        built = {"a-1.0.0": (GROUP, "a", "1.0.0")}
        held = {n: (None, hashlib.sha256(self.read_target(n)).hexdigest()) for n in NAMES}
        errors = []
        with self.private_tmp(), contextlib.redirect_stdout(io.StringIO()):
            ok = self.mod.check_bundle(self.target, self.bundle_path, built, errors.append, lambda a, b: True, held)
        self.assertTrue(ok, errors)
        self.assertEqual(os.listdir(self.tmpdir), [], "the scratch directory made for a call with none is removed")


class Oversize(Staged):
    def test_a_bundle_file_over_the_size_bound_is_refused_without_being_read(self):
        os.makedirs(os.path.dirname(self.bundle_path), exist_ok=True)
        with open(self.bundle_path, "wb") as fh:
            fh.truncate(self.mod.MAX_TOTAL_BYTES + 1)
        with bounded(60):
            res = self.run_gate("--expect-bundle", "true")
        self.assertEqual(res.rc, 1, res)
        self.assertIn(f"larger than {self.mod.MAX_TOTAL_BYTES} bytes", res.err)
        self.assertEqual(os.listdir(self.tmpdir), [], "nothing of it was copied")

    def test_the_refusal_of_an_oversize_bundle_is_a_central_bundle_line(self):
        os.makedirs(os.path.dirname(self.bundle_path), exist_ok=True)
        with open(self.bundle_path, "wb") as fh:
            fh.truncate(self.mod.MAX_TOTAL_BYTES + 1)
        res = self.run_gate("--expect-bundle", "true")
        self.assertIn("central bundle:", res.err)
        self.assertNotIn("unexpectedly", res.err)


class UnreadableEntries(Fixture):
    """The layout is sound and the content is not: an entry that cannot be read ends in one line that names why."""

    def setUp(self):
        super().setUp()
        self.real_coordinate()
        self.mod = h.load(S)

    def entries(self, last=False, **overrides):
        """The correct bundle, with OVERRIDES applied to the main jar's entry (or to the last entry)."""
        items = list(self.bundle_entries().items())
        out = []
        for i, (n, d) in enumerate(items):
            e = Entry(n, d, method=8)
            if (last and i == len(items) - 1) or (not last and n.endswith("a-1.0.0.jar")):
                for k, v in overrides.items():
                    setattr(e, k, v)
            out.append(e)
        return out

    def judge(self, entries, layout_off=False):
        data, _ = build(entries)
        os.makedirs(os.path.dirname(self.bundle_path), exist_ok=True)
        with open(self.bundle_path, "wb") as fh:
            fh.write(data)
        argv = ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"]
        if layout_off:
            with patched(self.mod, layout_problem=lambda *a: None):
                return h.run_main(S, argv)
        return h.run_main(S, argv)

    def one_line(self, res, kind):
        self.refused(res, f"central bundle: an entry cannot be read ({kind})")
        self.assertEqual(len([e for e in res.errors() if "central bundle:" in e]), 1)
        self.assertNotIn("unexpectedly", res.err)

    def test_a_bad_crc_is_a_bad_zip_file(self):
        jar = self.read_target("a-1.0.0.jar")
        entries = self.entries(method=0, raw=bytes([jar[0] ^ 0xFF]) + jar[1:])
        self.one_line(self.judge(entries), "BadZipFile")

    def test_a_damaged_deflate_stream_is_a_zlib_error(self):
        self.one_line(self.judge(self.entries(raw=b"\xff\xff\xff\xff\xff\xff")), "error")

    def test_an_entry_that_claims_more_bytes_than_the_file_holds_is_refused_by_zipfile_as_overlapping(self):
        """`EOFError` cannot be reached through an archive on disk: zipfile refuses an overlapping entry first."""
        entries = self.entries(last=True, method=0, local={"csize": 10 ** 5, "usize": 10 ** 5}, central={"csize": 10 ** 5, "usize": 10 ** 5})
        self.one_line(self.judge(entries, layout_off=True), "BadZipFile")

    def test_a_method_nobody_can_read_is_not_implemented_when_the_layout_check_is_out_of_the_way(self):
        entries = self.entries(local={"method": 1}, central={"method": 1})
        self.one_line(self.judge(entries, layout_off=True), "NotImplementedError")

    def test_every_error_a_reader_can_raise_while_an_entry_is_read_is_one_line(self):
        """Each kind of failure the handler names, raised at the point where an entry is read."""
        import zlib
        for exc in (zipfile.BadZipFile("bad"), zlib.error("bad"), EOFError("bad"), RuntimeError("bad"), NotImplementedError("bad")):
            with self.subTest(type(exc).__name__):
                def digest_of(*_a, _exc=exc):
                    raise _exc
                self.write_bundle(self.bundle_entries())
                with patched(self.mod, digest_of=digest_of):
                    res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"])
                self.one_line(res, type(exc).__name__)

    def test_an_error_that_is_not_one_of_those_is_the_generic_failure_line(self):
        def digest_of(*_a):
            raise KeyError("bad")
        self.write_bundle(self.bundle_entries())
        with patched(self.mod, digest_of=digest_of):
            res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"])
        self.refused(res, "failed unexpectedly (KeyError")
        self.assertEqual(len(res.errors()), 1)

    def test_an_encrypted_entry_needs_a_password_when_the_layout_check_is_out_of_the_way(self):
        entries = self.entries(flags=0x1)
        self.one_line(self.judge(entries, layout_off=True), "RuntimeError")


class Folds(Fixture):
    def test_names_that_are_equal_only_after_the_second_normalisation_collide(self):
        """Case folding can leave a string unnormalised: U+0390 and a capital iota with two marks fold to different
        spellings of the same text, which a file system that normalises again would merge."""
        mod = h.load(S)
        first, second = "x\u0390.txt", "x\u0399\u0308\u0301.txt"
        once = lambda n: unicodedata.normalize("NFKC", n).casefold()
        self.assertNotEqual(once(first), once(second), "a single pass tells them apart")
        self.assertEqual(mod.fold(first), mod.fold(second))
        self.real_coordinate()
        entries = self.bundle_entries()
        d = "eu/exeris/caps/a/1.0.0"
        entries[f"{d}/{first}"] = b"1"
        entries[f"{d}/{second}"] = b"2"
        write_zip(self.bundle_path, list(entries.items()))
        res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"])
        self.refused(res, "collide under case folding or Unicode normalisation")


class Reporting(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()

    def run_bundle(self, entries):
        write_zip(self.bundle_path, list(entries.items()))
        return h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"])

    def test_a_signature_of_a_signature_is_not_a_gated_file(self):
        entries = self.bundle_entries()
        d = "eu/exeris/caps/a/1.0.0/a-1.0.0"
        entries[f"{d}.jar.asc.asc"] = b"x"
        self.refused(self.run_bundle(entries), f"{d}.jar.asc.asc is not one of the gated files")

    def test_a_stray_name_is_reported_once_and_only_once(self):
        entries = self.bundle_entries()
        entries["eu/exeris/caps/a/1.0.0/orphan.txt"] = b"x"
        res = self.run_bundle(entries)
        self.refused(res)
        lines = [e for e in res.errors() if "orphan.txt" in e]
        self.assertEqual(len(lines), 1, lines)

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
