"""check_release_readiness --target-dir D [--gpg G] [--stage S]: the closed set of files, whatever else `target/` holds.

A coordinate is a main jar, its -sources and -javadoc jars, its pom and a detached `.asc` of each of the four. Every top-level
`*.jar`, `*.pom` and `*.asc` of `target/` is gated; nothing else is read.
"""
from __future__ import annotations

import os
import shutil
import socket
import time
import unittest

import caps_release_helpers as h
from readiness_support import Fixture, SUFFIXES, make_zip, pom_xml, sig_of

S = "check_release_readiness"
FILES = [f"a-1.0.0{s}{k}" for s in SUFFIXES for k in ("", ".asc")]


def bind_socket(path):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(path)


class Closed(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()
        self.stage = self.path("gated-files")

    def reset(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.real_coordinate()

    def gate(self, *extra):
        return h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, *extra])

    def test_the_options_of_a_removed_bundle_are_usage_errors(self):
        for argv in (["--expect-bundle", "true"], ["--expect-bundle", "false"], ["--expect-bundle"], ["--uploaded"],
                     ["--uploaded", "true"]):
            for run in (h.run_main, h.run_proc):
                with self.subTest(argv, run=run.__name__):
                    res = run(S, ["--target-dir", self.target, "--gpg", self.gpg, *argv])
                    self.assertEqual(res.rc, 2, res)
                    self.assertEqual(res.errors(), [])
        self.assertEqual(h.run_proc(S, ["--gpg", self.gpg]).rc, 2, "--target-dir is required")

    def test_a_central_publishing_directory_in_target_is_ignored_and_not_staged(self):
        bundle = os.path.join(self.target, "central-publishing")
        os.makedirs(bundle)
        make_zip(os.path.join(bundle, "central-bundle.zip"), ["eu/exeris/caps/a/1.0.0/a-1.0.0.pom"])
        for name in ("a.jar", "b.pom", "c.asc"):
            with open(os.path.join(bundle, name), "w") as fh:
                fh.write("not gated: the gate reads the top level of target/")
        res = self.gate("--stage", self.stage)
        self.accepted(res)
        self.assertNotIn("central", res.out + res.err)
        self.assertEqual(sorted(os.listdir(self.stage)), sorted(FILES))

    def test_a_central_publishing_directory_does_not_excuse_a_finding(self):
        os.makedirs(os.path.join(self.target, "central-publishing"))
        os.remove(os.path.join(self.target, "a-1.0.0-javadoc.jar.asc"))
        self.refused(self.gate(), "a-1.0.0-javadoc.jar has no detached signature")

    def test_a_non_regular_file_in_place_of_each_released_file_is_refused_without_blocking(self):
        makers = {
            "fifo": os.mkfifo,
            "directory": os.mkdir,
            "socket": bind_socket,
            "link to a device": lambda p: os.symlink("/dev/null", p),
            "dangling link": lambda p: os.symlink(self.path("absent"), p),
        }
        for name in FILES:
            for kind, make in makers.items():
                with self.subTest(name, kind=kind):
                    self.reset()
                    os.remove(os.path.join(self.target, name))
                    make(os.path.join(self.target, name))
                    start = time.monotonic()
                    res = self.gate("--stage", self.stage)
                    self.assertLess(time.monotonic() - start, 10)
                    self.assertEqual(res.rc, 1, res)
                    self.assertTrue(res.errors())
                    subject = name[:-len(".asc")] if name.endswith(".asc") else name
                    if not (kind == "directory" and name == "a-1.0.0.jar"):      # a directory is no main jar at all
                        self.assertTrue(any(subject in e for e in res.errors()), res.errors())
                    self.assertFalse(os.path.lexists(self.stage), "a refusal stages nothing")

    def test_every_other_kind_of_entry_beside_a_coordinate_is_refused_or_ignored_by_extension(self):
        refused = ("a-1.0.0-tests.jar", "a-1.0.0-shaded.jar", "a-1.0.0-test-sources.jar", "b-2.0.0.jar", "b-2.0.0.pom",
                   "a-1.0.0.pom.asc.asc", "orphan.asc", "a-1.0.0-tests.jar.asc", "a-1.0.0-SNAPSHOT.pom")
        ignored = ("a-1.0.0.module", "a-1.0.0.jar.md5", "a-1.0.0.jar.sha1", "a-1.0.0.pom.sha256", "x.zip", "notes.txt", "a-1.0.0.jar.asc.md5",
                   "central-bundle.zip", ".jar.keep", "a-1.0.0-cyclonedx.json")
        for name in refused:
            with self.subTest("refused " + name):
                self.reset()
                make_zip(os.path.join(self.target, name), ["x"])
                res = self.gate()
                self.refused(res)
        for name in ignored:
            with self.subTest("ignored " + name):
                self.reset()
                with open(os.path.join(self.target, name), "w") as fh:
                    fh.write("x")
                self.accepted(self.gate())

    def test_a_directory_beside_the_files_is_not_gated_unless_it_is_named_like_one(self):
        os.makedirs(os.path.join(self.target, "classes", "x"))
        os.makedirs(os.path.join(self.target, "generated-sources"))
        self.accepted(self.gate())
        os.makedirs(os.path.join(self.target, "extra.jar"))
        self.refused(self.gate(), "extra.jar is not part of a release")

    def test_each_finding_is_one_error_line_and_the_run_closes_with_one_more(self):
        os.remove(os.path.join(self.target, "a-1.0.0-sources.jar"))
        os.remove(os.path.join(self.target, "a-1.0.0.pom.asc"))
        with open(os.path.join(self.target, "a-1.0.0.jar.asc"), "w") as fh:
            fh.write("garbage\n")
        make_zip(os.path.join(self.target, "a-1.0.0-tests.jar"), ["x"])
        res = self.gate()
        self.assertEqual(res.rc, 1)
        errors = res.errors()
        self.assertEqual(len(errors), len(res.err.splitlines()), "every line of stderr is an error line")
        text = "\n".join(errors)
        for fragment in ("a-1.0.0 is missing a-1.0.0-sources.jar", "a-1.0.0.pom has no detached signature",
                         "a-1.0.0.jar.asc is not a good signature", "a-1.0.0-tests.jar is not part of a release"):
            self.assertEqual(len([e for e in errors if fragment in e]), 1, fragment)
        self.assertEqual(len(errors), 5)
        self.assertTrue(errors[-1].startswith("::error::release-readiness failed"))
        self.assertNotIn("coordinate: a-1.0.0", res.out, "a coordinate with a finding is not reported as ready")
        self.assertNotIn("release-readiness: ok", res.out)

    def test_a_second_coordinate_is_gated_on_its_own_and_staged_whole(self):
        self.real_coordinate(artifact="b", version="2.0.0")
        res = self.gate("--stage", self.stage)
        self.accepted(res)
        self.assertIn("coordinate: a-1.0.0 - main, sources, javadoc, pom, signatures", res.out)
        self.assertIn("coordinate: b-2.0.0 - main, sources, javadoc, pom, signatures", res.out)
        self.assertEqual(len(os.listdir(self.stage)), 16)

    def test_a_signature_is_checked_against_its_own_file_with_the_gpg_given(self):
        calls = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(FAKE_GPG_LOG=self.log))
        self.accepted(calls)
        with open(self.log) as fh:
            self.assertEqual(len(fh.readlines()), 4)
        other = self.write("other-gpg", "#!/bin/sh\nexit 1\n")
        os.chmod(other, 0o755)
        res = h.run_main(S, ["--target-dir", self.target, "--gpg", other])
        self.refused(res, "is not a good signature")
        self.assertEqual(len([e for e in res.errors() if "not a good signature" in e]), 4)

    def test_a_signature_made_for_one_file_does_not_cover_a_file_with_the_same_content_under_another_name(self):
        jar = os.path.join(self.target, "a-1.0.0.jar")
        sources = os.path.join(self.target, "a-1.0.0-sources.jar")
        shutil.copy(jar, sources)                   # the same bytes, so the same signature text is valid for both
        with open(sources + ".asc", "w") as fh:
            fh.write(sig_of(sources))
        self.accepted(self.gate())
        os.remove(sources + ".asc")
        self.refused(self.gate(), "a-1.0.0-sources.jar has no detached signature")

    def test_a_ready_run_prints_one_line_per_coordinate_and_the_closing_line_and_nothing_else(self):
        res = self.gate()
        self.accepted(res)
        self.assertEqual(res.out.splitlines(), ["coordinate: a-1.0.0 - main, sources, javadoc, pom, signatures", "release-readiness: ok"])
        self.assertEqual(res.err, "")

    def test_a_gated_name_with_an_unusual_character_is_refused_and_shown_escaped(self):
        for label, char, escaped in (("line separator", "\u2028", "\\u2028"), ("paragraph separator", "\u2029", "\\u2029"),
                                     ("unassigned", "\u0378", "\\u0378"), ("zero width", "\u200b", "\\u200b"),
                                     ("escape", "\x1b", "\\u001b"), ("delete", "\x7f", "\\u007f")):
            for suffix in (".jar", ".pom", ".asc"):
                with self.subTest(label, suffix=suffix):
                    self.reset()
                    name = f"x{char}y{suffix}"
                    with open(os.path.join(self.target, name), "w") as fh:
                        fh.write("x")
                    res = self.gate()
                    self.refused(res, "has a control or unassigned character in its name")
                    self.assertIn(f"x{escaped}y{suffix}", "\n".join(res.errors()))
                    self.assertNotIn(char, res.err)

    def test_a_name_with_an_unusual_character_that_is_not_gated_is_not_refused(self):
        for name in ("notes\u2028.txt", "a-1.0.0.jar.md5\x1b", "x\n.zip", "\u0378", "report\u200b.json"):
            with self.subTest(repr(name)):
                self.reset()
                with open(os.path.join(self.target, name), "w") as fh:
                    fh.write("x")
                self.accepted(self.gate())

    def test_a_namespaced_or_prefixed_pom_yields_its_coordinate(self):
        ns = "http://maven.apache.org/POM/4.0.0"
        plain = pom_xml()
        namespaced = plain.replace("<project>", f'<project xmlns="{ns}">')
        prefixed = ("<p:project xmlns:p=\"" + ns + "\"><p:groupId>eu.exeris.caps</p:groupId><p:artifactId>a</p:artifactId>"
                    "<p:version>1.0.0</p:version></p:project>")
        for label, text in (("default namespace", namespaced), ("prefix", prefixed)):
            with self.subTest(label):
                self.coordinate("a-1.0.0", pom_text=text)
                self.accepted(self.gate())

    def test_the_poms_own_group_wins_over_its_parents(self):
        parent = "<parent><groupId>{}</groupId><artifactId>p</artifactId><version>1.0.0</version></parent>"
        own_ascii = f"<project>{parent.format(chr(0xe9))}<groupId>eu.exeris.caps</groupId><artifactId>a</artifactId><version>1.0.0</version></project>"
        own_other = f"<project>{parent.format('eu.exeris.caps')}<groupId>{chr(0xe9)}</groupId><artifactId>a</artifactId><version>1.0.0</version></project>"
        self.coordinate("a-1.0.0", pom_text=own_ascii)
        self.accepted(self.gate())
        self.coordinate("a-1.0.0", pom_text=own_other)
        self.refused(self.gate(), "names a coordinate that is not ASCII")

    def test_a_pom_that_lacks_a_part_of_the_coordinate_is_one_finding(self):
        lacking = {
            "groupId": "<project><artifactId>a</artifactId><version>1.0.0</version></project>",
            "artifactId": "<project><groupId>g</groupId><version>1.0.0</version></project>",
            "version": "<project><groupId>g</groupId><artifactId>a</artifactId></project>",
            "all": "<project/>",
            "empty version": "<project><groupId>g</groupId><artifactId>a</artifactId><version> </version></project>",
        }
        for label, text in lacking.items():
            with self.subTest(label):
                self.coordinate("a-1.0.0", pom_text=text)
                res = self.gate()
                self.refused(res, "a-1.0.0.pom does not yield a groupId, an artifactId and a version")
                self.assertEqual(len(res.errors()), 2, res.errors())
                self.assertTrue(res.errors()[-1].startswith("::error::release-readiness failed"), "the closing line, not a crash")
                self.assertNotIn("unexpectedly", res.err)


if __name__ == "__main__":
    unittest.main()
