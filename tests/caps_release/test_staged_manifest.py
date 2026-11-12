"""`staged_manifest.py`: the binding between the files the gate staged and the files a later job received.

`create` writes the manifest of a directory; `verify` compares a directory with a manifest taken from the
environment. The manifest is the only trust that crosses from the job that gated the files to the jobs that
upload and attest them, so `verify` is tested on every way a downloaded directory can differ from it: content,
names, the kind of entry, and the text of the manifest itself.

Every case runs in this process and as a child process (`Case.both`), which must agree.
"""
from __future__ import annotations

import errno
import os
import shutil
import socket
import subprocess
import sys
import unicodedata
import unittest
from unittest import mock

import caps_release_helpers as h
from manifest_support import (FINAL, SCRIPT, Timeout, bounded, coordinate_names, make_coordinate, manifest_of,
                              parse_github_output, put, random_sets, sha)

# Names that look like keys, commands, delimiters or expansions. As the stem of a file that is not a main jar they are legal and `create`
# lists them; as the base of a main jar the rule for a releasable base refuses them (see `test_base_rule`).
ODD_STEMS = ["a=b", "a<<b", "::set-output name=x::y", "::error::boom", "a%0Ab", "a%0Db", "MANIFEST_0123456789abcdef",
             "a b", "x'y", 'x"y', "$(id)", "`id`", "a;b", "a|b", "-rf", "é", "a,b"]
LEGAL_ODD_NAMES = [stem + ".pom" for stem in ODD_STEMS] + ["MANIFEST_0123456789abcdef"]
REFUSED_ODD_JARS = [stem + ".jar" for stem in ODD_STEMS]
ILLEGAL_NAMES = [".hidden.jar", ".mvn", "a\nb.jar", "a\rb.jar", "a\tb.jar", "a\x1b[31mb.jar", "a\x7fb.jar", " lead.jar", "trail.jar ",
                 "a\\b.jar", "a‮b.jar", "a​b.jar", "a b.jar", "a b.jar", "a͸b.jar", "a﻿b.jar", "a b.jar",
                 "a\x85b.jar", "x\n::error::forged\n.jar", "a\nMANIFEST_x\n.jar"]


