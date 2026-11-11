"""The four scripts that read a POM as XML: release profile, POM version, SNAPSHOT scan, auto-publish."""
from __future__ import annotations

import os
import time
import unittest

import caps_release_helpers as h
from caps_release_helpers import pom

NS = "http://maven.apache.org/POM/4.0.0"

PROFILE = "<profiles><profile><id>release</id></profile></profiles>"
CENTRAL_PLUGIN = """<plugin><groupId>org.sonatype.central</groupId>
<artifactId>central-publishing-maven-plugin</artifactId>
<configuration><publishingServerId>central</publishingServerId></configuration></plugin>"""
RELEASE_WITH_CENTRAL = f"<profiles><profile><id>release</id><build><plugins>{CENTRAL_PLUGIN}</plugins></build></profile></profiles>"

BOMB = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaaaaaaaaaaaa">'
        + "".join(f'<!ENTITY {c} "' + f"&{p};" * 10 + '">' for p, c in zip("abcdefgh", "bcdefghi"))
        + ']><project><version>&i;</version></project>')
XXE = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY x SYSTEM "file:///etc/hostname">]>'
       '<project><version>&x;</version><profiles><profile><id>&x;</id></profile></profiles></project>')


class XmlHostile(h.Case):
    """Entity expansion and external entities: refused, bounded in time, and never read from disk."""
    scripts = {
        "check_release_profile": lambda self, f: ["--pom", f, "--target", "none"],
        "check_pom_version": lambda self, f: ["--pom", f, "--want", "1.0.0"],
        "scan_snapshots": lambda self, f: ["--effective-pom", f, "--dependencies", self.write("deps", ""), "--upload", "true"],
        "check_auto_publish": lambda self, f: ["--effective-pom", f],
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


class ReleaseProfile(h.Case):
    S = "check_release_profile"

    def run_check(self, body, target="none", ns="", extra=()):
        f = self.write("pom.xml", pom(body, ns))
        return self.both(self.S, ["--pom", f, "--target", target, *extra])

    def test_profile_present_for_every_target_without_central_plugin(self):
        for target in ("none", "github-packages"):
            with self.subTest(target):
                res = self.run_check(PROFILE, target)
                self.accepted(res)
                self.assertIn("Central plugin: false", res.out)

    def test_central_target_needs_plugin_and_server_id(self):
        res = self.run_check(RELEASE_WITH_CENTRAL, "central")
        self.accepted(res)
        self.assertIn("Central plugin: true", res.out)

    def test_server_id_and_artifact_id_are_compared_without_surrounding_whitespace(self):
        spaced = RELEASE_WITH_CENTRAL.replace(">central<", "> central <").replace(
            ">central-publishing-maven-plugin<", ">\n central-publishing-maven-plugin\n<")
        self.accepted(self.run_check(spaced, "central"))

    def test_output_flag_records_whether_the_central_plugin_exists(self):
        for body, want in ((PROFILE, "false"), (RELEASE_WITH_CENTRAL, "true")):
            with self.subTest(want):
                out = self.path("out")
                if os.path.exists(out):
                    os.remove(out)
                self.accepted(self.run_check(body, "none", extra=["--output", out]))
                with open(out) as fh:
                    self.assertEqual(fh.read(), f"has_central_plugin={want}\n")

    def test_output_is_appended_not_replaced(self):
        out = self.write("out", "keep=1\n")
        self.accepted(self.run_check(PROFILE, "none", extra=["--output", out]))
        with open(out) as fh:
            self.assertEqual(fh.read(), "keep=1\nhas_central_plugin=false\n")

    def test_namespace_and_prefix_are_read(self):
        self.accepted(self.run_check(PROFILE, "none", ns=NS))
        prefixed = ('<?xml version="1.0"?><p:project xmlns:p="http://maven.apache.org/POM/4.0.0"><p:profiles>'
                    '<p:profile><p:id>release</p:id></p:profile></p:profiles></p:project>')
        f = self.write("p.xml", prefixed)
        self.accepted(self.both(self.S, ["--pom", f, "--target", "none"]))

    def test_id_with_surrounding_whitespace_or_in_cdata_is_the_value_xml_says(self):
        for ident in ("  release \n", "<![CDATA[release]]>"):
            with self.subTest(ident):
                self.accepted(self.run_check(f"<profiles><profile><id>{ident}</id></profile></profiles>"))

    def test_no_release_profile(self):
        bodies = {
            "no profiles": "",
            "other id": "<profiles><profile><id>releases</id></profile></profiles>",
            "case": "<profiles><profile><id>Release</id></profile></profiles>",
            "suffix": "<profiles><profile><id>release-candidate</id></profile></profiles>",
            "empty id": "<profiles><profile><id/></profile></profiles>",
            "comment": "<profiles><profile><!-- <id>release</id> --><id>other</id></profile></profiles>",
            "comment only": "<!-- <profiles><profile><id>release</id></profile></profiles> -->",
            "id outside a profile": "<id>release</id>",
            "profile outside profiles": "<profile><id>release</id></profile>",
            "id nested deeper": "<profiles><profile><build><id>release</id></build></profile></profiles>",
            "profiles under build": "<build><profiles><profile><id>release</id></profile></profiles></build>",
            "artifact id": "<artifactId>release</artifactId>",
            "whitespace inside the word": "<profiles><profile><id>rel ease</id></profile></profiles>",
        }
        for label, body in bodies.items():
            with self.subTest(label):
                self.refused(self.run_check(body), "release")

    def test_root_modules_is_refused_in_every_form(self):
        for mods in ("<modules><module>a</module></modules>", "<modules/>", "<modules></modules>"):
            for ns in ("", NS):
                with self.subTest(mods, ns=ns):
                    self.refused(self.run_check(PROFILE + mods, "none", ns), "single-module")

    def test_modules_in_a_comment_is_not_a_modules_element(self):
        self.accepted(self.run_check(PROFILE + "<!-- <modules><module>a</module></modules> -->"))

    def test_central_target_without_the_plugin_or_the_server_id(self):
        cases = {
            "no plugin": (PROFILE, "central-publishing-maven-plugin"),
            "no server id": (PROFILE.replace("</profile>", "<build><plugins><plugin><artifactId>central-publishing-maven-plugin"
                                             "</artifactId></plugin></plugins></build></profile>"), "publishingServerId"),
            "wrong server id": (RELEASE_WITH_CENTRAL.replace(">central<", ">ossrh<"), "publishingServerId"),
            "server id case": (RELEASE_WITH_CENTRAL.replace(">central<", ">Central<"), "publishingServerId"),
            "plugin in a comment": (PROFILE + "<!-- " + CENTRAL_PLUGIN + " -->", "central-publishing-maven-plugin"),
            "similar plugin name": (RELEASE_WITH_CENTRAL.replace("central-publishing-maven-plugin",
                                                                "central-publishing-maven-plugin2"), "central-publishing"),
        }
        for label, (body, frag) in cases.items():
            with self.subTest(label):
                self.refused(self.run_check(body, "central"), frag)

    def test_every_missing_item_is_listed_on_the_one_error_line(self):
        res = self.run_check("<modules><module>a</module></modules>", "central")
        self.refused(res)
        self.assertEqual(len(res.errors()), 1)
        for frag in ("release", "single-module", "central-publishing-maven-plugin", "publishingServerId"):
            self.assertIn(frag, res.errors()[0])

    def test_refusal_writes_nothing_to_output(self):
        out = self.path("out")
        self.refused(self.run_check("", "none", extra=["--output", out]))
        self.assertFalse(os.path.exists(out))
        self.refused(self.run_check(PROFILE + "<modules/>", "none", extra=["--output", out]))
        self.assertFalse(os.path.exists(out))

    def test_target_outside_its_set_is_a_usage_error(self):
        f = self.write("pom.xml", pom(PROFILE))
        self.assertEqual(h.run_main(self.S, ["--pom", f, "--target", "maven"]).rc, 2)
        self.assertEqual(h.run_proc(self.S, ["--pom", f, "--target", "maven"]).rc, 2)
        self.assertEqual(h.run_proc(self.S, ["--pom", f]).rc, 2)

    # --- gaps: states the behaviour the contract and the error text promise ---------------------

    def test_modules_inside_the_release_profile_is_refused(self):
        body = "<profiles><profile><id>release</id><modules><module>a</module></modules></profile></profiles>"
        self.refused(self.run_check(body))

    def test_central_plugin_outside_the_release_profile_is_refused(self):
        body = PROFILE + f"<build><plugins>{CENTRAL_PLUGIN}</plugins></build>"
        self.refused(self.run_check(body, "central"))

    def test_a_dependency_named_like_the_plugin_is_not_the_plugin(self):
        body = PROFILE + ("<dependencies><dependency><artifactId>central-publishing-maven-plugin</artifactId></dependency>"
                          "</dependencies><properties><publishingServerId>central</publishingServerId></properties>")
        self.refused(self.run_check(body, "central"))


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


EFF_PLUGIN = """<plugin><groupId>org.sonatype.central</groupId><artifactId>central-publishing-maven-plugin</artifactId>
<version>0.8.0</version>{cfg}</plugin>"""


def aeff(cfg="", managed=None, ns=""):
    plugin = EFF_PLUGIN.format(cfg=cfg)
    body = f"<build><plugins>{plugin}</plugins>"
    if managed is not None:
        body += f"<pluginManagement><plugins>{EFF_PLUGIN.format(cfg=managed)}</plugins></pluginManagement>"
    return pom(body + "</build>", ns)


class AutoPublish(h.Case):
    S = "check_auto_publish"

    def check(self, xml):
        return self.both(self.S, ["--effective-pom", self.write("eff.xml", xml)])

    def test_absent_values_pass(self):
        res = self.check(aeff())
        self.accepted(res)
        self.assertIn("1 central-publishing-maven-plugin declaration(s)", res.out)

    def test_a_dependency_with_the_plugins_artifact_id_is_not_a_plugin(self):
        res = self.check(pom("<dependencies><dependency><artifactId>central-publishing-maven-plugin</artifactId>"
                             "<autoPublish>true</autoPublish></dependency></dependencies>"))
        self.accepted(res)
        self.assertIn("0 central-publishing-maven-plugin", res.out)

    def test_pom_without_the_plugin_passes(self):
        res = self.check(pom("<build><plugins><plugin><artifactId>other</artifactId><configuration>"
                             "<autoPublish>true</autoPublish></configuration></plugin></plugins></build>"))
        self.accepted(res)
        self.assertIn("0 central-publishing-maven-plugin", res.out)

    def test_good_values(self):
        for cfg in ("<configuration><autoPublish>false</autoPublish><waitUntil>validated</waitUntil></configuration>",
                    "<configuration><waitUntil>VALIDATED</waitUntil></configuration>",
                    "<configuration><waitUntil>Validated</waitUntil></configuration>",
                    "<configuration><autoPublish> false </autoPublish></configuration>",
                    "<configuration><autoPublish>false</autoPublish></configuration>",
                    "<executions><execution><configuration><autoPublish>false</autoPublish>"
                    "</configuration></execution></executions>"):
            with self.subTest(cfg):
                self.accepted(self.check(aeff(cfg)))

    def test_contrary_autopublish_values(self):
        for v in ("true", "True", "TRUE", "False", "FALSE", "", "${autoPublish}", "${env.X}", "0", "no", "falsey",
                  "false false", "fals"):
            with self.subTest(repr(v)):
                res = self.check(aeff(f"<configuration><autoPublish>{v}</autoPublish></configuration>"))
                self.refused(res, "autoPublish")

    def test_contrary_waituntil_values(self):
        for v in ("published", "PUBLISHED", "uploaded", "UPLOADED", "", "${waitUntil}", "validate", "validated2",
                  "not validated"):
            with self.subTest(repr(v)):
                self.refused(self.check(aeff(f"<configuration><waitUntil>{v}</waitUntil></configuration>")), "waitUntil")

    def test_value_given_as_an_attribute_or_empty_element_is_refused(self):
        for cfg in ('<configuration><autoPublish value="false"/></configuration>',
                    "<configuration><autoPublish/></configuration>",
                    '<configuration><waitUntil value="validated"/></configuration>'):
            with self.subTest(cfg):
                self.refused(self.check(aeff(cfg)))

    def test_execution_level_and_nested_values(self):
        cfg = "<executions><execution><configuration><autoPublish>true</autoPublish></configuration></execution></executions>"
        self.refused(self.check(aeff(cfg)), "autoPublish")
        deep = "<configuration><a><b><waitUntil>published</waitUntil></b></a></configuration>"
        self.refused(self.check(aeff(deep)), "waitUntil")

    def test_a_managed_declaration_is_checked_too(self):
        """pluginManagement with autoPublish true, beside a build plugin that says false."""
        res = self.check(aeff("<configuration><autoPublish>false</autoPublish></configuration>",
                              managed="<configuration><autoPublish>true</autoPublish></configuration>"))
        self.refused(res, "autoPublish")
        res = self.check(aeff("<configuration><autoPublish>false</autoPublish></configuration>",
                              managed="<configuration><waitUntil>published</waitUntil></configuration>"))
        self.refused(res, "waitUntil")

    def test_a_second_declaration_that_is_contrary_is_refused_among_good_ones(self):
        res = self.check(pom("<build><plugins>"
                             + EFF_PLUGIN.format(cfg="<configuration><autoPublish>false</autoPublish></configuration>")
                             + EFF_PLUGIN.format(cfg="<configuration><autoPublish>true</autoPublish></configuration>")
                             + "</plugins></build>"))
        self.refused(res)

    def test_every_contrary_value_is_reported_one_per_line(self):
        res = self.check(aeff("<configuration><autoPublish>true</autoPublish><waitUntil>published</waitUntil></configuration>"))
        self.refused(res)
        self.assertEqual(len(res.errors()), 2)

    def test_the_plugin_under_another_group_is_still_checked(self):
        xml = pom("<build><plugins><plugin><groupId>evil</groupId><artifactId>central-publishing-maven-plugin</artifactId>"
                  "<configuration><autoPublish>true</autoPublish></configuration></plugin></plugins></build>")
        self.refused(self.check(xml), "autoPublish")

    def test_namespace_prefix_and_profile_contexts(self):
        self.refused(self.check(aeff("<configuration><autoPublish>true</autoPublish></configuration>", ns=NS)))
        xml = pom("<profiles><profile><id>release</id><build><plugins>"
                  + EFF_PLUGIN.format(cfg="<configuration><autoPublish>true</autoPublish></configuration>")
                  + "</plugins></build></profile></profiles>")
        self.refused(self.check(xml))
        prefixed = ('<?xml version="1.0"?><p:project xmlns:p="http://maven.apache.org/POM/4.0.0"><p:build><p:plugins><p:plugin>'
                    '<p:artifactId>central-publishing-maven-plugin</p:artifactId><p:configuration>'
                    '<p:autoPublish>true</p:autoPublish></p:configuration></p:plugin></p:plugins></p:build></p:project>')
        self.refused(self.check(prefixed))

    def test_artifact_id_with_surrounding_whitespace_is_still_the_plugin(self):
        xml = pom("<build><plugins><plugin><artifactId>\n central-publishing-maven-plugin \n</artifactId>"
                  "<configuration><autoPublish>true</autoPublish></configuration></plugin></plugins></build>")
        self.refused(self.check(xml))

    def test_a_commented_out_value_is_not_a_value(self):
        self.accepted(self.check(aeff("<configuration><!-- <autoPublish>true</autoPublish> --></configuration>")))

    def test_usage(self):
        self.assertEqual(h.run_proc(self.S, []).rc, 2)
        self.assertEqual(h.run_main(self.S, []).rc, 2)


if __name__ == "__main__":
    unittest.main()
