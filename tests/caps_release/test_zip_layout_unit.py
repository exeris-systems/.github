"""`layout_problem` called directly: each branch gives its own reason, so a check that another check would also catch is still tested.

Through the gate, many of these inputs are refused by `zipfile` itself or by a later check; here the function is handed the
bytes and the listed entries and must say why, in words, without raising.
"""
from __future__ import annotations

import os
import struct
import zipfile

import caps_release_helpers as h
from zip_support import Entry, build, extra_block

S = "check_release_readiness"
FILES = [("a/one.txt", b"first entry, long enough to be deflated " * 3), ("a/two.txt", b"second" * 20), ("a/three.txt", b"third" * 5)]


class Unit(h.Case):
    def setUp(self):
        super().setUp()
        self.mod = h.load(S)
        self.n = 0

    def entries(self, method=8, **kw):
        return [Entry(n, d, method=method, **kw) for n, d in FILES]

    def put(self, data):
        self.n += 1
        path = self.path(f"archive-{self.n}.zip")
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def infos(self, path):
        with zipfile.ZipFile(path) as zf:
            return zf.infolist()

    def problem(self, data, infos=None, mutate=None):
        path = self.put(data)
        listed = self.infos(path) if infos is None else infos
        if mutate:
            mutate(listed)
        return self.mod.layout_problem(path, listed)

    def expect(self, fragment, data, **kw):
        reason = self.problem(data, **kw)
        self.assertIsNotNone(reason, "a reason is given")
        self.assertIn(fragment, reason)

    @staticmethod
    def end_field(data, name, value):
        """DATA with one field of its end record replaced (the fields are named as in zip_support.build)."""
        offsets = {"disk": ("<H", 4), "cd_disk": ("<H", 6), "here": ("<H", 8), "total": ("<H", 10), "cd_size": ("<I", 12),
                   "cd_off": ("<I", 16), "comment": ("<H", 20)}
        fmt, at = offsets[name]
        out = bytearray(data)
        struct.pack_into(fmt, out, len(data) - 22 + at, value)
        return bytes(out)


class EndRecord(Unit):
    def test_a_well_formed_archive_has_no_problem_whether_stored_or_deflated(self):
        for method in (0, 8):
            with self.subTest(method):
                self.assertIsNone(self.problem(build(self.entries(method))[0]))

    def test_an_archive_with_descriptors_and_a_cp437_name_has_no_problem(self):
        self.assertIsNone(self.problem(build(self.entries(8, descriptor="sig"))[0]))
        self.assertIsNone(self.problem(build(self.entries(8, descriptor="nosig"))[0]))
        entries = self.entries()
        entries[0].name = b"caf\x82/\x80.txt"
        self.assertIsNone(self.problem(build(entries)[0]), "a name without the UTF-8 flag is cp437, as zipfile reads it")

    def test_the_minimum_archive_is_an_end_record_alone(self):
        data, _ = build([])
        self.assertEqual(len(data), 22)
        self.assertIsNone(self.problem(data, infos=[]))
        for size in (0, 4, 21):
            with self.subTest(size):
                self.expect("it has no end record", b"\0" * size, infos=[])

    def test_the_end_record_must_be_the_last_22_bytes_and_carry_no_comment(self):
        data, _ = build(self.entries())
        for label, bad in (("a trailing byte", data + b"\0"), ("a long tail", data + b"x" * 100),
                           ("a comment length with no comment", self.end_field(data, "comment", 5)),
                           ("a stub before the end record only", data[:-22] + b"\0" * 22)):
            with self.subTest(label):
                self.expect("end record is not the last 22 bytes", bad, infos=self.infos(self.put(data)))

    def test_the_end_record_describes_one_archive_of_the_listed_entries(self):
        data, _ = build(self.entries())
        cases = {"disk": self.end_field(data, "disk", 1), "central directory disk": self.end_field(data, "cd_disk", 1),
                 "here differs": self.end_field(data, "here", 2), "total differs": self.end_field(data, "total", 2),
                 "both count fewer": self.end_field(self.end_field(data, "here", 2), "total", 2),
                 "both count more": self.end_field(self.end_field(data, "here", 4), "total", 4),
                 "both count none": self.end_field(self.end_field(data, "here", 0), "total", 0)}
        for label, bad in cases.items():
            with self.subTest(label):
                self.expect("does not describe one archive of the listed entries", bad, infos=self.infos(self.put(data)))

    def test_zip64_markers_are_named_in_every_field(self):
        data, _ = build(self.entries())
        listed = self.infos(self.put(data))
        self.expect("it is a ZIP64 archive", self.end_field(data, "cd_size", 0xFFFFFFFF), infos=listed)
        self.expect("it is a ZIP64 archive", self.end_field(data, "cd_off", 0xFFFFFFFF), infos=listed)
        fake = [zipfile.ZipInfo(f"f{i}") for i in range(0xFFFF)]
        marked = self.end_field(self.end_field(data, "here", 0xFFFF), "total", 0xFFFF)
        self.expect("it is a ZIP64 archive", marked, infos=fake)
        for field in ("here", "total"):
            with self.subTest(field):
                self.assertNotIn("ZIP64", self.problem(self.end_field(data, field, 0xFFFF), infos=listed) or "")

    def test_a_zip64_locator_just_before_the_end_record_is_named(self):
        data, _ = build([], locator=True)
        self.assertEqual(len(data), 42)
        self.expect("it is a ZIP64 archive", data, infos=[])
        # the locator inside the central directory's own size, so that no sum is off
        base, _ = build(self.entries())
        listed = self.infos(self.put(base))
        cd_size = struct.unpack_from("<I", base, len(base) - 10)[0]
        hidden = base[:-22] + b"PK\x06\x07" + b"\0" * 16 + self.end_field(base, "cd_size", cd_size + 20)[-22:]
        self.expect("it is a ZIP64 archive", hidden, infos=listed)

    def test_the_central_directory_must_end_where_the_end_record_begins(self):
        data, _ = build(self.entries())
        size = struct.unpack_from("<I", data, len(data) - 10)[0]
        off = struct.unpack_from("<I", data, len(data) - 6)[0]
        listed = self.infos(self.put(data))
        for label, bad in (("offset too large", self.end_field(data, "cd_off", off + 1)), ("offset too small", self.end_field(data, "cd_off", off - 1)),
                           ("size too large", self.end_field(data, "cd_size", size + 1)), ("size too small", self.end_field(data, "cd_size", size - 1))):
            with self.subTest(label):
                self.expect("data before the entries or between them and the central directory", bad, infos=listed)


