"""The closed set `staged_manifest.py verify` accepts is the set `check_release_readiness.py --stage` produces.

The gate stages the files of a build; the manifest is made of what it staged; a later job verifies what it downloaded against that
manifest. If the two disagree about what a release is, a directory the gate would never have produced can pass the later check.
Here the real gate stages fixture builds, and every single-file deletion, addition and rename of the staged set is judged.
"""
from __future__ import annotations

import os
import shutil
import unittest

import caps_release_helpers as h
from manifest_support import SCRIPT, coordinate_names, make_coordinate, manifest_of, parse_github_output, put, sha
from readiness_support import Fixture

GATE = "check_release_readiness"


class Agreement(Fixture):
    def stage(self, *bases, name="stage"):
        for base in bases:
            self.coordinate(base)
        staged = self.path(name)
        res = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", staged])
        self.accepted(res)
        out = self.path(f"output-{name}")
        made = h.run_main(SCRIPT, ["create", "--dir", staged, "--output", out])
        self.accepted(made)
        with open(out, encoding="utf-8") as fh:
            return staged, parse_github_output(fh.read())["manifest"]

    def verify(self, directory, manifest):
        return h.run_main(SCRIPT, ["verify", "--dir", directory, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))

    def copy(self, staged, label):
        dest = self.path(f"copy-{label}")
        shutil.copytree(staged, dest)
        return dest

    def test_what_the_gate_staged_passes_for_one_and_for_several_coordinates(self):
        for n, bases in enumerate((("a-1.0.0",), ("a-1.0.0", "b-2.1.0"), ("x_y.z-0.1.0", "a-b-c-3.4.5", "q-10.20.30"))):
            with self.subTest(bases):
                self.setUp() if n else None
                staged, manifest = self.stage(*bases, name=f"stage{n}")
                res = self.verify(staged, manifest)
                self.accepted(res)
                self.assertEqual(res.out, f"ok - {8 * len(bases)} files match the manifest\n")
                self.assertEqual(sorted(os.listdir(staged)), sorted(n_ for b in bases for n_ in coordinate_names(b)))

    def test_every_single_file_deletion_is_refused_with_the_manifest_of_the_staged_set_and_with_one_made_after(self):
        staged, manifest = self.stage("a-1.0.0", "b-2.0.0")
        for name in sorted(os.listdir(staged)):
            with self.subTest(name):
                d = self.copy(staged, f"del-{name}")
                os.remove(os.path.join(d, name))
                self.refused(self.verify(d, manifest))
                self.refused(self.verify(d, manifest_of(d)))

    def test_every_single_file_addition_is_refused_whether_or_not_the_manifest_lists_it(self):
        staged, manifest = self.stage("a-1.0.0")
        extras = ["extra.txt", "pom.xml", "settings.xml", "a-1.0.0-tests.jar", "a-1.0.0-tests.jar.asc", "a-1.0.0.jar.sha1", "b-1.0.0.jar.asc",
                  "b-1.0.0.jar", "a-1.0.0-bin.jar", "a-1.0.0.pom.asc.asc", "A-1.0.0.jar", "a-1.0.0.JAR", ".hidden", "a-1.0.0 .jar"]
        for name in extras:
            with self.subTest(name):
                d = self.copy(staged, f"add-{name}")
                put(d, name)
                self.refused(self.verify(d, manifest))
                self.refused(self.verify(d, manifest_of(d)))

    def test_every_single_file_rename_is_refused_whether_or_not_the_manifest_follows_it(self):
        staged, manifest = self.stage("a-1.0.0")
        for name in sorted(os.listdir(staged)):
            for label, new in (("suffix", name + ".x"), ("case", name.upper()), ("classifier", name.replace("-sources", "-tests").replace("-javadoc", "-bin")
                                                                                   .replace("a-1.0.0.pom", "a-1.0.0.xml")),
                               ("version", name.replace("1.0.0", "1.0.1"))):
                if new == name:
                    continue
                with self.subTest(f"{name} -> {new}"):
                    d = self.copy(staged, f"ren-{name}-{label}")
                    os.rename(os.path.join(d, name), os.path.join(d, new))
                    self.refused(self.verify(d, manifest))
                    self.refused(self.verify(d, manifest_of(d)))

    def test_what_the_gate_refuses_for_a_missing_file_the_verification_refuses_too(self):
        for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom"):
            with self.subTest(suffix):
                self.setUp()
                self.coordinate("a-1.0.0", skip=(suffix,))
                gate = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])
                self.refused(gate)
                d = self.path("what-is-there")
                os.makedirs(d)
                for n in os.listdir(self.target):
                    put(d, n)
                self.refused(self.verify(d, manifest_of(d)))

    def test_what_the_gate_refuses_as_an_unsigned_file_is_not_a_complete_coordinate_either(self):
        self.coordinate("a-1.0.0", sign=False)
        self.refused(h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg]))
        d = self.path("unsigned")
        os.makedirs(d)
        for n in os.listdir(self.target):
            put(d, n)
        self.refused(self.verify(d, manifest_of(d)))

    def test_what_the_gate_refuses_as_an_extra_classifier_the_verification_refuses_too(self):
        staged, manifest = self.stage("a-1.0.0")
        put(self.target, "a-1.0.0-tests.jar")
        self.refused(h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg]))
        d = self.copy(staged, "classifier")
        put(d, "a-1.0.0-tests.jar")
        self.refused(self.verify(d, manifest_of(d)))

    def gate_and_verify(self, base):
        """(gate result, verify result) for the eight files of BASE, laid out as a build and as a downloaded directory."""
        self.coordinate(base)
        gate = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])
        d = self.path("downloaded")
        os.makedirs(d)
        for n in coordinate_names(base):
            put(d, n)
        return gate, self.verify(d, manifest_of(d))

    def test_a_plain_coordinate_is_judged_the_same_by_both(self):
        for base in ("a-1.0.0", "a-b_c.d-12.0.3", "x-0.0.0"):
            with self.subTest(base):
                self.setUp()
                gate, verified = self.gate_and_verify(base)
                self.assertEqual((gate.rc, verified.rc), (0, 0), (gate, verified))

    @h.known_defect("closed-set-agreement", "verify accepts a coordinate whose name is not ASCII, which the gate refuses "
                                             "(staged_manifest.py closed_set puts no limit on the characters of a base)")
    def test_a_coordinate_that_is_not_ascii_is_refused_by_the_verification_as_by_the_gate(self):
        gate, verified = self.gate_and_verify("é-1.0.0")
        self.assertEqual(gate.rc, 1, gate)
        self.assertEqual(verified.rc, 1, verified)

    @h.known_defect("closed-set-agreement", "verify accepts a SNAPSHOT coordinate, which the gate refuses (staged_manifest.py closed_set)")
    def test_a_snapshot_coordinate_is_refused_by_the_verification_as_by_the_gate(self):
        for base in ("a-1.0.0-SNAPSHOT", "a-1.0.0-20260101.101010-1"):
            self.setUp()
            gate, verified = self.gate_and_verify(base)
            self.assertEqual(gate.rc, 1, gate)
            self.assertEqual(verified.rc, 1, f"{base}: {verified}")

    @h.known_defect("closed-set-agreement", "verify takes a `-tests` jar for the main jar of a coordinate of its own, which the gate "
                                             "refuses as a classifier (staged_manifest.py closed_set)")
    def test_a_tests_jar_with_its_own_eight_files_is_refused_by_the_verification_as_by_the_gate(self):
        gate, verified = self.gate_and_verify("a-1.0.0-tests")
        self.assertEqual(gate.rc, 1, gate)
        self.assertEqual(verified.rc, 1, verified)


if __name__ == "__main__":
    unittest.main()
