"""The archive layout of the Central bundle against a hand-built corpus: the gate and a streaming extractor must see the same files.

Every case is a bundle that is correct in every way but one, written header by header with `zip_support.build`.
"""
from __future__ import annotations

import os
import struct
import zlib

import caps_release_helpers as h
from caps_release_helpers import known_defect
from readiness_support import Fixture
from zip_support import (Entry, build, extra_block, strict_reason, stream_view, unicode_path_extra, zipfile_view,
                         DESCRIPTOR)

S = "check_release_readiness"
D = "eu/exeris/caps/a/1.0.0"
STEM = "a-1.0.0"
LAYOUT = "central bundle: "


class Layout(Fixture):
    def setUp(self):
        super().setUp()
        self.real_coordinate()

    def entries(self, method=8, **kw):
        return [Entry(n, d, method=method, **kw) for n, d in self.bundle_entries().items()]

    def named(self, suffix):
        return f"{D}/{STEM}{suffix}"

    def put(self, data):
        os.makedirs(os.path.dirname(self.bundle_path), exist_ok=True)
        with open(self.bundle_path, "wb") as fh:
            fh.write(data)

    def judge(self, entries, **build_kw):
        data, _ = build(entries, **build_kw)
        self.put(data)
        return data, self.check("--expect-bundle", "true")

    def refuse(self, entries, fragment=None, **build_kw):
        data, res = self.judge(entries, **build_kw)
        self.refused(res, fragment)
        lines = [e for e in res.errors() if LAYOUT in e or "is not a zip file" in e]
        self.assertTrue(lines, res)
        self.assertNotIn("unexpectedly", res.err)
        self.assertNotIn("Traceback", res.err)
        return data, res

    def assert_layout_refusal(self, entries, fragment, **build_kw):
        """One `central bundle:` line about the layout, then the closing line, and nothing about the files inside."""
        data, res = self.refuse(entries, fragment, **build_kw)
        self.assertEqual(len([e for e in res.errors() if LAYOUT in e]), 1, res)
        self.assertEqual(len(res.errors()), 2, res)
        return data


class Baseline(Layout):
    def test_the_builder_writes_a_bundle_the_gate_and_the_independent_readers_accept(self):
        for label, method, kw in (("deflated", 8, {}), ("stored", 0, {}),
                                  ("descriptors with signature", 8, {"descriptor": "sig"}),
                                  ("descriptors without signature", 8, {"descriptor": "nosig"})):
            with self.subTest(label):
                data, res = self.judge(self.entries(method, **kw))
                self.accepted(res)
                self.assertIsNone(strict_reason(data))
                self.assertEqual(stream_view(data), zipfile_view(self.bundle_path))

    def test_a_stored_entry_with_a_descriptor_is_read_from_the_central_sizes(self):
        data, res = self.judge(self.entries(0, descriptor="sig"))
        self.accepted(res)
        self.assertIsNone(strict_reason(data))

    def test_a_nested_end_record_in_a_stored_entry_does_not_move_the_real_one(self):
        nested, _ = build([Entry("inner.txt", b"x")])
        jar = nested + b"PK\x05\x06" + b"\0" * 18
        with open(os.path.join(self.target, f"{STEM}.jar"), "wb") as fh:
            fh.write(jar)
        from readiness_support import sig_of
        with open(os.path.join(self.target, f"{STEM}.jar.asc"), "w") as fh:
            fh.write(sig_of(os.path.join(self.target, f"{STEM}.jar")))
        data, res = self.judge(self.entries(0))
        self.accepted(res)
        self.assertIsNone(strict_reason(data))
        self.assertEqual(stream_view(data), zipfile_view(self.bundle_path))
        self.assertGreater(data.count(b"PK\x05\x06"), 2, "the payload holds end records beside the real one")


