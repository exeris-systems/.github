"""`staged_manifest.py`: how a directory is named, how a vanished file is reported, how every refusal of `verify` ends, and what `--name` may be.

  * `--dir` is judged by its literal text: a trailing separator or `.` component is dropped and nothing is resolved, so `link/` is the
    link and not the directory it points to;
  * a file that vanishes between the listing and the open is one finding and the final line, never a traceback;
  * every refusal of `verify`, of whatever class, ends with `the staged files are not what the gate staged`;
  * `create --name` is `[A-Za-z][A-Za-z0-9_-]*`; anything else is a usage error that writes nothing;
  * an unexpected exception is one `::error::` line and exit 1.
"""
from __future__ import annotations

import errno
import os
import re
import shutil
import unittest
from unittest import mock

import caps_release_helpers as h
from manifest_support import FINAL, SCRIPT, coordinate_names, make_coordinate, manifest_of, put, sha


class Base(h.Case):
    def directory(self, name="staged", *bases):
        d = self.path(name)
        for base in bases or ("a-1.0.0",):
            make_coordinate(d, base)
        return d

    def verify(self, directory, manifest, **kw):
        return self.both(SCRIPT, ["verify", "--dir", directory, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest), **kw)

    def create(self, directory, output=None):
        output = output or self.path("github-output")
        return self.both(SCRIPT, ["create", "--dir", directory, "--output", output]), output

    def link_to(self, directory):
        link = self.path("link")
        os.symlink(directory, link)
        return link