class Base(h.Case):
    def directory(self, name="staged", *bases):
        d = self.path(name)
        for base in bases or ("a-1.0.0",):
            make_coordinate(d, base)
        return d

    def verify(self, directory, manifest, var="MANIFEST", set_var=True, **kw):
        env = h.clean_env()
        if set_var:
            env[var] = manifest
        return self.both(SCRIPT, ["verify", "--dir", directory, "--manifest-env", var], env=env, **kw)

    def create(self, directory, output=None, *extra):
        output = output or self.path("github-output")
        return self.both(SCRIPT, ["create", "--dir", directory, "--output", output, *extra]), output

    def output(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def refused_findings(self, res, *fragments, findings=None, final=True):
        """Exit 1, `::error::` lines on stderr, nothing on stdout, and (when asked) one line per finding plus the final one."""
        self.assertEqual(res.rc, 1, res)
        self.assertEqual(res.out, "", res)
        errs = res.errors()
        self.assertTrue(errs, res)
        self.assertEqual(len(res.err.splitlines()), len(errs), "every stderr line is an ::error:: line, so a name cannot forge one")
        if final:
            self.assertEqual(errs[-1], FINAL, res)
        body = errs[:-1] if final else errs
        for fragment in fragments:
            self.assertTrue(any(fragment in e for e in body), f"{fragment!r} not reported: {errs}")
        if findings is not None:
            self.assertEqual(len(body), findings, errs)


class Accepts(Base):
    def test_one_whole_coordinate_matches_its_manifest(self):
        d = self.directory()
        res = self.verify(d, manifest_of(d))
        self.accepted(res)
        self.assertEqual(res.out, "ok - 8 files match the manifest\n")
        self.assertEqual(res.err, "")

    def test_several_whole_coordinates_match(self):
        d = self.directory("staged", "a-1.0.0", "b-2.1.0", "c-d-0.0.1")
        res = self.verify(d, manifest_of(d))
        self.accepted(res)
        self.assertEqual(res.out, "ok - 24 files match the manifest\n")

    def test_the_manifest_may_lack_its_last_newline_as_a_job_output_may(self):
        d = self.directory()
        self.accepted(self.verify(d, manifest_of(d).rstrip("\n")))

    def test_the_order_of_the_lines_does_not_matter(self):
        d = self.directory()
        self.accepted(self.verify(d, "".join(reversed(manifest_of(d).splitlines(keepends=True)))))

    def test_files_of_any_content_including_empty_and_larger_than_a_read_chunk(self):
        d = self.directory()
        put(d, "a-1.0.0.jar", b"")
        put(d, "a-1.0.0-sources.jar", os.urandom((1 << 20) * 2 + 5))
        self.accepted(self.verify(d, manifest_of(d)))

    def test_the_manifest_is_read_from_the_variable_that_is_named(self):
        d = self.directory()
        self.accepted(self.verify(d, manifest_of(d), var="OTHER_NAME"))


class Contents(Base):
    def test_one_changed_byte_is_one_finding(self):
        d = self.directory()
        manifest = manifest_of(d)
        with open(os.path.join(d, "a-1.0.0.jar"), "r+b") as fh:
            fh.seek(3)
            fh.write(b"X")
        res = self.verify(d, manifest)
        self.refused_findings(res, "a-1.0.0.jar differs from the manifest", findings=1)

    def test_a_swapped_pair_of_files_is_a_refusal_for_each_of_them(self):
        d = self.directory()
        manifest = manifest_of(d)
        a, b = os.path.join(d, "a-1.0.0.jar"), os.path.join(d, "a-1.0.0.pom")
        os.rename(a, a + ".t")
        os.rename(b, a)
        os.rename(a + ".t", b)
        res = self.verify(d, manifest)
        self.refused_findings(res, "a-1.0.0.jar differs", "a-1.0.0.pom differs", findings=2)

    def test_an_extra_file_is_refused_by_name_even_when_the_manifest_lists_it(self):
        d = self.directory()
        manifest = manifest_of(d)
        put(d, "extra.txt")
        self.refused_findings(self.verify(d, manifest), "extra.txt is not in the manifest", "extra.txt is not part of a release")
        self.refused_findings(self.verify(d, manifest_of(d)), "extra.txt is not part of a release", findings=1)

    def test_a_missing_file_is_refused_whether_or_not_the_manifest_still_lists_it(self):
        d = self.directory()
        manifest = manifest_of(d)
        os.remove(os.path.join(d, "a-1.0.0-javadoc.jar"))
        self.refused_findings(self.verify(d, manifest), "a-1.0.0-javadoc.jar is in the manifest and not in the directory",
                              "a-1.0.0-javadoc.jar is missing")
        self.refused_findings(self.verify(d, manifest_of(d)), "a-1.0.0-javadoc.jar is missing", findings=1)

    def test_a_manifest_that_lists_more_files_than_are_present_is_refused_naming_each(self):
        d = self.directory()
        extra = "".join(f"{sha(b'x')}  more-{i}.jar\n" for i in range(3))
        res = self.verify(d, manifest_of(d) + extra)
        self.refused_findings(res, *(f"more-{i}.jar is in the manifest and not in the directory" for i in range(3)))

    def test_a_whole_coordinate_the_manifest_does_not_list_is_refused_file_by_file(self):
        d = self.directory("staged", "a-1.0.0")
        manifest = manifest_of(d)
        make_coordinate(d, "b-2.0.0")
        res = self.verify(d, manifest)
        self.refused_findings(res, *(f"{n} is not in the manifest" for n in coordinate_names("b-2.0.0")), findings=8)

    def test_a_hash_that_differs_in_one_digit_anywhere_is_a_different_hash(self):
        d = self.directory()
        lines = manifest_of(d).splitlines()
        for position in (0, 1, 31, 32, 33, 62, 63):
            with self.subTest(position):
                digest, name = lines[0].split("  ", 1)
                flipped = digest[:position] + ("0" if digest[position] != "0" else "1") + digest[position + 1:]
                res = self.verify(d, "\n".join([f"{flipped}  {name}", *lines[1:]]) + "\n")
                self.refused_findings(res, f"{name} differs from the manifest", findings=1)

    def test_a_zero_length_file_is_not_the_file_the_manifest_lists(self):
        d = self.directory()
        manifest = manifest_of(d)
        put(d, "a-1.0.0.pom", b"")
        self.refused_findings(self.verify(d, manifest), "a-1.0.0.pom differs", findings=1)

    def test_a_file_that_is_replaced_by_another_of_the_same_length_is_refused(self):
        d = self.directory()
        manifest = manifest_of(d)
        path = os.path.join(d, "a-1.0.0.jar")
        size = os.path.getsize(path)
        put(d, "a-1.0.0.jar", b"z" * size)
        self.refused_findings(self.verify(d, manifest), "a-1.0.0.jar differs", findings=1)


def sym_to_listed(d):
    shutil.copy(os.path.join(d, "a-1.0.0.jar"), os.path.join(d, "copy"))
    os.remove(os.path.join(d, "a-1.0.0.jar"))
    os.symlink("copy", os.path.join(d, "a-1.0.0.jar"))


def sym_outside(d):
    target = os.path.join(os.path.dirname(d), "outside.jar")
    shutil.copy(os.path.join(d, "a-1.0.0.jar"), target)
    os.remove(os.path.join(d, "a-1.0.0.jar"))
    os.symlink(target, os.path.join(d, "a-1.0.0.jar"))


def sym_same_bytes_as_other_listed(d):
    os.remove(os.path.join(d, "a-1.0.0-sources.jar"))
    shutil.copy(os.path.join(d, "a-1.0.0.jar"), os.path.join(d, "a-1.0.0-sources.jar.real"))
    os.symlink("a-1.0.0.jar", os.path.join(d, "a-1.0.0-sources.jar"))


def dangling(d):
    os.symlink("nowhere", os.path.join(d, "dangling.jar"))


def fifo(d):
    os.mkfifo(os.path.join(d, "a-1.0.0-extra.jar"))


def sock(d):
    s = socket.socket(socket.AF_UNIX)
    s.bind(os.path.join(d, "s.sock"))
    s.close()


def subdir(d):
    os.mkdir(os.path.join(d, "sub"))


def subdir_with_file(d):
    os.mkdir(os.path.join(d, "sub"))
    put(os.path.join(d, "sub"), "x.jar")


def mvn_dir(d):
    os.mkdir(os.path.join(d, ".mvn"))
    put(os.path.join(d, ".mvn"), "extensions.xml", "<extensions/>")


def mvn_file(d):
    put(d, ".mvn", "x")


def hardlink(d):
    os.link(os.path.join(d, "a-1.0.0.jar"), os.path.join(d, "a-1.0.0-link.jar"))


def hardlink_to_outside(d):
    outside = os.path.join(os.path.dirname(d), "outside")
    put(os.path.dirname(d), "outside", b"x")
    os.link(outside, os.path.join(d, "a-1.0.0-x.jar"))


NOT_REGULAR = {"symlink to a listed file": sym_to_listed, "symlink to a file outside": sym_outside,
               "symlink whose bytes equal another listed file": sym_same_bytes_as_other_listed, "dangling symlink": dangling,
               "FIFO": fifo, "socket": sock, "directory": subdir, "directory with a file": subdir_with_file,
               ".mvn directory": mvn_dir, ".mvn file": mvn_file, "hard link": hardlink, "hard link to a file outside": hardlink_to_outside}


class Entries(Base):
    """What the directory holds besides the eight regular files of a coordinate."""

    def good_manifest(self, d, skip=()):
        """The manifest of the regular, unlinked files only, so that the entry under test is the only difference."""
        lines = []
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            if n in skip or os.path.islink(p) or not os.path.isfile(p) or os.lstat(p).st_nlink != 1:
                continue
            with open(p, "rb") as fh:
                lines.append(f"{sha(fh.read())}  {n}\n")
        return "".join(lines)

    def test_every_kind_of_entry_that_is_not_a_plain_file_is_refused(self):
        for label, make in NOT_REGULAR.items():
            with self.subTest(label):
                d = self.directory(f"d-{abs(hash(label))}")
                make(d)
                with bounded(30):
                    res = self.verify(d, self.good_manifest(d))
                self.refused_findings(res)
                self.assertNotIn("ok", res.out)

    def test_a_symlink_to_a_listed_file_with_identical_bytes_is_not_a_file_of_the_release(self):
        d = self.directory()
        manifest = manifest_of(d)
        sym_to_listed(d)
        res = self.verify(d, manifest)
        self.refused_findings(res, "a-1.0.0.jar is not a regular file")

    def test_a_fifo_is_refused_without_being_opened_for_reading(self):
        d = self.directory()
        manifest = manifest_of(d)
        fifo(d)
        with bounded(15):
            res = self.verify(d, manifest)
        self.refused_findings(res, "a-1.0.0-extra.jar is not a regular file", findings=1)

    def test_a_hard_linked_file_is_refused_for_each_name_it_has(self):
        d = self.directory()
        hardlink(d)
        res = self.verify(d, self.good_manifest(d))
        self.refused_findings(res, "a-1.0.0.jar is a hard link", "a-1.0.0-link.jar is a hard link")

    def test_a_pom_xml_is_refused_even_when_the_manifest_lists_it_with_its_right_hash(self):
        d = self.directory()
        put(d, "pom.xml", "<project/>")
        res = self.verify(d, manifest_of(d))
        self.refused_findings(res, "pom.xml is not part of a release: nothing a project would build from is staged", findings=1)
        self.assertNotIn("a-1.0.0.pom", "\n".join(res.errors()))

    def test_a_settings_xml_and_other_project_files_are_refused_even_when_listed(self):
        for name in ("settings.xml", "build.gradle", "Makefile", "toolchains.xml", "mvnw", "README.md", "a-1.0.0.pom.sha1", "a-1.0.0.jar.asc.asc",
                     "a-1.0.0-tests.jar.asc"):
            with self.subTest(name):
                d = self.directory(f"d-{name}")
                put(d, name)
                res = self.verify(d, manifest_of(d))
                self.refused_findings(res, f"{name} is not part of a release")

    def test_a_mvn_directory_is_refused(self):
        d = self.directory()
        mvn_dir(d)
        res = self.verify(d, manifest_of(self_dir_files(d)))
        self.refused_findings(res, ".mvn is not a regular file")

    def test_a_dot_mvn_file_is_refused_as_a_name_even_though_it_is_regular(self):
        d = self.directory()
        mvn_file(d)
        self.refused_findings(self.verify(d, manifest_of(d)), ".mvn is not a plain file name")

    def test_a_directory_that_is_a_symlink_is_not_read(self):
        d = self.directory()
        link = self.path("link")
        os.symlink(d, link)
        res = self.verify(link, manifest_of(d))
        self.refused_findings(res, "is not a directory", findings=1)

    def test_a_directory_that_is_a_file_or_is_absent_is_refused(self):
        d = self.directory()
        manifest = manifest_of(d)
        file_ = put(self.tmp, "afile", "x")
        for target in (file_, self.path("absent")):
            with self.subTest(target):
                self.refused_findings(self.verify(target, manifest), "is not a directory", findings=1)

    def test_a_symlinked_directory_named_with_a_trailing_slash_is_refused(self):
        d = self.directory()
        link = self.path("link")
        os.symlink(d, link)
        res = self.verify(link + "/", manifest_of(d))
        self.assertEqual(res.rc, 1, res)


def self_dir_files(d):
    """A scratch directory with copies of the regular files of D, for a manifest that does not list the entry under test."""
    scratch = d + "-regular"
    os.makedirs(scratch, exist_ok=True)
    for n in os.listdir(d):
        if os.path.isfile(os.path.join(d, n)) and not os.path.islink(os.path.join(d, n)):
            shutil.copy(os.path.join(d, n), os.path.join(scratch, n))
    return scratch


class ClosedSet(Base):
    def test_a_signature_without_its_base_file_is_refused(self):
        d = self.directory()
        put(d, "b-1.0.0.jar.asc")
        res = self.verify(d, manifest_of(d))
        self.refused_findings(res, "b-1.0.0.jar.asc is not part of a release", findings=1)

    def test_only_signatures_are_refused_and_say_no_main_jar_is_staged(self):
        d = self.path("only")
        os.makedirs(d)
        put(d, "x.jar.asc")
        res = self.verify(d, manifest_of(d))
        self.refused_findings(res, "x.jar.asc is not part of a release", "no main jar is staged", findings=2)

    def test_each_of_the_eight_files_missing_is_refused_though_the_manifest_matches_what_is_left(self):
        for missing in coordinate_names("a-1.0.0"):
            with self.subTest(missing):
                d = self.directory(f"d-{missing}")
                os.remove(os.path.join(d, missing))
                res = self.verify(d, manifest_of(d))
                if missing == "a-1.0.0.jar":
                    self.assertEqual(res.rc, 1, res)           # no main jar: every other file is an orphan
                    self.assertTrue(res.errors(), res)
                else:
                    self.refused_findings(res, f"{missing} is missing - a release holds all eight files of a coordinate", findings=1)

    def test_another_classifier_is_refused(self):
        for extra in ("a-1.0.0-tests.jar", "a-1.0.0-tests.jar.asc", "a-1.0.0-bin.jar", "a-1.0.0-all.jar", "a-1.0.0.zip", "a-1.0.0.tar.gz",
                      "a-1.0.0-sources.jar.sha1", "a-1.0.0.module", "a-1.0.0-javadoc.jar.asc.asc"):
            with self.subTest(extra):
                d = self.directory(f"d-{extra}")
                put(d, extra)
                self.refused_findings(self.verify(d, manifest_of(d)))

    def test_a_coordinate_next_to_a_stray_signature_is_refused(self):
        d = self.directory("staged", "a-1.0.0", "b-1.0.0")
        os.remove(os.path.join(d, "b-1.0.0.pom"))
        res = self.verify(d, manifest_of(d))
        self.refused_findings(res, "b-1.0.0.pom is missing")

    def test_an_empty_directory_has_no_main_jar(self):
        d = self.path("empty")
        os.makedirs(d)
        res = self.verify(d, f"{sha(b'x')}  a-1.0.0.jar\n")
        self.refused_findings(res, "a-1.0.0.jar is in the manifest and not in the directory", "no main jar is staged")


class ManifestText(Base):
    """The manifest is text from an environment variable, and a malformed one is a refusal."""

    def setUp(self):
        super().setUp()
        self.d = self.directory()
        self.good = manifest_of(self.d)

    def assert_refused(self, manifest, fragment="", **kw):
        res = self.verify(self.d, manifest, **kw)
        self.assertEqual(res.rc, 1, res)
        self.assertEqual(res.out, "")
        self.assertTrue(res.errors(), res)
        self.assertIn(fragment, "\n".join(res.errors()), res)
        self.assertEqual(res.errors()[-1], FINAL, "every refusal of verify ends with the same line")
        self.assertNotIn("ok", res.out)
        return res

    def test_an_unset_variable_is_a_refusal_not_zero_files_matching(self):
        res = self.assert_refused("", "the manifest is empty", set_var=False)
        self.assertEqual(res.errors(), ["::error::the manifest is empty", FINAL], "the directory is not judged against nothing")

    def test_an_empty_variable_is_a_refusal(self):
        res = self.assert_refused("", "the manifest is empty")
        self.assertEqual(res.errors(), ["::error::the manifest is empty", FINAL])

    def test_a_manifest_of_whitespace_is_a_refusal(self):
        for text in (" ", "\n", "\n\n\n", " \n ", "\t\n"):
            with self.subTest(text):
                res = self.assert_refused(text, "the manifest is empty")
                self.assertEqual(res.errors(), ["::error::the manifest is empty", FINAL])

    def test_upper_case_hex_is_malformed(self):
        first = self.good.splitlines()[0]
        self.assert_refused(self.good.replace(first, first.upper().replace(first.split("  ", 1)[1].upper(), first.split("  ", 1)[1])), "malformed")

    def test_one_space_between_hash_and_name_is_malformed(self):
        self.assert_refused(self.good.replace("  ", " ", 1), "malformed")

    def test_three_spaces_and_a_tab_are_malformed(self):
        self.assert_refused(self.good.replace("  ", "   ", 1), "malformed")
        self.assert_refused(self.good.replace("  ", "\t", 1), "malformed")

    def test_a_hash_of_the_wrong_length_is_malformed(self):
        first = self.good.splitlines()[0]
        self.assert_refused(self.good.replace(first, first[1:], 1), "malformed")
        self.assert_refused(self.good.replace(first, "0" + first, 1), "malformed")

    def test_a_non_hex_hash_is_malformed(self):
        first = self.good.splitlines()[0]
        self.assert_refused(self.good.replace(first, "g" + first[1:], 1), "malformed")

    def test_crlf_line_ends_are_malformed(self):
        self.assert_refused(self.good.replace("\n", "\r\n"), "malformed")

    def test_a_byte_order_mark_is_malformed(self):
        self.assert_refused("﻿" + self.good, "malformed")

    def test_trailing_blank_lines_are_malformed(self):
        for text in (self.good + "\n", self.good + "\n\n", self.good.rstrip("\n") + "\n\n"):
            with self.subTest(repr(text[-3:])):
                res = self.assert_refused(text, "a blank line")
                self.assertEqual(res.errors(), ["::error::manifest line is malformed: a blank line", FINAL])

    def test_a_blank_line_inside_the_manifest_is_malformed(self):
        for text in (self.good.replace("\n", "\n\n", 1), "\n" + self.good):
            with self.subTest(repr(text[:3])):
                res = self.assert_refused(text, "a blank line")
                self.assertEqual(res.errors(), ["::error::manifest line is malformed: a blank line", FINAL])

    def test_a_line_of_blanks_is_a_malformed_line_not_a_blank_one(self):
        for blanks in (" ", "  ", "\t"):
            with self.subTest(repr(blanks)):
                res = self.assert_refused(self.good + blanks + "\n", "malformed")
                self.assertEqual(res.errors(), [f"::error::manifest line is malformed: {blanks.replace(chr(9), chr(92) + 'u0009')}", FINAL])

    def test_a_manifest_may_end_with_one_newline_or_none(self):
        self.accepted(self.verify(self.d, self.good))
        self.accepted(self.verify(self.d, self.good[:-1]))

    def test_a_name_listed_twice_is_refused(self):
        first = self.good.splitlines()[0]
        self.assert_refused(self.good + first + "\n", "twice")

    def test_a_name_with_a_leading_dot_dot_dot_a_separator_or_a_control_character_is_malformed(self):
        h0 = sha(b"x")
        for name in (".hidden.jar", ".", "..", "sub/a-1.0.0.jar", "../a-1.0.0.jar", "/abs.jar", "a\\b.jar", "a\tb.jar", "a\x1b.jar",
                     "a‮b.jar", " a.jar", "a.jar ", "a b.jar", "a\x85b.jar"):
            with self.subTest(name):
                self.assert_refused(self.good + f"{h0}  {name}\n", "malformed")

    def test_a_malformed_line_is_reported_without_a_raw_control_character(self):
        res = self.assert_refused(self.good + f"{sha(b'x')}  a\x1b[31m\nfoo\n", "malformed")
        self.assertNotIn("\x1b", res.err)
        self.assertEqual(len(res.err.splitlines()), len(res.errors()))

    def test_a_malformed_line_is_shown_but_cut_to_a_bounded_length(self):
        line = "x" * 400
        res = self.assert_refused(self.good + line + "\n", "manifest line is malformed: ")
        shown = [e for e in res.errors() if "malformed" in e][0]
        self.assertIn("x" * 100, shown)
        self.assertLess(len(shown), 200)

    def test_a_line_with_only_a_name_or_only_a_hash_is_malformed(self):
        self.assert_refused(self.good + "a-1.0.0.jar\n", "malformed")
        self.assert_refused(self.good + sha(b"x") + "\n", "malformed")
        self.assert_refused(self.good + sha(b"x") + "  \n", "malformed")

    def test_a_manifest_naming_the_same_file_with_another_hash_is_refused(self):
        first = self.good.splitlines()[0]
        self.assert_refused(first.split("  ")[0].replace(first[:1], "0" if first[0] != "0" else "1", 1) + "  " + first.split("  ", 1)[1], "")


class Names(Base):
    """Names in the directory: the legal ones are plain file names, anything else is refused and never printed raw."""

    def test_an_illegal_name_in_the_directory_is_refused_and_printed_escaped(self):
        for name in ILLEGAL_NAMES:
            with self.subTest(repr(name)):
                d = self.directory(f"d-{abs(hash(name))}")
                put(d, name)
                res = self.verify(d, manifest_of(d))
                self.refused_findings(res)
                self.assertEqual(len(res.err.splitlines()), len(res.errors()), "no name starts a second line")
                for c in "\n\r\x1b\x7f‮ ​":
                    self.assertNotIn(c, res.err.replace("\n", "") if c != "\n" else "", f"{c!r} printed raw")

    def test_a_space_inside_a_name_is_shown_as_a_space(self):
        d = self.directory()
        put(d, "extra file.txt")
        self.refused_findings(self.verify(d, manifest_of(d)), "extra file.txt is not part of a release")

    def test_a_name_that_looks_like_a_workflow_command_is_only_ever_inside_an_error_line(self):
        d = self.directory()
        put(d, "x\n::set-output name=a::b\n.jar")
        res = self.verify(d, manifest_of(d))
        self.assertEqual(res.rc, 1)
        self.assertTrue(all(ln.startswith("::error::") for ln in res.err.splitlines()), res.err)

    def test_names_that_differ_only_by_case_are_refused(self):
        d = self.directory("staged", "a-1.0.0", "A-1.0.0")
        res = self.verify(d, manifest_of(d))
        self.assertEqual(res.rc, 1, res)

    def test_names_that_differ_only_by_unicode_normalisation_are_refused(self):
        nfc, nfd = unicodedata.normalize("NFC", "é-1.0.0"), unicodedata.normalize("NFD", "é-1.0.0")
        self.assertNotEqual(nfc, nfd)
        d = self.directory("staged", nfc, nfd)
        res = self.verify(d, manifest_of(d))
        self.assertEqual(res.rc, 1, res)

    def test_a_base_with_a_comma_a_quote_or_a_dollar_is_refused(self):
        accepted = []
        for base in ("a,b-1.0.0", 'a"b-1.0.0', "a$b-1.0.0", "a`b-1.0.0", "a b-1.0.0", "a'b-1.0.0", "a;b-1.0.0"):
            d = self.directory(f"d-{abs(hash(base))}", base)
            if self.verify(d, manifest_of(d)).rc == 0:
                accepted.append(base)
        self.assertEqual(accepted, [])


class Size(Base):
    def test_a_long_manifest_naming_files_that_are_absent_is_refused(self):
        d = self.directory()
        many = "".join(f"{sha(str(i).encode())}  extra-{i}-1.0.0.jar\n" for i in range(1000))
        self.assertLess(len(manifest_of(d) + many), 131072)
        res = self.verify(d, manifest_of(d) + many)
        self.assertEqual(res.rc, 1)
        self.assertGreaterEqual(len(res.errors()), 1000)

    @unittest.skipUnless(sys.platform.startswith("linux"), "the single-string environment limit is a Linux one")
    def test_a_manifest_beyond_the_size_of_one_environment_string_cannot_even_start_the_check(self):
        """The runner passes the manifest in an environment variable, and one string is bounded by the kernel (MAX_ARG_STRLEN).

        A manifest that large is therefore a step that fails to start, never a check that sees a truncated manifest.
        """
        if h.SCRIPT_DIR_OVERRIDE:
            self.skipTest("a process is not started for a mutant")
        d = self.directory()
        huge = manifest_of(d) + ("0" * 64 + "  x.jar\n") * 2500        # > 128 KiB
        self.assertGreater(len(huge), 131072)
        with self.assertRaises(OSError) as ctx:
            subprocess.run([sys.executable, "-I", "-B", h.script_path(SCRIPT), "verify", "--dir", d, "--manifest-env", "MANIFEST"],
                           env=h.clean_env(MANIFEST=huge), capture_output=True, timeout=30)
        self.assertEqual(ctx.exception.errno, errno.E2BIG)

    def test_a_manifest_at_the_limit_of_the_environment_is_still_judged(self):
        d = self.directory()
        pad = "".join(f"{sha(str(i).encode())}  e{i}-1.0.0.jar\n" for i in range(1200))
        self.assertLess(len(manifest_of(d) + pad), 131072)
        res = self.verify(d, manifest_of(d) + pad)
        self.refused_findings(res, "is in the manifest and not in the directory")


class Usage(Base):
    def test_usage_errors_exit_2_and_print_nothing_on_stdout(self):
        d = self.directory()
        out = self.path("out")
        cases = [[], ["bogus"], ["create"], ["create", "--dir", d], ["create", "--output", out], ["verify"], ["verify", "--dir", d],
                 ["verify", "--manifest-env", "M"], ["verify", "--dir", d, "--manifest-env", "M", "--extra"], ["--help-me"]]
        for argv in cases:
            with self.subTest(argv):
                res = self.both(SCRIPT, argv)
                self.assertEqual(res.rc, 2, res)
                self.assertEqual(res.out, "")
                self.assertFalse(os.path.exists(out))

    def test_help_exits_0(self):
        res = h.run_main(SCRIPT, ["--help"])
        self.assertEqual(res.rc, 0)
        self.assertIn("create", res.out)


class Unexpected(Base):
    def run_with(self, seam, argv, exc=RuntimeError):
        module = h.load(SCRIPT)
        original = getattr(module, seam)

        def boom(*_a, **_k):
            raise exc("boom\n::error::forged\nsecond line")
        setattr(module, seam, boom)
        try:
            return h.run_main(SCRIPT, argv, env=h.clean_env(MANIFEST="x"))
        finally:
            setattr(module, seam, original)

    def test_an_unexpected_exception_is_one_error_line_and_exit_one(self):
        d = self.directory()
        for argv in (["verify", "--dir", d, "--manifest-env", "MANIFEST"], ["create", "--dir", d, "--output", self.path("o")]):
            res = self.run_with("scan", argv)
            self.assertEqual(res.rc, 1, res)
            self.assertEqual(len(res.errors()), 1, res)
            self.assertEqual(len(res.err.splitlines()), 1, "the message is flattened to one line")

    def test_a_file_that_vanishes_while_the_directory_is_read_is_a_refusal(self):
        d = self.directory()
        module = h.load(SCRIPT)
        real = os.lstat

        def vanish(path, *a, **k):
            if str(path).endswith("a-1.0.0.jar"):
                raise FileNotFoundError(errno.ENOENT, "gone", str(path))
            return real(path, *a, **k)
        with mock.patch.object(module.os, "lstat", vanish):
            res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        self.assertEqual(res.rc, 1, res)

    def test_an_unwritable_output_is_one_error_line_and_exit_one(self):
        d = self.directory()
        res = h.run_main(SCRIPT, ["create", "--dir", d, "--output", self.path("no-such-dir", "out")])
        self.assertEqual(res.rc, 1, res)
        self.assertEqual(len(res.errors()), 1, res)

    def test_a_directory_that_cannot_be_listed_is_one_finding(self):
        d = self.directory()
        manifest = manifest_of(d)
        module = h.load(SCRIPT)

        def denied(path):
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        with mock.patch.object(module.os, "listdir", denied):
            res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))
        self.refused_findings(res, "cannot be read", findings=1)

    def test_a_file_that_cannot_be_read_is_one_finding_and_no_manifest_line_for_it(self):
        d = self.directory()
        manifest = manifest_of(d)
        module = h.load(SCRIPT)
        real = module.digest

        def unreadable(path):
            if path.endswith("a-1.0.0.pom"):
                raise PermissionError(errno.EACCES, "Permission denied", path)
            return real(path)
        with mock.patch.object(module, "digest", unreadable):
            res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))
            self.refused_findings(res, "a-1.0.0.pom cannot be read", findings=1)
            out = self.path("out")
            res = h.run_main(SCRIPT, ["create", "--dir", d, "--output", out])
        self.refused_findings(res, "a-1.0.0.pom cannot be read", findings=1, final=False)
        self.assertFalse(os.path.exists(out))

    def test_keyboard_interrupt_is_not_swallowed(self):
        d = self.directory()
        with self.assertRaises(KeyboardInterrupt):
            self.run_with("scan", ["verify", "--dir", d, "--manifest-env", "MANIFEST"], KeyboardInterrupt)


