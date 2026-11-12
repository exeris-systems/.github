"""The file set of the Central bundle is closed: per built coordinate the four files, their signatures and the checksums of those.

Names that a case-folding or normalising file system would merge are refused by name, a checksum file is a bounded one- or
two-token text, and nothing the build did not produce is released.
"""
from __future__ import annotations

import hashlib
import os
import unittest

import caps_release_helpers as h
from readiness_support import GROUP, Fixture, write_zip

S = "check_release_readiness"
GATED = "is not one of the gated files"
COLLIDE = "collide under case folding or Unicode normalisation"
ALGORITHMS = (".md5", ".sha1", ".sha256", ".sha512")


class Set(Fixture):
    artifact = "a"

    def setUp(self):
        super().setUp()
        self.real_coordinate(artifact=self.artifact)
        self.dir = f"eu/exeris/caps/{self.artifact}/1.0.0"
        self.stem = f"{self.artifact}-1.0.0"

    def entries(self, **kw):
        return self.bundle_entries(coords=((self.artifact, "1.0.0"),), **kw)

    def name(self, suffix):
        return f"{self.dir}/{self.stem}{suffix}"

    def judge(self, items):
        write_zip(self.bundle_path, list(items.items()) if isinstance(items, dict) else items)
        return h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"])

    def all_checksums(self):
        """Every gated file with all four checksums, which is the full set."""
        entries = self.entries()
        for n, data in list(entries.items()):
            if n.endswith(ALGORITHMS):
                continue
            for ext in ALGORITHMS:
                entries[n + ext] = hashlib.new(ext[1:], data).hexdigest().encode()
        return entries


class ClosedSet(Set):
    def test_the_full_set_of_thirty_two_files_is_accepted(self):
        entries = self.all_checksums()
        self.assertEqual(len(entries), 8 + 8 * 4)
        res = self.judge(entries)
        self.accepted(res)
        self.assertIn("central bundle: 40 file(s), 0 outside a coordinate", res.out)

    def test_a_subset_of_the_checksums_is_refused_and_each_missing_file_is_named(self):
        """All four checksum files of each of the eight files are required, not some of them."""
        for label, keep in (("md5 and sha1 only", (".md5", ".sha1")), ("sha512 only", (".sha512",)), ("one algorithm per file", None)):
            with self.subTest(label):
                full = self.all_checksums()
                entries = {n: d for n, d in full.items() if not n.endswith(ALGORITHMS)}
                for i, n in enumerate(sorted(entries)):
                    for ext in (keep if keep is not None else (ALGORITHMS[i % 4],)):
                        entries[n + ext] = full[n + ext]
                missing = sorted(set(full) - set(entries))
                self.assertTrue(missing)
                res = self.judge(entries)
                self.refused(res)
                for n in missing:
                    self.assertIn(f"central bundle: {self.dir} holds no {n.rpartition('/')[2]}", res.err)

    def test_a_bundle_without_any_checksum_is_refused(self):
        entries = {n: d for n, d in self.entries().items() if not n.endswith(ALGORITHMS)}
        self.assertEqual(len(entries), 8)
        self.refused(self.judge(entries))

    def test_each_of_the_eight_files_is_required_and_named_when_missing(self):
        for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom"):
            for extra in ("", ".asc"):
                with self.subTest(suffix + extra):
                    entries = self.all_checksums()
                    gone = self.name(suffix + extra)
                    for n in [n for n in entries if n == gone or n.startswith(gone + ".")]:
                        if n == gone or n.endswith(ALGORITHMS):
                            del entries[n]
                    res = self.judge(entries)
                    self.refused(res)

    def test_a_checksum_of_a_checksum_is_not_a_gated_file(self):
        for ext in ALGORITHMS:
            with self.subTest(ext):
                entries = self.all_checksums()
                entries[self.name(".jar.md5" + ext)] = hashlib.new(ext[1:], entries[self.name(".jar.md5")]).hexdigest().encode()
                self.refused(self.judge(entries), GATED)

    def test_a_signature_of_a_checksum_is_not_a_gated_file(self):
        entries = self.all_checksums()
        entries[self.name(".jar.md5.asc")] = b"x"
        self.refused(self.judge(entries), GATED)

    def test_a_checksum_of_a_file_the_bundle_does_not_hold_is_named(self):
        entries = self.all_checksums()
        for ext in ALGORITHMS:
            del entries[self.name(".jar" + ext)]
        entries[self.name("-extra.jar.md5")] = b"0" * 32
        self.refused(self.judge(entries), GATED)

    def test_a_checksum_of_a_missing_signature_is_a_finding_about_the_signature(self):
        entries = self.all_checksums()
        del entries[self.name(".jar.asc")]
        res = self.judge(entries)
        self.refused(res, f"holds no {self.stem}.jar.asc")

    def test_a_second_coordinate_is_refused_when_it_was_not_built(self):
        entries = self.all_checksums()
        for n, d in list(entries.items()):
            entries[n.replace("/a/", "/b/").replace("a-1.0.0", "b-1.0.0")] = d
        self.refused(self.judge(entries), "eu/exeris/caps/b/1.0.0 is a coordinate that was not built")

    def test_two_built_coordinates_need_two_complete_sets(self):
        self.real_coordinate(artifact="b")
        both = {**self.bundle_entries(coords=(("a", "1.0.0"), ("b", "1.0.0")))}
        self.accepted(self.judge(both))
        only_a = {n: d for n, d in both.items() if "/a/" in n}
        self.refused(self.judge(only_a), "it holds no coordinate for the built b-1.0.0")

    def test_a_file_of_the_right_name_under_the_wrong_depth_is_not_the_gated_file(self):
        for label, rename in (("one level up", lambda n: n.replace("/1.0.0/", "/", 1)),
                              ("one level down", lambda n: n.replace("/1.0.0/", "/1.0.0/sub/", 1)),
                              ("group shifted", lambda n: n.replace("eu/exeris/caps/", "exeris/caps/", 1)),
                              ("version directory renamed", lambda n: n.replace("/1.0.0/", "/1.0.1/", 1))):
            with self.subTest(label):
                entries = {rename(n): d for n, d in self.all_checksums().items()}
                self.refused(self.judge(entries))

    def test_a_duplicate_entry_name_is_refused_whatever_the_bytes(self):
        base = list(self.all_checksums().items())
        for victim in (self.name(".jar"), self.name(".jar.sha1"), self.name(".pom.asc")):
            for data in (dict(base)[victim], b"other"):
                with self.subTest(f"{victim} / {len(data)}"):
                    res = self.judge(base + [(victim, data)])
                    self.refused(res, f"{victim} occurs 2 times")


