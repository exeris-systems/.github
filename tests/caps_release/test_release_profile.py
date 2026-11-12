"""check_release_profile --pom P: a release profile that signs and builds the sources and javadoc jars, a single module, and no
Central publishing plugin in the release profile.

The check reads the POM as XML (element values only), looks at the profile whose <id> is `release`, and nowhere else for what it
requires. Every problem found is listed on one `::error::` line.
"""
from __future__ import annotations

import os
import re
import unittest

import caps_release_helpers as h
from caps_release_helpers import pom

S = "check_release_profile"
NS = "http://maven.apache.org/POM/4.0.0"
GROUP = "org.apache.maven.plugins"
REQUIRED = ("maven-gpg-plugin", "maven-source-plugin", "maven-javadoc-plugin")
CENTRAL_GROUP = "org.sonatype.central"
CENTRAL = "central-publishing-maven-plugin"


def plugin(artifact, group=None, extra=""):
    g = f"<groupId>{group}</groupId>" if group is not None else ""
    return f"<plugin>{g}<artifactId>{artifact}</artifactId>{extra}</plugin>"


def central(group=CENTRAL_GROUP):
    return plugin(CENTRAL, group, "<extensions>true</extensions>")


REQ = "".join(plugin(a) for a in REQUIRED)
REQ_GROUPED = "".join(plugin(a, GROUP) for a in REQUIRED)


def release(plugins=REQ, managed="", extra="", profile_extra=""):
    build = f"<build><plugins>{plugins}</plugins>"
    if managed:
        build += f"<pluginManagement><plugins>{managed}</plugins></pluginManagement>"
    build += "</build>"
    return f"<profile><id>release</id>{build}{profile_extra}</profile>"


def profiles(*items):
    return f"<profiles>{''.join(items)}</profiles>"


GOOD = profiles(release())


def prefixed(xml: str) -> str:
    xml = re.sub(r"<(/?)([A-Za-z][\w.-]*)", r"<\1p:\2", xml)
    return xml.replace("<p:project", f'<p:project xmlns:p="{NS}"', 1)


class Check(h.Case):
    def run_check(self, body, ns="", extra=(), pre=False):
        text = prefixed(pom(body)) if pre else pom(body, ns)
        return self.both(S, ["--pom", self.write("pom.xml", text), *extra])

    def problems(self, body, **kw):
        res = self.run_check(body, **kw)
        self.assertEqual(res.rc, 1, res)
        self.assertEqual(len(res.errors()), 1, "all the problems are on one line")
        self.assertEqual(len(res.err.splitlines()), 1)
        return res.errors()[0]


class Misuse(Check):
    def test_a_missing_pom_argument_is_a_usage_error(self):
        for run in (h.run_main, h.run_proc):
            with self.subTest(run.__name__):
                res = run(S, [])
                self.assertEqual(res.rc, 2, res)
                self.assertEqual(res.errors(), [])

    def test_a_pom_that_cannot_be_opened_is_named_and_is_not_an_unexpected_failure(self):
        for path in (self.path("absent.xml"), self.tmp):
            with self.subTest(path):
                res = self.both(S, ["--pom", path])
                self.refused(res, "cannot be read as a POM")
                self.assertEqual(len(res.errors()), 1)
                self.assertNotIn("unexpectedly", res.err)

    def test_an_element_that_is_written_twice_is_not_read_as_one_joined_value(self):
        split = "<plugin><artifactId>maven-gpg-</artifactId><artifactId>plugin</artifactId></plugin>"
        rest = plugin("maven-source-plugin") + plugin("maven-javadoc-plugin")
        self.assertIn("maven-gpg-plugin", self.problems(profiles(release(split + rest))))
        halves = f"<plugin><artifactId>central-publishing-</artifactId><artifactId>maven-plugin</artifactId></plugin>"
        self.accepted(self.run_check(profiles(release(REQ + halves))))


