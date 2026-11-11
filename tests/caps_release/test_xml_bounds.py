"""The five POM readers bound what they parse: at most 16 MiB and 200 levels of nesting, and a DOCTYPE is still refused."""
from __future__ import annotations

import os
import time
import unittest
import xml.etree.ElementTree as ET

import caps_release_helpers as h
from readiness_support import Fixture, pom_xml, sig_of

MAX_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 200

READERS = {
    "check_pom_version": "read_xml", "check_release_profile": "read_xml", "check_auto_publish": "read_xml",
    "scan_snapshots": "read_xml", "check_release_readiness": "read_pom",
}


def nested(levels: int, leaf: str = "x") -> str:
    return "<e>" * (levels - 1) + f"<e>{leaf}</e>" + "</e>" * (levels - 1)


def padded(size: int) -> bytes:
    head, tail = b"<project>", b"</project>"
    return head + b" " * (size - len(head) - len(tail)) + tail


class Readers(h.Case):
    big: str
    over: str

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.dir = tempfile.mkdtemp(prefix="caps-xml-")
        cls.big = os.path.join(cls.dir, "exact.xml")
        cls.over = os.path.join(cls.dir, "over.xml")
        with open(cls.big, "wb") as fh:
            fh.write(padded(MAX_BYTES))
        with open(cls.over, "wb") as fh:
            fh.write(padded(MAX_BYTES + 1))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.dir, ignore_errors=True)

    def read(self, script, path):
        return getattr(h.load(script), READERS[script])(path)

    def test_the_documented_bounds_are_the_constants(self):
        for script in READERS:
            with self.subTest(script):
                module = h.load(script)
                self.assertEqual((module.MAX_XML_BYTES, module.MAX_XML_DEPTH), (MAX_BYTES, MAX_DEPTH))

    def test_a_document_of_exactly_the_size_bound_is_read_and_one_byte_more_is_refused(self):
        for script in READERS:
            with self.subTest(script):
                self.assertEqual(self.read(script, self.big).tag, "project")
                with self.assertRaisesRegex(ET.ParseError, f"larger than {MAX_BYTES} bytes"):
                    self.read(script, self.over)

    def test_nesting_of_exactly_the_depth_bound_is_read_and_one_level_more_is_refused(self):
        for script in READERS:
            with self.subTest(script):
                ok = self.write(f"{script}-ok.xml", nested(MAX_DEPTH))
                self.assertEqual(self.read(script, ok).tag, "e")
                deep = self.write(f"{script}-deep.xml", nested(MAX_DEPTH + 1))
                with self.assertRaisesRegex(ET.ParseError, f"nested deeper than {MAX_DEPTH} elements"):
                    self.read(script, deep)

    def test_the_depth_is_the_nesting_and_not_the_number_of_elements(self):
        wide = "<p>" + "<c>x</c>" * 50000 + "</p>"
        repeated = "<p>" + nested(MAX_DEPTH - 1) * 50 + "</p>"
        for script in READERS:
            with self.subTest(script):
                self.assertEqual(self.read(script, self.write(f"{script}-wide.xml", wide)).tag, "p")
                self.assertEqual(self.read(script, self.write(f"{script}-rep.xml", repeated)).tag, "p")

    def test_a_document_nested_far_beyond_the_bound_is_refused_quickly_without_exhausting_the_stack(self):
        text = nested(100000)
        for script in READERS:
            with self.subTest(script):
                f = self.write(f"{script}-bomb.xml", text)
                start = time.monotonic()
                with self.assertRaises(ET.ParseError):
                    self.read(script, f)
                self.assertLess(time.monotonic() - start, 5)

    def test_a_doctype_is_still_refused_whatever_the_size_or_depth(self):
        for script in READERS:
            for label, text in (("tiny", '<!DOCTYPE project><project/>'),
                                ("with an entity", '<!DOCTYPE project [<!ENTITY e "x">]><project>&e;</project>'),
                                ("deep", "<!DOCTYPE p>" + nested(5))):
                with self.subTest(f"{script} {label}"):
                    with self.assertRaisesRegex(ET.ParseError, "DOCTYPE"):
                        self.read(script, self.write(f"{script}-dt.xml", text))

    def test_the_depth_counter_is_not_shared_between_documents(self):
        for script in READERS:
            with self.subTest(script):
                for _ in range(3):
                    self.assertEqual(self.read(script, self.write(f"{script}-n.xml", nested(MAX_DEPTH))).tag, "e")


class Scripts(h.Case):
    """Each script, run as the workflow runs it, ends a hostile POM in one refusal line."""

    def cases(self, doc):
        pom = self.write("pom.xml", doc)
        deps = self.write("deps.txt", "")
        return {
            "check_pom_version": ["--pom", pom, "--want", "1.0.0"],
            "check_release_profile": ["--pom", pom, "--target", "none"],
            "check_auto_publish": ["--effective-pom", pom],
            "scan_snapshots": ["--effective-pom", pom, "--dependencies", deps, "--upload", "true"],
        }

    def test_a_document_nested_past_the_bound_is_a_refusal_with_one_error_line(self):
        for name, argv in self.cases(nested(MAX_DEPTH + 1)).items():
            with self.subTest(name):
                res = self.both(name, argv)
                self.refused(res, f"nested deeper than {MAX_DEPTH} elements")
                self.assertEqual(len(res.errors()), 1, res)
                self.assertNotIn("Traceback", res.err)

    def test_a_document_over_the_size_bound_is_a_refusal_with_one_error_line(self):
        for name, argv in self.cases("<project>" + " " * (MAX_BYTES) + "</project>").items():
            with self.subTest(name):
                res = h.run_main(name, argv)
                self.refused(res, f"larger than {MAX_BYTES} bytes")
                self.assertEqual(len(res.errors()), 1, res)

    def test_a_document_at_the_depth_bound_is_not_refused_for_its_depth(self):
        for name, argv in self.cases(nested(MAX_DEPTH)).items():
            with self.subTest(name):
                res = h.run_main(name, argv)
                self.assertNotIn("nested deeper", res.err)
                self.assertNotIn("larger than", res.err)


class Gate(Fixture):
    def pom_case(self, text):
        self.coordinate("a-1.0.0", pom_text=text)
        return self.check()

    def test_the_gate_refuses_a_pom_nested_past_the_bound(self):
        deep = pom_xml(extra=nested(MAX_DEPTH))
        res = self.pom_case(deep)
        self.refused(res, f"a-1.0.0.pom cannot be read as a POM (the document is nested deeper than {MAX_DEPTH} elements)")
        self.assertNotIn("unexpectedly", res.err)

    def test_the_gate_reads_a_pom_nested_to_the_bound(self):
        self.accepted(self.pom_case(pom_xml(extra=nested(MAX_DEPTH - 2))))

    def test_the_gate_refuses_a_pom_over_the_size_bound(self):
        res = self.pom_case(pom_xml(extra="<!--" + "x" * MAX_BYTES + "-->"))
        self.refused(res, f"larger than {MAX_BYTES} bytes")
        self.assertNotIn("unexpectedly", res.err)

    def test_the_gate_refuses_a_pom_with_a_doctype(self):
        res = self.pom_case('<!DOCTYPE project [<!ENTITY e "x">]>' + pom_xml())
        self.refused(res, "DOCTYPE")


if __name__ == "__main__":
    unittest.main()