class OpenOnce(Base):
    """A file is opened once, without following a link, and judged by what that descriptor says, not by a look taken earlier."""

    def spied(self, d, manifest, before_open=None):
        module = h.load(SCRIPT)
        opens, reads, fstats, stats, closes = [], [], [], [], []
        real_open, real_read, real_fstat, real_stat, real_close = os.open, os.read, os.fstat, os.stat, os.close
        self.closes = closes

        def spy_open(path, flags, *a, **k):
            if str(path).startswith(d):
                opens.append((str(path), flags))
                if before_open:
                    before_open(str(path))
            fd = real_open(path, flags, *a, **k)
            return fd

        def spy_read(fd, n):
            reads.append(fd)
            return real_read(fd, n)

        def spy_fstat(fd):
            fstats.append(fd)
            return real_fstat(fd)

        def spy_close(fd):
            closes.append(fd)
            return real_close(fd)

        def spy_stat(path, *a, **k):
            if str(path).startswith(d + os.sep):
                stats.append(str(path))
            return real_stat(path, *a, **k)
        with mock.patch.object(os, "open", spy_open), mock.patch.object(os, "read", spy_read), \
                mock.patch.object(os, "fstat", spy_fstat), mock.patch.object(os, "stat", spy_stat), mock.patch.object(os, "close", spy_close):
            res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))
        return res, opens, reads, fstats, stats

    def test_each_file_is_opened_once_with_nofollow_and_checked_with_fstat(self):
        d = self.directory()
        res, opens, reads, fstats, stats = self.spied(d, manifest_of(d))
        self.accepted(res)
        self.assertEqual(sorted(os.path.basename(p) for p, _ in opens), sorted(coordinate_names("a-1.0.0")), "one open per file")
        for _, flags in opens:
            self.assertTrue(flags & os.O_NOFOLLOW, "a link is not followed")
            self.assertTrue(flags & os.O_NONBLOCK, "opening a FIFO does not block")
            self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        self.assertEqual(len(fstats), len(opens), "the kind of file is asked of the descriptor, once per file")
        self.assertTrue(reads, "the bytes come from the descriptor")
        self.assertEqual(stats, [], "no path is stat-ed: nothing is decided by a look at the name and then re-opened")
        self.assertEqual(len(self.closes), len(opens), "every descriptor is closed, so a long list of files does not run out of them")

    def test_the_file_builtin_open_is_not_used_on_the_directory(self):
        import builtins
        d = self.directory()
        seen = []
        real = builtins.open

        def spy(path, *a, **k):
            if isinstance(path, str) and path.startswith(d):
                seen.append(path)
            return real(path, *a, **k)
        manifest = manifest_of(d)
        with mock.patch.object(builtins, "open", spy):
            self.accepted(h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest)))
        self.assertEqual(seen, [])

    def swap(self, how):
        d = self.directory()
        manifest = manifest_of(d)
        victim = os.path.join(d, "a-1.0.0.jar")

        def do(path):
            if path != victim:
                return
            os.remove(victim)
            how(victim)
        return d, manifest, do

    def test_a_file_swapped_for_a_link_after_the_directory_was_listed_is_refused(self):
        d, manifest, do = self.swap(lambda p: os.symlink("a-1.0.0.pom", p))
        res, *_ = self.spied(d, manifest, before_open=do)
        self.refused_findings(res, "a-1.0.0.jar cannot be read")

    def test_a_file_swapped_for_a_fifo_after_the_directory_was_listed_is_refused_without_blocking(self):
        d, manifest, do = self.swap(os.mkfifo)
        with bounded(15):
            res, *_ = self.spied(d, manifest, before_open=do)
        self.refused_findings(res, "a-1.0.0.jar cannot be read")

    def test_a_file_swapped_for_a_directory_after_the_directory_was_listed_is_refused(self):
        d, manifest, do = self.swap(os.mkdir)
        res, *_ = self.spied(d, manifest, before_open=do)
        self.refused_findings(res, "a-1.0.0.jar cannot be read")

    def test_a_file_swapped_for_other_bytes_after_the_directory_was_listed_is_judged_by_the_bytes_that_were_read(self):
        d, manifest, do = self.swap(lambda p: put(os.path.dirname(p), os.path.basename(p), b"other"))
        res, *_ = self.spied(d, manifest, before_open=do)
        self.refused_findings(res, "a-1.0.0.jar differs from the manifest", findings=1)


