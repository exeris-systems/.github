"""The POM scripts against hostile input: Maven's snapshot rule, floating versions and a DOCTYPE."""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import caps_release_helpers as h
from test_pom_scripts import dep, eff

SCAN = "scan_snapshots"
TS = "1.0-20260101.120000-1"


def scan_args(case, effective, deps="g:d:jar:1.0:compile\n", upload="true", summary=None):
    argv = ["--effective-pom", case.write("eff.xml", effective), "--dependencies", case.write("deps.txt", deps), "--upload", upload]
    return argv + (["--summary", summary] if summary else [])


def prefixed(xml: str) -> str:
    """The same document with every element written as p:element under a declared prefix."""
    xml = re.sub(r"<(/?)([A-Za-z][\w.-]*)", r"<\1p:\2", xml)
    return xml.replace("<p:project", '<p:project xmlns:p="http://maven.apache.org/POM/4.0.0"', 1)


class SnapshotVersions(h.Case):
    """A timestamped snapshot is a snapshot wherever a version sits."""

    def scan(self, effective, deps="g:d:jar:1.0:compile\n", upload="true"):
        return self.both(SCAN, scan_args(self, effective, deps, upload))

    def test_a_timestamped_snapshot_in_each_place_a_version_sits(self):
        parent = f"<parent><groupId>g</groupId><artifactId>p</artifactId><version>{TS}</version></parent>"
        places = {
            "project": (eff(version=TS), "SNAPSHOT pins"),
            "parent": (eff(parent=parent), "SNAPSHOT pins"),
            "plugin": (eff(plugins=f"<plugin><artifactId>p</artifactId><version>{TS}</version></plugin>"), "SNAPSHOT pins"),
            "plugin dependency": (eff(plugins="<plugin><artifactId>p</artifactId><version>1.0</version><dependencies>"
                                              + dep(TS) + "</dependencies></plugin>"), "SNAPSHOT pins"),
            "extension": (eff(extra=f"<build><extensions><extension><artifactId>e</artifactId><version>{TS}</version>"
                                    "</extension></extensions></build>"), "SNAPSHOT pins"),
            "annotation processor path": (eff(plugins="<plugin><artifactId>maven-compiler-plugin</artifactId><configuration>"
                                                      "<annotationProcessorPaths><path><groupId>g</groupId><artifactId>proc</artifactId>"
                                                      f"<version>{TS}</version></path></annotationProcessorPaths></configuration></plugin>"),
                                          "SNAPSHOT pins"),
            "dependency": (eff(dep(TS)), "SNAPSHOT dependencies"),
            "managed dependency": (eff(dep_mgmt=dep(TS)), "SNAPSHOT dependencies"),
        }
        for label, (xml, fragment) in places.items():
            for upload in ("true", "false"):
                with self.subTest(label, upload=upload):
                    res = self.scan(xml, upload=upload)
                    if fragment == "SNAPSHOT pins" or upload == "true":
                        self.refused(res, fragment)
                    else:
                        self.accepted(res)
                        self.assertIn("::warning::", res.out)
                    self.assertIn(TS, res.out)

    def test_a_snapshot_in_any_letter_case_and_without_a_dash(self):
        for v in ("1.0-snapshot", "1.0-Snapshot", "1.0-SNAPSHOT", "1.0-sNaPsHoT", "1.0.SNAPSHOT", "1.0snapshot", "SNAPSHOT",
                  "snapshot", "x-SNAPSHOT-SNAPSHOT"):
            with self.subTest(v):
                self.refused(self.scan(eff(version=v), upload="false"), "SNAPSHOT pins")
                self.refused(self.scan(eff(dep(v)), upload="true"), "SNAPSHOT dependencies")

    def test_a_dependency_list_line_with_a_timestamped_version_is_a_soft_hit(self):
        for line in (f"g:d:jar:{TS}:compile", f"g:d:jar:sources:{TS}:compile", f"    g:d:jar:{TS}:test  -- module x",
                     "g:d:jar:1.0-snapshot:compile", "g:d:jar:1.0-SNAPSHOT:compile"):
            with self.subTest(line):
                self.refused(self.scan(eff(dep("1.0")), deps=line + "\n", upload="true"), "SNAPSHOT dependencies")
                res = self.scan(eff(dep("1.0")), deps=line + "\n", upload="false")
                self.accepted(res)
                self.assertIn("::warning::", res.out)

    def test_what_is_not_a_snapshot_by_maven_s_rule_is_not_one_here(self):
        for v in ("1.0-20260101.120000", "1.0-2026.120000-1", "1.0-20260101.12000-1", "1.0-20260101.1200000-1",
                  "1.0-20260101.120000-", "1.0-20260101.120000-x", "20260101.120000-1", "1.0-2026010a.120000-1",
                  "1.0-SNAPSH0T", "1.0-SNAPSHO", "1.0.snapshots", "1.0-20260101.120000-1-final", "1.0-final-20260101.120000"):
            for upload in ("true", "false"):
                with self.subTest(v, upload=upload):
                    res = self.scan(eff(dep(v)), upload=upload)
                    self.accepted(res)
                    self.assertNotIn("::warning::", res.out)
                    self.accepted(self.scan(eff(version=v), upload=upload))

    def test_a_dependency_list_line_is_judged_by_its_version_fields(self):
        for line in ("g:d:jar:1.0-20260101.120000:compile", "g:d:jar:1.0-2026.120000-1:compile", "g:d:jar:20260101.120000-1:compile"):
            with self.subTest(line):
                self.accepted(self.scan(eff(dep("1.0")), deps=line + "\n"))

    def test_a_version_that_contains_the_upper_case_literal_is_refused_though_maven_calls_it_final(self):
        """Characterised: the literal `-SNAPSHOT` anywhere in a version is refused too, which is stricter than Maven's rule."""
        for v in ("1.0-SNAPSHOTS", "1.0-SNAPSHOT-1", "1.0-SNAPSHOT.final"):
            with self.subTest(v):
                self.refused(self.scan(eff(dep(v)), upload="true"), "SNAPSHOT dependencies")
                self.refused(self.scan(eff(version=v), upload="false"), "SNAPSHOT pins")

    def test_an_artifact_id_or_name_containing_snapshot_is_not_a_snapshot(self):
        xml = eff(extra="<name>snapshot tools</name><description>about snapshots</description>",
                  body=f"<dependency><groupId>snapshot.group</groupId><artifactId>my-snapshot-lib</artifactId>"
                       f"<version>1.0</version></dependency><dependency><groupId>g</groupId><artifactId>Snapshot</artifactId>"
                       f"<version>2.0</version></dependency>")
        for upload in ("true", "false"):
            res = self.scan(xml, "g:lib-snapshot:jar:1.0:compile\n", upload)
            self.accepted(res)
            self.assertIn("ok - no SNAPSHOT", res.out)

    def test_a_literal_dash_snapshot_in_any_element_text_is_still_a_hard_hit(self):
        """Characterised: the literal is judged wherever it sits, so a description that says it is refused, on the safe side."""
        self.refused(self.scan(eff(extra="<description>built from 1.0-SNAPSHOT</description>"), upload="false"), "SNAPSHOT pins")

    def test_a_snapshot_inside_an_enforcer_rule_is_not_a_version_of_the_build(self):
        rule = ("<plugin><artifactId>maven-enforcer-plugin</artifactId><version>3.5.0</version><configuration><rules>"
                "<requireMavenVersion><version>[3.6.3,)</version></requireMavenVersion>"
                "<requireJavaVersion><version>[21,)</version></requireJavaVersion></rules></configuration></plugin>")
        for upload in ("true", "false"):
            res = self.scan(eff(plugins=rule), upload=upload)
            self.accepted(res)
            self.assertNotIn("floating", res.out)


