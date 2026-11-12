"""One rule for a releasable base name, held to the same table by the readiness gate, `staged_manifest.py create` and `verify`.

A base is `<artifactId>-<MAJOR.MINOR.PATCH>` (see `base_rule_support`). The upload step splices the base into a comma separated
argument list in the job that holds the package credential, so the three places that look at a base must agree on what one is, and
the files the real upload step names must be exactly the files of the base. The expected answer comes from `base_rule_support.rule`,
written in the test and sharing nothing with the scripts.
"""
from __future__ import annotations

import os
import shutil
import unittest

import base_rule_support as b
import caps_release_helpers as h
import upload_job_support as job
from manifest_support import FINAL, SCRIPT, make_coordinate, manifest_of, put
from readiness_support import Fixture

GATE = "check_release_readiness"
GATE_MESSAGES = ("is not a releasable coordinate name", "is not ASCII", "is a SNAPSHOT")
MANIFEST_MESSAGES = ("is not a releasable coordinate name", "is not a plain file name")
COLLISION = "are the same name under case folding or Unicode normalisation"


class Consumers(Fixture):
    """The three consumers of a base, each run on the eight files of one base."""

    n = 0

    def fresh(self, label):
        Consumers.n += 1
        return self.path(f"{label}-{Consumers.n}")

    def gate(self, base):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.coordinate(base)
        return h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])

    def create(self, base):
        d = self.fresh("create")
        make_coordinate(d, base)
        out = self.fresh("create-output")
        res = h.run_main(SCRIPT, ["create", "--dir", d, "--output", out])
        return res, out

    def verify(self, base):
        d = self.fresh("verify")
        make_coordinate(d, base)
        return h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))

    def check(self, base, expected):
        """All three consumers judge BASE as EXPECTED says, and a refusal names the base (not some other defect of the fixture)."""
        gate = self.gate(base)
        created, out = self.create(base)
        verified = self.verify(base)
        if expected:
            self.accepted(gate)
            self.accepted(created)
            self.accepted(verified)
            self.assertEqual(verified.out, "ok - 8 files match the manifest\n")
            self.assertTrue(os.path.exists(out))
            return
        self.refused(gate)
        self.assertTrue(any(m in gate.err for m in GATE_MESSAGES), gate)
        self.refused(created)
        self.assertEqual(created.out, "")
        self.assertTrue(any(m in created.err for m in MANIFEST_MESSAGES), created)
        self.assertFalse(os.path.exists(out), "a refused base leaves no manifest behind")
        self.refused(verified)
        self.assertEqual(verified.errors()[-1], FINAL)
        self.assertTrue(any(m in verified.err for m in MANIFEST_MESSAGES), verified)


class Table(Consumers):
    def test_the_table_agrees_with_the_independent_statement_of_the_rule(self):
        self.assertEqual([x for x in b.ACCEPTED if not b.rule(x)], [])
        self.assertEqual([x for x in b.REFUSED if b.rule(x)], [])

    def test_the_vectors_cover_what_the_task_names(self):
        self.assertIn("a-1.0.0", b.ACCEPTED)
        self.assertIn("a_b.c-0.0.0", b.ACCEPTED)
        self.assertIn("A.b-c_d-10.20.30", b.ACCEPTED)
        self.assertIn(200, {len(x) for x in b.ACCEPTED})
        self.assertIn(201, {len(x) for x in b.REFUSED})
        for c in ',"$\';`*?[]{}()<>|&!#~%^=+@:/\\ \t\n\x00é':
            self.assertIn(f"a{c}b-1.0.0", b.REFUSED, repr(c))

    def test_the_accepted_vectors_by_the_functions_of_the_scripts(self):
        gate, manifest = h.load(GATE).releasable_base, h.load(SCRIPT).releasable_base
        for base in b.ACCEPTED:
            with self.subTest(base[:60]):
                self.assertTrue(gate(base))
                self.assertTrue(manifest(base))

    def test_the_refused_vectors_by_the_functions_of_the_scripts(self):
        gate, manifest = h.load(GATE).releasable_base, h.load(SCRIPT).releasable_base
        for base in b.REFUSED:
            with self.subTest(repr(base[:60])):
                self.assertFalse(gate(base))
                self.assertFalse(manifest(base))

    def test_the_length_bound_is_two_hundred_characters_of_the_whole_base(self):
        for length in (199, 200):
            self.assertTrue(h.load(GATE).releasable_base(b.padded(length)), length)
            self.assertTrue(h.load(SCRIPT).releasable_base(b.padded(length)), length)
        for length in (201, 202, 255, 1000):
            self.assertFalse(h.load(GATE).releasable_base(b.padded(length)), length)
            self.assertFalse(h.load(SCRIPT).releasable_base(b.padded(length)), length)
        self.assertEqual(h.load(GATE).MAX_BASE, 200)
        self.assertEqual(h.load(SCRIPT).MAX_BASE, 200)