class Accepts(Check):
    def test_a_release_profile_with_the_three_plugins(self):
        res = self.run_check(GOOD)
        self.accepted(res)
        self.assertIn("ok - this ref carries a release profile that signs and builds the sources and javadoc jars", res.out)

    def test_the_plugins_may_name_their_group_or_leave_it_out(self):
        self.accepted(self.run_check(profiles(release(REQ_GROUPED))))
        self.accepted(self.run_check(profiles(release(plugin("maven-gpg-plugin", GROUP) + plugin("maven-source-plugin")
                                                      + plugin("maven-javadoc-plugin", "")))))

    def test_namespace_and_prefix_are_read(self):
        self.accepted(self.run_check(GOOD, ns=NS))
        self.accepted(self.run_check(GOOD, pre=True))

    def test_values_are_compared_without_surrounding_whitespace_and_in_cdata(self):
        spaced = "".join(f"<plugin><groupId> {GROUP}\n</groupId><artifactId>\n {a} \n</artifactId></plugin>" for a in REQUIRED)
        self.accepted(self.run_check(profiles(release(spaced))))
        self.accepted(self.run_check(GOOD.replace("<id>release</id>", "<id>  release \n</id>")))
        self.accepted(self.run_check(GOOD.replace("<id>release</id>", "<id><![CDATA[release]]></id>")))

    def test_other_profiles_and_other_plugins_do_not_matter(self):
        other = "<profile><id>other</id><build><plugins>" + plugin("maven-enforcer-plugin") + "</plugins></build></profile>"
        self.accepted(self.run_check(profiles(other, release(REQ + plugin("maven-jar-plugin")))))

    def test_nothing_is_written_beside_the_pom(self):
        f = self.write("pom.xml", pom(GOOD))
        before = set(os.listdir(self.tmp))
        self.accepted(self.both(S, ["--pom", f]))
        self.assertEqual(set(os.listdir(self.tmp)), before)


class NoReleaseProfile(Check):
    def test_every_way_of_not_having_one(self):
        bodies = {
            "no profiles": "",
            "other id": profiles(release().replace("<id>release</id>", "<id>releases</id>")),
            "case": profiles(release().replace("<id>release</id>", "<id>Release</id>")),
            "suffix": profiles(release().replace("<id>release</id>", "<id>release-candidate</id>")),
            "empty id": profiles(release().replace("<id>release</id>", "<id/>")),
            "id in a comment": profiles(release().replace("<id>release</id>", "<!-- <id>release</id> --><id>other</id>")),
            "profiles in a comment": "<!-- " + GOOD + " -->",
            "id outside a profile": "<id>release</id>",
            "profile outside profiles": release(),
            "id nested deeper": profiles(release().replace("<id>release</id>", "<build><id>release</id></build>")),
            "profiles under build": f"<build>{GOOD}</build>",
            "artifact id": "<artifactId>release</artifactId>",
            "whitespace inside the word": profiles(release().replace("<id>release</id>", "<id>rel ease</id>")),
            "the plugins only in the project build": f"<build><plugins>{REQ}</plugins></build>",
        }
        for label, body in bodies.items():
            with self.subTest(label):
                self.assertIn("missing: the 'release' profile in pom.xml", self.problems(body))

    def test_without_a_profile_the_three_plugins_are_not_asked_for_again(self):
        line = self.problems("")
        for artifact in REQUIRED:
            self.assertNotIn(artifact, line)


class Modules(Check):
    MODS = "<modules><module>m</module></modules>"

    def test_modules_anywhere_is_refused_in_every_form(self):
        other = lambda inner: f"<profile><id>other</id>{inner}</profile>"
        placements = {
            "root": GOOD + self.MODS,
            "root, empty element": GOOD + "<modules/>",
            "root, empty pair": GOOD + "<modules></modules>",
            "release profile": profiles(release(profile_extra=self.MODS)),
            "release profile, empty": profiles(release(profile_extra="<modules/>")),
            "another profile": profiles(release(), other(self.MODS)),
            "another profile, empty element": profiles(release(), other("<modules/>")),
            "another profile, empty pair": profiles(release(), other("<modules></modules>")),
        }
        for ns in ("", NS):
            for label, body in placements.items():
                with self.subTest(label, ns=ns):
                    line = self.problems(body, ns=ns)
                    self.assertIn("single-module", line)
                    self.assertNotIn("missing: org.apache", line)

    def test_prefixed_modules_are_refused(self):
        self.assertIn("single-module", self.problems(GOOD + self.MODS, pre=True))

    def test_modules_nested_elsewhere_are_not_the_modules_of_the_build(self):
        for body in (GOOD + "<build><plugins><plugin><artifactId>x</artifactId><configuration><modules>a</modules>"
                            "</configuration></plugin></plugins></build>",
                     GOOD + "<properties><modules>a</modules></properties>",
                     GOOD + "<!-- <modules><module>a</module></modules> -->"):
            with self.subTest(body[-60:]):
                self.accepted(self.run_check(body))