FLOATING = ["LATEST", "RELEASE", "(1.0)", "[1.0,2.0)", "(,1.0]", "[1.0,)", "(1.0,2.0)", "[1.0,2.0]", "1.0,2.0", " LATEST ", "[1.0]", "[ 1.0 , 2.0 )"]


class FloatingVersions(h.Case):
    def scan(self, effective, deps="g:d:jar:1.0:compile\n", upload="true", summary=None):
        return self.both(SCAN, scan_args(self, effective, deps, upload, summary))

    def test_every_floating_form_is_refused_on_upload_and_warned_on_a_dry_run(self):
        for v in FLOATING:
            with self.subTest(repr(v)):
                res = self.scan(eff(dep(v)), upload="true")
                self.refused(res, "Floating versions")
                self.assertEqual(len(res.errors()), 1, "a floating hit alone is one error")
                self.assertIn("floating version: <version>", res.out)
                summary = self.path("summary.md")
                if os.path.exists(summary):
                    os.remove(summary)
                res = self.scan(eff(dep(v)), upload="false", summary=summary)
                self.accepted(res)
                self.assertIn("::warning::", res.out)
                with open(summary) as fh:
                    text = fh.read()
                self.assertIn("### WARNING: floating versions", text)
                self.assertIn(v.strip(), text)
                self.assertNotIn("SNAPSHOT dependencies", text)

    def test_a_hard_pin_written_as_a_range_is_treated_as_floating(self):
        """Characterised: `[1.0]` selects exactly 1.0, but the rule is the syntax, so it is refused on upload (the safe side)."""
        res = self.scan(eff(dep("[1.0]")), upload="true")
        self.refused(res, "Floating versions")

    def test_floating_versions_in_every_place_a_version_sits(self):
        parent = "<parent><groupId>g</groupId><artifactId>p</artifactId><version>[1,2)</version></parent>"
        for label, xml in {
            "project": eff(version="LATEST"), "parent": eff(parent=parent),
            "plugin": eff(plugins="<plugin><artifactId>p</artifactId><version>RELEASE</version></plugin>"),
            "plugin dependency": eff(plugins="<plugin><artifactId>p</artifactId><version>1.0</version><dependencies>"
                                             + dep("[1,2)") + "</dependencies></plugin>"),
            "extension": eff(extra="<build><extensions><extension><artifactId>e</artifactId><version>LATEST</version>"
                                   "</extension></extensions></build>"),
            "managed dependency": eff(dep_mgmt=dep("(,1.0]")),
            "annotation processor path": eff(plugins="<plugin><artifactId>c</artifactId><configuration><annotationProcessorPaths>"
                                                     "<path><groupId>g</groupId><artifactId>x</artifactId><version>LATEST</version>"
                                                     "</path></annotationProcessorPaths></configuration></plugin>"),
        }.items():
            with self.subTest(label):
                self.refused(self.scan(xml, upload="true"), "Floating versions")
                self.accepted(self.scan(xml, upload="false"))

    def test_a_range_inside_an_enforcer_rule_or_a_property_is_not_flagged(self):
        rule = ("<plugin><artifactId>maven-enforcer-plugin</artifactId><version>3.5.0</version><configuration><rules>"
                "<requireMavenVersion><version>[3.6.3,)</version></requireMavenVersion></rules></configuration></plugin>")
        xml = eff(dep("1.0"), plugins=rule, extra="<properties><range>[1,2)</range><v>LATEST</v></properties>")
        for upload in ("true", "false"):
            res = self.scan(xml, upload=upload)
            self.accepted(res)
            self.assertNotIn("floating", res.out)

    def test_a_snapshot_and_a_range_together_report_both_on_upload_and_both_in_the_summary(self):
        xml = eff(dep("1.0-SNAPSHOT") + dep("[1,2)"))
        res = self.scan(xml, upload="true")
        self.refused(res, "SNAPSHOT dependencies")
        self.assertEqual(len(res.errors()), 2)
        self.assertIn("Floating versions", "\n".join(res.errors()))
        summary = self.path("summary.md")
        self.accepted(self.scan(xml, upload="false", summary=summary))
        with open(summary) as fh:
            text = fh.read()
        self.assertIn("### WARNING: SNAPSHOT dependencies", text)
        self.assertIn("### WARNING: floating versions", text)

    def test_a_hard_hit_wins_over_a_floating_one_and_writes_no_summary(self):
        summary = self.path("summary.md")
        self.refused(self.scan(eff(dep("[1,2)"), version="1.0-SNAPSHOT"), upload="false", summary=summary), "SNAPSHOT pins")
        self.assertFalse(os.path.exists(summary))

    def test_a_clean_build_writes_no_summary(self):
        summary = self.path("summary.md")
        self.accepted(self.scan(eff(dep("1.0")), upload="false", summary=summary))
        self.assertFalse(os.path.exists(summary))

    def test_the_summary_is_appended_to(self):
        summary = self.write("summary.md", "# earlier\n")
        self.accepted(self.scan(eff(dep("LATEST")), upload="false", summary=summary))
        with open(summary) as fh:
            self.assertTrue(fh.read().startswith("# earlier\n### WARNING: floating"))