class Vectors(Consumers):
    def test_every_accepted_vector_passes_the_gate_create_and_verify(self):
        for base in b.ACCEPTED:
            with self.subTest(base[:60]):
                self.check(base, True)

    def test_every_refused_vector_that_a_file_can_be_named_is_refused_by_the_gate_create_and_verify(self):
        for base in b.REFUSED:
            if not b.storable(base):
                continue
            with self.subTest(repr(base[:60])):
                self.check(base, False)

    def test_a_double_dash_belongs_to_the_artifact_id(self):
        """`a--1.0.0` is the artifactId `a-` and the version 1.0.0; Maven allows a dash at the end of an artifactId."""
        self.assertIn("a--1.0.0", b.ACCEPTED)
        self.check("a--1.0.0", True)

    def test_a_refusal_of_a_length_names_the_bound(self):
        res = self.gate(b.padded(201))
        self.refused(res, "at most 200 characters")
        created, _ = self.create(b.padded(201))
        self.refused(created, "at most 200 characters")

    def test_the_gate_judges_the_base_of_a_main_jar_whatever_its_other_files_are(self):
        res = self.gate("a,b-1.0.0")
        self.refused(res, "a,b-1.0.0 is not a releasable coordinate name")
        self.assertEqual(sum("is not a releasable coordinate name" in ln for ln in res.errors()), 1)

    def test_create_refuses_a_directory_with_one_bad_base_among_good_ones_and_writes_nothing(self):
        d = self.path("mixed")
        make_coordinate(d, "a-1.0.0")
        make_coordinate(d, "b,c-1.0.0")
        make_coordinate(d, "d-2.0.0")
        out = self.path("out")
        res = h.run_main(SCRIPT, ["create", "--dir", d, "--output", out])
        self.refused(res, "b,c-1.0.0 is not a releasable coordinate name")
        self.assertEqual(len(res.errors()), 1, "one finding for the one bad base")
        self.assertFalse(os.path.exists(out))

    def test_create_judges_the_base_only_and_leaves_the_whole_set_to_verify_and_the_gate(self):
        d = self.path("loose")
        os.makedirs(d)
        put(d, "a-1.0.0.jar")
        put(d, "stray.txt")
        out = self.path("out")
        self.accepted(h.run_main(SCRIPT, ["create", "--dir", d, "--output", out]))
        # a classifier jar is not a main jar, so its name is not a base
        d2 = self.path("classifiers")
        os.makedirs(d2)
        for n in ("a-1.0.0.jar", "a-1.0.0-sources.jar", "a-1.0.0-javadoc.jar", "a-1.0.0-tests.jar", "weird name-tests.jar"):
            put(d2, n)
        self.accepted(h.run_main(SCRIPT, ["create", "--dir", d2, "--output", self.path("out2")]))

    def test_a_tests_jar_is_a_classifier_for_verify_and_never_a_main_jar_with_a_base_of_its_own(self):
        d = self.path("tests-jar")
        make_coordinate(d, "a-1.0.0")
        put(d, "a-1.0.0-tests.jar")
        res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        self.refused(res, "a-1.0.0-tests.jar is not part of a release")
        self.assertNotIn("a-1.0.0-tests is not a releasable", res.err, "it is judged as a classifier, not as the main jar of a base")
        self.assertEqual(res.errors()[-1], FINAL)


class Property(Consumers):
    SEED = 20261112

    def test_the_gate_create_verify_and_the_independent_rule_agree_on_twenty_thousand_names(self):
        gate, manifest = h.load(GATE).releasable_base, h.load(SCRIPT).releasable_base
        accepted = refused = 0
        disagreements = []
        for base in b.sample(self.SEED, 20000):
            want = b.rule(base)
            if not (gate(base) == manifest(base) == want):
                disagreements.append((base, want, gate(base), manifest(base)))
            accepted += want
            refused += not want
        self.assertEqual(disagreements[:5], [])
        self.assertGreater(accepted, 1000)
        self.assertGreater(refused, 1000)

    def test_the_same_agreement_through_the_three_programs_on_a_seeded_sample_of_names_a_file_can_hold(self):
        yes, no, seen = [], [], set()
        for base in b.sample(self.SEED + 1, 6000):
            key = base.casefold()
            if not b.storable(base) or key in seen:
                continue
            seen.add(key)
            (yes if b.rule(base) else no).append(base)
        self.assertGreaterEqual(len(yes), 12)
        self.assertGreaterEqual(len(no), 12)
        for base in yes[:12]:
            with self.subTest(base[:60]):
                self.check(base, True)
        for base in no[:12]:
            with self.subTest(repr(base[:60])):
                self.check(base, False)