class Create(Base):
    def test_the_manifest_is_the_sorted_hash_and_name_lines_and_is_printed(self):
        d = self.directory("staged", "b-2.0.0", "a-1.0.0")
        res, out = self.create(d)
        self.accepted(res)
        want = manifest_of(d)
        self.assertEqual(res.out, want)
        self.assertEqual(want.splitlines(), sorted(want.splitlines(), key=lambda ln: ln.split("  ", 1)[1]))
        for ln in want.splitlines():
            digest, name = ln.split("  ", 1)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            with open(os.path.join(d, name), "rb") as fh:
                self.assertEqual(sha(fh.read()), digest)
        self.assertEqual(len(want.splitlines()), 16)

    def test_the_output_file_holds_the_manifest_its_digest_and_its_id(self):
        d = self.directory()
        res, out = self.create(d)
        values = parse_github_output(self.output(out))
        self.assertEqual(set(values), {"manifest", "manifest-digest", "manifest-id"})
        self.assertEqual(values["manifest"], manifest_of(d))
        self.assertEqual(values["manifest-digest"], sha(manifest_of(d).encode()))
        self.assertEqual(values["manifest-id"], values["manifest-digest"][:12])
        self.assertRegex(values["manifest-id"], r"^[0-9a-f]{12}$")

    def test_the_key_can_be_named(self):
        d = self.directory()
        res, out = self.create(d, None, "--name", "caps")
        values = parse_github_output(self.output(out))
        self.assertEqual(set(values), {"caps", "caps-digest", "caps-id"})

    def test_the_output_is_appended_to_not_replacing_what_is_there(self):
        d = self.directory()
        out = self.write("github-output", "earlier=1\nother<<EOF\nx\nEOF\n")
        self.create(d, out)
        values = parse_github_output(self.output(out))
        self.assertEqual(values["earlier"], "1")
        self.assertEqual(values["other"], "x\n")
        self.assertEqual(values["manifest"], manifest_of(d))

    def test_the_delimiter_occurs_in_no_line_of_the_manifest(self):
        d = self.directory()
        _, out = self.create(d)
        text = self.output(out)
        delimiter = text.split("\n", 1)[0].split("<<", 1)[1]
        self.assertGreaterEqual(len(delimiter), 16)
        body = text.split("\n", 1)[1]
        self.assertEqual(body.count(delimiter), 1, "the delimiter closes the value once and is not inside it")
        for ln in manifest_of(d).splitlines():
            self.assertNotIn(delimiter, ln)

    def test_names_that_look_like_commands_or_delimiters_stay_inside_the_value(self):
        d = self.directory("staged", "a-1.0.0", "a_b.c-0.0.0", "A.b-c_d-10.20.30")
        for name in LEGAL_ODD_NAMES:
            put(d, name)
        res, out = self.create(d)
        self.accepted(res)
        values = parse_github_output(self.output(out))
        self.assertEqual(set(values), {"manifest", "manifest-digest", "manifest-id"}, "no name started a key of its own")
        self.assertEqual(values["manifest"], manifest_of(d))
        self.assertNotIn("\n::", res.out.replace("  ::", ""))
        delimiter = self.output(out).split("\n", 1)[0].split("<<", 1)[1]
        for ln in manifest_of(d).splitlines():
            self.assertNotIn(delimiter, ln, "the delimiter occurs in no line, whatever the names are")

    def test_a_main_jar_with_a_name_that_looks_like_a_command_or_a_delimiter_is_refused_and_nothing_is_written(self):
        for name in REFUSED_ODD_JARS:
            with self.subTest(name):
                d = self.directory(f"d-{abs(hash(name))}")
                put(d, name)
                out = self.path(f"out-{abs(hash(name))}")
                res, _ = self.create(d, out)
                self.refused_findings(res, f"{name[:-len('.jar')]} is not a releasable coordinate name", findings=1, final=False)
                self.assertFalse(os.path.exists(out))
                self.assertEqual(res.out, "")

    def test_a_file_named_like_the_delimiter_does_not_end_the_value(self):
        d = self.directory()
        _, out = self.create(d)
        delimiter = self.output(out).split("\n", 1)[0].split("<<", 1)[1]
        for name in (delimiter, delimiter + "x", "key=" + delimiter, "x<<" + delimiter):
            put(d, name)
        out2 = self.path("second-output")
        res, _ = self.create(d, out2)
        self.accepted(res)
        values = parse_github_output(self.output(out2))
        self.assertEqual(values["manifest"], manifest_of(d))
        second = self.output(out2).split("\n", 1)[0].split("<<", 1)[1]
        self.assertNotEqual(second, delimiter)
        self.assertNotIn(second, manifest_of(d))

    def test_an_illegal_name_is_refused_and_nothing_is_written(self):
        for name in ILLEGAL_NAMES:
            with self.subTest(repr(name)):
                d = self.directory(f"d-{abs(hash(name))}")
                put(d, name)
                out = self.path(f"out-{abs(hash(name))}")
                res, _ = self.create(d, out)
                self.refused_findings(res, "is not a plain file name", findings=1, final=False)
                self.assertFalse(os.path.exists(out), "an illegal name is refused, not escaped into the output file")
                self.assertEqual(res.out, "")

    def test_an_entry_that_is_not_a_plain_regular_file_is_refused_and_nothing_is_written(self):
        for label, make in NOT_REGULAR.items():
            with self.subTest(label):
                d = self.directory(f"d-{abs(hash(label))}")
                make(d)
                out = self.path(f"out-{abs(hash(label))}")
                with bounded(30):
                    res, _ = self.create(d, out)
                self.refused_findings(res, final=False)
                self.assertFalse(os.path.exists(out))

    def test_an_empty_directory_is_refused(self):
        d = self.path("empty")
        os.makedirs(d)
        res, out = self.create(d)
        self.refused_findings(res, "nothing is staged", findings=1, final=False)
        self.assertFalse(os.path.exists(out))

    def test_a_directory_that_is_a_file_a_link_or_absent_is_refused(self):
        d = self.directory()
        link = self.path("link")
        os.symlink(d, link)
        for target in (put(self.tmp, "afile", "x"), link, self.path("absent")):
            with self.subTest(target):
                res, out = self.create(target, self.path(f"o-{os.path.basename(target)}"))
                self.refused_findings(res, "is not a directory", findings=1, final=False)
                self.assertFalse(os.path.exists(out))

    def test_a_subdirectory_even_an_empty_one_is_refused(self):
        d = self.directory()
        os.mkdir(os.path.join(d, "empty"))
        res, out = self.create(d)
        self.refused_findings(res, "empty is not a regular file", findings=1, final=False)
        self.assertFalse(os.path.exists(out))

    def test_create_does_not_judge_the_closed_set_that_is_the_gates_and_the_verifys(self):
        d = self.path("loose")
        os.makedirs(d)
        put(d, "anything.txt")
        res, out = self.create(d)
        self.accepted(res)