class Literal(Base):
    def test_trailing_separators_and_dot_components_are_dropped_on_the_text_alone(self):
        literal = h.load(SCRIPT).literal
        table = {"a": "a", "a/": "a", "a//": "a", "a///": "a", "a/.": "a", "a/./": "a", "a/./.": "a", "a/.//": "a", "a//.": "a", "a/b/.": "a/b",
                 "/": "/", "//": "/", "///": "/", "/.": "/", "/./": "/", ".": ".", "./": ".", "./.": ".", "": "", "a/..": "a/..", "a/.b": "a/.b",
                 "a/..b": "a/..b", "a.": "a.", "/a/": "/a", "/a/.": "/a", "a/b/": "a/b"}
        for given, want in table.items():
            self.assertEqual(literal(given), want, repr(given))

    def test_a_link_is_refused_whatever_trailing_text_names_it(self):
        d = self.directory()
        manifest = manifest_of(d)
        link = self.link_to(d)
        for tail in ("", "/", "//", "/.", "/./", "/./.", "/.//"):
            with self.subTest(tail):
                res = self.verify(link + tail, manifest)
                self.assertEqual(res.rc, 1, res)
                self.assertEqual(res.errors(), [f"::error::{link} is not a directory", FINAL])
                self.assertEqual(res.out, "")
                out = self.path(f"out{len(tail)}")
                res, _ = self.create(link + tail, out)
                self.assertEqual(res.rc, 1, res)
                self.assertEqual(res.errors(), [f"::error::{link} is not a directory"])
                self.assertFalse(os.path.exists(out))

    def test_a_real_directory_is_accepted_with_or_without_the_trailing_text(self):
        d = self.directory()
        manifest = manifest_of(d)
        for tail in ("", "/", "//", "/.", "/./", "/./."):
            with self.subTest(tail):
                self.accepted(self.verify(d + tail, manifest))
                res, out = self.create(d + tail, self.path(f"out{len(tail)}"))
                self.accepted(res)

    def test_a_relative_directory_is_judged_in_the_working_directory(self):
        d = self.directory()
        manifest = manifest_of(d)
        before = os.getcwd()
        os.chdir(self.tmp)
        try:
            res = h.run_main(SCRIPT, ["verify", "--dir", "staged/.", "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))
            self.accepted(res)
            os.symlink("staged", "rel-link")
            res = h.run_main(SCRIPT, ["verify", "--dir", "rel-link/.", "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))
            self.assertEqual(res.errors(), ["::error::rel-link is not a directory", FINAL])
        finally:
            os.chdir(before)

    def test_a_directory_name_that_ends_in_a_space_is_judged_as_written(self):
        d = self.directory("staged ")
        self.accepted(self.verify(d, manifest_of(d)))
        res, _ = self.create(d, self.path("o"))
        self.accepted(res)

    def test_dot_dot_is_left_to_the_filesystem_and_never_collapsed_on_the_text(self):
        """`X/link/..` is the parent of the link's target, which a textual normalisation would call X."""
        real = os.path.join(self.tmp, "base", "staged")
        make_coordinate(real, "a-1.0.0")
        outer = os.path.join(self.tmp, "outer")
        os.makedirs(outer)
        os.symlink(real, os.path.join(outer, "link"))
        res = self.verify(os.path.join(outer, "link", ".."), "x")
        self.assertIn("::error::staged is not a regular file; only regular files are released", res.errors())
        self.assertNotIn("::error::link is not a regular file; only regular files are released", res.errors())

    def test_the_directory_in_a_message_is_the_literal_one(self):
        res = self.verify(self.path("absent") + "//.", "x")
        self.assertEqual(res.errors()[0], f"::error::{self.path('absent')} is not a directory")


def self_regular(d):
    """A copy of the regular files of D, for a manifest that does not list the entry under test."""
    scratch = d + "-regular"
    os.makedirs(scratch, exist_ok=True)
    for n in os.listdir(d):
        if os.path.isfile(os.path.join(d, n)):
            shutil.copy(os.path.join(d, n), os.path.join(scratch, n))
    return scratch


class Vanishing(Base):
    def run_verify(self, patch_target, replacement):
        d = self.directory()
        manifest = manifest_of(d)
        module = h.load(SCRIPT)
        with mock.patch.object(module.os, patch_target, replacement):
            return h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest)), d

    def assert_one_finding_and_the_final_line(self, res, name):
        self.assertEqual(res.rc, 1, res)
        self.assertEqual(res.out, "")
        self.assertEqual(len(res.errors()), 2, res)
        self.assertRegex(res.errors()[0], rf"^::error::{re.escape(name)} cannot be read \(")
        self.assertEqual(res.errors()[1], FINAL)
        self.assertEqual(len(res.err.splitlines()), 2, "nothing but the two lines, so no traceback")

    def test_a_file_that_vanishes_before_it_is_looked_at(self):
        real = os.lstat

        def gone(path, *a, **k):
            if str(path).endswith("a-1.0.0.jar"):
                os.remove(path)
                raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(path))
            return real(path, *a, **k)
        res, _ = self.run_verify("lstat", gone)
        self.assert_one_finding_and_the_final_line(res, "a-1.0.0.jar")

    def test_every_entry_is_still_looked_at_after_one_that_cannot_be_read(self):
        """The scan reports every finding it can: the entries after the unreadable one are judged too."""
        real = os.lstat
        d = self.directory()
        os.mkdir(os.path.join(d, "z-dir"))
        manifest = manifest_of(self_regular(d))
        module = h.load(SCRIPT)

        def denied(path, *a, **k):
            if str(path).endswith("a-1.0.0.jar"):
                raise PermissionError(errno.EACCES, "Permission denied", str(path))
            return real(path, *a, **k)
        with mock.patch.object(module.os, "lstat", denied):
            res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))
        self.assertEqual(len(res.errors()), 3, res)
        self.assertRegex(res.errors()[0], r"^::error::a-1\.0\.0\.jar cannot be read \(")
        self.assertEqual(res.errors()[1], "::error::z-dir is not a regular file; only regular files are released")
        self.assertEqual(res.errors()[2], FINAL)

    def test_the_name_of_an_entry_that_cannot_be_read_is_escaped_in_the_finding(self):
        d = self.directory()
        name = "x\x1b[0m\u202e.jar"
        put(d, name)
        real = os.lstat

        def denied(path, *a, **k):
            if str(path).endswith(name):
                raise PermissionError(errno.EACCES, "Permission denied", "p")
            return real(path, *a, **k)
        module = h.load(SCRIPT)
        with mock.patch.object(module.os, "lstat", denied):
            res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST="x"))
        self.assertIn("::error::x\\u001b[0m\\u202e.jar cannot be read ([Errno 13] Permission denied: 'p')", res.errors())
        self.assertEqual(len(res.err.splitlines()), len(res.errors()))

    def test_a_file_that_vanishes_between_the_listing_and_the_open(self):
        real = os.open

        def gone(path, flags, *a, **k):
            if str(path).endswith("a-1.0.0-sources.jar"):
                os.remove(path)
            return real(path, flags, *a, **k)
        res, _ = self.run_verify("open", gone)
        self.assert_one_finding_and_the_final_line(res, "a-1.0.0-sources.jar")

    def test_the_reason_is_flattened_and_escaped_in_the_finding(self):
        real = os.lstat

        def gone(path, *a, **k):
            if str(path).endswith("a-1.0.0.jar"):
                raise OSError(errno.EIO, "bad\nline\x1b[0m\u202e")
            return real(path, *a, **k)
        res, _ = self.run_verify("lstat", gone)
        self.assertEqual(len(res.errors()), 2, res)
        self.assertIn("a-1.0.0.jar cannot be read ([Errno 5] bad line\\u001b[0m\\u202e)", res.errors()[0])
        self.assertEqual(len(res.err.splitlines()), 2)

    def test_create_reports_the_same_vanishing_as_one_finding_without_a_final_line(self):
        d = self.directory()
        real = os.open
        module = h.load(SCRIPT)

        def gone(path, flags, *a, **k):
            if str(path).endswith("a-1.0.0.pom"):
                os.remove(path)
            return real(path, flags, *a, **k)
        out = self.path("out")
        with mock.patch.object(module.os, "open", gone):
            res = h.run_main(SCRIPT, ["create", "--dir", d, "--output", out])
        self.assertEqual(res.rc, 1, res)
        self.assertEqual(len(res.errors()), 1, res)
        self.assertIn("a-1.0.0.pom cannot be read", res.err)
        self.assertFalse(os.path.exists(out))


