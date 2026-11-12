"""The upload command of caps-release.yml, run for real against a `file://` repository.

The `run:` block of the step "Upload the gated files" is parsed out of the workflow and executed by bash, so the command under
test is the one the workflow holds and not a copy of it. The settings file is written by running the "Write the Maven settings"
step's block too. Two things are substituted in the text, and nothing else:

  * `https://maven.pkg.github.com/${GITHUB_REPOSITORY}`, which is hard-wired in the workflow, becomes a `file://` URL;
  * the settings file gets a `<mirrors>` element that sends every remote repository to a closed local port, so a missing
    plugin or dependency fails at once instead of being downloaded. The deploy plugin refuses to run in offline mode
    (`Cannot deploy artifacts when Maven is in offline mode`), so `mvn -o` is not available for this command.

The staged directory is what the real readiness gate stages from a fixture build. When the deploy plugin is not in the local
Maven repository, the tests are skipped with that reason and never pass.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import textwrap
import unittest
import xml.etree.ElementTree as ET

import caps_release_helpers as h
import workflow_invariants as w
from readiness_support import Fixture, sig_of

GATE = "check_release_readiness"
URL = "https://maven.pkg.github.com/${GITHUB_REPOSITORY}"
PLUGIN_JAR = os.path.join(os.path.expanduser("~"), ".m2", "repository", "org", "apache", "maven", "plugins", "maven-deploy-plugin",
                          "3.1.4", "maven-deploy-plugin-3.1.4.jar")
MIRROR = ('<mirrors><mirror><id>central</id><mirrorOf>*</mirrorOf><url>http://127.0.0.1:9/</url></mirror></mirrors>')
UNRESOLVED = re.compile(r"could not be resolved|Could not transfer|present, but unavailable|Could not find artifact")


def step_run(name: str) -> str:
    with open(h.WORKFLOW, encoding="utf-8") as fh:
        text = fh.read()
    steps = [s for s in w.parse(text)["jobs"]["publish"]["steps"] if s["name"] == name]
    assert len(steps) == 1, f"the workflow must hold exactly one step named {name!r}"
    return textwrap.dedent(steps[0]["run"]).strip("\n") + "\n"


def pom_text(group, artifact, version, parent_group=None):
    parent = (f"<parent><groupId>{parent_group}</groupId><artifactId>p</artifactId><version>{version}</version></parent>"
              if parent_group else "")
    own_group = f"<groupId>{group}</groupId>" if group else ""
    own_version = f"<version>{version}</version>" if group else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<project xmlns="http://maven.apache.org/POM/4.0.0">'
            f"<modelVersion>4.0.0</modelVersion>{parent}{own_group}<artifactId>{artifact}</artifactId>{own_version}"
            f"<packaging>jar</packaging></project>\n")


@unittest.skipUnless(shutil.which("mvn") and shutil.which("bash"), "mvn and bash are needed to run the upload command")
@unittest.skipUnless(os.path.exists(PLUGIN_JAR), f"the deploy plugin 3.1.4 is not in the local Maven repository ({PLUGIN_JAR}); "
                                                  "it is not downloaded here")
class Upload(Fixture):
    def setUp(self):
        super().setUp()
        self.runner = self.path("runner")
        self.private_tmp = self.path("tmp")
        self.repo = self.path("repo")
        for d in (self.runner, self.private_tmp, self.repo):
            os.makedirs(d)
        self.staged = os.path.join(self.runner, "gated-files")

    def stage(self, *coordinates):
        """Build the fixture coordinates in target/ and stage them with the real gate."""
        for artifact, version, group, parent_group in coordinates:
            self.coordinate(f"{artifact}-{version}", pom_text=pom_text(group, artifact, version, parent_group))
        res = h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.staged])
        self.accepted(res)

    def execute(self):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.path.expanduser("~"), "LC_ALL": "C.UTF-8",
               "TMPDIR": self.private_tmp, "RUNNER_TEMP": self.runner, "GITHUB_REPOSITORY": "owner/repository",
               "GITHUB_ACTOR": "actor", "GITHUB_TOKEN": "not-a-token"}
        if "JAVA_HOME" in os.environ:
            env["JAVA_HOME"] = os.environ["JAVA_HOME"]
        settings = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step_run("Write the Maven settings")],
                                  env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(settings.returncode, 0, settings.stderr)
        path = os.path.join(self.runner, "release-settings.xml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count("<settings"), 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(re.sub(r"(<settings[^>]*>)", lambda m: m.group(1) + MIRROR, text, count=1))
        script = step_run("Upload the gated files")
        self.assertEqual(script.count(URL), 1, "the upload names its repository once")
        script = script.replace(URL, f"file://{self.repo}")
        done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script], env=env, capture_output=True,
                              text=True, timeout=300)
        if done.returncode != 0 and UNRESOLVED.search(done.stdout + done.stderr):
            self.skipTest("the deploy plugin or one of its dependencies is not in the local Maven repository: "
                          + " ".join((done.stdout + done.stderr).split())[-300:])
        return done

    def files(self):
        out = {}
        for root, _, names in os.walk(self.repo):
            for n in names:
                out[os.path.relpath(os.path.join(root, n), self.repo)] = os.path.join(root, n)
        return out

    @staticmethod
    def read(path):
        with open(path, "rb") as fh:
            return fh.read()

    def assert_coordinate(self, group_path, artifact, version, staged_names):
        """The repository holds exactly the eight files, under the right names, byte for byte, and Maven's own checksums."""
        directory = f"{group_path}/{artifact}/{version}"
        base = f"{artifact}-{version}"
        wanted = {f"{base}.jar", f"{base}.pom", f"{base}-sources.jar", f"{base}-javadoc.jar",
                  f"{base}.jar.asc", f"{base}.pom.asc", f"{base}-sources.jar.asc", f"{base}-javadoc.jar.asc"}
        files = self.files()
        here = {os.path.basename(k): v for k, v in files.items() if os.path.dirname(k) == directory}
        checksums = {n: v for n, v in here.items() if n.endswith((".md5", ".sha1"))}
        payload = {n: v for n, v in here.items() if n not in checksums}
        self.assertEqual(set(payload), wanted)
        self.assertEqual(wanted, set(staged_names) & wanted, "the staged directory holds the same eight names")
        for name in wanted:
            self.assertEqual(self.read(payload[name]), self.read(os.path.join(self.staged, name)), f"{name} is byte-identical")
        for name, path in checksums.items():
            subject, ext = name.rsplit(".", 1)
            self.assertIn(subject, wanted, f"a checksum of a file that is not part of the release: {name}")
            algorithm = {"md5": "md5", "sha1": "sha1"}[ext]
            self.assertEqual(self.read(path).decode().split()[0], hashlib.new(algorithm, self.read(payload[subject])).hexdigest())
        for subject in (f"{base}.jar", f"{base}.pom", f"{base}-sources.jar", f"{base}-javadoc.jar"):
            self.assertIn(subject + ".sha1", checksums)
        return here

    def test_one_coordinate_deploys_under_the_right_names_and_bytes(self):
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        done = self.execute()
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
        self.assertIn("BUILD SUCCESS", done.stdout)
        self.assert_coordinate("eu/exeris/caps", "a", "1.0.0", os.listdir(self.staged))
        metadata = ET.parse(os.path.join(self.repo, "eu", "exeris", "caps", "a", "maven-metadata.xml")).getroot()
        self.assertEqual(metadata.findtext("groupId"), "eu.exeris.caps")
        self.assertEqual(metadata.findtext("artifactId"), "a")
        self.assertEqual([v.text for v in metadata.find("versioning").find("versions")], ["1.0.0"])
        # nothing but that coordinate and its metadata is in the repository
        self.assertEqual({os.path.dirname(k) for k in self.files()} - {"eu/exeris/caps/a/1.0.0", "eu/exeris/caps/a"}, set())

    def test_the_signature_files_are_attached_with_the_names_a_consumer_looks_for(self):
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        self.assertEqual(self.execute().returncode, 0)
        here = self.assert_coordinate("eu/exeris/caps", "a", "1.0.0", os.listdir(self.staged))
        for name in ("a-1.0.0.jar.asc", "a-1.0.0.pom.asc", "a-1.0.0-sources.jar.asc", "a-1.0.0-javadoc.jar.asc"):
            self.assertIn(name, here)
            self.assertEqual(self.read(here[name]).decode(), sig_of(os.path.join(self.staged, name[:-len(".asc")])))
        for wrong in ("a-1.0.0.asc", "a-1.0.0-sources.asc", "a-1.0.0-javadoc.asc", "a-1.0.0-sources.jar.asc.asc",
                      "a-1.0.0-asc.asc", "a-1.0.0-jar.asc"):
            self.assertNotIn(wrong, here)

    def test_a_pom_that_takes_its_group_and_version_from_the_parent_deploys_under_that_coordinate(self):
        self.stage(("a", "1.0.0", None, "org.parent"))
        done = self.execute()
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
        self.assert_coordinate("org/parent", "a", "1.0.0", os.listdir(self.staged))
        self.assertFalse(any(k.startswith("eu/") for k in self.files()))

    def test_every_pom_in_the_staged_directory_is_deployed_once(self):
        self.stage(("a", "1.0.0", "eu.exeris.caps", None), ("b", "2.1.0", "eu.exeris.caps", None))
        done = self.execute()
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
        self.assertEqual(done.stdout.count("BUILD SUCCESS"), 2)
        self.assert_coordinate("eu/exeris/caps", "a", "1.0.0", os.listdir(self.staged))
        self.assert_coordinate("eu/exeris/caps", "b", "2.1.0", os.listdir(self.staged))

    def test_nothing_is_left_in_the_private_temporary_directory(self):
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        self.assertEqual(self.execute().returncode, 0)
        self.assertEqual(os.listdir(self.private_tmp), [])
        self.assertFalse(os.path.exists(os.path.join(self.staged, "pom.xml")), "the staging directory holds no pom.xml")
        self.assertEqual(sorted(n for n in os.listdir(self.staged) if n.startswith("pom")), [])

    def test_a_staged_directory_with_a_pom_xml_would_make_the_command_load_a_project(self):
        """Why the staging directory must hold no pom.xml: with one, Maven reads it as the project and runs its build."""
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        with open(os.path.join(self.staged, "pom.xml"), "w") as fh:
            fh.write(pom_text("eu.exeris.caps", "project-run", "9.9.9"))
        done = self.execute()
        self.assertIn("project-run", done.stdout, "the project in the working directory was loaded")


if __name__ == "__main__":
    unittest.main()