class RoundTrip(Base):
    def test_create_then_verify_passes_for_a_seeded_sample_of_file_sets(self):
        for n, files in enumerate(random_sets(20261112, 40)):
            d = self.path(f"set-{n}")
            os.makedirs(d)
            for name, data in files:
                put(d, name, data)
            out = self.path(f"out-{n}")
            created = h.run_main(SCRIPT, ["create", "--dir", d, "--output", out])
            self.accepted(created)
            manifest = parse_github_output(self.output(out))["manifest"]
            self.assertEqual(manifest, manifest_of(d))
            res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))
            self.accepted(res)
            self.assertEqual(res.out, f"ok - {len(files)} files match the manifest\n")

    def test_the_same_round_trip_as_two_programs(self):
        d = self.directory("staged", "a-1.0.0", "b-0.1.0")
        res, out = self.create(d)
        manifest = parse_github_output(self.output(out))["manifest"]
        self.accepted(self.verify(d, manifest))

    def test_a_manifest_made_for_one_directory_does_not_pass_for_a_copy_with_one_changed_file(self):
        d = self.directory()
        _, out = self.create(d)
        manifest = parse_github_output(self.output(out))["manifest"]
        copy = self.path("copy")
        shutil.copytree(d, copy)
        with open(os.path.join(copy, "a-1.0.0.pom.asc"), "ab") as fh:
            fh.write(b"\n")
        self.refused_findings(self.verify(copy, manifest), "a-1.0.0.pom.asc differs", findings=1)


if __name__ == "__main__":
    unittest.main()