class Checksums(Set):
    def with_checksum(self, ext, content, of=".jar"):
        entries = self.entries()
        entries[self.name(of + ext)] = content
        return entries

    def digest(self, ext, of=".jar"):
        return hashlib.new(ext[1:], self.entries()[self.name(of)]).hexdigest()

    def test_one_token_and_two_token_forms_are_accepted(self):
        for ext in ALGORITHMS:
            d = self.digest(ext)
            for label, text in (("digest", d), ("digest and newline", d + "\n"), ("upper case", d.upper()),
                                ("digest and name", f"{d}  {self.stem}.jar\n"), ("binary marker", f"{d} *{self.stem}.jar"),
                                ("tab", f"{d}\t{self.stem}.jar"), ("leading space", f"  {d}\n"), ("padding to the bound", d + "\n" * (4096 - len(d)))):
                with self.subTest(f"{ext} {label}"):
                    self.accepted(self.judge(self.with_checksum(ext, text.encode())))

    def test_every_other_form_is_refused(self):
        d = self.digest(".sha256")
        wrong = "0" * 64
        cases = {
            "empty": "", "whitespace only": " \n", "wrong digest": wrong, "a digest of the wrong length": d[:-1],
            "three tokens": f"{d} {self.stem}.jar extra", "wrong file name": f"{d}  other.jar",
            "a path as name": f"{d}  {self.dir}/{self.stem}.jar", "digest after name": f"{self.stem}.jar {d}",
            "over the bound": d + " " * 4096, "one past the bound": d + "\n" * (4097 - len(d)),
            "non-ascii": d[:-1] + "é", "nul": d + "\0", "hex with a prefix": "0x" + d, "bom": "﻿" + d,
        }
        for label, text in cases.items():
            with self.subTest(label):
                res = self.judge(self.with_checksum(".sha256", text.encode("utf-8")))
                self.refused(res, f"{self.name('.jar.sha256')} does not match {self.stem}.jar")

    def test_a_name_with_two_leading_stars_is_not_the_file_name(self):
        d = self.digest(".sha256")
        self.refused(self.judge(self.with_checksum(".sha256", f"{d} **{self.stem}.jar".encode())), "does not match")

    def test_the_program_and_the_process_agree_on_a_checksum_refusal(self):
        write_zip(self.bundle_path, list(self.with_checksum(".md5", b"0" * 32).items()))
        self.refused(self.check("--expect-bundle", "true"), "does not match")

    def test_the_digest_must_belong_to_the_algorithm_of_the_file(self):
        for ext, other in ((".md5", ".sha1"), (".sha1", ".sha256"), (".sha256", ".sha512"), (".sha512", ".md5")):
            with self.subTest(ext):
                self.refused(self.judge(self.with_checksum(ext, self.digest(other).encode())), "does not match")

    def test_a_checksum_of_each_gated_file_is_checked_against_that_file(self):
        full = self.entries()
        for of in (".jar", "-sources.jar", "-javadoc.jar", ".pom", ".jar.asc", ".pom.asc"):
            with self.subTest(of):
                good = hashlib.sha256(full[self.name(of)]).hexdigest()
                self.accepted(self.judge({**full, self.name(of + ".sha256"): good.encode()}))
                self.refused(self.judge({**full, self.name(of + ".sha256"): ("0" * 64).encode()}), "does not match")

    def test_a_checksum_of_the_wrong_file_is_refused(self):
        sources = hashlib.md5(self.entries()[self.name("-sources.jar")]).hexdigest()
        self.refused(self.judge(self.with_checksum(".md5", sources.encode())), "does not match")