class Collisions(Consumers):
    """Two names equal after NFKC and case folding are refused: a case-insensitive extraction would let one overwrite the other."""

    def collide(self, upper, lower):
        for base in (upper, lower):
            self.coordinate(base)
        gate = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])
        d = self.path("downloaded")
        for base in (upper, lower):
            make_coordinate(d, base)
        verified = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        return gate, verified

    def lines(self, res):
        return [ln for ln in res.errors() if COLLISION in ln]

    def test_the_gate_and_verify_refuse_a_case_variant_with_the_same_message(self):
        gate, verified = self.collide("A-1.0.0", "a-1.0.0")
        self.refused(gate, COLLISION)
        self.refused(verified, COLLISION)
        self.assertEqual(verified.errors()[-1], FINAL)
        self.assertEqual(len(self.lines(gate)), 8, "one finding for each of the eight files")
        self.assertEqual(self.lines(gate), self.lines(verified))
        self.assertIn("::error::a-1.0.0.jar and A-1.0.0.jar are the same name under case folding or Unicode normalisation", self.lines(gate))

    def test_the_gate_refuses_a_case_variant_of_a_single_file_beside_a_whole_coordinate(self):
        self.coordinate("a-1.0.0")
        put(self.target, "A-1.0.0.pom")
        res = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])
        self.refused(res, COLLISION)

    def test_a_normalisation_variant_is_a_collision_too(self):
        """U+FB01 normalises to `fi` under NFKC, so `ﬁ-1.0.0.jar` and `fi-1.0.0.jar` are one name to an extractor that normalises."""
        d = self.path("nfkc")
        os.makedirs(d)
        for n in ("fi-1.0.0.jar", "ﬁ-1.0.0.jar"):
            put(d, n)
        res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        self.refused(res, COLLISION)
        self.coordinate("fi-1.0.0")
        put(self.target, "ﬁ-1.0.0.pom")
        self.refused(h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg]), COLLISION)

    def test_case_folding_is_full_case_folding_not_lower_casing(self):
        """`\u00df` folds to `ss`, which lower-casing leaves alone."""
        d = self.path("sharp-s")
        os.makedirs(d)
        for n in ("strasse-1.0.0.jar", "stra\u00dfe-1.0.0.jar", "ss-1.0.0.jar", "\u00df-1.0.0.jar"):
            put(d, n)
        res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        self.assertIn("::error::\u00df-1.0.0.jar and ss-1.0.0.jar are the same name under case folding or Unicode normalisation", res.errors())
        self.coordinate("ss-1.0.0")
        put(self.target, "\u00df-1.0.0.pom")
        gate = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])
        self.assertIn("::error::\u00df-1.0.0.pom and ss-1.0.0.pom are the same name under case folding or Unicode normalisation", gate.errors())

    def test_normalisation_is_compatibility_normalisation_beyond_what_case_folding_does(self):
        """NFKC maps `\u2460` to `1`, a full-width letter to its ASCII form and a decomposed accent to the precomposed one; case folding alone does none of that."""
        pairs = [("1-1.0.0.pom", "\u2460-1.0.0.pom"), ("a-1.0.0.pom", "\uff41-1.0.0.pom"), ("\u00e9-1.0.0.pom", "e\u0301-1.0.0.pom"),
                 ("k-1.0.0.pom", "\u212a-1.0.0.pom")]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                d = self.path(f"nf-{abs(hash(first))}")
                os.makedirs(d)
                for n in (first, second):
                    put(d, n)
                res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
                self.assertEqual(len(self.lines(res)), 1, res)
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.coordinate("m-1.0.0")
                for n in (first, second):
                    put(self.target, n)
                gate = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])
                self.assertEqual(len(self.lines(gate)), 1, gate)

    def test_case_folding_is_not_upper_casing_the_dotless_i_is_not_an_i(self):
        names = ("i-1.0.0.pom", "\u0131-1.0.0.pom")
        d = self.path("dotless")
        os.makedirs(d)
        for n in names:
            put(d, n)
        res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        self.assertEqual(self.lines(res), [])
        self.coordinate("m-1.0.0")
        for n in names:
            put(self.target, n)
        gate = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])
        self.assertEqual(self.lines(gate), [])
        self.assertTrue(any("not part of a release" in ln for ln in gate.errors()), "the gate did look at the names")

    def test_names_that_differ_only_in_their_last_character_are_not_a_collision(self):
        d = self.path("last")
        make_coordinate(d, "a-1.0.0")
        put(d, "a-1.0.0.pom.asd")
        res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        self.assertEqual(len(res.errors()), 2, res)
        self.assertTrue(res.errors()[0].startswith("::error::a-1.0.0.pom.asd is not part of a release"), res)
        self.assertEqual(res.errors()[1], FINAL)

    def test_three_names_that_fold_together_are_each_reported_against_the_first(self):
        names = ("fi-1.0.0.pom", "FI-1.0.0.pom", "\ufb01-1.0.0.pom")
        d = self.path("three")
        os.makedirs(d)
        for n in names:
            put(d, n)
        want = ["::error::fi-1.0.0.pom and FI-1.0.0.pom are the same name under case folding or Unicode normalisation",
                "::error::\ufb01-1.0.0.pom and FI-1.0.0.pom are the same name under case folding or Unicode normalisation"]
        res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d)))
        self.assertEqual(self.lines(res), want)
        self.coordinate("a-1.0.0")
        for n in names:
            put(self.target, n)
        gate = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg])
        self.assertEqual(self.lines(gate), want)

    def test_files_that_are_not_released_may_differ_by_case_only(self):
        """The gate judges the names it would release; a build directory holds many others."""
        self.coordinate("a-1.0.0")
        put(self.target, "Notes.txt")
        put(self.target, "notes.txt")
        os.makedirs(os.path.join(self.target, "Classes"))
        os.makedirs(os.path.join(self.target, "classes"))
        self.accepted(h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg]))

    def test_two_different_names_are_not_a_collision(self):
        self.coordinate("a-1.0.0")
        self.coordinate("b-1.0.0")
        self.accepted(h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg]))
        d = self.path("two")
        make_coordinate(d, "a-1.0.0")
        make_coordinate(d, "b-1.0.0")
        self.accepted(h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest_of(d))))

    def test_create_leaves_the_collision_to_verify_and_the_gate(self):
        d = self.path("pair")
        for base in ("a-1.0.0", "A-1.0.0"):
            make_coordinate(d, base)
        self.accepted(h.run_main(SCRIPT, ["create", "--dir", d, "--output", self.path("out")]))


