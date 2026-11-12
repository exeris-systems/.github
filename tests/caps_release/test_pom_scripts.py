"""The scripts that read a POM as XML: the hostile-document refusals, the POM version and the SNAPSHOT scan."""
from __future__ import annotations

import os
import time
import unittest

import caps_release_helpers as h
from caps_release_helpers import pom

NS = "http://maven.apache.org/POM/4.0.0"

BOMB = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaaaaaaaaaaaa">'
        + "".join(f'<!ENTITY {c} "' + f"&{p};" * 10 + '">' for p, c in zip("abcdefgh", "bcdefghi"))
        + ']><project><version>&i;</version></project>')
XXE = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY x SYSTEM "file:///etc/hostname">]>'
       '<project><version>&x;</version><profiles><profile><id>&x;</id></profile></profiles></project>')


class XmlHostile(h.Case):
    """Entity expansion and external entities: refused, bounded in time, and never read from disk."""
    scripts = {
        "check_release_profile": lambda self, f: ["--pom", f],
        "check_pom_version": lambda self, f: ["--pom", f, "--want", "1.0.0"],
        "scan_snapshots": lambda self, f: ["--effective-pom", f, "--dependencies", self.write("deps", ""), "--upload", "true"],
    }

    def test_billion_laughs_is_refused_in_bounded_time(self):
        f = self.write("bomb.xml", BOMB)
        for name, args in self.scripts.items():
            with self.subTest(name):
                start = time.monotonic()
                res = h.run_proc(name, args(self, f), timeout=30)
                self.assertLess(time.monotonic() - start, 20)
                self.refused(res)

    def test_external_entity_is_not_read(self):
        f = self.write("xxe.xml", XXE)
        with open("/etc/hostname", encoding="utf-8") as fh:
            secret = fh.read().strip()
        for name, args in self.scripts.items():
            with self.subTest(name):
                res = h.run_proc(name, args(self, f), timeout=30)
                self.assertNotIn(secret, res.out + res.err) if secret else None
                self.refused(res)

    def test_unreadable_and_malformed_pom_is_refused_by_every_script(self):
        for body in ("", "<project>", "not xml", "<a></b>", "\x00"):
            f = self.write("bad.xml", body)
            for name, args in self.scripts.items():
                with self.subTest(name, body=body):
                    self.refused(self.both(name, args(self, f)))
        for name, args in self.scripts.items():
            with self.subTest(name, case="missing"):
                self.refused(self.both(name, args(self, self.path("absent.xml"))))
            with self.subTest(name, case="directory"):
                self.refused(self.both(name, args(self, self.tmp)))


class PomVersion(h.Case):
    S = "check_pom_version"

    def run_check(self, body, want="1.2.3", ns=""):
        f = self.write("pom.xml", pom(body, ns))
        return self.both(self.S, ["--pom", f, "--want", want])

    def test_own_version_matches(self):
        res = self.run_check("<version>1.2.3</version>")
        self.accepted(res)
        self.assertIn("pom version 1.2.3 matches the tag", res.out)

    def test_namespaced_whitespace_and_cdata(self):
        self.accepted(self.run_check("<version>1.2.3</version>", ns=NS))
        self.accepted(self.run_check("<version>\n  1.2.3 \n</version>"))
        self.accepted(self.run_check("<version><![CDATA[1.2.3]]></version>"))

    def test_own_version_differs(self):
        for have in ("1.2.4", "1.2.3-SNAPSHOT", "v1.2.3", "1.2", "01.2.3", "1.2.3.0", "1.2.3 rc", ""):
            with self.subTest(have):
                self.refused(self.run_check(f"<version>{have}</version>"), "wrong commit")

    def test_absent_version_is_refused_and_an_inherited_one_does_not_count(self):
        self.refused(self.run_check("<artifactId>a</artifactId>"), "no <version>")
        parent = "<parent><groupId>g</groupId><artifactId>p</artifactId><version>1.2.3</version></parent>"
        self.refused(self.run_check(parent), "no <version>")

    def test_a_version_elsewhere_does_not_count(self):
        for body in ("<dependencies><dependency><version>1.2.3</version></dependency></dependencies>",
                     "<properties><version>1.2.3</version></properties>",
                     "<!-- <version>1.2.3</version> -->",
                     "<build><plugins><plugin><version>1.2.3</version></plugin></plugins></build>"):
            with self.subTest(body):
                self.refused(self.run_check(body))

    def test_own_version_wins_over_the_parent_version_whatever_the_order(self):
        parent = "<parent><version>9.9.9</version></parent>"
        self.accepted(self.run_check(parent + "<version>1.2.3</version>"))
        self.accepted(self.run_check("<version>1.2.3</version>" + parent))
        self.refused(self.run_check(parent + "<version>1.2.4</version>", want="9.9.9"))

    def test_a_property_reference_is_not_the_version(self):
        self.refused(self.run_check("<version>${revision}</version><properties><revision>1.2.3</revision></properties>"))

    def test_usage(self):
        self.assertEqual(h.run_proc(self.S, ["--pom", "x"]).rc, 2)
        self.assertEqual(h.run_main(self.S, ["--want", "1.2.3"]).rc, 2)