class Folding(Set):
    artifact = "file"

    def pair(self, original_suffix, variant_name, data=b"x"):  # noqa: the suffix names the file the variant imitates
        entries = self.all_checksums()
        entries[variant_name] = data
        return entries

    def test_a_ligature_a_fullwidth_letter_and_a_case_variant_collide_with_the_file_they_imitate(self):
        d, s = self.dir, self.stem
        for label, name in (("ligature fi", f"{d}/ﬁle-1.0.0.jar".replace("ﬁle", "ﬁle")),
                            ("fullwidth i", f"{d}/fｉle-1.0.0.jar"), ("upper case", f"{d}/{s}.JAR"),
                            ("title case", f"{d}/File-1.0.0.jar")):
            with self.subTest(label):
                res = self.judge(self.pair(".jar", name))
                self.refused(res, COLLIDE)
                self.assertIn(self.name(".jar"), "\n".join(res.errors()))

    def test_a_directory_and_a_file_with_the_same_fold_collide(self):
        entries = self.all_checksums()
        jar = self.name(".jar")
        items = list(entries.items()) + [(jar + "/", b"")]
        res = self.judge(items)
        self.refused(res, COLLIDE)
        self.assertIn(jar + "/", "\n".join(res.errors()))

    def test_a_directory_that_shadows_a_file_with_a_payload_is_one_finding_more(self):
        items = list(self.all_checksums().items()) + [(self.name(".pom") + "/", b"payload")]
        res = self.judge(items)
        self.refused(res, "is a directory entry that carries a payload")
        self.assertIn(COLLIDE, "\n".join(res.errors()))


class FoldingElsewhere(Set):
    """Variants of a name that are not file names of a coordinate: refused as strays, and as a pair when their fold agrees."""

    artifact = "kit"

    def test_kelvin_sign_collides_with_k(self):
        d, s = self.dir, self.stem
        entries = self.all_checksums()
        entries[f"{d}/Kit-1.0.0.jar"] = b"x"
        self.refused(self.judge(entries), COLLIDE)

    def test_a_sharp_s_collides_with_ss(self):
        self.tearDown_target()
        self.real_coordinate(artifact="strasse")
        entries = self.bundle_entries(coords=(("strasse", "1.0.0"),))
        entries["eu/exeris/caps/strasse/1.0.0/straße-1.0.0.jar"] = b"x"
        self.refused(self.judge(entries), COLLIDE)

    def tearDown_target(self):
        import shutil
        shutil.rmtree(self.target)
        os.makedirs(self.target)

    def test_combining_and_precomposed_forms_collide_with_each_other(self):
        d = self.dir
        entries = self.all_checksums()
        entries[f"{d}/café.txt"] = b"x"
        entries[f"{d}/café.txt"] = b"x"
        res = self.judge(entries)
        self.refused(res, COLLIDE)

    def test_turkish_dotted_and_dotless_i_are_refused_as_strays_though_their_fold_differs(self):
        d = self.dir
        for label, name in (("dotless i", f"{d}/kıt-1.0.0.jar"), ("capital dotted I", f"{d}/kİt-1.0.0.jar"),
                            ):
            with self.subTest(label):
                entries = self.all_checksums()
                entries[name] = b"x"
                res = self.judge(entries)
                self.refused(res, "is not a file of a published coordinate")
                self.assertNotIn(COLLIDE, "\n".join(res.errors()))


if __name__ == "__main__":
    unittest.main()