class Upload(h.Case):
    """The real upload step, with a `mvn` that records its arguments, on every accepted base of a sample."""

    def bases(self):
        seen, out = set(), []
        for base in list(b.ACCEPTED) + [x for x in b.sample(20261113, 4000) if b.rule(x)]:
            key = base.casefold()
            if key not in seen and b.storable(base):
                seen.add(key)
                out.append(base)
            if len(out) >= 60:
                break
        return out

    def test_the_step_names_exactly_the_files_of_each_base_and_no_option_a_base_could_add(self):
        bases = self.bases()
        self.assertGreaterEqual(len(bases), 60)
        calls = job.upload_arguments(self, bases)
        self.assertEqual(len(calls), len(bases), "one deploy call for each pom")
        settings = os.path.join(self.path("runner"), "release-settings.xml")
        by_base = {}
        for argv in calls:
            pom = next(a for a in argv if a.startswith("-DpomFile="))[len("-DpomFile="):]
            by_base[pom[:-len(".pom")]] = argv
        self.assertEqual(set(by_base), set(bases))
        for base, argv in by_base.items():
            with self.subTest(base[:60]):
                job.assert_arguments_of(self, argv, base, settings)

    def test_the_longest_base_and_a_base_with_dots_dashes_and_underscores_are_whole_in_the_arguments(self):
        bases = [b.padded(200), "A.b-c_d-10.20.30", "a--keyring-1.0.0", "a--1.0.0"]
        calls = job.upload_arguments(self, bases)
        settings = os.path.join(self.path("runner"), "release-settings.xml")
        self.assertEqual(sorted(next(a for a in c if a.startswith("-DpomFile="))[len("-DpomFile="):-len(".pom")] for c in calls), sorted(bases))
        for argv in calls:
            base = next(a for a in argv if a.startswith("-DpomFile="))[len("-DpomFile="):-len(".pom")]
            job.assert_arguments_of(self, argv, base, settings)

    def test_a_base_that_starts_with_a_dash_is_refused_before_and_no_accepted_base_can_start_with_one(self):
        for base in ("-a-1.0.0", "--version-1.0.0", "-Dx=y-1.0.0"):
            self.assertFalse(b.rule(base))
            self.assertFalse(h.load(GATE).releasable_base(base))
            self.assertFalse(h.load(SCRIPT).releasable_base(base))
        for base in b.sample(20261114, 20000):
            if base.startswith("-"):
                self.assertFalse(b.rule(base), base)
        self.assertFalse(any(x.startswith("-") for x in b.ACCEPTED))


if __name__ == "__main__":
    unittest.main()
