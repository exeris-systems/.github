"""check_release_readiness: completeness and signatures of the built files (a gpg double and real gpg)."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

import caps_release_helpers as h
from readiness_support import Fixture, GROUP, make_zip, pom_xml, sig_of

S = "check_release_readiness"


class Complete(Fixture):
    def test_a_complete_signed_coordinate(self):
        self.coordinate()
        res = self.check()
        self.accepted(res)
        self.assertIn("coordinate: a-1.0.0 - main, sources, javadoc, pom, signatures", res.out)
        self.assertIn("release-readiness: ok", res.out)

    def test_two_coordinates_are_both_gated(self):
        self.coordinate("a-1.0.0")
        self.coordinate("b-1.0.0")
        self.accepted(self.check())
        os.remove(os.path.join(self.target, "b-1.0.0.pom"))
        res = self.check()
        self.refused(res, "b-1.0.0 is missing b-1.0.0.pom")

    def test_one_bad_coordinate_among_good_ones_fails_the_gate(self):
        self.coordinate("a-1.0.0")
        self.coordinate("b-1.0.0")
        os.remove(os.path.join(self.target, "b-1.0.0-sources.jar.asc"))
        res = self.check()
        self.refused(res, "b-1.0.0-sources.jar has no detached signature")
        self.assertIn("coordinate: a-1.0.0", res.out)
        self.assertNotIn("coordinate: b-1.0.0", res.out)

    def test_no_main_jar_is_fatal_at_once(self):
        self.assertEqual(self.check().rc, 1)
        make_zip(os.path.join(self.target, "a-1.0.0-sources.jar"), ["x"])
        make_zip(os.path.join(self.target, "a-1.0.0-javadoc.jar"), ["index.html"])
        make_zip(os.path.join(self.target, "a-1.0.0-tests.jar"), ["x"])
        os.makedirs(os.path.join(self.target, "dir.jar"))
        res = self.check()
        self.refused(res, "no main jar")
        self.assertEqual(len(res.errors()), 1)

    def test_unreadable_target_dir(self):
        res = self.both(S, ["--target-dir", self.path("absent"), "--gpg", self.gpg])
        self.refused(res, "cannot be read")

    def test_missing_parts_are_each_named(self):
        for part in ("-sources.jar", "-javadoc.jar", ".pom"):
            with self.subTest(part):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.coordinate(skip=(part,))
                res = self.check()
                self.refused(res, f"a-1.0.0 is missing a-1.0.0{part}")

    def test_every_finding_is_reported_before_the_gate_fails(self):
        self.coordinate(skip=("-sources.jar", ".pom"))
        os.remove(os.path.join(self.target, "a-1.0.0.jar.asc"))
        res = self.check()
        self.refused(res)
        text = "\n".join(res.errors())
        for frag in ("missing a-1.0.0-sources.jar", "missing a-1.0.0.pom", "a-1.0.0.jar has no detached signature",
                     "release-readiness failed"):
            self.assertIn(frag, text)

    def test_snapshot_main_jar_is_refused(self):
        self.coordinate("a-1.0.0-SNAPSHOT")
        self.refused(self.check(), "is a SNAPSHOT")

    def test_javadoc_without_a_root_index(self):
        for label, names in (("none", ["a/B.html"]), ("subdirectory", ["docs/index.html"]), ("empty", []),
                             ("case", ["Index.html"]), ("leading dot", ["./index.html"])):
            with self.subTest(label):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.coordinate(javadoc_names=names)
                self.refused(self.check(), "holds no index.html")

    def test_javadoc_that_is_not_a_zip(self):
        self.coordinate()
        javadoc = os.path.join(self.target, "a-1.0.0-javadoc.jar")
        with open(javadoc, "w") as fh:
            fh.write("not a zip")
        with open(javadoc + ".asc", "w") as fh:
            fh.write(sig_of(javadoc))
        res = self.check()
        self.refused(res, "a-1.0.0-javadoc.jar is not a zip file")
        self.assertNotIn("unexpectedly", res.err)

    def test_a_missing_signature_for_each_file(self):
        for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom"):
            with self.subTest(suffix):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.coordinate()
                os.remove(os.path.join(self.target, f"a-1.0.0{suffix}.asc"))
                self.refused(self.check(), f"a-1.0.0{suffix} has no detached signature")

    def test_a_signature_that_does_not_verify_for_each_file(self):
        for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom"):
            with self.subTest(suffix):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.coordinate()
                with open(os.path.join(self.target, f"a-1.0.0{suffix}.asc"), "w") as fh:
                    fh.write("garbage\n")
                self.refused(self.check(), f"a-1.0.0{suffix}.asc is not a good signature")

    def test_a_signature_of_a_different_file_is_refused(self):
        self.coordinate()
        t = self.target
        with open(os.path.join(t, "a-1.0.0.jar.asc"), "w") as fh:         # the sources jar's signature
            fh.write(sig_of(os.path.join(t, "a-1.0.0-sources.jar")))
        self.refused(self.check(), "a-1.0.0.jar.asc is not a good signature")

    def test_a_signature_made_before_the_file_changed_is_refused(self):
        self.coordinate()
        with open(os.path.join(self.target, "a-1.0.0.pom"), "a") as fh:
            fh.write("<!-- changed after signing -->")
        self.refused(self.check(), "a-1.0.0.pom.asc is not a good signature")

    def test_a_directory_in_place_of_a_signature_is_no_signature(self):
        self.coordinate()
        asc = os.path.join(self.target, "a-1.0.0.jar.asc")
        os.remove(asc)
        os.makedirs(asc)
        self.refused(self.check(), "has no detached signature")

    def test_gpg_is_asked_to_verify_each_file_against_its_own_signature(self):
        self.coordinate("a-1.0.0")
        self.coordinate("b-2.0.0")
        res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(FAKE_GPG_LOG=self.log))
        self.accepted(res)
        with open(self.log) as fh:
            calls = [ln.rstrip("\n").split("\t") for ln in fh]
        t = self.target
        expected = []
        for base in ("a-1.0.0", "b-2.0.0"):
            for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom"):
                f = os.path.join(t, base + suffix)
                expected.append((base + suffix + ".asc", base + suffix, hashlib.sha256(self.read_target(base + suffix)).hexdigest()))
        # gpg is handed the gate's private copies (same base names, same bytes), never the live files
        got = sorted((os.path.basename(c[1]), os.path.basename(c[2]), c[3]) for c in calls)
        self.assertEqual(got, sorted(expected))
        for call in calls:
            self.assertEqual(call[0], "--verify")
            self.assertEqual(os.path.basename(call[1]), os.path.basename(call[2]) + ".asc")
            self.assertTrue(os.path.isabs(call[1]) and os.path.isabs(call[2]))
            self.assertNotEqual(os.path.dirname(call[2]), t, "gpg is not handed the live file")
            self.assertNotEqual(os.path.dirname(call[1]), t)

    def test_gpg_is_not_asked_about_a_file_that_has_no_signature_or_does_not_exist(self):
        self.coordinate(skip=(".pom",))
        os.remove(os.path.join(self.target, "a-1.0.0.jar.asc"))
        res = h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg], env=h.clean_env(FAKE_GPG_LOG=self.log))
        self.refused(res)
        with open(self.log) as fh:
            calls = [ln.rstrip("\n").split("\t") for ln in fh]
        self.assertEqual(len(calls), 2)
        self.assertFalse(any(c[2].endswith(".pom") or c[2].endswith("a-1.0.0.jar") for c in calls))

    def test_a_gpg_that_cannot_run_makes_every_signature_bad(self):
        self.coordinate()
        res = self.both(S, ["--target-dir", self.target, "--gpg", self.path("no-such-gpg")])
        self.refused(res, "is not a good signature")
        self.assertEqual(len([e for e in res.errors() if "not a good signature" in e]), 4)

    def test_usage(self):
        self.assertEqual(h.run_proc(S, []).rc, 2)
        for flag in ("--expect-bundle", "--uploaded"):
            with self.subTest(flag):
                self.assertEqual(h.run_proc(S, ["--target-dir", self.target, flag, "true"]).rc, 2)
                self.assertEqual(h.run_main(S, ["--target-dir", self.target, flag, "true"]).rc, 2)

    # --- gaps ---------------------------------------------------------------------------------

    def test_an_unsigned_tests_jar_beside_a_signed_coordinate_is_refused(self):
        self.coordinate()
        make_zip(os.path.join(self.target, "a-1.0.0-tests.jar"), ["T.class"])
        self.refused(self.check())

    def test_a_snapshot_sources_jar_is_refused(self):
        self.coordinate()
        make_zip(os.path.join(self.target, "a-1.0.0-SNAPSHOT-sources.jar"), ["x"])
        self.refused(self.check())

    def test_a_timestamped_snapshot_main_jar_is_refused(self):
        self.coordinate("a-1.0-20260101.120000-1")
        self.refused(self.check())

    def test_a_symlinked_main_jar_is_refused(self):
        self.coordinate()
        outside = self.path("outside.jar")
        os.rename(os.path.join(self.target, "a-1.0.0.jar"), outside)
        os.symlink(outside, os.path.join(self.target, "a-1.0.0.jar"))
        with open(os.path.join(self.target, "a-1.0.0.jar.asc"), "w") as fh:
            fh.write(sig_of(outside))
        self.refused(self.check())


@unittest.skipUnless(h.have_gpg(), "gpg is not installed")
class RealGpg(h.Case):
    """The same checks with the real gpg binary and keys generated here, in a temporary keyring."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="crg-")
        os.chmod(cls.home, 0o700)
        cls.other = tempfile.mkdtemp(prefix="crg-")
        os.chmod(cls.other, 0o700)
        cls.env = h.clean_env(GNUPGHOME=cls.home)
        done = subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key",
                               "Throwaway <t@invalid>", "ed25519", "sign", "1d"], env=cls.env, capture_output=True)
        if done.returncode != 0:
            cls.tearDownClass()
            raise unittest.SkipTest("gpg cannot generate a key here: " + done.stderr.decode(errors="replace"))

    @classmethod
    def tearDownClass(cls):
        for d in (cls.home, cls.other):
            subprocess.run(["gpgconf", "--homedir", d, "--kill", "gpg-agent"], capture_output=True)
            shutil.rmtree(d, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.target = self.path("target")
        os.makedirs(self.target)

    def sign(self, f, as_name=None):
        out = (as_name or f) + ".asc"
        subprocess.run(["gpg", "--batch", "--armor", "--pinentry-mode", "loopback", "--passphrase", "", "--detach-sign",
                        "--yes", "-o", out, f], env=self.env, check=True, capture_output=True)

    def coordinate(self, base="a-1.0.0"):
        t = self.target
        make_zip(os.path.join(t, f"{base}.jar"), ["a/B.class"])
        make_zip(os.path.join(t, f"{base}-sources.jar"), ["a/B.java"])
        make_zip(os.path.join(t, f"{base}-javadoc.jar"), ["index.html"])
        with open(os.path.join(t, f"{base}.pom"), "w") as fh:
            fh.write(pom_xml(GROUP, "a", "1.0.0"))
        for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom"):
            self.sign(os.path.join(t, base + suffix))

    def run_check(self, env=None):
        return h.run_main(S, ["--target-dir", self.target], env=env or self.env)

    def test_good_signatures(self):
        self.coordinate()
        self.accepted(self.run_check())

    def test_the_default_gpg_is_looked_up_on_path(self):
        self.coordinate()
        self.accepted(h.run_proc(S, ["--target-dir", self.target], env=self.env))

    def test_a_signature_of_another_file_is_refused(self):
        self.coordinate()
        t = self.target
        shutil.copy(os.path.join(t, "a-1.0.0-sources.jar.asc"), os.path.join(t, "a-1.0.0.jar.asc"))
        self.refused(self.run_check(), "a-1.0.0.jar.asc is not a good signature")

    def test_a_file_changed_after_signing_is_refused(self):
        self.coordinate()
        with open(os.path.join(self.target, "a-1.0.0.pom"), "a") as fh:
            fh.write("<!-- x -->")
        self.refused(self.run_check(), "a-1.0.0.pom.asc is not a good signature")

    def test_empty_and_garbage_signatures_are_refused(self):
        for body in ("", "-----BEGIN PGP SIGNATURE-----\n\n-----END PGP SIGNATURE-----\n", "x"):
            with self.subTest(body[:10]):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.coordinate()
                with open(os.path.join(self.target, "a-1.0.0-javadoc.jar.asc"), "w") as fh:
                    fh.write(body)
                self.refused(self.run_check(), "a-1.0.0-javadoc.jar.asc is not a good signature")

    def test_a_signature_by_a_key_the_keyring_does_not_hold_is_refused(self):
        self.coordinate()
        self.refused(self.run_check(h.clean_env(GNUPGHOME=self.other)), "is not a good signature")
        subprocess.run(["gpgconf", "--homedir", self.other, "--kill", "gpg-agent"], capture_output=True)


if __name__ == "__main__":
    unittest.main()