class Descriptors(Layout):
    def test_a_descriptor_that_disagrees_with_the_central_record_is_refused(self):
        for label, index in (("crc", 0), ("compressed size", 1), ("size", 2)):
            with self.subTest(label):
                entries = self.entries(8, descriptor="sig")
                good = [zlib.crc32(entries[0].data) & 0xFFFFFFFF, len(zlib_deflate(entries[0].data)), len(entries[0].data)]
                good[index] += 1
                entries[0].descriptor_values = tuple(good)
                self.assert_layout_refusal(entries, "the data descriptor of")

    def test_a_descriptor_without_the_signature_that_disagrees_is_refused(self):
        entries = self.entries(8, descriptor="nosig")
        entries[3].descriptor_values = (0, 0, 0)
        self.assert_layout_refusal(entries, "the data descriptor of")

    def test_a_descriptor_flag_in_the_local_header_only_is_refused(self):
        entries = self.entries(8)
        entries[0].local["flags"] = 0x8
        self.assert_layout_refusal(entries, "disagrees with the central record in flags or method")

    def test_a_descriptor_flag_in_the_central_record_only_is_refused(self):
        entries = self.entries(8)
        entries[0].central["flags"] = 0x8
        self.assert_layout_refusal(entries, "disagrees with the central record in flags or method")


def zlib_deflate(data):
    from zip_support import compress
    return compress(data, 8)


class Disagreements(Layout):
    def test_each_local_field_that_differs_from_the_central_record_is_refused(self):
        cases = {"crc": ("crc", 0xDEADBEEF, "in size or CRC"), "compressed size": ("csize", 1, "in size or CRC"),
                 "size": ("usize", 1, "in size or CRC"), "method": ("method", 0, "in flags or method"),
                 "flags": ("flags", 0x800, "in flags or method"),
                 "name": ("name", b"zzz", "the local header name")}
        for label, (field, value, fragment) in cases.items():
            for victim in (0, 5, -1):
                with self.subTest(f"{label} of entry {victim}"):
                    entries = self.entries(8)
                    entries[victim].local[field] = value
                    self.assert_layout_refusal(entries, fragment)

    def test_each_central_field_that_differs_from_the_local_header_is_refused(self):
        cases = {"crc": ("crc", 0xDEADBEEF), "compressed size": ("csize", 1), "size": ("usize", 1), "flags": ("flags", 0x800),
                 "method": ("method", 0)}
        for label, (field, value) in cases.items():
            with self.subTest(label):
                entries = self.entries(8)
                entries[2].central[field] = value
                self.refuse(entries)

    def test_the_utf8_flag_differing_between_local_and_central_is_refused(self):
        for where in ("local", "central"):
            with self.subTest(where):
                entries = self.entries(8)
                getattr(entries[1], where)["flags"] = 0x800
                self.assert_layout_refusal(entries, "in flags or method")

    def test_a_name_that_decodes_differently_under_the_two_flags_is_refused(self):
        entries = self.entries(8)
        entries[0].name = "caf\u00e9".encode("utf-8")
        self.refuse(entries)

    def test_two_central_records_for_one_local_header_are_refused(self):
        entries = self.entries(8)
        data, _ = build(entries, order=[0, 0, *range(2, len(entries))])
        self.put(data)
        res = self.check("--expect-bundle", "true")
        self.refused(res)
        self.assertNotIn("unexpectedly", res.err)

    def test_a_central_record_that_points_into_another_entry_s_data_is_refused(self):
        for victim in (0, 4):
            with self.subTest(victim):
                entries = self.entries(8)
                data, _ = build(entries)
                inner = data.index(b"PK\x03\x04", 4) + 10
                entries[victim].central["offset"] = inner
                self.refuse(entries)

    def test_a_central_record_that_points_past_the_archive_or_at_the_end_record_is_refused(self):
        for offset in (10 ** 6, 0xFFFFFFFE):
            with self.subTest(offset):
                entries = self.entries(8)
                entries[0].central["offset"] = offset
                self.refuse(entries)

    def test_entries_swapped_in_the_central_directory_but_not_in_the_body_are_still_the_same_files(self):
        entries = self.entries(8)
        order = list(range(len(entries)))
        order[0], order[1] = order[1], order[0]
        data, res = self.judge(entries, order=order)
        self.accepted(res)
        self.assertIsNone(strict_reason(data))
        self.assertEqual(sorted(stream_view(data)), sorted(zipfile_view(self.bundle_path)))