class RequiredPlugins(Check):
    def test_each_plugin_missing_alone_is_named_and_the_others_are_not(self):
        for artifact in REQUIRED:
            with self.subTest(artifact):
                others = "".join(plugin(a) for a in REQUIRED if a != artifact)
                line = self.problems(profiles(release(others)))
                self.assertIn(f"missing: {GROUP}:{artifact} in the release profile's <build><plugins>", line)
                for other in REQUIRED:
                    if other != artifact:
                        self.assertNotIn(other, line)

    def test_every_missing_item_is_listed_on_the_one_line(self):
        line = self.problems(profiles(release("")) + "<modules><module>m</module></modules>" + "")
        for fragment in (*REQUIRED, "single-module"):
            self.assertIn(fragment, line)
        line = self.problems("<modules><module>m</module></modules>")
        for fragment in ("the 'release' profile", "single-module"):
            self.assertIn(fragment, line)

    def test_a_plugin_that_is_not_in_the_release_profiles_build_plugins_does_not_count(self):
        gpg = plugin("maven-gpg-plugin")
        rest = plugin("maven-source-plugin") + plugin("maven-javadoc-plugin")
        elsewhere = {
            "the project's build": profiles(release(rest)) + f"<build><plugins>{gpg}</plugins></build>",
            "the project's pluginManagement": profiles(release(rest)) + f"<build><pluginManagement><plugins>{gpg}</plugins></pluginManagement></build>",
            "the profile's pluginManagement": profiles(release(rest, managed=gpg)),
            "another profile": profiles(release(rest), f"<profile><id>other</id><build><plugins>{gpg}</plugins></build></profile>"),
            "the profile's reporting": profiles(release(rest, profile_extra=f"<reporting><plugins>{gpg}</plugins></reporting>")),
            "the profile's dependencies": profiles(release(rest, profile_extra="<dependencies><dependency><groupId>" + GROUP
                                                           + "</groupId><artifactId>maven-gpg-plugin</artifactId></dependency></dependencies>")),
            "the profile's build extensions": profiles(release(rest).replace("</build>", "<extensions><extension><groupId>" + GROUP
                                                                             + "</groupId><artifactId>maven-gpg-plugin</artifactId></extension></extensions></build>")),
            "a comment": profiles(release(rest + f"<!-- {gpg} -->")),
            "a property": profiles(release(rest, profile_extra="<properties><artifactId>maven-gpg-plugin</artifactId></properties>")),
            "a plugin's configuration": profiles(release(rest + plugin("x", None, f"<configuration>{gpg}</configuration>"))),
        }
        for label, body in elsewhere.items():
            with self.subTest(label):
                self.assertIn(f"missing: {GROUP}:maven-gpg-plugin", self.problems(body))

    def test_the_group_and_the_artifact_id_must_be_the_plugins(self):
        for label, group, artifact in (("a foreign group", "com.evil", "maven-gpg-plugin"), ("group case", "org.apache.maven.Plugins", "maven-gpg-plugin"),
                                       ("group prefix", GROUP + ".x", "maven-gpg-plugin"), ("artifact case", None, "Maven-GPG-Plugin"),
                                       ("artifact suffix", None, "maven-gpg-plugin2"), ("artifact prefix", None, "x-maven-gpg-plugin"),
                                       ("artifact property", None, "${gpg.plugin}")):
            with self.subTest(label):
                bad = plugin(artifact, group) + plugin("maven-source-plugin") + plugin("maven-javadoc-plugin")
                self.assertIn("maven-gpg-plugin", self.problems(profiles(release(bad))))

    def test_a_good_declaration_beside_a_bad_one_is_enough(self):
        both = plugin("maven-gpg-plugin", "com.evil") + REQ
        self.accepted(self.run_check(profiles(release(both))))

    def test_a_refusal_prints_the_instruction_and_no_ok_line(self):
        res = self.run_check("")
        self.assertIn("Release from a ref that carries the release machinery.", res.err)
        self.assertEqual(res.out, "")


