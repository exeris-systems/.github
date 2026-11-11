"""check_release_readiness: completeness, signatures (a gpg double and real gpg), and the Central bundle."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
import zipfile

import caps_release_helpers as h

S = "check_release_readiness"

FAKE_GPG = """#!/bin/sh
if [ -n "$FAKE_GPG_LOG" ]; then printf '%s\\t%s\\t%s\\n' "$1" "$2" "$3" >> "$FAKE_GPG_LOG"; fi
[ $# -eq 3 ] && [ "$1" = "--verify" ] || exit 2
want="SIG:$(sha256sum "$3" | cut -d' ' -f1)"
[ "$(cat "$2")" = "$want" ]
"""


def sig_of(path):
    with open(path, "rb") as fh:
        return "SIG:" + hashlib.sha256(fh.read()).hexdigest() + "\n"


def make_zip(path, names, payload=b"x"):
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, payload)


class Fixture(h.Case):
    """A target/ directory and a gpg double that accepts a signature only of the file it is handed."""

    def setUp(self):
        super().setUp()
        self.target = self.path("target")
        os.makedirs(self.target)
        self.gpg = self.write("fake-gpg", FAKE_GPG)
        os.chmod(self.gpg, 0o755)
        self.log = self.path("gpg.log")

    def coordinate(self, base="a-1.0.0", sign=True, skip=(), javadoc_names=("index.html", "a/B.html")):
        t = self.target
        make_zip(os.path.join(t, f"{base}.jar"), ["a/B.class"])
        make_zip(os.path.join(t, f"{base}-sources.jar"), ["a/B.java"])
        make_zip(os.path.join(t, f"{base}-javadoc.jar"), list(javadoc_names))
        with open(os.path.join(t, f"{base}.pom"), "w") as fh:
            fh.write(f"<project>{base}</project>")
        for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom"):
            f = os.path.join(t, base + suffix)
            if suffix in skip:
                os.remove(f)
            elif sign:
                with open(f + ".asc", "w") as fh:
                    fh.write(sig_of(f))
        return base

    def bundle(self, names, payload=b"x"):
        os.makedirs(os.path.join(self.target, "central-publishing"), exist_ok=True)
        make_zip(os.path.join(self.target, "central-publishing", "central-bundle.zip"), names, payload)

    @staticmethod
    def good_bundle(g="eu/exeris/caps", a="a", v="1.0.0"):
        d = f"{g}/{a}/{v}/{a}-{v}"
        return [f"{d}.pom", f"{d}.jar", f"{d}-sources.jar", f"{d}-javadoc.jar", f"{d}.pom.asc", f"{d}.jar.asc",
                f"{d}.jar.md5", f"{d}.jar.sha1", f"{d}-sources.jar.asc", f"{d}-javadoc.jar.asc", f"{d}.module"]

    def check(self, *extra):
        return self.both(S, ["--target-dir", self.target, "--gpg", self.gpg, *extra])


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
        self.refused(self.check(), "is not a zip file")

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
                expected.append(["--verify", f + ".asc", f])
        self.assertEqual(sorted(calls), sorted(expected))
        for call in calls:
            self.assertEqual(call[1], call[2] + ".asc")

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

    def test_expect_bundle_default_is_false(self):
        self.coordinate()
        self.accepted(self.check())
        self.accepted(self.check("--expect-bundle", "false"))

    def test_uploaded_changes_the_final_refusal(self):
        self.coordinate(skip=(".pom",))
        self.assertIn("DROP it", self.check("--uploaded").errors()[-1])
        self.assertNotIn("DROP", self.check().errors()[-1])

    def test_usage(self):
        self.assertEqual(h.run_proc(S, []).rc, 2)
        self.assertEqual(h.run_proc(S, ["--target-dir", self.target, "--expect-bundle", "maybe"]).rc, 2)

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


class Bundle(Fixture):
    def setUp(self):
        super().setUp()
        self.coordinate()

    def test_a_clean_bundle(self):
        self.bundle(self.good_bundle())
        res = self.check("--expect-bundle", "true")
        self.accepted(res)
        self.assertIn("central bundle: 11 file(s), 0 outside a coordinate", res.out)

    def test_directory_entries_are_allowed(self):
        self.bundle(["eu/", "eu/exeris/", "eu/exeris/caps/a/1.0.0/"] + self.good_bundle())
        self.accepted(self.check("--expect-bundle", "true"))

    def test_bundle_expected_but_missing_or_not_a_zip(self):
        self.refused(self.check("--expect-bundle", "true"), "central-bundle.zip is missing")
        os.makedirs(os.path.join(self.target, "central-publishing"))
        with open(os.path.join(self.target, "central-publishing", "central-bundle.zip"), "w") as fh:
            fh.write("nope")
        self.refused(self.check("--expect-bundle", "true"), "is not a zip file")

    def test_a_bundle_nobody_expects_is_not_read(self):
        self.bundle(["stray.txt"])
        self.accepted(self.check("--expect-bundle", "false"))
        self.accepted(self.check())

    def test_stray_entries_are_each_named(self):
        base = self.good_bundle()
        d = "eu/exeris/caps/a/1.0.0"
        strays = {
            "top level": "README.md",
            "wrong depth": "a/1.0.0/a-1.0.0.pom",
            "other artifact name": f"{d}/other-1.0.0.jar",
            "other version in the name": f"{d}/a-1.0.1.jar",
            "prefix only": f"{d}/a-1.0.0x.jar",
            "no separator": f"{d}/a-1.0.0jar",
            "dot file": f"{d}/.hidden",
            "own directory missing pom": "eu/exeris/caps/b/2.0.0/b-2.0.0.jar",
            "parent traversal": "../x",
            "traversal beside": f"{d}/../x",
            "empty name": "x/",
        }
        for label, name in strays.items():
            if name.endswith("/"):
                continue
            with self.subTest(label):
                self.bundle(base + [name])
                res = self.check("--expect-bundle", "true")
                self.refused(res, f"central bundle: {name} is not a file of a published coordinate")

    def test_a_coordinate_whose_pom_is_missing_is_all_stray(self):
        names = [n for n in self.good_bundle() if not n.endswith(".pom")]
        self.bundle(names)
        res = self.check("--expect-bundle", "true")
        self.refused(res)
        self.assertGreaterEqual(len([e for e in res.errors() if "is not a file of a published coordinate" in e]), len(names))

    def test_a_pom_of_another_version_does_not_make_the_files_belong(self):
        d = "eu/exeris/caps/a/1.0.0"
        self.bundle([f"{d}/a-1.0.0.jar", "eu/exeris/caps/a/0.9.0/a-0.9.0.pom"])
        self.refused(self.check("--expect-bundle", "true"), f"{d}/a-1.0.0.jar")

    def test_a_zip_bomb_is_listed_not_expanded(self):
        names = self.good_bundle()
        os.makedirs(os.path.join(self.target, "central-publishing"), exist_ok=True)
        path = os.path.join(self.target, "central-publishing", "central-bundle.zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for n in names:
                z.writestr(n, b"x")
            z.writestr("eu/exeris/caps/a/1.0.0/a-1.0.0.bomb", b"\0" * (100 * 1024 * 1024))
        start = time.monotonic()
        res = self.check("--expect-bundle", "true")
        self.accepted(res)
        self.assertLess(time.monotonic() - start, 20)

    def test_bundle_refusal_with_uploaded(self):
        self.bundle(self.good_bundle() + ["x.txt"])
        self.assertIn("DROP it", self.check("--expect-bundle", "true", "--uploaded").errors()[-1])

    # --- gaps ---------------------------------------------------------------------------------

    def test_entries_that_escape_the_bundle_root_are_stray(self):
        base = self.good_bundle()
        for evil in ("g/../../..-...pom", "/abs/a/1.0.0/a-1.0.0.pom"):
            with self.subTest(evil):
                self.bundle(base + [evil])
                self.refused(self.check("--expect-bundle", "true"))

    def test_a_bundle_for_a_different_coordinate_than_the_one_built_is_refused(self):
        self.bundle(self.good_bundle(a="other", v="9.9.9"))
        self.refused(self.check("--expect-bundle", "true"))

    def test_duplicate_entries_in_the_bundle_are_refused(self):
        names = self.good_bundle()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.bundle(names + [names[1]])
        self.refused(self.check("--expect-bundle", "true"))


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
            fh.write("<project/>")
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
