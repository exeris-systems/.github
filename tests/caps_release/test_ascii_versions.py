"""A release version is ASCII: any other character is a hard refusal wherever a version is read.

Maven's SNAPSHOT test folds characters that Python's `str.lower()` does not (U+017F), so a non-ASCII version is refused
before the snapshot question is asked, in `resolve_release` (the version input and the tag), in `scan_snapshots` (every
`<version>` element and every dependency field) and in the readiness gate (the coordinate of the POM and the base name of the
files).
"""
from __future__ import annotations

import unittest

import caps_release_helpers as h
from readiness_support import GROUP, Fixture, pom_xml
from test_pom_adversarial import scan_args
from test_pom_scripts import dep, eff
from test_resolve_release import BRANCH, TAG, argv

NON_ASCII = {
    "long s": "1.0-ſNAPSHOT", "long s release": "1.0.0ſ", "fullwidth digits": "１.２.３",
    "accent": "1.0.0-é", "kelvin": "1.0.0-K", "dotless i": "1.0.0-ı", "combining": "1.0.0́",
    "right to left": "1.0.0‏", "arabic digit": "1.0.٣", "emoji": "1.0.0-\U0001F680", "non-breaking space": "1.0.0 ",
}


class Resolve(h.Case):
    S = "resolve_release"

    @staticmethod
    def reason(version):
        """A format character is refused by the check that every input passes first; any other non-ASCII one by the ASCII rule."""
        import unicodedata
        if any(unicodedata.category(c) in ("Cf", "Cn", "Zl", "Zp", "Cc") for c in version):
            return "non-printing or unassigned character"
        return "the version holds a non-ASCII character; a release version is ASCII only."

    def test_a_non_ascii_version_input_is_refused_on_a_dispatch(self):
        for label, version in NON_ASCII.items():
            with self.subTest(label):
                res = self.both(self.S, argv(BRANCH, version=version))
                self.refused(res, self.reason(version))
                self.assertEqual(len(res.errors()), 1, res)

    def test_a_non_ascii_version_input_beside_a_valid_tag_is_refused_before_the_tag_is_compared(self):
        for label, version in NON_ASCII.items():
            with self.subTest(label):
                res = self.both(self.S, argv(TAG, version=version))
                self.refused(res, self.reason(version))
                self.assertNotIn("disagree", res.err)
                self.assertEqual(len(res.errors()), 1, res)

    def test_a_non_ascii_tag_is_not_a_release_tag(self):
        for label, version in NON_ASCII.items():
            with self.subTest(label):
                res = self.both(self.S, argv(TAG, ref_name="v" + version, ref="refs/tags/v" + version))
                self.refused(res)
                self.assertEqual(len(res.errors()), 1, res)

    def test_nothing_is_written_for_a_refused_version(self):
        out = self.path("out")
        for argv_ in (argv(BRANCH, version="1.0.0ſ", output=out), argv(TAG, version="ſ", output=out)):
            self.refused(self.both(self.S, argv_))
        self.assertFalse(__import__("os").path.exists(out))

    def test_an_ascii_version_is_unaffected(self):
        self.accepted(self.both(self.S, argv(BRANCH, version="10.20.30")))
        self.accepted(self.both(self.S, argv(TAG, version="1.2.3")))
        self.accepted(self.both(self.S, argv(TAG, version="")))