class Entries(Unit):
    def test_entries_must_follow_one_another_from_zero(self):
        data, _ = build(self.entries())
        listed = self.infos(self.put(data))
        for index in (0, 1, 2):
            for delta in (-5, 5, 1):
                with self.subTest(f"entry {index} moved by {delta}"):
                    def move(infos, i=index, d=delta):
                        infos[i].header_offset += d
                    self.expect("its entries do not follow one another from the start", data, infos=self.infos(self.put(data)), mutate=move)

    def test_the_order_of_the_listing_does_not_matter(self):
        data, _ = build(self.entries())
        self.assertIsNone(self.problem(data, mutate=lambda infos: infos.reverse()))
        self.assertIsNone(self.problem(data, mutate=lambda infos: infos.insert(0, infos.pop())))

    def test_encryption_in_each_flag_is_named(self):
        data, _ = build(self.entries())
        for bit in (0x1, 0x40, 0x2000):
            with self.subTest(hex(bit)):
                def flag(infos, b=bit):
                    infos[1].flag_bits |= b
                self.expect("an entry is encrypted", data, mutate=flag)

    def test_a_method_other_than_stored_or_deflated_is_named_and_both_are_fine(self):
        for method in (1, 6, 9, 12, 14, 99):
            with self.subTest(method):
                def set_method(infos, m=method):
                    infos[0].compress_type = m
                self.expect("other than stored or deflated", build(self.entries())[0], mutate=set_method)

    def test_a_zip64_value_in_any_field_of_an_entry_is_named(self):
        data, _ = build(self.entries())
        for field in ("compress_size", "file_size"):
            with self.subTest(field):
                def mark(infos, f=field):
                    setattr(infos[1], f, 0xFFFFFFFF)
                self.expect("an entry has a ZIP64 record", data, mutate=mark)
        def offset(infos):
            infos[1].header_offset = 0xFFFFFFFF
        self.expect("do not follow one another", data, mutate=offset)        # the contiguity check comes first
        def zip64_extra(infos):
            infos[1].extra = extra_block(1, struct.pack("<QQ", 1, 1))
        self.expect("an entry has a ZIP64 record", data, mutate=zip64_extra)

    def test_a_local_header_that_is_not_one_is_named(self):
        data, _ = build(self.entries())
        for label, bad in (("signature", b"PK\x05\x06" + data[4:]), ("zeros", b"\0\0\0\0" + data[4:])):
            with self.subTest(label):
                self.expect("a central-directory offset does not point at a local header", bad, infos=self.infos(self.put(data)))

    def test_each_disagreement_between_a_local_header_and_the_central_record_has_its_reason(self):
        cases = [("name", {"name": b"a/other.txt"}, "the local header name"), ("flags", {"flags": 0x800}, "in flags or method"),
                 ("method", {"method": 0}, "in flags or method"), ("crc", {"crc": 1}, "in size or CRC"),
                 ("compressed size", {"csize": 1}, "in size or CRC"), ("size", {"usize": 1}, "in size or CRC")]
        for label, local, fragment in cases:
            with self.subTest(label):
                entries = self.entries()
                entries[1].local = local
                data, _ = build(entries)
                self.expect(fragment, data, infos=self.infos(self.put(data)))

    def test_a_zip64_extra_field_in_a_local_header_alone_is_named(self):
        entries = self.entries()
        entries[2].extra = extra_block(1, struct.pack("<QQ", 1, 1))
        entries[2].central_extra = b""
        data, _ = build(entries)
        self.expect("an entry has a ZIP64 record", data, infos=self.infos(self.put(data)))

    def test_a_local_header_that_runs_past_the_end_of_the_file_is_cut_short(self):
        for junk in (0, 7):                                 # 22 and 29 bytes in all: fewer than the 30 of a local header
            with self.subTest(junk):
                data = b"\0" * junk + struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, 1, 1, junk, 0, 0)
                info = zipfile.ZipInfo("x")
                info.header_offset = 0
                self.expect("a local header is cut short", data, infos=[info])
        entries = self.entries()
        data, _ = build(entries)
        listed = self.infos(self.put(data))
        cut = bytearray(data)
        struct.pack_into("<H", cut, 26, 0xFFFF)                 # the first local header claims a name longer than the file
        self.expect("a local header is cut short", bytes(cut), infos=listed)
        cut = bytearray(data)
        struct.pack_into("<H", cut, 28, 0xFFFF)                 # ... or an extra field longer than the file
        self.expect("a local header is cut short", bytes(cut), infos=listed)

    def test_a_name_that_is_not_utf8_under_the_utf8_flag_is_named(self):
        entries = self.entries()
        entries[0].name = b"caf\xe9.txt"
        entries[0].flags = 0x800
        data, _ = build(entries)
        listed = self.infos(self.put(build(self.entries())[0]))
        listed[0].flag_bits = 0x800
        self.expect("a local header name cannot be decoded", data, infos=listed)

    def test_the_data_descriptor_is_compared_field_by_field_and_both_layouts_are_read(self):
        for kind in ("sig", "nosig"):
            for index in range(3):
                with self.subTest(f"{kind} field {index}"):
                    entries = self.entries(descriptor=kind)
                    data, _ = build(entries)
                    listed = self.infos(self.put(data))
                    field = ("CRC", "compress_size", "file_size")[index]
                    setattr(listed[1], field, getattr(listed[1], field) + 1)
                    self.expect("the data descriptor of", data, infos=listed)

    def test_a_descriptor_that_is_missing_because_the_listed_size_is_huge_is_named(self):
        data, _ = build(self.entries(descriptor="sig"))
        listed = self.infos(self.put(data))
        listed[2].compress_size = 10 ** 7
        self.expect("the data descriptor of", data, infos=listed)

    def test_an_entry_that_runs_into_the_central_directory_is_named(self):
        entries = self.entries(0)
        for e in entries:
            e.local = {"csize": 10 ** 6, "usize": 10 ** 6}
            e.central = {"csize": 10 ** 6, "usize": 10 ** 6}
        data, _ = build(entries)
        self.expect("an entry runs into the central directory", data, infos=self.infos(self.put(data)))

    def test_bytes_between_the_last_entry_and_the_central_directory_are_named(self):
        data, _ = build(self.entries())
        off = struct.unpack_from("<I", data, len(data) - 6)[0]
        padded = data[:off] + b"\0" * 4 + data[off:]
        padded = self.end_field(padded, "cd_off", off + 4)
        self.expect("there is data between the last entry and the central directory", padded, infos=self.infos(self.put(data)))

    def test_nothing_the_function_is_handed_makes_it_raise(self):
        data, _ = build(self.entries(descriptor="sig"))
        listed = self.infos(self.put(data))
        for field, value in (("compress_size", -5), ("header_offset", -1), ("file_size", -1), ("compress_size", 1 << 70)):
            with self.subTest(f"{field}={value}"):
                infos = self.infos(self.put(data))
                setattr(infos[0], field, value)
                reason = self.mod.layout_problem(self.put(data), infos)
                self.assertIsInstance(reason, str)
        self.assertIsNone(self.mod.layout_problem(self.put(data), listed))


if __name__ == "__main__":
    import unittest
    unittest.main()
