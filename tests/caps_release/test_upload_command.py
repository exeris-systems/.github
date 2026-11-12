"""The `upload` job of caps-release.yml, run for real against a `file://` repository.

The `run:` blocks of the job are parsed out of the workflow and executed by bash, so the commands under test are the workflow's own
and not copies of them. The job's input is built the way the job gets it: the real readiness gate stages a fixture build, the
manifest is made of the staged directory, the directory is COPIED to a fresh `gated-download` (what a downloaded artifact is), and
the job's own comparison step checks it against the manifest before the settings step and the upload step run. Two things are
substituted in the text of the upload step, and nothing else:

  * `https://maven.pkg.github.com/${GITHUB_REPOSITORY}`, which is hard-wired in the workflow, becomes a `file://` URL;
  * the settings file gets a `<mirrors>` element that sends every remote repository to a closed local port, so a missing
    plugin or dependency fails at once instead of being downloaded. The deploy plugin refuses to run in offline mode
    (`Cannot deploy artifacts when Maven is in offline mode`), so `mvn -o` is not available for this command.

When the deploy plugin is not in the local Maven repository, or `/usr/bin/python3` (which the comparison step names) is absent, the
tests are skipped with that reason and never pass.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import caps_release_helpers as h
import upload_job_support as job
from manifest_support import SCRIPT, coordinate_names, make_coordinate, manifest_of, parse_github_output, put
from readiness_support import Fixture, sig_of

GATE = "check_release_readiness"
URL = "https://maven.pkg.github.com/${GITHUB_REPOSITORY}"
PLUGIN_JAR = os.path.join(os.path.expanduser("~"), ".m2", "repository", "org", "apache", "maven", "plugins", "maven-deploy-plugin",
                          "3.1.4", "maven-deploy-plugin-3.1.4.jar")
MIRROR = ('<mirrors><mirror><id>central</id><mirrorOf>*</mirrorOf><url>http://127.0.0.1:9/</url></mirror></mirrors>')
UNRESOLVED = re.compile(r"could not be resolved|Could not transfer|present, but unavailable|Could not find artifact")


def pom_text(group, artifact, version, parent_group=None):
    parent = (f"<parent><groupId>{parent_group}</groupId><artifactId>p</artifactId><version>{version}</version></parent>"
              if parent_group else "")
    own_group = f"<groupId>{group}</groupId>" if group else ""
    own_version = f"<version>{version}</version>" if group else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<project xmlns="http://maven.apache.org/POM/4.0.0">'
            f"<modelVersion>4.0.0</modelVersion>{parent}{own_group}<artifactId>{artifact}</artifactId>{own_version}"
            f"<packaging>jar</packaging></project>\n")


@unittest.skipUnless(shutil.which("mvn") and shutil.which("bash"), "mvn and bash are needed to run the upload command")
@unittest.skipUnless(os.path.exists("/usr/bin/python3"), "the comparison step of the workflow runs /usr/bin/python3")
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
        self.download = os.path.join(self.runner, "gated-download")
        self.manifest = None
        self.digest = None

    def env(self):
        return job.runner_env(self.runner, TMPDIR=self.private_tmp, GITHUB_TOKEN="not-a-token")

    def stage(self, *coordinates):
        """What `publish` leaves: the real gate stages the fixture builds, and the manifest is made of the staged directory."""
        for artifact, version, group, parent_group in coordinates:
            self.coordinate(f"{artifact}-{version}", pom_text=pom_text(group, artifact, version, parent_group))
        self.accepted(h.run_main(GATE, ["--target-dir", self.target, "--gpg", self.gpg, "--stage", self.staged]))
        out = self.path("github-output")
        self.accepted(h.run_main(SCRIPT, ["create", "--dir", self.staged, "--output", out]))
        with open(out, encoding="utf-8") as fh:
            self.manifest = parse_github_output(fh.read())["manifest"]

    def download_artifact(self):
        """What `actions/download-artifact` leaves in the runner's temporary directory: a copy of the staged files."""
        shutil.copytree(self.staged, self.download)

    def compare(self, manifest="same"):
        if self.digest is None:
            self.digest = job.install_scripts(self, "upload", self.runner)
        return job.compare("upload", self.runner, self.digest, self.manifest if manifest == "same" else manifest)

    def settings(self):
        done = job.bash(job.step_run("upload", job.SETTINGS), self.env())
        self.assertEqual(done.returncode, 0, done.stderr)
        path = os.path.join(self.runner, "release-settings.xml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count("<settings"), 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(re.sub(r"(<settings[^>]*>)", lambda m: m.group(1) + MIRROR, text, count=1))

    def deploy(self, path_prefix=None):
        script = job.step_run("upload", job.UPLOAD)
        self.assertEqual(script.count(URL), 1, "the upload names its repository once")
        env = self.env()
        if path_prefix:
            env["PATH"] = path_prefix + ":" + env["PATH"]
        return job.bash(script.replace(URL, f"file://{self.repo}"), env)

    def execute(self):
        """The job from the download on: compare with the manifest, write the settings, upload. Returns the upload's result."""
        self.download_artifact()
        compared = self.compare()
        self.assertEqual(compared.returncode, 0, compared.stdout + compared.stderr)
        self.assertIn("files match the manifest", compared.stdout)
        self.settings()
        done = self.deploy()
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
            self.assertEqual(self.read(payload[name]), self.read(os.path.join(self.staged, name)), f"{name} is byte-identical to the staged file")
            self.assertEqual(self.read(payload[name]), self.read(os.path.join(self.download, name)), f"{name} is byte-identical to the downloaded file")
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
        self.assertFalse(os.path.exists(os.path.join(self.download, "pom.xml")), "the download directory holds no pom.xml")
        self.assertEqual(sorted(n for n in os.listdir(self.download) if n.startswith("pom")), [])

    def test_the_uploaded_files_come_from_the_downloaded_copy_not_from_the_staged_directory(self):
        """The upload job never sees the staged directory; the command reads the directory it was given."""
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        self.download_artifact()
        shutil.rmtree(self.staged)
        self.assertEqual(self.compare().returncode, 0)
        self.settings()
        done = self.deploy()
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
        self.assertIn("eu/exeris/caps/a/1.0.0/a-1.0.0.jar", " ".join(self.files()))

    def test_a_pom_xml_in_the_download_directory_is_refused_by_the_manifest_check_and_nothing_is_uploaded(self):
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        self.download_artifact()
        with open(os.path.join(self.download, "pom.xml"), "w") as fh:
            fh.write(pom_text("eu.exeris.caps", "project-run", "9.9.9"))
        done = self.compare()
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("pom.xml is not part of a release", done.stderr)
        self.assertEqual(self.files(), {}, "the check refuses before anything is uploaded")
        # even when the manifest lists it with its right hash
        done = self.compare(manifest=manifest_of(self.download))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("pom.xml is not part of a release", done.stderr)

    def test_a_staged_directory_with_a_pom_xml_would_make_the_command_load_a_project(self):
        """Why the check matters: with a pom.xml in the working directory, Maven reads it as the project and runs its build."""
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        self.download_artifact()
        with open(os.path.join(self.download, "pom.xml"), "w") as fh:
            fh.write(pom_text("eu.exeris.caps", "project-run", "9.9.9"))
        self.settings()
        done = self.deploy()
        self.assertIn("project-run", done.stdout, "the project in the working directory was loaded")

    def test_a_changed_byte_in_the_download_is_refused_before_the_settings_and_the_upload(self):
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        self.download_artifact()
        with open(os.path.join(self.download, "a-1.0.0.jar"), "ab") as fh:
            fh.write(b"\0")
        done = self.compare()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("a-1.0.0.jar differs from the manifest", done.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.runner, "release-settings.xml")), "the settings step has not run")
        self.assertEqual(self.files(), {})

    def test_an_empty_or_missing_manifest_is_refused_by_the_comparison_step(self):
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        self.download_artifact()
        for manifest in ("", None, "\n"):
            with self.subTest(manifest):
                done = self.compare(manifest=manifest)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("the manifest is empty", done.stderr)
                self.assertNotIn("files match", done.stdout)

    def test_scripts_changed_after_they_were_installed_are_refused_before_they_run(self):
        self.stage(("a", "1.0.0", "eu.exeris.caps", None))
        self.download_artifact()
        self.assertEqual(self.compare().returncode, 0)
        scripts = os.path.join(self.runner, "caps-release-scripts")
        os.chmod(scripts, 0o700)
        target = os.path.join(scripts, "staged_manifest.py")
        os.chmod(target, 0o700)
        with open(target, "a") as fh:
            fh.write("\nraise SystemExit(0)\n")
        done = self.compare()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("the gate scripts changed after they were installed", done.stderr)

    @h.known_defect("base-comma", "the upload step joins the file base name into the comma separated `-Dfiles`, and neither the gate nor the "
                                   "manifest check limits the characters of a base: `a,b-1.0.0` turns four signature entries into eight "
                                   "(caps-release.yml, step `Upload the gated files`)")
    def test_a_base_with_a_comma_keeps_the_four_signature_files_apart_in_the_deploy_arguments(self):
        """The `-Dfiles` list is comma separated and is built from the file base name; a comma in a base must not add entries to it."""
        d = self.download
        make_coordinate(d, "a,b-1.0.0")
        out = self.path("o")
        self.accepted(h.run_main(SCRIPT, ["create", "--dir", d, "--output", out]))
        with open(out, encoding="utf-8") as fh:
            manifest = parse_github_output(fh.read())["manifest"]
        self.digest = job.install_scripts(self, "upload", self.runner)
        self.assertEqual(job.compare("upload", self.runner, self.digest, manifest).returncode, 0, "the check accepts the name")
        record = self.path("argv")
        stub_dir = self.path("stub")
        os.makedirs(stub_dir)
        stub = os.path.join(stub_dir, "mvn")
        with open(stub, "w") as fh:
            fh.write(f'#!/bin/sh\nprintf \'%s\\n\' "$@" >> "{record}"\n')
        os.chmod(stub, 0o755)
        self.settings()
        done = self.deploy(path_prefix=stub_dir)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(record, encoding="utf-8") as fh:
            argv = fh.read().splitlines()
        files = [a for a in argv if a.startswith("-Dfiles=")]
        classifiers = [a for a in argv if a.startswith("-Dclassifiers=")]
        self.assertEqual(len(files), 1)
        self.assertEqual(len(files[0].split("=", 1)[1].split(",")), len(classifiers[0].split("=", 1)[1].split(",")),
                         f"one signature per classifier: {files[0]} / {classifiers[0]}")


if __name__ == "__main__":
    unittest.main()