class Unwritable(Base):
    def test_an_output_that_cannot_be_written_is_one_finding_with_the_reason_flattened_and_escaped(self):
        d = self.directory()
        module = h.load(SCRIPT)

        def refuse(path, *a, **k):
            raise OSError(errno.ENOSPC, "no\nspace\x1b[0m\u202e")
        out = self.path("out")
        with mock.patch.object(module, "open", refuse, create=True):
            res = h.run_main(SCRIPT, ["create", "--dir", d, "--output", out])
        self.assertEqual(res.rc, 1, res)
        self.assertEqual(res.out, "")
        self.assertEqual(res.err, f"::error::{out} cannot be written ([Errno 28] no space\\u001b[0m\\u202e)\n")

    def test_the_output_path_is_escaped_in_the_finding(self):
        d = self.directory()
        out = self.path("no\x1bsuch\u202edir", "out")
        res = h.run_main(SCRIPT, ["create", "--dir", d, "--output", out])
        self.assertEqual(res.rc, 1, res)
        self.assertEqual(len(res.errors()), 1, res)
        self.assertEqual(len(res.err.splitlines()), 1)
        self.assertIn(self.tmp + "/no\\u001bsuch\\u202edir/out cannot be written", res.err)
        self.assertNotIn("\x1b", res.err)
        self.assertNotIn("\u202e", res.err)

    def test_nothing_is_written_when_a_base_is_refused(self):
        d = self.directory("bad", "a,b-1.0.0")
        out = self.write("out", "keep=1\n")
        res = h.run_main(SCRIPT, ["create", "--dir", d, "--output", out])
        self.assertEqual(res.rc, 1, res)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "keep=1\n")