class CentralPlugin(Check):
    def test_the_central_publishing_plugin_in_the_release_profile_is_forbidden(self):
        spots = {
            "build plugins": profiles(release(REQ + central())),
            "build plugins, group left out": profiles(release(REQ + plugin(CENTRAL))),
            "build pluginManagement": profiles(release(managed=central())),
            "pluginManagement, group left out": profiles(release(managed=plugin(CENTRAL))),
            "plugins and pluginManagement": profiles(release(REQ + central(), managed=central())),
            "first of several": profiles(release(central() + REQ)),
        }
        for label, body in spots.items():
            with self.subTest(label):
                line = self.problems(body)
                self.assertIn(f"forbidden: {CENTRAL_GROUP}:{CENTRAL} in the release profile", line)
                self.assertNotIn("missing:", line)

    def test_spelling_variants_are_still_the_plugin(self):
        spaced = f"<plugin><groupId>\n {CENTRAL_GROUP} \n</groupId><artifactId>\n {CENTRAL}\n</artifactId></plugin>"
        self.assertIn("forbidden:", self.problems(profiles(release(REQ + spaced))))
        for kw in (dict(ns=NS), dict(pre=True)):
            with self.subTest(kw):
                self.assertIn("forbidden:", self.problems(profiles(release(REQ + central())), **kw))

    def test_what_is_not_the_plugin_is_not_forbidden(self):
        harmless = {
            "a dependency of that name": profiles(release(profile_extra=f"<dependencies><dependency><groupId>{CENTRAL_GROUP}</groupId>"
                                                                        f"<artifactId>{CENTRAL}</artifactId></dependency></dependencies>")),
            "another group": profiles(release(REQ + central("com.example"))),
            "another artifact": profiles(release(REQ + plugin(CENTRAL + "2", CENTRAL_GROUP))),
            "artifact case": profiles(release(REQ + plugin(CENTRAL.upper(), CENTRAL_GROUP))),
            "a comment": profiles(release(REQ + f"<!-- {central()} -->")),
            "a property named like the server id": profiles(release(REQ, profile_extra="<properties><publishingServerId>central</publishingServerId></properties>")),
        }
        for label, body in harmless.items():
            with self.subTest(label):
                self.accepted(self.run_check(body))

    def test_the_forbidden_plugin_and_a_missing_one_are_reported_together(self):
        line = self.problems(profiles(release(plugin("maven-gpg-plugin") + central())))
        self.assertIn("maven-source-plugin", line)
        self.assertIn("maven-javadoc-plugin", line)
        self.assertIn("forbidden:", line)
        self.assertIn("single-module", self.problems(profiles(release(REQ + central())) + "<modules/>"))

    def test_the_options_of_a_removed_target_do_not_exist(self):
        f = self.write("pom.xml", pom(GOOD))
        out = self.path("out")
        for argv in (["--pom", f, "--target", "none"], ["--pom", f, "--target", "github-packages"], ["--pom", f, "--output", out],
                     ["--pom", f, "--target", "none", "--output", out]):
            for run in (h.run_main, h.run_proc):
                with self.subTest(argv, run=run.__name__):
                    res = run(S, argv)
                    self.assertEqual(res.rc, 2, res)
                    self.assertEqual(res.errors(), [])
        self.assertFalse(os.path.exists(out))


class ScopeOfTheCheck(Check):
    """What the check does and does not look at. It requires its plugins in the release profile alone and forbids the Central
    plugin there alone: a plugin declared anywhere else in the POM is outside what it reads (the workflow uploads from a directory
    without a POM, so a project plugin never runs at upload time)."""

    def test_the_central_plugin_outside_the_release_profile_is_not_read(self):
        c = central()
        outside = {
            "the project's build": GOOD + f"<build><plugins>{c}</plugins></build>",
            "the project's pluginManagement": GOOD + f"<build><pluginManagement><plugins>{c}</plugins></pluginManagement></build>",
            "another profile": profiles(release(), f"<profile><id>other</id><build><plugins>{c}</plugins></build></profile>"),
            "another profile, active by default": profiles(
                release(), f"<profile><id>other</id><activation><activeByDefault>true</activeByDefault></activation>"
                           f"<build><plugins>{c}</plugins></build></profile>"),
        }
        for label, body in outside.items():
            with self.subTest(label):
                self.accepted(self.run_check(body))

    def test_a_parent_is_not_read(self):
        parent = "<parent><groupId>g</groupId><artifactId>p</artifactId><version>1</version></parent>"
        self.accepted(self.run_check(GOOD + parent))
        self.assertIn("missing:", self.problems(parent))

    def test_distribution_management_is_not_read(self):
        distribution = ("<distributionManagement><repository><id>x</id><url>https://elsewhere.example/r</url></repository>"
                        "</distributionManagement>")
        self.accepted(self.run_check(GOOD + distribution))
        self.accepted(self.run_check(profiles(release(profile_extra=distribution))))


class PublishingPluginsOfAnotherRepository(Check):
    """The workflow states that the release profile does not configure a publishing plugin of another repository. The check
    forbids one plugin by name, so these pass although they are such plugins."""

    @h.known_defect("CR-1", "a publishing plugin other than the Central one passes in the release profile")
    def test_the_nexus_staging_plugin_in_the_release_profile_is_refused(self):
        nexus = plugin("nexus-staging-maven-plugin", "org.sonatype.plugins", "<extensions>true</extensions>")
        self.refused(self.run_check(profiles(release(REQ + nexus))), "nexus-staging-maven-plugin")

    @h.known_defect("CR-1", "a deploy plugin that names another repository passes in the release profile")
    def test_a_deploy_plugin_with_an_alternative_repository_in_the_release_profile_is_refused(self):
        deploy = plugin("maven-deploy-plugin", None, "<configuration><altDeploymentRepository>x::https://elsewhere.example/r"
                                                      "</altDeploymentRepository></configuration>")
        self.refused(self.run_check(profiles(release(REQ + deploy))), "maven-deploy-plugin")


if __name__ == "__main__":
    unittest.main()