def _java_truth(versions):
    """What Maven's own ArtifactUtils.isSnapshot answers, or None when no Maven installation is at hand."""
    mvn = shutil.which("mvn")
    java = shutil.which("java")
    if not mvn or not java:
        return None
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(mvn))), "lib")
    jars = glob.glob(os.path.join(lib, "maven-artifact*.jar")) + glob.glob("/usr/share/java/maven*-artifact*.jar")
    jars = [os.path.realpath(j) for j in jars]
    if not jars:
        return None
    work = tempfile.mkdtemp(prefix="maven-truth-")
    try:
        import base64
        with open(os.path.join(work, "T.java"), "w") as fh:
            fh.write("import org.apache.maven.artifact.ArtifactUtils;import java.nio.file.*;import java.util.*;"
                     "public class T{public static void main(String[] a)throws Exception{for(String l:Files.readAllLines(Path.of(a[0])))"
                     "System.out.println(ArtifactUtils.isSnapshot(new String(Base64.getDecoder().decode(l),\"UTF-8\")));}}")
        with open(os.path.join(work, "in.txt"), "w") as fh:
            fh.write("\n".join(base64.b64encode(v.encode("utf-8", "surrogatepass")).decode() for v in versions) + "\n")
        done = subprocess.run([java, "-cp", jars[0], os.path.join(work, "T.java"), os.path.join(work, "in.txt")],
                              capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            return None
        return [ln == "true" for ln in done.stdout.split()]
    finally:
        shutil.rmtree(work, ignore_errors=True)


# (version, ArtifactUtils.isSnapshot) as Maven's source states it: SNAPSHOT at the end in any case, or the pattern
# ^(.*)-(\d{8}\.\d{6})-(\d+)$ over the whole string with `.` not matching a line terminator.
MAVEN_TABLE = [
    ("1.0-SNAPSHOT", True), ("1.0-snapshot", True), ("1.0-Snapshot", True), ("SNAPSHOT", True), ("snapshot", True),
    ("1.0.SNAPSHOT", True), ("1.0snapshot", True), ("1.0-SNAPSHOTS", False), ("1.0-SNAPSHOT-1", False), ("1.0-SNAPSHO", False),
    ("1.0", False), ("", False), ("SNAP", False), ("1.0-20260101.120000-1", True), ("1.0-20260101.120000-123456789", True),
    ("-20260101.120000-1", True), ("a-b-20260101.120000-1", True), ("1.0-20260101.120000", False), ("1.0-2026.120000-1", False),
    ("1.0-20260101.12000-1", False), ("1.0-20260101.1200000-1", False), ("1.0-20260101.120000-", False),
    ("1.0-20260101.120000-1\n", False), ("1.0-20260101.120000-1 ", False), (" 1.0-20260101.120000-1", True),
    ("1.0-2026010a.120000-1", False), ("1.0-20260101,120000-1", False),
    ("1.0-\uff12\uff10\uff12\uff16\uff10\uff11\uff10\uff11.\uff11\uff12\uff10\uff10\uff10\uff10-1", False),
    ("1.0-20260101.120000-\u0661", False), ("1.0-SNAPSHOT\n", False),
    ("a\nb-20260101.120000-1", False), ("1.0-202601011.120000-1", False), ("1.0-20260101.1200001-1", False),
]
# Java's `.` does not match these line terminators, Python's does: the scripts call these snapshots, Maven does not.
STRICTER = ["a\u2028b-20260101.120000-1", "a\u2029b-20260101.120000-1", "a\u0085b-20260101.120000-1", "a\rb-20260101.120000-1"]


LONG_S = ["1.0-\u017fNAPSHOT", "1.0-SNAP\u017fHOT", "1.0-\u017fnapshot"]
_TRUTH: dict = {}


def java_truth(versions):
    """Maven's answer for each version, computed once for the whole set of versions this module asks about."""
    if "all" not in _TRUTH:
        every = [v for v, _ in MAVEN_TABLE] + STRICTER + LONG_S
        answers = _java_truth(every)
        _TRUTH["all"] = None if answers is None else dict(zip(every, answers))
    if _TRUTH["all"] is None:
        return None
    return [_TRUTH["all"][v] for v in versions]


class ScanGaps(h.Case):
    """Places a weaker scan would miss: ranges that carry a timestamped bound, odd dependency lines, error counts."""

    def scan(self, effective, deps="g:d:jar:1.0:compile\n", upload="true", summary=None):
        return self.both(SCAN, scan_args(self, effective, deps, upload, summary))

    def test_a_timestamped_snapshot_inside_a_range_is_a_snapshot_dependency(self):
        for v in (f"[1.0-20260101.120000-1,2.0)", f"(1.0,2.0-20260101.120000-1]", f"[ 1.0 , 2.0-20260101.120000-1 ]",
                  f"[1.0,2.0-20260101.120000-1)", f"(1.0-20260101.120000-1,)", f"[1.0-20260101.120000-1]"):
            with self.subTest(v):
                res = self.scan(eff(dep(v)), upload="true")
                self.refused(res, "SNAPSHOT dependencies")
                self.assertEqual(len(res.errors()), 2, "the snapshot and the range are both reported")

    def test_one_error_for_each_class_that_is_present(self):
        res = self.scan(eff(dep("1.0-SNAPSHOT")), upload="true")
        self.assertEqual(len(res.errors()), 1)
        self.assertIn("SNAPSHOT dependencies", res.errors()[0])
        summary = self.path("s.md")
        self.accepted(self.scan(eff(dep("1.0-SNAPSHOT")), upload="false", summary=summary))
        with open(summary) as fh:
            text = fh.read()
        self.assertIn("SNAPSHOT dependencies", text)
        self.assertNotIn("floating", text)

    def test_dependency_list_lines_of_every_shape(self):
        ts = "1.0-20260101.120000-1"
        for line in (f"g:d:jar:{ts}\n", f"g:d:jar::{ts}:compile\n", f"g:d:jar:{ts}::compile\n", f"g:d:jar:{ts} :compile\n"):
            with self.subTest(line):
                self.refused(self.scan(eff(dep("1.0")), deps=line), "SNAPSHOT dependencies")
        for line in ("g:d:jar::compile\n", "g:lib-snapshot:jar:1.0:compile\n", "group-snapshot:d:jar:1.0:compile\n",
                     "g:d:jar-snapshot:1.0:compile\n"):
            with self.subTest(line):
                self.accepted(self.scan(eff(dep("1.0")), deps=line))

    def test_a_dependency_list_with_undecodable_bytes_is_scanned_not_rejected_for_its_encoding(self):
        deps = self.write("deps.bin", b"\xff\xfe g:e:jar:1.0-SNAPSHOT:compile\n", mode="wb")
        res = self.both(SCAN, ["--effective-pom", self.write("e.xml", eff(dep("1.0"))), "--dependencies", deps, "--upload", "true"])
        self.refused(res, "SNAPSHOT dependencies")

    def test_a_version_with_the_literal_in_a_later_segment_is_a_hit_on_a_resolved_line_too(self):
        self.refused(self.scan(eff(dep("1.0")), deps="g:d:jar:1.0-SNAPSHOT-1:compile\n"), "SNAPSHOT dependencies")


class MalformedPoms(h.Case):
    """A POM that is not well-formed is reported as unreadable, by name, and not as an unexpected failure."""

    def test_the_message_names_the_problem(self):
        bad = self.write("bad.xml", "<project><a></project>")
        deps = self.write("deps", "")
        for name, argv, fragment in (("check_release_profile", ["--pom", bad], "cannot be read as a POM"),
                                     ("check_pom_version", ["--pom", bad, "--want", "1.0.0"], "cannot be read as a POM"),
                                     ("scan_snapshots", ["--effective-pom", bad, "--dependencies", deps, "--upload", "true"], "cannot read its inputs")):
            with self.subTest(name):
                res = self.both(name, argv)
                self.refused(res, fragment)
                self.assertNotIn("unexpectedly", res.err)


class MavenRule(h.Case):
    """The scripts' snapshot test is Maven's ArtifactUtils.isSnapshot, as far as a table can show."""

    def test_both_scripts_implement_the_table(self):
        for name in (SCAN, "check_release_readiness"):
            module = h.load(name)
            for version, want in MAVEN_TABLE:
                if "\n" in version and version != "1.0-SNAPSHOT\n":
                    continue            # see the next test: a line terminator inside the prefix
                with self.subTest(script=name, version=version):
                    self.assertEqual(module.is_snapshot(version), want)

    def test_a_line_terminator_in_the_prefix_makes_the_script_stricter_than_maven_never_laxer(self):
        for name in (SCAN, "check_release_readiness"):
            module = h.load(name)
            for version in STRICTER:
                with self.subTest(script=name, version=version):
                    self.assertTrue(module.is_snapshot(version))
        truth = java_truth(STRICTER)
        if truth is not None:
            self.assertEqual(truth, [False] * len(STRICTER), "Maven's `.` does not match a line terminator")

    def test_the_two_scripts_agree_with_each_other(self):
        a, b = h.load(SCAN), h.load("check_release_readiness")
        for version, _ in MAVEN_TABLE + [("1.0-\u017fNAPSHOT", True)] + [(v, True) for v in STRICTER]:
            with self.subTest(version):
                self.assertEqual(a.is_snapshot(version), b.is_snapshot(version))

    def truth(self):
        versions = [v for v, _ in MAVEN_TABLE]
        truth = java_truth(versions)
        if truth is None:
            self.skipTest("no Maven installation with maven-artifact and a JDK on this machine")
        self.assertEqual(len(truth), len(versions))
        return dict(zip(versions, truth))

    def test_the_table_is_what_maven_answers(self):
        truth = self.truth()
        for version, want in MAVEN_TABLE:
            with self.subTest(version):
                self.assertEqual(truth[version], want, "the table is Maven's rule, not a guess")

    def test_the_scripts_never_call_a_snapshot_final_where_maven_would_not(self):
        """The direction that matters: a version Maven treats as a snapshot must be a snapshot here too."""
        truth = self.truth()
        for name in (SCAN, "check_release_readiness"):
            module = h.load(name)
            for version, maven in truth.items():
                if maven:
                    with self.subTest(script=name, version=version):
                        self.assertTrue(module.is_snapshot(version))

    def test_the_case_folding_of_the_suffix_is_maven_s(self):
        versions = LONG_S
        truth = java_truth(versions)
        if truth is None:
            self.skipTest("no Maven installation with maven-artifact and a JDK on this machine")
        self.assertEqual(truth, [True, True, True])
        for name in (SCAN, "check_release_readiness"):
            module = h.load(name)
            for version in versions:
                self.assertTrue(module.is_snapshot(version), f"{name}: {version!r}")

    def test_a_long_s_version_is_a_snapshot_to_maven_and_is_refused_by_the_scan_as_non_ascii(self):
        res = h.run_main(SCAN, scan_args(self, eff(version="1.0-\u017fNAPSHOT"), upload="true"))
        self.refused(res, "SNAPSHOT pins")
        self.assertIn("is not ASCII", res.out)
        self.assertIn("1.0-\\u017fNAPSHOT", res.out, "the character is shown as an escape")


class Doctype(h.Case):
    """A DOCTYPE with no entity at all is refused by every script that reads a POM."""

    CASES = {
        "bare": '<?xml version="1.0"?><!DOCTYPE project><project><version>1.0.0</version></project>',
        "with a system id": '<?xml version="1.0"?><!DOCTYPE project SYSTEM "x.dtd"><project><version>1.0.0</version></project>',
        "empty internal subset": '<?xml version="1.0"?><!DOCTYPE project []><project><version>1.0.0</version></project>',
        "an internal entity": '<?xml version="1.0"?><!DOCTYPE project [<!ENTITY a "b">]><project><version>1.0.0</version></project>',
        "after a comment": '<?xml version="1.0"?><!-- c --><!DOCTYPE project><project><version>1.0.0</version></project>',
        "parameter entity": '<?xml version="1.0"?><!DOCTYPE project [<!ENTITY % p "x">]><project><version>1.0.0</version></project>',
    }
    SCRIPTS = {
        "check_release_profile": lambda self, f: ["--pom", f],
        "check_pom_version": lambda self, f: ["--pom", f, "--want", "1.0.0"],
        "scan_snapshots": lambda self, f: ["--effective-pom", f, "--dependencies", self.write("deps", ""), "--upload", "true"],
    }

    def test_every_script_refuses_every_doctype(self):
        for label, xml in self.CASES.items():
            f = self.write("doctype.xml", xml)
            for name, args in self.SCRIPTS.items():
                with self.subTest(label, script=name):
                    res = self.both(name, args(self, f))
                    self.refused(res, "DOCTYPE")
                    self.assertEqual(len(res.errors()), 1)

    def test_a_document_without_a_doctype_is_read(self):
        f = self.write("ok.xml", '<?xml version="1.0"?><!-- DOCTYPE is only a word here --><project><version>1.0.0</version></project>')
        self.accepted(self.both("check_pom_version", ["--pom", f, "--want", "1.0.0"]))

    def test_a_doctype_word_in_text_or_cdata_is_not_a_declaration(self):
        f = self.write("ok.xml", '<project><version>1.0.0</version><description><![CDATA[<!DOCTYPE x>]]></description></project>')
        self.accepted(self.both("check_pom_version", ["--pom", f, "--want", "1.0.0"]))


if __name__ == "__main__":
    unittest.main()
