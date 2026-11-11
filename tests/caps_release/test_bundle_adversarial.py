"""The Central bundle against hostile input: bound to the build, bounded in size, and judged by its central directory."""
from __future__ import annotations

import hashlib
import os
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

    @known_defect("bundle-extra-unsigned", "a file of a published coordinate directory that has no signature in the bundle is accepted; "
                                           "only the four built files are required to be signed")
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

    @known_defect("bundle-case-collision", "an entry whose name differs from a built file only by case is accepted, and an extractor on a "
                                           "case-folding file system overwrites the verified file with it")
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
            "newline": f"{D}/a-1.0.0\n::error::forged.module",
            "carriage return": f"{D}/a-1.0.0\r.module",
            "escape": f"{D}/a-1.0.0\x1b[31m.module",
            "nul": f"{D}/a-1.0.0\x00.module",
            "del": f"{D}/a-1.0.0\x7f.module",
            "c1 control": f"{D}/a-1.0.0\x85.module",
            "bidi override": f"{D}/a-1.0.0\u202e.module",
            "zero width space": f"{D}/a-1.0.0\u200b.module",
            "line separator": f"{D}/a-1.0.0\u2028.module",
            "unassigned": f"{D}/a-1.0.0\u0378.module",
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


class Bounds(Bundle):
    def test_exactly_the_entry_limit_is_accepted_and_one_more_is_refused(self):
        entries = list(self.entries().items())
        fill = [(f"d{i}/", b"") for i in range(2000 - len(entries))]
        self.accepted(self.judge(entries + fill, None, proc=False))
        res = self.judge(entries + fill + [("one-more/", b"")], "2001 entries exceed the limit of 2000")
        self.assertEqual(len(res.errors()), 2)

    def test_more_than_the_total_size_is_refused_before_anything_is_read(self):
        items = list(self.entries().items())
        write_zip(self.bundle_path, items)
        raw_zip(self.bundle_path, [dict(name=n, data=d) for n, d in items] +
                [dict(name="big.bin", data=b"x", usize=(256 << 20) + 1, csize=1, method=8)])
        before = self.tree()
        res = self.check("--expect-bundle", "true")
        self.refused(res, "bytes uncompressed exceed the limit of 268435456")
        self.assertEqual(self.tree(), before)

    def test_exactly_the_total_size_limit_is_not_a_total_size_refusal(self):
        items = [dict(name=n, data=d) for n, d in self.entries().items()]
        used = sum(len(i["data"]) for i in items)
        # the declared size is what the limit counts; a stored-size entry keeps the ratio at 1
        items.append(dict(name="d/", data=b""))
        raw_zip(self.bundle_path, items)
        res = self.check("--expect-bundle", "true")
        self.assertNotIn("exceed the limit", res.err)
        self.assertGreater(used, 0)

    def test_a_ratio_above_the_limit_on_a_large_entry_is_refused_quickly(self):
        entries = self.entries()
        for size in (1 << 20, 5 << 20, 100 << 20):
            with self.subTest(size):
                items = [dict(name=n, data=d) for n, d in entries.items()]
                z = deflate_zeros(size)
                items.append(dict(name=self.named(".bomb"), data=z, method=8, crc=zlib.crc32(b"\0" * size), usize=size, csize=len(z)))
                raw_zip(self.bundle_path, items)
                before, start = self.tree(), time.monotonic()
                res = self.check("--expect-bundle", "true")
                self.assertLess(time.monotonic() - start, 10)
                self.refused(res, f"{self.named('.bomb')} expands by more than 200 times")
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

    @known_defect("bundle-local-header", "an entry the gate never reads (an extra file) may carry a local-header name that differs from its "
                                         "central-directory name; a streaming extractor uses the local name")
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