class Scan(h.Case):
    S = "scan_snapshots"

    def scan(self, effective, deps="g:d:jar:1.0:compile\n", upload="true"):
        return h.run_main(self.S, scan_args(self, effective, deps, upload))

    def test_a_non_ascii_version_element_is_a_hard_hit_in_every_place_a_version_sits(self):
        places = {
            "project": lambda v: eff(version=v),
            "parent": lambda v: eff(parent=f"<parent><groupId>g</groupId><artifactId>p</artifactId><version>{v}</version></parent>"),
            "dependency": lambda v: eff(dep(v)),
            "managed dependency": lambda v: eff(dep_mgmt=dep(v)),
            "plugin": lambda v: eff(plugins=f"<plugin><artifactId>p</artifactId><version>{v}</version></plugin>"),
            "extension": lambda v: eff(extra=f"<build><extensions><extension><artifactId>e</artifactId><version>{v}</version>"
                                             "</extension></extensions></build>"),
            "plugin dependency": lambda v: eff(plugins="<plugin><artifactId>p</artifactId><dependencies>" + dep(v) + "</dependencies></plugin>"),
            "a version element anywhere else": lambda v: eff(extra=f"<configuration><version>{v}</version></configuration>"),
        }
        for place, make in places.items():
            for label in ("long s", "accent", "fullwidth digits"):
                for upload in ("true", "false"):
                    with self.subTest(f"{place} / {label} / upload={upload}"):
                        res = self.scan(make(NON_ASCII[label]), upload=upload)
                        self.assertEqual(res.rc, 1, res)
                        self.assertIn("is not ASCII; a release version is ASCII only", res.out)
                        self.assertTrue(res.errors(), res)

    def test_the_offending_version_is_shown_escaped(self):
        res = self.scan(eff(version="1.0-ſNAPSHOT‮"))
        self.assertIn("1.0-\\u017fNAPSHOT\\u202e", res.out)
        self.assertNotIn("‮", res.out + res.err)
        self.assertNotIn("ſ", res.out + res.err)

    def test_a_non_ascii_version_is_not_also_reported_as_something_else(self):
        res = self.scan(eff(version="1.0-ſNAPSHOT"))
        self.assertEqual(sum(1 for ln in res.out.splitlines() if "<version>" in ln), 1, res.out)

    def test_a_non_ascii_dependency_field_is_a_hard_hit(self):
        lines = {"version": "g:d:jar:1.0-ſNAPSHOT:compile\n", "scope": "g:d:jar:1.0:compïle\n",
                 "classifier": "g:d:jar:clä:1.0:compile\n", "type": "g:d:jär:1.0:compile\n"}
        for label, line in lines.items():
            for upload in ("true", "false"):
                with self.subTest(f"{label} upload={upload}"):
                    res = self.scan(eff(), deps=line, upload=upload)
                    if label == "type":
                        self.assertEqual(res.rc, 0, "the group, the artifact and the type are not version fields")
                        continue
                    self.assertEqual(res.rc, 1, res)
                    self.assertIn("has a version field that is not ASCII", res.out)
                    self.assertRegex(res.out, r"\\[xu][0-9a-f]+", "the field is shown escaped")

    def test_a_non_ascii_value_in_a_property_is_a_property_and_not_a_version(self):
        res = self.scan(eff(extra="<properties><my.version>1.0-ſ</my.version></properties>"))
        self.assertEqual(res.rc, 0, res)

    def test_ascii_versions_are_judged_as_before(self):
        self.assertEqual(self.scan(eff(version="1.2.3")).rc, 0)
        self.assertEqual(self.scan(eff(version="1.2.3-SNAPSHOT")).rc, 1)
        self.assertEqual(self.scan(eff(), deps="g:d:jar:1.0-snapshot:compile\n", upload="true").rc, 1)
        self.assertEqual(self.scan(eff(), deps="g:d:jar:1.0-snapshot:compile\n", upload="false").rc, 0)


class Gate(Fixture):
    def test_a_non_ascii_pom_version_is_refused(self):
        for label in ("long s", "accent", "fullwidth digits", "right to left"):
            with self.subTest(label):
                self.reset()
                version = NON_ASCII[label]
                self.coordinate("a-1.0.0", pom_text=pom_xml(GROUP, "a", version))
                res = self.check()
                self.refused(res, "names a coordinate that is not ASCII; a release version is ASCII only")
                self.assertNotIn("unexpectedly", res.err)

    def test_a_non_ascii_artifact_or_group_is_refused_the_same_way(self):
        for label, text in (("artifact", pom_xml(GROUP, "ä", "1.0.0")), ("group", pom_xml("eu.é", "a", "1.0.0"))):
            with self.subTest(label):
                self.reset()
                self.coordinate("a-1.0.0", pom_text=text)
                self.refused(self.check(), "is not ASCII")

    def test_a_non_ascii_file_base_name_is_refused_before_the_snapshot_question(self):
        for base in ("a-1.0-ſNAPSHOT", "a-1.0.0ſ", "a-１.0.0", "ä-1.0.0"):
            with self.subTest(base):
                self.reset()
                self.coordinate(base, pom_text=pom_xml(GROUP, "a", "1.0.0"))
                res = self.check()
                self.refused(res, f"{base} is not ASCII; a release version is ASCII only")
                self.assertNotIn("is a SNAPSHOT", "\n".join(res.errors()), "the question is not asked of a name that is refused")

    def test_a_long_s_snapshot_pom_is_refused_either_way(self):
        self.coordinate("a-1.0.0", pom_text=pom_xml(GROUP, "a", "1.0-ſNAPSHOT"))
        res = self.check()
        self.refused(res, "names a coordinate that is not ASCII")
        self.assertNotIn("declares the SNAPSHOT version", "\n".join(res.errors()), "the question is not asked of a version that is refused")

    def test_ascii_snapshots_are_still_snapshots(self):
        for version in ("1.0.0-SNAPSHOT", "1.0.0-snapshot", "1.0.0-20260101.120000-3"):
            with self.subTest(version):
                self.reset()
                self.coordinate(f"a-{version}", pom_text=pom_xml(GROUP, "a", version))
                self.refused(self.check(), "SNAPSHOT")

    def reset(self):
        import os
        import shutil
        shutil.rmtree(self.target)
        os.makedirs(self.target)


if __name__ == "__main__":
    unittest.main()