def eff(body="", dep_mgmt="", plugins="", ns="", version="1.2.3", parent="", extra=""):
    return pom(f"""{parent}<groupId>g</groupId><artifactId>a</artifactId><version>{version}</version>
{extra}{f'<dependencyManagement><dependencies>{dep_mgmt}</dependencies></dependencyManagement>' if dep_mgmt else ''}
{f'<dependencies>{body}</dependencies>' if body else ''}
{f'<build><plugins>{plugins}</plugins></build>' if plugins else ''}""", ns)


def dep(v):
    return f"<dependency><groupId>g</groupId><artifactId>d</artifactId><version>{v}</version></dependency>"


class ScanSnapshots(h.Case):
    S = "scan_snapshots"

    def scan(self, effective, deps="g:d:jar:1.0:compile\n", upload="true", summary=None):
        f = self.write("eff.xml", effective)
        d = self.write("deps.txt", deps)
        argv = ["--effective-pom", f, "--dependencies", d, "--upload", upload]
        if summary:
            argv += ["--summary", summary]
        return self.both(self.S, argv)

    def test_clean_build_passes_on_both_modes(self):
        for up in ("true", "false"):
            res = self.scan(eff(dep("1.0")), upload=up)
            self.accepted(res)
            self.assertIn("ok - no SNAPSHOT", res.out)

    def test_hard_hits_are_refused_on_every_run(self):
        hard = {
            "project version": eff(version="1.2.3-SNAPSHOT"),
            "parent": eff(parent="<parent><groupId>g</groupId><artifactId>p</artifactId><version>2.0-SNAPSHOT</version></parent>"),
            "plugin": eff(plugins="<plugin><artifactId>p</artifactId><version>1.0-SNAPSHOT</version></plugin>"),
            "plugin dependency": eff(plugins="<plugin><artifactId>p</artifactId><version>1.0</version><dependencies>"
                                             + dep("1.0-SNAPSHOT") + "</dependencies></plugin>"),
            "processor path": eff(plugins="<plugin><artifactId>maven-compiler-plugin</artifactId><configuration>"
                                          "<annotationProcessorPaths><path><groupId>g</groupId><artifactId>proc</artifactId>"
                                          "<version>1.0-SNAPSHOT</version></path></annotationProcessorPaths>"
                                          "</configuration></plugin>"),
            "extension": eff(extra="<build><extensions><extension><artifactId>e</artifactId>"
                                   "<version>1.0-SNAPSHOT</version></extension></extensions></build>"),
            "plugin management": eff(extra="<build><pluginManagement><plugins><plugin><artifactId>p</artifactId>"
                                           "<version>1.0-SNAPSHOT</version></plugin></plugins></pluginManagement></build>"),
            "reporting plugin": eff(extra="<reporting><plugins><plugin><artifactId>p</artifactId>"
                                          "<version>1.0-SNAPSHOT</version></plugin></plugins></reporting>"),
            "cdata": eff(version="<![CDATA[1.2.3-SNAPSHOT]]>"),
            "split by a comment": eff(version="1.2.3<!-- c -->-SNAPSHOT"),
            "namespaced": eff(version="1.2.3-SNAPSHOT", ns=NS),
        }
        for label, xml in hard.items():
            for up in ("true", "false"):
                with self.subTest(label, upload=up):
                    out = self.path("summary.md")
                    res = self.scan(xml, upload=up, summary=out)
                    self.refused(res, "SNAPSHOT pins")
                    self.assertIn("SNAPSHOT", res.out)
                    self.assertFalse(os.path.exists(out), "a hard refusal writes no summary")

    def test_soft_hits_are_refused_when_uploading(self):
        soft = {
            "declared dependency": eff(dep("1.0-SNAPSHOT")),
            "managed dependency": eff(dep_mgmt=dep("1.0-SNAPSHOT")),
            "version range with a snapshot": eff(dep("[1.0-SNAPSHOT,2.0)")),
            "range with a snapshot upper bound": eff(dep("[1.0,2.0-SNAPSHOT)")),
        }
        for label, xml in soft.items():
            with self.subTest(label):
                out = self.path("summary.md")
                res = self.scan(xml, upload="true", summary=out)
                self.refused(res, "SNAPSHOT dependencies")
                self.assertFalse(os.path.exists(out), "an uploading refusal writes no summary")
        with self.subTest("resolved list only"):
            self.refused(self.scan(eff(dep("1.0")), deps="g:d:jar:2.0-SNAPSHOT:compile\n", upload="true"), "SNAPSHOT dependencies")

    def test_soft_hits_on_a_dry_run_warn_and_write_the_summary(self):
        for label, kw in (("declared", dict(xml=eff(dep("1.0-SNAPSHOT")))),
                          ("managed", dict(xml=eff(dep_mgmt=dep("1.0-SNAPSHOT")))),
                          ("listed", dict(xml=eff(dep("1.0")), deps="g:d:jar:2.0-SNAPSHOT:compile\n"))):
            with self.subTest(label):
                out = self.write("summary.md", "# before\n")
                res = self.scan(kw["xml"], deps=kw.get("deps", "g:d:jar:1.0:compile\n"), upload="false", summary=out)
                self.accepted(res)
                self.assertIn("::warning::", res.out)
                self.assertIn("SNAPSHOT", res.out)
                with open(out) as fh:
                    text = fh.read()
                self.assertTrue(text.startswith("# before\n### WARNING: SNAPSHOT dependencies"), text)
                self.assertIn("- ", text)
                self.assertIn("SNAPSHOT", text.split("Dependencies:")[1])

    def test_dry_run_without_a_summary_flag_still_warns(self):
        res = self.scan(eff(dep("1.0-SNAPSHOT")), upload="false")
        self.accepted(res)
        self.assertIn("::warning::", res.out)

    def test_dry_run_hard_hit_is_still_refused_alongside_a_soft_one(self):
        res = self.scan(eff(dep("1.0-SNAPSHOT"), version="1.2.3-SNAPSHOT"), upload="false")
        self.refused(res, "SNAPSHOT pins")

    def test_comments_and_properties_are_ignored(self):
        xml = eff(dep("1.0"), extra="<!-- 1.0-SNAPSHOT --><properties><dep.version>1.0-SNAPSHOT</dep.version>"
                                    "<nested><x>2-SNAPSHOT</x></nested></properties>")
        for up in ("true", "false"):
            self.accepted(self.scan(xml, upload=up))

    def test_a_property_is_judged_where_it_is_consumed(self):
        xml = eff(dep("1.0-SNAPSHOT"), extra="<properties><dep.version>1.0-SNAPSHOT</dep.version></properties>")
        self.refused(self.scan(xml, upload="true"))

    def test_unreadable_inputs_are_refused(self):
        good = self.write("eff.xml", eff(dep("1.0")))
        deps = self.write("deps.txt", "")
        for argv in (["--effective-pom", self.path("absent"), "--dependencies", deps],
                     ["--effective-pom", good, "--dependencies", self.path("absent")],
                     ["--effective-pom", self.write("bad.xml", "<a>"), "--dependencies", deps],
                     ["--effective-pom", good, "--dependencies", self.tmp]):
            for up in ("true", "false"):
                with self.subTest(argv, upload=up):
                    self.refused(self.both(self.S, argv + ["--upload", up]), "cannot read")

    def test_dependency_list_with_undecodable_bytes_is_still_scanned(self):
        deps = self.write("deps.bin", b"g:d:jar:1.0:compile\n\xff\xfe g:e:jar:1.0-SNAPSHOT:compile\n", mode="wb")
        f = self.write("eff.xml", eff(dep("1.0")))
        self.refused(self.both(self.S, ["--effective-pom", f, "--dependencies", deps, "--upload", "true"]))

    def test_upload_outside_its_set_is_a_usage_error(self):
        f = self.write("eff.xml", eff())
        d = self.write("deps.txt", "")
        self.assertEqual(h.run_proc(self.S, ["--effective-pom", f, "--dependencies", d, "--upload", "maybe"]).rc, 2)
        self.assertEqual(h.run_proc(self.S, ["--effective-pom", f, "--dependencies", d]).rc, 2)

    # --- gaps ---------------------------------------------------------------------------------

    def test_a_timestamped_snapshot_dependency_is_refused_when_uploading(self):
        self.refused(self.scan(eff(dep("1.0-20260101.120000-1")), upload="true"))

    def test_a_timestamped_snapshot_plugin_is_refused(self):
        self.refused(self.scan(eff(plugins="<plugin><artifactId>p</artifactId><version>1.0-20260101.120000-1</version></plugin>"),
                               upload="false"))


if __name__ == "__main__":
    unittest.main()