class Surroundings(Layout):
    def test_trailing_bytes_after_the_end_record_are_refused(self):
        for tail in (b"\0", b"PK\x05\x06" + b"\0" * 18, b"x" * 100):
            with self.subTest(tail[:4]):
                self.refuse(self.entries(), suffix=tail)

    def test_an_archive_comment_is_refused(self):
        self.assert_layout_refusal(self.entries(), "end record is not the last 22 bytes", comment=b"hello")

    def test_a_prepended_stub_is_refused_whether_offsets_count_it_or_not(self):
        for relative in (True, False):
            with self.subTest(relative):
                self.refuse(self.entries(), prefix=b"#!/bin/sh\nexit 0\n", relative_offsets=relative)

    def test_a_gap_between_two_entries_is_refused(self):
        entries = self.entries()
        data, _ = build(entries)
        cut = data.index(b"PK\x03\x04", 4)
        padded = data[:cut] + b"\0\0\0\0" + data[cut:]
        self.put(padded)
        res = self.check("--expect-bundle", "true")
        self.refused(res)
        self.assertNotIn("unexpectedly", res.err)

    def test_a_gap_before_the_central_directory_is_refused(self):
        entries = self.entries()
        data, _ = build(entries)
        cd = struct.unpack_from("<I", data, len(data) - 6)[0]
        padded = data[:cd] + b"\0\0\0\0" + data[cd:]
        self.put(padded)
        res = self.check("--expect-bundle", "true")
        self.refused(res)

    def test_a_zero_entry_archive_is_not_a_bundle(self):
        data, _ = build([])
        self.assertEqual(len(data), 22)
        self.put(data)
        res = self.check("--expect-bundle", "true")
        self.refused(res, "it holds no coordinate for the built a-1.0.0")
        self.assertNotIn("unexpectedly", res.err)

    def test_an_empty_file_and_a_file_shorter_than_an_end_record_are_not_zip_files(self):
        for payload in (b"", b"PK", b"PK\x05\x06", b"\0" * 21):
            with self.subTest(len(payload)):
                self.put(payload)
                res = self.check("--expect-bundle", "true")
                self.refused(res, "is not a zip file")
                self.assertNotIn("unexpectedly", res.err)

    def test_a_zip64_locator_before_the_end_record_is_refused(self):
        self.refuse(self.entries(), locator=True)

    def test_every_zip64_marker_in_every_field_of_the_end_record_is_refused(self):
        for field, value in (("disk", 0xFFFF), ("cd_disk", 0xFFFF), ("here", 0xFFFF), ("total", 0xFFFF), ("cd_size", 0xFFFFFFFF),
                             ("cd_off", 0xFFFFFFFF), ("here", 65535), ("total", 65535)):
            with self.subTest(f"{field}={value:#x}"):
                self.refuse(self.entries(), end={field: value})

    def test_an_end_record_that_counts_other_than_what_the_directory_lists_is_refused(self):
        for field, value in (("here", 1), ("total", 1), ("here", 99), ("total", 99), ("cd_size", 1), ("cd_off", 1)):
            with self.subTest(f"{field}={value}"):
                self.refuse(self.entries(), end={field: value})

    def test_every_zip64_marker_in_the_entry_records_is_refused(self):
        for where, field in (("central", "csize"), ("central", "usize"), ("central", "offset"), ("local", "csize"), ("local", "usize")):
            with self.subTest(f"{where} {field}"):
                entries = self.entries()
                getattr(entries[2], where)[field] = 0xFFFFFFFF
                self.refuse(entries)

    def test_a_zip64_extra_field_in_either_header_is_refused(self):
        for where in ("local", "central"):
            with self.subTest(where):
                entries = self.entries()
                block = extra_block(1, struct.pack("<QQ", 1, 1))
                if where == "local":
                    entries[1].extra, entries[1].central_extra = block, b""
                else:
                    entries[1].central_extra = block
                self.assert_layout_refusal(entries, "an entry has a ZIP64 record")

    def test_encryption_in_any_form_is_refused(self):
        for flags in (0x1, 0x40, 0x2000, 0x1 | 0x40):
            with self.subTest(hex(flags)):
                entries = self.entries()
                entries[0].flags = flags
                self.assert_layout_refusal(entries, "an entry is encrypted")

    def test_a_compression_method_other_than_stored_or_deflated_is_refused(self):
        for method in (1, 6, 9, 12, 14, 93, 98, 99):
            with self.subTest(method):
                entries = self.entries()
                entries[0].local["method"] = entries[0].central["method"] = method
                self.assert_layout_refusal(entries, "other than stored or deflated")

    def test_a_malformed_extra_field_is_refused_instead_of_crashing(self):
        for label, blob in (("one byte", b"\x01"), ("length past the end", struct.pack("<HH", 0x5455, 40) + b"ab"),
                            ("header cut", b"\xff\xff\x00")):
            for where in ("local", "central"):
                with self.subTest(f"{label} in {where}"):
                    entries = self.entries()
                    if where == "local":
                        entries[1].extra, entries[1].central_extra = blob, b""
                    else:
                        entries[1].central_extra = blob
                    self.refuse(entries)

    def test_a_harmless_extra_field_in_both_headers_is_not_a_finding(self):
        entries = self.entries()
        entries[1].extra = extra_block(0x5455, b"\x01\0\0\0\0")
        data, res = self.judge(entries)
        self.accepted(res)
        self.assertIsNone(strict_reason(data))

    def test_extra_fields_that_differ_between_local_and_central_are_not_part_of_the_contract(self):
        entries = self.entries()
        entries[1].extra = extra_block(0x5455, b"\x01\0\0\0\0")
        entries[1].central_extra = extra_block(0x7875, b"\x01\x04\0\0\0\0\x04\0\0\0\0")
        data, res = self.judge(entries)
        self.accepted(res)
        self.assertEqual(stream_view(data), zipfile_view(self.bundle_path))


