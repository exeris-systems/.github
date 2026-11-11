"""The Central bundle against hostile input: bound to the build, bounded in size, and judged by its central directory."""
from __future__ import annotations

import hashlib
import os
import shutil
import resource
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib

import caps_release_helpers as h
from caps_release_helpers import known_defect
from readiness_support import GROUP, Fixture, deflate_zeros, pom_xml, raw_zip, sig_bytes, sig_of, write_zip

S = "check_release_readiness"
D = "eu/exeris/caps/a/1.0.0"
STEM = "a-1.0.0"


class Bundle(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()
        self.tmp_listing = self.scratch()

    @staticmethod
    def scratch():
        return {n for n in os.listdir(tempfile.gettempdir()) if n.startswith("bundle-verify-")}

    def entries(self, **kw):
        return self.bundle_entries(**kw)

    def judge(self, entries, fragment=None, proc=True):
        """Write the bundle, judge it within a time bound, and require that nothing was written to disk."""
        self.write_bundle(entries) if isinstance(entries, dict) else write_zip(self.bundle_path, entries)
        before = self.tree()
        start = time.monotonic()
        res = self.check("--expect-bundle", "true") if proc else h.run_main(
            S, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"])
        self.assertLess(time.monotonic() - start, 20)
        self.assertEqual(self.tree(), before, "the gate extracts nothing into the tree")
        self.assertEqual(self.scratch() - self.tmp_listing, set(), "the verification scratch directory is removed")
        if fragment is None:
            return res
        self.refused(res, fragment)
        return res

    def named(self, name):
        return f"{D}/{STEM}{name}"


class Binding(Bundle):
    def test_the_correct_bundle_passes_with_every_digest_algorithm_checked(self):
        entries = self.entries()
        self.assertEqual(sum(1 for n in entries if n.endswith((".md5", ".sha1", ".sha256", ".sha512"))), 4)
        self.accepted(self.judge(entries))

    def test_the_wrong_group_path_is_refused(self):
        for group in ("eu.exeris", "eu.exeris.other", "eu.exeris.caps.sub", "EU.exeris.caps", "org.attacker"):
            with self.subTest(group):
                self.judge(self.entries(group=group), f"is not under the group {GROUP}", proc=False)

    def test_a_foreign_coordinate_alone_is_refused(self):
        entries = {n.replace("/a/", "/zzz/").replace("a-1.0.0", "zzz-1.0.0"): d for n, d in self.entries().items()}
        res = self.judge(entries, "is a coordinate that was not built")
        self.assertIn("it holds no coordinate for the built a-1.0.0", "\n".join(res.errors()))

    def test_a_foreign_coordinate_beside_the_right_one_is_refused(self):
        entries = self.entries()
        for n, d in list(entries.items()):
            entries[n.replace("/a/", "/zzz/").replace("a-1.0.0", "zzz-1.0.0")] = d
        res = self.judge(entries, "eu/exeris/caps/zzz/1.0.0 is a coordinate that was not built")
        self.assertNotIn("holds no", "\n".join(res.errors()))

    def test_a_foreign_version_of_the_built_artifact_is_refused(self):
        entries = self.entries()
        for n, d in list(entries.items()):
            entries[n.replace("/1.0.0/", "/9.9.9/").replace("a-1.0.0", "a-9.9.9")] = d
        self.judge(entries, "a-9.9.9 is a coordinate that was not built" if False else "eu/exeris/caps/a/9.9.9 is a coordinate that was not built")

    def test_the_same_coordinate_in_two_directories_is_refused(self):
        entries = self.entries()
        for n, d in list(entries.items()):
            entries["org/evil/" + n.split("/", 3)[3]] = d
        self.judge(entries, "a-1.0.0 is in 2 directories")

    def test_a_missing_built_coordinate_is_refused(self):
        self.real_coordinate(artifact="b", version="2.0.0")
        entries = self.bundle_entries(coords=(("a", "1.0.0"),))
        self.judge(entries, "it holds no coordinate for the built b-2.0.0")

    def test_each_required_file_missing_alone_is_named(self):
        for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom"):
            for extra in ("", ".asc"):
                name = self.named(suffix + extra)
                with self.subTest(name):
                    entries = self.entries()
                    del entries[name]
                    if suffix == ".jar" and not extra:
                        for ext in (".md5", ".sha1", ".sha256", ".sha512", ".asc"):
                            entries.pop(name + ext, None)
                    res = self.judge(entries, None, proc=False)
                    self.refused(res)
                    if suffix == ".pom" and not extra:
                        self.assertIn("it holds no coordinate for the built a-1.0.0", "\n".join(res.errors()))
                    else:
                        self.assertIn(f"holds no {STEM}{suffix}{extra}", "\n".join(res.errors()))

    def test_one_changed_byte_in_each_file_kind_is_refused(self):
        for suffix in (".jar", "-sources.jar", "-javadoc.jar", ".pom", ".jar.asc", "-sources.jar.asc", "-javadoc.jar.asc", ".pom.asc"):
            with self.subTest(suffix):
                entries = self.entries()
                name = self.named(suffix)
                data = bytearray(entries[name])
                data[len(data) // 2] ^= 0x01
                entries[name] = bytes(data)
                res = self.judge(entries, f"{name} differs from target/{STEM}{suffix}", proc=False)
                if not suffix.endswith(".asc"):
                    self.assertIn("is not a good signature of the bundle's own file", "\n".join(res.errors()))

    def test_one_changed_byte_in_a_checksum_file_is_refused(self):
        for ext in (".md5", ".sha1", ".sha256", ".sha512"):
            with self.subTest(ext):
                entries = self.entries()
                name = self.named(".jar" + ext)
                value = entries[name].decode()
                entries[name] = (("0" if value[0] != "0" else "1") + value[1:]).encode()
                self.judge(entries, f"{name} does not match {STEM}.jar", proc=False)

    def test_a_signature_that_verifies_a_different_file_is_refused(self):
        entries = self.entries()
        entries[self.named(".jar.asc")] = entries[self.named("-sources.jar.asc")]
        res = self.judge(entries, f"{self.named('.jar.asc')} differs from target/{STEM}.jar.asc")
        self.assertIn("is not a good signature of the bundle's own file", "\n".join(res.errors()))

    def test_a_signature_valid_for_the_bundle_file_but_not_the_built_one_is_refused(self):
        """The jar and its signature were replaced together in the bundle: the signature verifies, the bytes are not the build's."""
        entries = self.entries()
        evil = b"PK-evil-jar"
        entries[self.named(".jar")] = evil
        entries[self.named(".jar.asc")] = sig_bytes(evil)
        for ext, algo in ((".md5", "md5"), (".sha1", "sha1"), (".sha256", "sha256"), (".sha512", "sha512")):
            entries[self.named(".jar" + ext)] = hashlib.new(algo, evil).hexdigest().encode()
        res = self.judge(entries, f"{self.named('.jar')} differs from target/{STEM}.jar")
        self.assertNotIn("not a good signature", "\n".join(res.errors()))
        self.assertNotIn("does not match", "\n".join(res.errors()))

    def test_checksum_forms(self):
        jar = self.named(".jar")
        digest = hashlib.sha1(self.read_target(f"{STEM}.jar")).hexdigest()
        wrong = ("0" if digest[0] != "0" else "1") + digest[1:]
        forms = {
            "bare hex": (digest.encode(), True), "bare hex and newline": (digest.encode() + b"\n", True),
            "digest two spaces filename": (f"{digest}  {STEM}.jar\n".encode(), True),
            "digest star filename": (f"{digest} *{STEM}.jar\n".encode(), True),
            "upper case hex": (digest.upper().encode(), True),
            "wrong bare hex": (wrong.encode(), False), "wrong digest and filename": (f"{wrong}  {STEM}.jar\n".encode(), False),
            "filename first": (f"{STEM}.jar {digest}\n".encode(), False),
            "empty": (b"", False), "only whitespace": (b" \n\n", False), "truncated": (digest[:-1].encode(), False),
            "prefixed": (b"sha1:" + digest.encode(), False),
        }
        for label, (content, ok) in forms.items():
            with self.subTest(label):
                entries = self.entries()
                entries[jar + ".sha1"] = content
                res = self.judge(entries, None, proc=False)
                if ok:
                    self.accepted(res)
                else:
                    self.refused(res, f"{jar}.sha1 does not match {STEM}.jar")

    def test_a_checksum_or_signature_whose_subject_is_absent_is_refused(self):
        digest = hashlib.sha1(b"x").hexdigest().encode()
        for name, fragment in ((self.named("-extra.jar.sha1"), "is a checksum of a-1.0.0-extra.jar, which the bundle does not hold"),
                               (self.named(".module.md5"), "is a checksum of a-1.0.0.module, which the bundle does not hold"),
                               (self.named("-extra.jar.asc"), "signs a-1.0.0-extra.jar, which the bundle does not hold")):
            with self.subTest(name):
                entries = self.entries()
                entries[name] = digest
                self.judge(entries, fragment, proc=False)

    def test_checksums_of_signatures_are_checked_too(self):
        entries = self.entries()
        asc = self.named(".jar.asc")
        entries[asc + ".sha256"] = hashlib.sha256(entries[asc]).hexdigest().encode()
        self.accepted(self.judge(entries, None, proc=False))
        entries[asc + ".sha256"] = b"0" * 64
        self.judge(entries, f"{asc}.sha256 does not match", proc=False)

    def test_a_directory_is_never_a_subject(self):
        entries = self.entries()
        entries[self.named(".jar.sha1")] = hashlib.sha1(entries[self.named(".jar")]).hexdigest().encode()
        self.accepted(self.judge(entries, None, proc=False))

    def test_an_extra_file_without_a_signature_must_not_pass(self):
        entries = self.entries()
        entries[self.named("-extra.jar")] = b"PK unsigned extra jar"
        res = self.judge(entries, None, proc=False)
        self.assertNotEqual(res.rc, 0, res)

    def test_an_extra_file_with_a_good_signature_in_the_bundle_passes(self):
        entries = self.entries()
        entries[self.named(".module")] = b"{}"
        entries[self.named(".module.asc")] = sig_bytes(b"{}")
        self.accepted(self.judge(entries, None, proc=False))

    def test_an_extra_signed_file_with_a_signature_that_does_not_verify_is_refused(self):
        entries = self.entries()
        entries[self.named(".module")] = b"{}"
        entries[self.named(".module.asc")] = sig_bytes(b"other")
        self.judge(entries, f"{self.named('.module.asc')} is not a good signature of the bundle's own file", proc=False)


class Names(Bundle):
    def with_extra(self, name, data=b"x", attr=None):
        entries = list(self.entries().items())
        entries.append((name, data) if attr is None else (name, data, attr))
        return entries

    def test_duplicate_names_are_refused_whatever_the_content(self):
        base = list(self.entries().items())
        jar = self.named(".jar")
        for label, data in (("same bytes", self.read_target(f"{STEM}.jar")), ("other bytes", b"evil")):
            with self.subTest(label):
                res = self.judge(base + [(jar, data)], f"{jar} occurs 2 times")
                self.assertEqual(len(res.errors()) >= 2, True)

    def test_names_that_differ_only_by_case(self):
        """Characterised, not endorsed: the extra file is accepted, so an extractor that folds case would merge it with the jar."""
        res = self.judge(self.with_extra(self.named(".JAR"), b"upper"), None, proc=False)
        self.assertEqual(res.rc, 0, res)

    def test_names_that_differ_only_by_case_must_not_pass(self):
        res = self.judge(self.with_extra(self.named(".JAR"), b"upper"), None, proc=False)
        self.assertNotEqual(res.rc, 0, res)

    def test_a_directory_whose_name_differs_by_case_is_another_coordinate(self):
        entries = self.entries()
        for n, d in list(entries.items()):
            entries["EU/" + n.split("/", 1)[1]] = d
        self.judge(entries, "a-1.0.0 is in 2 directories", proc=False)

    def test_symbolic_link_entries_are_refused_wherever_they_sit(self):
        link = 0o120777 << 16
        for label, name in (("a built file", self.named(".jar")), ("an extra file", self.named(".module")),
                            ("a checksum", self.named(".jar.sha1")), ("a signature", self.named(".pom.asc"))):
            with self.subTest(label):
                entries = {n: d for n, d in self.entries().items() if n != name}
                items = list(entries.items()) + [(name, b"/etc/passwd", link)]
                res = self.judge(items, f"{name} is not a file of a published coordinate (a symbolic link)", proc=False)

    def test_other_file_types_in_the_mode_bits_are_judged_by_the_name_alone(self):
        for label, mode in (("regular", 0o100644), ("executable", 0o100755), ("setuid", 0o104755)):
            with self.subTest(label):
                items = [(n, d, mode << 16) for n, d in self.entries().items()]
                self.accepted(self.judge(items, None, proc=False))

    def test_unsafe_names_are_refused_and_printed_escaped(self):
        unsafe = {
            "backslash separators": "eu\\exeris\\caps\\a\\1.0.0\\a-1.0.0.module",
            "backslash in the file": f"{D}/a-1.0.0\\x.module",
            "newline": f"{D}/a-1.0.0-x\n::error::forged.module",
            "carriage return": f"{D}/a-1.0.0-x\r.module",
            "escape": f"{D}/a-1.0.0-x\x1b[31m.module",
            "nul": f"{D}/a-1.0.0-x\x00.module",
            "del": f"{D}/a-1.0.0-x\x7f.module",
            "c1 control": f"{D}/a-1.0.0-x\x85.module",
            "bidi override": f"{D}/a-1.0.0-x\u202e.module",
            "zero width space": f"{D}/a-1.0.0-x\u200b.module",
            "line separator": f"{D}/a-1.0.0-x\u2028.module",
            "unassigned": f"{D}/a-1.0.0-x\u0378.module",
            "paragraph separator": f"{D}/a-1.0.0-x\u2029.module",
            "dot segment": f"{D}/./a-1.0.0.module",
            "dot dot segment": f"eu/exeris/caps/a/../a/1.0.0/a-1.0.0.module",
            "dot dot at the end": f"{D}/a-1.0.0.module/..",
            "empty segment": f"eu//exeris/caps/a/1.0.0/a-1.0.0.module",
            "doubled slash before the file": f"{D}//a-1.0.0.module",
            "absolute": f"/{D}/a-1.0.0.module",
            "drive letter": f"C:/{D}/a-1.0.0.module",
            "drive letter, backslash": f"C:\\{D}\\a-1.0.0.module",
            "unc": f"//host/share/{D}/a-1.0.0.module",
            "only slashes": "///",
            "parent only": "../x",
        }
        for label, name in unsafe.items():
            with self.subTest(label):
                if "\x00" in name:
                    continue            # zipfile cuts a name at NUL before it is written
                res = self.judge(self.with_extra(name), None, proc=False)
                self.refused(res)
                text = res.err
                self.assertNotIn("\n::error::forged", text)
                self.assertNotIn("\x1b", text)
                self.assertNotIn("\r", text)
                self.assertTrue(all(ln.startswith("::error::") for ln in text.splitlines()), text)

    def test_an_unsafe_name_inside_the_coordinate_directory_is_stray_not_silently_dropped(self):
        res = self.judge(self.with_extra(f"{D}/./a-1.0.0.module"), None, proc=False)
        self.assertIn("is not a file of a published coordinate", "\n".join(res.errors()))

    def test_an_unsafe_directory_entry_is_refused(self):
        for name in ("/", "//", "../", "a/../", "a//", "./", "back\\slash/", "ctl\x01/"):
            with self.subTest(repr(name)):
                self.judge(self.with_extra(name, b""), "is not a file of a published coordinate (an unsafe name)", proc=False)

    def test_a_whole_bundle_under_a_drive_letter_or_an_absolute_root_is_refused(self):
        for prefix in ("C:/", "/", "./", "../"):
            with self.subTest(prefix):
                entries = {prefix + n: d for n, d in self.entries().items()}
                self.judge(entries, None, proc=False)
                self.refused(h.run_main(S, ["--target-dir", self.target, "--gpg", self.gpg, "--expect-bundle", "true"]))

    def test_a_trailing_slash_on_a_name_makes_it_a_directory_that_is_not_counted_as_a_file(self):
        res = self.judge(self.with_extra(self.named(".module") + "/", b"payload"), None, proc=False)
        self.accepted(res)
        self.assertIn("central bundle: 12 file(s), 0 outside a coordinate", res.out)


class Gaps(Bundle):
    """Each of these is a place where a weaker gate would still have refused for some other reason."""

    def err(self, res):
        return "\n".join(res.errors())

    def test_an_unusual_character_is_the_only_fault_of_these_names(self):
        for ch in ("\u2029", "\u0378", "\u2028", "\u200b", "\x01"):
            with self.subTest(hex(ord(ch))):
                self.write_bundle(self.entries())
                self.accepted(self.check("--expect-bundle", "true"))
                entries = list(self.entries().items()) + [(self.named(f"-x{ch}.module"), b"{}")]
                write_zip(self.bundle_path, entries)
                res = self.check("--expect-bundle", "true")
                self.refused(res, "is not a file of a published coordinate")

    def test_a_group_of_one_segment_is_a_coordinate(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.real_coordinate(group="acme")
        self.accepted(self.check_bundle(group="acme"))

    def test_a_namespaced_pom_binds_the_name_and_the_group(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        ns = pom_xml(artifact="b").replace("<project>", '<project xmlns="http://maven.apache.org/POM/4.0.0">')
        self.coordinate("a-1.0.0", pom_text=ns)
        self.refused(self.check(), "which the files are not named after")
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.coordinate("a-1.0.0", pom_text=pom_xml().replace("<project>", '<project xmlns="http://maven.apache.org/POM/4.0.0">'))
        self.refused(self.check_bundle(group="org.other"), "is not under the group eu.exeris.caps")

    def test_the_pom_s_own_group_wins_over_its_parent_s(self):
        shutil.rmtree(self.target)
        os.makedirs(self.target)
        self.coordinate("a-1.0.0", pom_text=pom_xml(group="own.group", parent_group="parent.group"))
        self.accepted(self.check_bundle(group="own.group"))
        self.refused(self.check_bundle(group="parent.group"), "is not under the group own.group")

    def test_a_pom_naming_only_one_of_artifact_and_version_binds_nothing_it_does_not_name(self):
        for text in ("<project><groupId>eu.exeris.caps</groupId><version>1.0.0</version></project>",
                     "<project><groupId>eu.exeris.caps</groupId><artifactId>a</artifactId></project>"):
            with self.subTest(text):
                shutil.rmtree(self.target)
                os.makedirs(self.target)
                self.coordinate("a-1.0.0", pom_text=text)
                self.accepted(self.check())

    def test_a_name_that_is_not_a_jar_pom_or_signature_is_not_judged_by_its_characters(self):
        with open(os.path.join(self.target, "notes\x01.txt"), "w") as fh:
            fh.write("x")
        self.accepted(self.check())

    def test_a_stray_entry_is_not_compared_or_verified_as_if_it_belonged_to_a_coordinate(self):
        entries = list(self.entries().items()) + [("o/p/q/a-1.0.0.jar", b"different bytes"),
                                                  ("zzz/yyy/xxx/orphan.asc", b"x"), ("zzz/yyy/xxx/orphan.sha1", b"x")]
        res = self.judge(entries, "o/p/q/a-1.0.0.jar is not a file of a published coordinate", proc=False)
        text = self.err(res)
        self.assertNotIn("differs from target", text)
        self.assertNotIn("which the bundle does not hold", text)

    def test_an_entry_with_other_type_bits_in_the_mode_is_not_taken_for_a_symlink(self):
        items = [(n, d, 0o160000 << 16) for n, d in self.entries().items()]
        self.accepted(self.judge(items, None, proc=False))

    def test_a_bundle_that_is_not_a_zip_is_named_as_such(self):
        os.makedirs(os.path.dirname(self.bundle_path))
        with open(self.bundle_path, "w") as fh:
            fh.write("nope")
        res = self.check("--expect-bundle", "true")
        self.refused(res, "central-bundle.zip is not a zip file")
        self.assertNotIn("unexpectedly", res.err)


class Bounds(Bundle):
    def test_exactly_the_entry_limit_is_accepted_and_one_more_is_refused(self):
        entries = list(self.entries().items())
        fill = [(f"d{i}/", b"") for i in range(2000 - len(entries))]
        self.accepted(self.judge(entries + fill, None, proc=False))
        res = self.judge(entries + fill + [("one-more/", b""), ("stray.txt", b"x")], "2002 entries exceed the limit of 2000")
        self.assertEqual(len(res.errors()), 2, "nothing else is judged once a bound is exceeded")

    def test_more_than_the_total_size_is_refused_before_anything_is_read(self):
        items = list(self.entries().items())
        write_zip(self.bundle_path, items)
        raw_zip(self.bundle_path, [dict(name=n, data=d) for n, d in items] +
                [dict(name="stray.txt", data=b"x"), dict(name="big.bin", data=b"x", usize=(256 << 20) + 1, csize=1, method=8)])
        before = self.tree()
        res = self.check("--expect-bundle", "true")
        self.refused(res, "bytes uncompressed exceed the limit of 268435456")
        self.assertEqual(len(res.errors()), 2)
        self.assertEqual(self.tree(), before)

    def test_exactly_the_total_size_limit_is_not_a_total_size_refusal_and_the_sum_is_what_counts(self):
        items = [dict(name=n, data=d) for n, d in self.entries().items()]
        used = sum(len(i["data"]) for i in items)
        limit = 256 * 1024 * 1024
        big = limit - used
        raw_zip(self.bundle_path, items + [dict(name="big.bin", data=b"x", usize=big, csize=big // 100, method=8)])
        res = self.check("--expect-bundle", "true")
        self.assertNotIn("exceed the limit", res.err, "a total equal to the limit is within it")
        half = limit // 2 + 1
        raw_zip(self.bundle_path, items + [dict(name="a.bin", data=b"x", usize=half, csize=half // 100, method=8),
                                           dict(name="b.bin", data=b"x", usize=half, csize=half // 100, method=8)])
        self.refused(self.check("--expect-bundle", "true"), "bytes uncompressed exceed the limit")

    def test_the_ratio_limit_is_exactly_two_hundred(self):
        items = [dict(name=n, data=d) for n, d in self.entries().items()]
        usize = 2097200
        for csize, refused in ((usize // 200, False), (usize // 200 - 1, True), (usize // 200 + 1, False)):
            with self.subTest(csize=csize):
                raw_zip(self.bundle_path, items + [dict(name="stray.txt", data=b"x"),
                                                   dict(name="big.bin", data=b"x", usize=usize, csize=csize, method=8)])
                res = self.check("--expect-bundle", "true")
                self.assertEqual("expands by more than" in res.err, refused, res)
                if refused:
                    self.assertEqual(len(res.errors()), 2, "nothing else is judged once a bound is exceeded")

    def test_a_ratio_above_the_limit_on_a_large_entry_is_refused_quickly(self):
        entries = self.entries()
        for size in (1 << 20, 5 << 20, 20 << 20):
            with self.subTest(size):
                items = [dict(name=n, data=d) for n, d in entries.items()]
                z = deflate_zeros(size)
                items.append(dict(name="stray.txt", data=b"x"))
                items.append(dict(name=self.named(".bomb"), data=z, method=8, crc=zlib.crc32(b"\0" * size), usize=size, csize=len(z)))
                raw_zip(self.bundle_path, items)
                before, start = self.tree(), time.monotonic()
                res = self.check("--expect-bundle", "true")
                self.assertLess(time.monotonic() - start, 10)
                self.refused(res, f"{self.named('.bomb')} expands by more than 200 times")
                self.assertEqual(len(res.errors()), 2)
                self.assertEqual(self.tree(), before)

    def test_the_ratio_limit_does_not_apply_below_one_mebibyte_and_not_to_incompressible_entries(self):
        entries = self.entries()
        items = [dict(name=n, data=d) for n, d in entries.items()]
        z = deflate_zeros((1 << 20) - 1)
        items.append(dict(name=self.named(".small"), data=z, method=8, crc=zlib.crc32(b"\0" * ((1 << 20) - 1)),
                          usize=(1 << 20) - 1, csize=len(z)))
        items.append(dict(name=self.named(".random"), data=os.urandom(2 << 20)))
        raw_zip(self.bundle_path, items)
        res = self.check("--expect-bundle", "true")
        self.assertNotIn("expands by more than", res.err)

    def test_a_declared_size_that_lies_small_is_never_inflated_beyond_the_declaration(self):
        """Declared 10 bytes, 256 MiB of data: the reader stops at the declaration, in bounded time and memory."""
        entries = self.entries()
        z = deflate_zeros(256 << 20)
        items = [dict(name=n, data=d) for n, d in entries.items() if n != self.named(".jar")]
        items.append(dict(name=self.named(".jar"), data=z, method=8, crc=zlib.crc32(b"\0" * 10), usize=10, csize=len(z)))
        raw_zip(self.bundle_path, items)

        def limit():
            resource.setrlimit(resource.RLIMIT_AS, (600 << 20, 600 << 20))
        start = time.monotonic()
        proc = subprocess.run([sys.executable, "-I", "-B", h.script_path(S), "--target-dir", self.target, "--gpg", self.gpg,
                               "--expect-bundle", "true"], capture_output=True, env=h.clean_env(), preexec_fn=limit, timeout=60)
        self.assertLess(time.monotonic() - start, 15)
        err = proc.stderr.decode()
        self.assertEqual(proc.returncode, 1, err)
        self.assertIn(f"{self.named('.jar')} differs from target/{STEM}.jar", err)
        self.assertNotIn("MemoryError", err)

    def test_a_lie_that_makes_the_visible_prefix_equal_to_the_build_is_accepted_by_the_reader_and_rejected_by_a_checking_extractor(self):
        """The gate reads the declared prefix, as zipfile does. Every extractor that inflates the stream sees a CRC error."""
        jar = self.read_target(f"{STEM}.jar")
        z = zlib.compressobj(9, zlib.DEFLATED, -15)
        stream = z.compress(jar + b"\0" * 4096) + z.flush()
        entries = self.entries()
        items = [dict(name=n, data=d) for n, d in entries.items() if n != self.named(".jar")]
        items.append(dict(name=self.named(".jar"), data=stream, method=8, crc=zlib.crc32(jar), usize=len(jar), csize=len(stream)))
        raw_zip(self.bundle_path, items)
        gate = self.check("--expect-bundle", "true")
        self.accepted(gate)
        unzip = subprocess.run(["unzip", "-tq", self.bundle_path], capture_output=True) if self.have("unzip") else None
        if unzip is not None:
            self.assertNotEqual(unzip.returncode, 0, "unzip -t rejects the entry, so the gate's acceptance is not an extractor's")

    @staticmethod
    def have(tool):
        from shutil import which
        return which(tool) is not None


class Headers(Bundle):
    def test_a_central_directory_name_that_disagrees_with_the_local_header_of_a_read_entry_is_one_error_line(self):
        for victim in (".jar", ".jar.asc", ".jar.sha1", ".pom"):
            with self.subTest(victim):
                items = []
                for n, d in self.entries().items():
                    e = dict(name=n, data=d)
                    if n == self.named(victim):
                        e["local_name"] = "../../evil.sh"
                    items.append(e)
                raw_zip(self.bundle_path, items)
                res = self.check("--expect-bundle", "true")
                self.refused(res, "failed unexpectedly (BadZipFile")
                self.assertEqual(len(res.errors()), 1)

    def test_a_local_header_name_that_differs_on_an_unread_entry_must_not_pass(self):
        items = [dict(name=n, data=d) for n, d in self.entries().items()]
        items.append(dict(name=self.named(".module"), data=b"{}", local_name="../../../../tmp/planted"))
        raw_zip(self.bundle_path, items)
        res = self.check("--expect-bundle", "true")
        self.assertNotEqual(res.rc, 0, res)

    def test_the_names_the_gate_sees_are_the_central_directory_names_and_unzip_agrees(self):
        items = [dict(name=n, data=d) for n, d in self.entries().items()]
        items.append(dict(name=self.named(".module"), data=b"{}", local_name="../../../../tmp/planted"))
        raw_zip(self.bundle_path, items)
        if not self.have("unzip"):
            self.skipTest("unzip is not installed")
        listing = subprocess.run(["unzip", "-Z1", self.bundle_path], capture_output=True, text=True).stdout.split("\n")
        self.assertIn(self.named(".module"), listing)
        self.assertNotIn("../../../../tmp/planted", listing)

    @staticmethod
    def have(tool):
        from shutil import which
        return which(tool) is not None

    def test_garbage_before_and_after_the_archive_is_not_a_second_archive(self):
        self.write_bundle(self.entries())
        with open(self.bundle_path, "rb") as fh:
            data = fh.read()
        with open(self.bundle_path, "wb") as fh:
            fh.write(b"JUNK" * 10 + data)
        res = self.check("--expect-bundle", "true")
        self.assertIn(res.rc, (0, 1))
        self.assertEqual(len(res.errors()) > 0, res.rc == 1)

    def test_a_truncated_or_empty_bundle_is_not_a_zip(self):
        self.write_bundle(self.entries())
        with open(self.bundle_path, "rb") as fh:
            data = fh.read()
        for label, content in (("empty", b""), ("half", data[: len(data) // 2]), ("magic only", b"PK\x03\x04")):
            with self.subTest(label):
                with open(self.bundle_path, "wb") as fh:
                    fh.write(content)
                self.refused(self.check("--expect-bundle", "true"), "is not a zip file")


class Links(Bundle):
    def test_a_symlinked_bundle_file_is_refused(self):
        self.write_bundle(self.entries())
        real = self.path("real-bundle.zip")
        os.rename(self.bundle_path, real)
        os.symlink(real, self.bundle_path)
        self.refused(self.check("--expect-bundle", "true"), "central-bundle.zip is missing")

    def test_a_symlinked_central_publishing_directory_is_refused(self):
        self.write_bundle(self.entries())
        real = self.path("real-dir")
        os.rename(os.path.join(self.target, "central-publishing"), real)
        os.symlink(real, os.path.join(self.target, "central-publishing"))
        self.refused(self.check("--expect-bundle", "true"), "central-bundle.zip is missing")

    def test_a_dangling_link_and_a_directory_in_place_of_the_bundle_are_refused(self):
        os.makedirs(os.path.dirname(self.bundle_path))
        os.symlink(self.path("absent"), self.bundle_path)
        self.refused(self.check("--expect-bundle", "true"), "is missing")
        os.remove(self.bundle_path)
        os.makedirs(self.bundle_path)
        self.refused(self.check("--expect-bundle", "true"), "is not a regular file")

    def test_a_fifo_in_place_of_the_bundle_is_refused_without_blocking(self):
        os.makedirs(os.path.dirname(self.bundle_path))
        os.mkfifo(self.bundle_path)
        start = time.monotonic()
        self.refused(self.check("--expect-bundle", "true"), "is not a regular file")
        self.assertLess(time.monotonic() - start, 10)


if __name__ == "__main__":
    unittest.main()