class Handler(Base):
    def test_an_unexpected_exception_is_one_line_naming_the_type_and_a_flattened_message(self):
        d = self.directory()
        module = h.load(SCRIPT)

        def boom(*_a, **_k):
            raise RuntimeError("first\n::error::forged\n\tsecond\x1b[31m\u202e")
        for argv in (["verify", "--dir", d, "--manifest-env", "MANIFEST"], ["create", "--dir", d, "--output", self.path("o")]):
            with mock.patch.object(module, "scan", boom):
                res = h.run_main(SCRIPT, argv, env=h.clean_env(MANIFEST="x"))
            self.assertEqual(res.rc, 1, res)
            self.assertEqual(res.err, "::error::the staged-files check failed unexpectedly (RuntimeError: first ::error::forged second\\u001b[31m\\u202e).\n")
            self.assertEqual(res.out, "")

    def test_a_usage_error_is_not_turned_into_a_failure(self):
        for argv in ([], ["bogus"], ["create", "--dir", "x"], ["verify", "--dir", "x", "--manifest-env", "M", "--nope"]):
            with self.subTest(argv):
                res = self.both(SCRIPT, argv)
                self.assertEqual(res.rc, 2, res)
                self.assertNotIn("failed unexpectedly", res.err)

    def test_the_exit_status_of_an_unexpected_exception_is_one_in_a_program_too(self):
        d = self.directory()
        res = h.run_proc(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        self.accepted(res)


class KeyName(Base):
    BAD = ["", "1a", "-a", "_a", "a b", "a.b", "a=b", "a\nb", "a<<b", "é", "a;b", "a/b", "a\tb", "a\x00b", "a b\n", "a$b", "a,b", "a:b", "\u017f", "a\u017f", "\u212a", "a\u212a", "\uff21", "a\uff11", "a\u0661"]
    GOOD = ["a", "A", "manifest", "caps", "A-b_c9", "a-", "a_", "z" * 80, "aBC", "Manifest", "ABC", "a-B", "aZ9", "Z" * 3]

    def test_a_name_outside_the_pattern_is_a_usage_error_that_writes_nothing(self):
        d = self.directory()
        for name in self.BAD:
            if "\x00" in name:
                continue
            with self.subTest(repr(name)):
                out = self.path(f"out-{abs(hash(name))}")
                res = self.both(SCRIPT, ["create", "--dir", d, "--output", out, f"--name={name}"])
                self.assertEqual(res.rc, 2, res)
                self.assertEqual(res.out, "")
                self.assertIn("must match [A-Za-z][A-Za-z0-9_-]*", res.err)
                self.assertFalse(os.path.exists(out))

    def test_a_name_inside_the_pattern_is_the_key_of_the_three_lines(self):
        d = self.directory()
        for name in self.GOOD:
            with self.subTest(name):
                out = self.path(f"out-{len(name)}-{name[:3]}")
                self.accepted(self.both(SCRIPT, ["create", "--dir", d, "--output", out, "--name", name]))
                with open(out, encoding="utf-8") as fh:
                    keys = re.findall(r"^([^=<\n]+)(?:<<|=)", fh.read(), re.M)
                self.assertEqual(keys, [name, f"{name}-digest", f"{name}-id"])

    def test_the_default_key_is_manifest(self):
        d = self.directory()
        out = self.path("out")
        self.accepted(self.both(SCRIPT, ["create", "--dir", d, "--output", out]))
        with open(out, encoding="utf-8") as fh:
            self.assertTrue(fh.read().startswith("manifest<<MANIFEST_"))

    def test_a_name_that_is_a_usage_error_is_judged_before_the_directory_is_read(self):
        out = self.path("out")
        res = self.both(SCRIPT, ["create", "--dir", self.path("absent"), "--output", out, "--name=1a"])
        self.assertEqual(res.rc, 2, res)
        self.assertNotIn("is not a directory", res.err)


class FinalLine(Base):
    """Every class of refusal of `verify` ends with the same line, and an accepted directory prints none of it."""

    def stage(self, *bases):
        return self.directory("staged", *bases)

    def classes(self):
        """label -> (directory, manifest), one for each way `verify` refuses."""
        out = {}
        good = self.stage()
        manifest = manifest_of(good)

        def variant(label, edit, manifest_for=None):
            d = self.path(f"v-{label}")
            shutil.copytree(good, d)
            edit(d)
            out[label] = (d, manifest if manifest_for is None else manifest_for(d))
        out["absent directory"] = (self.path("absent"), manifest)
        out["file as directory"] = (put(self.tmp, "afile", "x"), manifest)
        out["link as directory"] = (self.link_to(good), manifest)
        out["empty manifest"] = (good, "")
        out["whitespace manifest"] = (good, " \n")
        out["malformed line"] = (good, manifest + "not a line\n")
        out["blank line"] = (good, manifest + "\n")
        out["name listed twice"] = (good, manifest + manifest.splitlines()[0] + "\n")
        out["uppercase hash"] = (good, "A" * 64 + "  extra.jar\n" + manifest)
        out["name that is not plain in the manifest"] = (good, manifest + f"{sha(b'x')}  ../x.jar\n")
        variant("changed byte", lambda d: put(d, "a-1.0.0.jar", b"other"))
        variant("missing file", lambda d: os.remove(os.path.join(d, "a-1.0.0.pom")), None)
        variant("extra file", lambda d: put(d, "extra.txt"))
        variant("extra file listed", lambda d: put(d, "extra.txt"), manifest_of)
        variant("pom.xml", lambda d: put(d, "pom.xml", "<project/>"), manifest_of)
        variant("missing member listed", lambda d: os.remove(os.path.join(d, "a-1.0.0.pom.asc")), manifest_of)
        variant("tests jar", lambda d: put(d, "a-1.0.0-tests.jar"), manifest_of)
        variant("no main jar", lambda d: [os.remove(os.path.join(d, n)) for n in os.listdir(d) if not n.endswith(".asc")], manifest_of)
        variant("bad base", lambda d: make_coordinate(d, "b,c-1.0.0"), manifest_of)
        variant("snapshot base", lambda d: make_coordinate(d, "b-1.0.0-SNAPSHOT"), manifest_of)
        variant("long base", lambda d: make_coordinate(d, "b" * 201 + "-1.0.0"), manifest_of)
        variant("case collision", lambda d: make_coordinate(d, "A-1.0.0"), manifest_of)
        variant("directory entry", lambda d: os.mkdir(os.path.join(d, "sub")))
        variant("symbolic link entry", lambda d: os.symlink("a-1.0.0.jar", os.path.join(d, "ln.jar")))
        variant("hard link entry", lambda d: os.link(os.path.join(d, "a-1.0.0.jar"), os.path.join(d, "hl.jar")), manifest_of)
        variant("fifo entry", lambda d: os.mkfifo(os.path.join(d, "ff.jar")))
        variant("illegal name", lambda d: put(d, "bad\nname.jar"), manifest_of)
        variant("hidden name", lambda d: put(d, ".hidden"), manifest_of)
        return out

    def test_every_refusal_class_ends_with_the_final_line(self):
        cases = self.classes()
        self.assertGreaterEqual(len(cases), 28)
        for label, (d, manifest) in cases.items():
            with self.subTest(label):
                res = self.verify(d, manifest)
                self.assertEqual(res.rc, 1, res)
                self.assertEqual(res.out, "")
                self.assertEqual(res.errors()[-1], FINAL, res)
                self.assertEqual(res.errors().count(FINAL), 1, "once, at the end")
                self.assertEqual(len(res.errors()), len(res.err.splitlines()), "every stderr line is an ::error:: line")

    def test_a_refusal_has_at_least_one_finding_before_the_final_line(self):
        for label, (d, manifest) in self.classes().items():
            with self.subTest(label):
                res = self.verify(d, manifest)
                self.assertGreaterEqual(len(res.errors()), 2, res)
                self.assertNotEqual(res.errors()[0], FINAL)

    def test_an_accepted_directory_prints_neither_a_finding_nor_the_final_line(self):
        d = self.stage("a-1.0.0", "b-2.0.0")
        res = self.verify(d, manifest_of(d))
        self.accepted(res)
        self.assertEqual(res.err, "")
        self.assertNotIn(FINAL, res.out)

    def test_create_does_not_print_the_final_line(self):
        d = self.stage()
        os.mkdir(os.path.join(d, "sub"))
        res, _ = self.create(d)
        self.assertEqual(res.rc, 1, res)
        self.assertNotIn(FINAL, res.err)

    def test_the_final_line_is_the_one_the_documentation_names(self):
        self.assertEqual(FINAL, "::error::the staged files are not what the gate staged")
        self.assertEqual(h.load(SCRIPT).FINAL, "the staged files are not what the gate staged")
        with open(h.script_path(SCRIPT), encoding="utf-8") as fh:
            self.assertIn("`the staged files are not what the gate staged`", fh.read().split('"""')[1])


if __name__ == "__main__":
    unittest.main()