class Bookkeeping(Layout):
    """What the gate does not look at in the central directory and in a deflate stream. The names and the bytes `zipfile` reads
    are right in each of these; a stricter extractor refuses the archive or reads it differently."""

    @known_defect("central-entry-disk", "a central record that starts on another disk is accepted; layout_problem reads only the end "
                  "record's disk numbers")
    def test_a_central_record_on_another_disk_is_refused(self):
        entries = self.entries()
        entries[2].central["disk"] = 1
        self.refuse(entries)

    @known_defect("central-record-overrun", "a last central record whose name length runs past the directory is accepted; "
                  "layout_problem never compares the record lengths with cd_size")
    def test_a_central_record_that_overruns_the_directory_is_refused(self):
        entries = self.entries()
        data, _ = build(entries)
        n = len(data)
        cd_off = struct.unpack_from("<I", data, n - 6)[0]
        pos, last = cd_off, cd_off
        while data[pos:pos + 4] == b"PK\x01\x02":
            last = pos
            nl, el, cl = struct.unpack_from("<HHH", data, pos + 28)
            pos += 46 + nl + el + cl
        patched = bytearray(data)
        struct.pack_into("<H", patched, last + 28, 0xFFFF)
        self.put(bytes(patched))
        self.refused(self.check("--expect-bundle", "true"))

    @known_defect("deflate-overrun", "an entry whose deflate stream goes on after the declared size is accepted: zipfile reads the "
                  "declared bytes, a streaming extractor reads the whole stream; layout_problem never inflates")
    def test_a_deflate_stream_that_inflates_to_more_than_the_declared_size_is_refused(self):
        entries = self.entries()
        victim = entries[0]
        victim.raw = zlib_deflate(victim.data + b"APPENDED-AFTER-THE-DECLARED-SIZE")
        data, res = self.judge(entries)
        self.refused(res)

    def test_the_overrun_is_real_for_a_streaming_reader(self):
        entries = self.entries()
        victim = entries[0]
        victim.raw = zlib_deflate(victim.data + b"APPENDED")
        data, _ = build(entries)
        self.put(data)
        self.assertEqual(zipfile_view(self.bundle_path)[0][1], victim.data)
        self.assertEqual(stream_view(data, False)[0][1], victim.data + b"APPENDED")


class RenamingExtras(Layout):
    """A Unicode Path extra field (0x7075) replaces the entry name for the extractors that honour it, so the gate
    and such an extractor would not see the same files."""

    def renamed(self, where):
        entries = self.entries()
        victim = entries[3]
        block = unicode_path_extra(victim.name, "../../../../tmp/planted.sh")
        if where in ("local", "both"):
            victim.extra = block
        victim.central_extra = block if where in ("central", "both") else b""
        return entries

    @known_defect("unicode-path-extra", "an entry renamed by a Unicode Path extra field is accepted; check_release_readiness.py:"
                  "layout_problem compares names but never the extra fields")
    def test_a_unicode_path_extra_field_that_renames_an_entry_is_refused(self):
        for where in ("local", "central", "both"):
            with self.subTest(where):
                data, res = self.judge(self.renamed(where))
                self.refused(res)

    def test_the_renaming_is_real_for_an_extractor_that_honours_the_field_and_not_for_zipfile(self):
        data, _ = build(self.renamed("local"))
        seen = [n for n, _ in stream_view(data)]
        self.assertIn(b"../../../../tmp/planted.sh", seen)
        self.assertNotIn(b"../../../../tmp/planted.sh", [n for n, _ in stream_view(data, honour_unicode_path=False)])


class Names(Layout):
    def one_extra(self, name, data=b"x"):
        entries = self.entries()
        entries.append(Entry(name, data))
        return entries

    def test_names_that_are_not_plain_relative_paths_are_refused_whatever_they_name(self):
        names = {"nul": f"{D}/a\x00b.jar", "backslash": f"{D}\\{STEM}.jar", "absolute": "/" + self.named(".jar"),
                 "dot dot": f"{D}/../{STEM}.jar", "dot": f"./{self.named('.jar')}", "empty segment": f"{D}//{STEM}.jar",
                 "drive": "C:/" + self.named(".jar"), "unc": "//host/share/" + self.named(".jar"),
                 "trailing dot": self.named(".jar") + ".", "trailing space": self.named(".jar") + " ",
                 "device": f"{D}/CON", "device with extension": f"{D}/nul.jar", "aux dir": f"aux/{D}/{STEM}.jar",
                 "newline": self.named(".jar") + "\nx", "bell": self.named(".jar") + "\a",
                 "right to left override": self.named("\u202e.jar"), "zero width": self.named("\u200b.jar"),
                 "colon stream": self.named(".jar") + ":stream", "tilde short name": f"{D}/A-1~1.JAR"}
        for label, name in names.items():
            with self.subTest(label):
                data, res = self.judge(self.one_extra(name))
                self.refused(res)
                self.assertNotIn("unexpectedly", res.err)
                self.assertNotIn("Traceback", res.err)

    def test_the_name_of_a_gated_file_with_a_changed_segment_is_not_the_gated_file(self):
        for old, new in ((".jar", ".jaR"), ("1.0.0", "1.0.0 "), ("eu", "EU"), ("caps", "caps.")):
            with self.subTest(new):
                entries = [Entry(n.replace(old, new, 1) if n.endswith(".jar") else n, d, method=8)
                           for n, d in self.bundle_entries().items()]
                data, res = self.judge(entries)
                self.refused(res)

    def test_the_file_name_in_a_bundle_that_has_a_wrong_directory_depth_is_refused(self):
        for name in (f"eu/exeris/caps/1.0.0/{STEM}.jar", f"{D}/sub/{STEM}.jar", f"{STEM}.jar", f"exeris/caps/a/1.0.0/{STEM}.jar",
                     f"x/{D}/{STEM}.jar"):
            with self.subTest(name):
                data, res = self.judge(self.one_extra(name))
                self.refused(res)
                self.assertNotIn("unexpectedly", res.err)

    def test_an_undecodable_name_is_one_finding_not_a_crash(self):
        entries = self.entries()
        entries.append(Entry(b"\xff\xfe/x.jar", b"x"))
        data, res = self.judge(entries)
        self.refused(res)
        self.assertNotIn("unexpectedly", res.err)

    @known_defect("undecodable-utf8-name", "a UTF-8-flagged entry name that is not UTF-8 ends in the generic unexpected-failure line "
                  "instead of a `central bundle:` reason; check_release_readiness.py:judge_private_copy catches only BadZipFile "
                  "around zipfile.ZipFile(copy)")
    def test_an_undecodable_utf8_flagged_name_is_one_central_bundle_line(self):
        entries = self.entries()
        entries.append(Entry(b"\xff\xfe/x.jar", b"x", flags=0x800))
        data, res = self.judge(entries)
        self.assert_layout_refusal(entries, "")
        self.assertNotIn("unexpectedly", res.err)
