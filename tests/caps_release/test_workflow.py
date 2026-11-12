"""The structure of caps-release.yml, and one mutation per invariant to prove each can fail."""
from __future__ import annotations

import re
import unittest

import caps_release_helpers as h
import workflow_invariants as w


def read() -> str:
    with open(h.WORKFLOW, encoding="utf-8") as fh:
        return fh.read()


def mutate(text: str, old: str, new: str, nth: int = 0) -> str:
    """Replace the nth occurrence of `old`; the occurrence must exist, so a refactor cannot hollow a mutation out."""
    pos = -1
    for _ in range(nth + 1):
        pos = text.find(old, pos + 1)
        if pos < 0:
            raise AssertionError(f"mutation anchor not found (occurrence {nth}): {old!r}")
    return text[:pos] + new + text[pos + len(old):]


SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
DIGEST = '= "$SCRIPTS_DIGEST" ]'
REMOVAL = "      - name: Remove the signing key\n        if: ${{ always() }}"

MUTATIONS = {
    "secrets-outside-publish:build": [
        ("GH_TOKEN: ${{ github.token }}", "GH_TOKEN: ${{ secrets.GPG_PASSPHRASE }}", 0)],
    "secrets-outside-publish:attest": [("path: uploaded", "path: ${{ secrets.GPG_PASSPHRASE }}", 0)],
    "id-token-outside-attest:build": [
        ("    permissions:\n      contents: read\n    outputs:",
         "    permissions:\n      contents: read\n      id-token: write\n    outputs:", 0)],
    "id-token-outside-attest:publish": [("      packages: write\n", "      packages: write\n      id-token: write\n", 0)],
    "attest-lacks-id-token": [("      id-token: write ", "      contents: read ", 0)],
    "build-permissions": [
        ("    permissions:\n      contents: read\n    outputs:",
         "    permissions:\n      contents: read\n      packages: write\n    outputs:", 0)],
    "attest-runs-code": [("      - name: Attest build provenance (SLSA)", "      - name: Run something\n        run: echo hi\n"
                                                                             "      - name: Attest build provenance (SLSA)", 0)],
    "publish-not-conditional": [("if: ${{ needs.build.outputs.publish == 'true' }}", "if: ${{ always() }}", 0)],
    "secret-value-outside-allowed-step": [
        ("      - name: Write the Maven settings\n        run: |",
         "      - name: Write the Maven settings\n        env:\n          P: ${{ secrets.GPG_PASSPHRASE }}\n        run: |", 0),
        ("run: mvn -B -ntp compile -Dexeris.codegen.skip=true", "run: mvn compile ${{ secrets.GPG_PASSPHRASE }}", 1),
        ("          GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}\n        run:",
         "          GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}\n          GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n        run:", 0),
        ("          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n",
         "          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n          X: ${{ secrets.GPG_PRIVATE_KEY }}\n", 0)],
    "import-step-runs-more": [
        ('GNUPGHOME="$home" gpg --list-secret-keys --keyid-format long',
         'GNUPGHOME="$home" gpg --list-secret-keys --keyid-format long\n          mvn -v', 0)],
    "removal-not-directly-after-signing": [(REMOVAL, "      - name: Interlude\n        run: echo hi\n\n" + REMOVAL, 0)],
    "removal-not-always": [(REMOVAL, "      - name: Remove the signing key\n        if: ${{ success() }}", 0)],
    "digest-not-reverified:build": [(DIGEST, '= "x" ]', 0), (DIGEST, '= "x" ]', 1)],
    "digest-not-reverified:publish": [(DIGEST, '= "x" ]', 2), (DIGEST, '= "x" ]', 3),
                                      ('!= "$SCRIPTS_DIGEST" ]', '!= "x" ]', 0)],
    "digest-not-passed:build": [("          SCRIPTS_DIGEST: ${{ steps.scripts.outputs.digest }}\n        run: |\n          set -euo pipefail\n"
                                 "          mvn -B -ntp -q -P release org.apache.maven.plugins:maven-help-plugin:3.5.1:effective-pom"
                                 " -Doutput=\"$RUNNER_TEMP/effective-pom.xml\"\n          mvn -B -ntp -q -P release org.apache.maven.plugins:maven-dependency",
                                 "        run: |\n          set -euo pipefail\n"
                                 "          mvn -B -ntp -q -P release org.apache.maven.plugins:maven-help-plugin:3.5.1:effective-pom"
                                 " -Doutput=\"$RUNNER_TEMP/effective-pom.xml\"\n          mvn -B -ntp -q -P release org.apache.maven.plugins:maven-dependency", 0)],
    "scripts-checkout-ref:build": [("ref: ${{ github.job_workflow_sha }}", "ref: ${{ github.sha }}", 0)],
    "scripts-checkout-ref:publish": [("ref: ${{ github.job_workflow_sha }}", "ref: main", 1)],
    "scripts-checkout-missing:build": [("          repository: exeris-systems/.github\n", "", 0)],
    "upload-default": [("upload:         { type: boolean, default: false,", "upload:         { type: boolean, default: true, ", 0)],
    "target-default": [('default: "none"', 'default: "github-packages"', 0), ('type: string,  default: "none",', 'type: string,  default: "",    ', 0)],
    "gate-not-staging:build": [('--stage "$RUNNER_TEMP/gated-files"', '--stage "$RUNNER_TEMP/elsewhere"', 0),
                               (' --stage "$RUNNER_TEMP/gated-files"', "", 0)],
    "gate-not-staging:publish": [('--stage "$RUNNER_TEMP/gated-files"', '--stage "$RUNNER_TEMP/elsewhere"', 1),
                                 (' --stage "$RUNNER_TEMP/gated-files"', "", 1)],
    "gate-step-not-unique:build": [("check_release_readiness.py", "check_release_readiness_.py", 0)],
    "upload-from-target:build": [("          path: ${{ runner.temp }}/gated-files\n", "          path: target\n", 0),
                                 ("          path: ${{ runner.temp }}/gated-files\n",
                                  "          path: |\n            ${{ runner.temp }}/gated-files\n            target/*.jar\n", 0)],
    "upload-from-target:publish": [("          path: ${{ runner.temp }}/gated-files\n", "          path: target/\n", 1),
                                   ("          path: ${{ runner.temp }}/gated-files\n",
                                    "          path: |\n            ${{ runner.temp }}/gated-files\n            target/central-publishing/*.zip\n", 1)],
    "upload-not-on-success:build": [
        ("      - name: Keep what was built as a run artifact\n", "      - name: Keep what was built as a run artifact\n        if: always()\n", 0),
        ("      - name: Keep what was built as a run artifact\n", "      - name: Keep what was built as a run artifact\n        if: ${{ always() }}\n", 0),
        ("      - name: Keep what was built as a run artifact\n", "      - name: Keep what was built as a run artifact\n        if: ${{ failure() }}\n", 0),
        ("      - name: Keep what was built as a run artifact\n", "      - name: Keep what was built as a run artifact\n        if: ${{ !cancelled() }}\n", 0)],
    "upload-not-on-success:publish": [
        ("      - name: Keep what was uploaded as a run artifact\n", "      - name: Keep what was uploaded as a run artifact\n        if: always()\n", 0),
        ("      - name: Keep what was uploaded as a run artifact\n", "      - name: Keep what was uploaded as a run artifact\n        if: ${{ always() }}\n", 0),
        ("      - name: Keep what was uploaded as a run artifact\n", "      - name: Keep what was uploaded as a run artifact\n        if: ${{ failure() || success() }}\n", 0)],
    "forbidden-word:central": [("# Reusable: release", "# a central repository\n# Reusable: release", 0),
                               ("name: caps-release\n", "name: caps-release-central\n", 0), ("run: mvn -B -ntp compile", "run: mvn -B -ntp -Pcentral compile", 0)],
    "forbidden-word:central_token": [("GPG_PASSPHRASE:         { required: false", "CENTRAL_TOKEN_USERNAME: { required: false", 0)],
    "forbidden-word:expect_bundle": [("          GENERATED: ${{ inputs.generated-path }}\n          SCRIPTS_DIGEST", "          EXPECT_BUNDLE: false\n          SCRIPTS_DIGEST", 0)],
    "forbidden-word:--expect-bundle": [("--gpg /usr/bin/gpg --stage", "--gpg /usr/bin/gpg --expect-bundle false --stage", 0)],
    "forbidden-word:sonatype": [("# Reusable: release", "# sonatype\n# Reusable: release", 0)],
    "target-values": [("or 'github-packages'\"", "or 'github-package'\"", 0),
                      ("if: ${{ needs.build.outputs.publish == 'true' }}", "if: ${{ needs.build.outputs.publish == 'true' && inputs.target == 'maven' }}", 0),
                      ],
    "publish-permissions": [("      contents: read\n      packages: write\n", "      contents: read\n", 0),
                            ("      contents: read\n      packages: write\n", "      contents: write\n      packages: write\n", 0),
                            ("      contents: read\n      packages: write\n", "      contents: read\n      packages: write\n      actions: write\n", 0)],
    "attest-permissions": [("      attestations: write   # writing the attestation back to the repository\n", "", 0),
                           ("      id-token: write       # SLSA provenance signing (Sigstore, keyless)\n", "", 0),
                           ("      attestations: write ", "      packages: write\n      attestations: write ", 0)],
    "publish-output-not-resolved": [("      publish: ${{ steps.rel.outputs.publish }}", "      publish: 'true'", 0),
                                    ("      publish: ${{ steps.rel.outputs.publish }}", "      publish: ${{ steps.rel.outputs.version }}", 0)],
    "publish-not-resolved-from-inputs": [("          IN_TARGET: ${{ inputs.target }}", "          IN_TARGET: github-packages", 0),
                                         ("          IN_UPLOAD: ${{ inputs.upload }}", "          IN_UPLOAD: true", 0),
                                         ('--target "$IN_TARGET" --upload "$IN_UPLOAD"', '--target github-packages --upload "$IN_UPLOAD"', 0),
                                         ('--target "$IN_TARGET" --upload "$IN_UPLOAD"', '--target "$IN_TARGET" --upload true', 0)],
    "token-outside-upload": [("      - name: Write the Maven settings\n        run: |",
                              "      - name: Write the Maven settings\n        env:\n          GH_TOKEN: ${{ github.token }}\n        run: |", 0),
                             ("      - name: Import the signing key\n        env:", "      - name: Import the signing key\n        env:\n          GITHUB_TOKEN: ${{ github.token }}", 0),
                             ("          GITHUB_TOKEN: ${{ github.token }}\n        run: |\n          set -euo pipefail\n          cd ", "        run: |\n          set -euo pipefail\n          cd ", 0),
                             ("      - name: Seed capability metadata (first pass, codegen skipped)\n        run: mvn -B -ntp compile -Dexeris.codegen.skip=true",
                              "      - name: Seed capability metadata (first pass, codegen skipped)\n        env:\n          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n        run: mvn -B -ntp compile -Dexeris.codegen.skip=true", 1)],
    "passphrase-outside-sign": [("          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n", "", 0),
                                ("      - name: Upload the gated files\n        env:\n", "      - name: Upload the gated files\n        env:\n          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n", 0)],
    "step-holds-token-and-passphrase": [("          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n", "          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n          GITHUB_TOKEN: ${{ github.token }}\n", 0),
                                         ("          GITHUB_TOKEN: ${{ github.token }}\n        run: |\n          set -euo pipefail\n          cd ", "          GITHUB_TOKEN: ${{ github.token }}\n          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n        run: |\n          set -euo pipefail\n          cd ", 0)],
    "sign-step-not-unique": [("run: mvn -B -ntp -P release verify -DskipTests", "run: mvn -B -ntp -P release package -DskipTests", 0)],
    "upload-step-not-unique": [("maven-deploy-plugin:3.1.4:deploy-file", "maven-deploy-plugin:3.1.4:deploy", 0)],
    "upload-goal": [("org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file", "org.apache.maven.plugins:maven-install-plugin:3.1.4:deploy-file", 0),
                    ("org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file", "org.apache.maven.plugins:maven-deploy-plugin:deploy-file", 0),
                    ("org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file", "org.apache.maven.plugins:maven-deploy-plugin:LATEST:deploy-file", 0)],
    "upload-with-profile": [("mvn -B -ntp org.apache.maven.plugins:maven-deploy-plugin", "mvn -B -ntp -P release org.apache.maven.plugins:maven-deploy-plugin", 0),
                            ("mvn -B -ntp org.apache.maven.plugins:maven-deploy-plugin", "mvn -B -ntp -Prelease org.apache.maven.plugins:maven-deploy-plugin", 0),
                            ("              --settings \"$RUNNER_TEMP/release-settings.xml\" \\\n", "              --settings \"$RUNNER_TEMP/release-settings.xml\" --activate-profiles release \\\n", 0)],
    "upload-loads-a-project": [("              --settings \"$RUNNER_TEMP/release-settings.xml\" \\\n", "              --settings \"$RUNNER_TEMP/release-settings.xml\" -f \"$GITHUB_WORKSPACE/pom.xml\" \\\n", 0),
                               ("              --settings \"$RUNNER_TEMP/release-settings.xml\" \\\n", "              --settings \"$RUNNER_TEMP/release-settings.xml\" --file ../pom.xml \\\n", 0),
                               ("              --settings \"$RUNNER_TEMP/release-settings.xml\" \\\n", "              --settings \"$RUNNER_TEMP/release-settings.xml\" -pl x \\\n", 0)],
    "upload-directory": [('          cd "$RUNNER_TEMP/gated-files"\n', "", 0),
                         ('          cd "$RUNNER_TEMP/gated-files"\n', '          cd "$RUNNER_TEMP"\n', 0),
                         ('          cd "$RUNNER_TEMP/gated-files"\n', '          cd "$GITHUB_WORKSPACE"\n', 0),
                         ("      - name: Upload the gated files\n        env:", "      - name: Upload the gated files\n        working-directory: ${{ github.workspace }}\n        env:", 0),
                         ('          cd "$RUNNER_TEMP/gated-files"\n', '          cd "$RUNNER_TEMP/gated-files"\n          cp "$GITHUB_WORKSPACE/pom.xml" "$RUNNER_TEMP/gated-files/pom.xml"\n', 0)],
    "upload-url": [('-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}"', '-Durl="https://maven.pkg.github.com/other/repo"', 0),
                   ('-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}"', '-Durl="http://maven.pkg.github.com/${GITHUB_REPOSITORY}"', 0),
                   ('-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}"', '-Durl="https://example.org/${GITHUB_REPOSITORY}"', 0),
                   ('-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}"', '-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}/"', 0),
                   ('-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}"', '-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}" -DaltDeploymentRepository=x::https://example.org/r', 0),
                   ('-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}"', '-Durl="${DEPLOY_URL}"', 0)],
    "upload-server-id": [("-DrepositoryId=github", "-DrepositoryId=other", 0), ("<id>github</id>", "<id>other</id>", 0)],
    "upload-settings": [('              --settings "$RUNNER_TEMP/release-settings.xml" \\\n', "", 0),
                        ('--settings "$RUNNER_TEMP/release-settings.xml"', "--settings settings.xml", 0)],
    "upload-empty-allowed:build": [("          if-no-files-found: error\n", "          if-no-files-found: warn\n", 0),
                                   ("          if-no-files-found: error\n", "          if-no-files-found: ignore\n", 0),
                                   ("          if-no-files-found: error\n", "", 0)],
    "upload-empty-allowed:publish": [("          if-no-files-found: error\n", "          if-no-files-found: warn\n", 1),
                                     ("          if-no-files-found: error\n", "          if-no-files-found: ignore\n", 1),
                                     ("          if-no-files-found: error\n", "", 1)],
    "gated-files-written-elsewhere:build": [
        ("      - name: Keep what was built as a run artifact\n",
         "      - name: Prepare\n        run: mkdir -p \"$RUNNER_TEMP/gated-files\"\n      - name: Keep what was built as a run artifact\n", 0)],
    "gated-files-written-elsewhere:publish": [
        ("      - name: Keep what was uploaded as a run artifact\n",
         "      - name: Prepare\n        env:\n          D: ${{ runner.temp }}/gated-files\n        run: cp -r target \"$D\"\n"
         "      - name: Keep what was uploaded as a run artifact\n", 0)],
    "upload-path-not-gated:build": [("          path: ${{ runner.temp }}/gated-files\n", "          path: ${{ runner.temp }}/other\n", 0)],
    "upload-path-not-gated:publish": [("          path: ${{ runner.temp }}/gated-files\n", "          path: ${{ runner.temp }}/other\n", 1)],
    "upload-missing:build": [("        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2",
                              "        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1", 0)],
    "upload-missing:publish": [("        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2",
                                "        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1", 1)],
    "attest-subject-outside-download": [("            uploaded/**/*.jar\n", "            target/**/*.jar\n", 0),
                                        ("            uploaded/**/*.pom\n", "            uploaded/**/*.pom\n            ../target/*.jar\n", 0),
                                        ("          path: uploaded\n", "          path: elsewhere\n", 0)],
    "attest-before-download": [('      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1\n        with:\n          name: release-${{ needs.build.outputs.version }}\n          path: uploaded\n      - name: Attest build provenance (SLSA)\n        uses: actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8 # v4.2.2\n        with:\n          subject-path: |\n            uploaded/**/*.jar\n            uploaded/**/*.pom\n', '      - name: Attest build provenance (SLSA)\n        uses: actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8 # v4.2.2\n        with:\n          subject-path: |\n            uploaded/**/*.jar\n            uploaded/**/*.pom\n      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1\n        with:\n          name: release-${{ needs.build.outputs.version }}\n          path: uploaded\n', 0)],
    "attest-wrong-artifact": [("          name: release-${{ needs.build.outputs.version }}\n          path: uploaded",
                               "          name: release-gate-${{ needs.build.outputs.version }}\n          path: uploaded", 0)],
    "attest-steps-unexpected": [("      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1",
                                 "      - uses: actions/checkout@" + SHA, 0)],
    "uses-not-pinned": [(f"actions/checkout@{SHA}", "actions/checkout@v7", 0),
                        (f"actions/checkout@{SHA}", "actions/checkout@" + SHA[:39], 3),
                        ("actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9", "actions/upload-artifact@main", 1),
                        ("actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
                         "actions/attest-build-provenance@" + "G" * 40, 0)],
}


class Real(h.Case):
    def test_the_workflow_breaks_no_invariant(self):
        self.assertEqual(w.violations(read()), set())

    def test_the_parse_sees_what_the_invariants_assume(self):
        wf = w.parse(read())
        self.assertEqual(set(wf["jobs"]), {"build", "publish", "attest"})
        self.assertGreaterEqual(len(wf["jobs"]["build"]["steps"]), 10)
        self.assertGreaterEqual(len(wf["jobs"]["publish"]["steps"]), 10)
        names = [s["name"] for s in wf["jobs"]["publish"]["steps"]]
        self.assertIn("Import the signing key", names)
        self.assertIn("Build and sign", names)
        self.assertEqual(names.index("Remove the signing key"), names.index("Build and sign") + 1)

    def test_the_build_job_names_no_secret_at_all(self):
        build = "\n".join(w.parse(read())["jobs"]["build"]["lines"])
        self.assertNotRegex(build, r"\bsecrets\b")

    def test_only_publish_holds_secrets_and_only_attest_the_id_token(self):
        text = read()
        jobs = w.parse(text)["jobs"]
        self.assertRegex("\n".join(jobs["publish"]["lines"]), r"secrets\.GPG_PRIVATE_KEY")
        self.assertEqual([n for n, j in jobs.items() if re.search(r"id-token:\s*write", "\n".join(j["header"]))], ["attest"])

    def test_the_secrets_each_step_holds(self):
        steps = w.parse(read())["jobs"]["publish"]["steps"]
        held = {s["name"]: sorted({n for where, n, boolean in w.secret_refs(s) if not boolean}) for s in steps}
        held = {k: v for k, v in held.items() if v}
        self.assertEqual(held, {
            "Import the signing key": ["GPG_PRIVATE_KEY"],
            "Build and sign": ["GPG_PASSPHRASE"],
        })

    def test_every_uses_is_a_40_hex_pin(self):
        uses = re.findall(r"^\s*(?:- )?uses:\s*(\S+)", "\n".join(w.strip_comments(read())), re.M)
        self.assertGreaterEqual(len(uses), 8)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

    def test_both_gate_steps_stage_and_both_uploads_take_the_staged_set(self):
        wf = w.parse(read())["jobs"]
        for job in ("build", "publish"):
            gates = [s for s in wf[job]["steps"] if "check_release_readiness.py" in s["run"]]
            self.assertEqual(len(gates), 1, job)
            self.assertRegex(gates[0]["run"], r'--stage "\$RUNNER_TEMP/gated-files"')
            uploads = [s for s in wf[job]["steps"] if s["uses"].startswith("actions/upload-artifact@")]
            self.assertEqual(len(uploads), 1, job)
            self.assertEqual(w.block_lines(uploads[0], "path"), [w.GATED])
            self.assertNotIn("target", uploads[0]["raw"].replace("target:", ""))

    def test_both_upload_steps_fail_when_they_find_no_file(self):
        wf = w.parse(read())["jobs"]
        for job in ("build", "publish"):
            uploads = [s for s in wf[job]["steps"] if s["uses"].startswith("actions/upload-artifact@")]
            self.assertEqual(len(uploads), 1, job)
            self.assertEqual(uploads[0]["with"].get("if-no-files-found"), "error", job)

    def test_neither_upload_step_has_a_condition_and_nothing_but_the_gate_names_the_staging_directory(self):
        wf = w.parse(read())["jobs"]
        for job in ("build", "publish"):
            steps = wf[job]["steps"]
            uploads = [s for s in steps if s["uses"].startswith("actions/upload-artifact@")]
            self.assertEqual(len(uploads), 1, job)
            self.assertEqual(uploads[0]["if"], "", f"{job}: an upload that runs after a failed gate would keep what was refused")
            self.assertNotRegex(uploads[0]["raw"], r"\b(always|failure|cancelled)\s*\(")
            gate = [i for i, s in enumerate(steps) if "check_release_readiness.py" in s["run"]]
            self.assertEqual(len(gate), 1, job)
            self.assertLess(gate[0], steps.index(uploads[0]), f"{job}: the upload follows the gate")
            names = [s["name"] for s in steps if "gated-files" in s["run"]]
            self.assertEqual(names, [steps[gate[0]]["name"]] + (["Upload the gated files"] if job == "publish" else []), job)

    def test_the_attestation_takes_its_subjects_only_from_the_downloaded_artifact(self):
        steps = w.parse(read())["jobs"]["attest"]["steps"]
        download = [s for s in steps if s["uses"].startswith("actions/download-artifact@")]
        attest = [s for s in steps if s["uses"].startswith("actions/attest-build-provenance@")]
        self.assertEqual((len(download), len(attest)), (1, 1))
        root = download[0]["with"]["path"]
        subjects = w.block_lines(attest[0], "subject-path")
        self.assertTrue(subjects)
        for subject in subjects:
            self.assertTrue(subject.startswith(root + "/"), subject)
        self.assertEqual(download[0]["with"]["name"], "release-${{ needs.build.outputs.version }}")

    def test_the_block_reader_reads_blocks_and_one_line_values(self):
        step = w.step(["      - uses: x/y@" + "0" * 40, "        with:", "          path: |", "            a/b", "            c", "          name: n"])
        self.assertEqual(w.block_lines(step, "path"), ["a/b", "c"])
        self.assertEqual(w.block_lines(step, "name"), ["n"])
        self.assertEqual(w.block_lines(step, "absent"), [])

    def test_the_inputs_default_to_no_upload(self):
        text = "\n".join(w.strip_comments(read()))
        self.assertRegex(text, r"upload:\s*\{[^}]*type:\s*boolean,\s*default:\s*false")
        self.assertRegex(text, r'target:\s*\{[^}]*default:\s*"none"')


class Mutations(h.Case):
    def test_every_invariant_is_killed_by_its_mutations(self):
        text = read()
        self.assertEqual(w.violations(text), set())
        survivors = []
        for expected, edits in MUTATIONS.items():
            for old, new, nth in edits:
                broken = mutate(text, old, new, nth)
                self.assertNotEqual(broken, text)
                got = w.violations(broken)
                if expected not in got:
                    survivors.append((expected, old[:50], nth, sorted(got)))
        self.assertEqual(survivors, [], "mutations the invariants did not notice")

    def test_every_invariant_the_checker_can_report_has_a_mutation(self):
        import inspect
        source = inspect.getsource(w.violations)
        ids = set(re.findall(r'out\.add\(f?"([\w-]+)', source))
        covered = {k.split(":")[0] for k in MUTATIONS}
        # identifiers about the shape of the parse itself are not workflow properties
        ignore = {"job-missing", "import-step-not-unique", "removal-step-not-unique",
                  "publish-reads-no-secret", "top-level-write-permission", "build-not-read-only",
                  "attestations-outside-attest", "packages-outside-publish", "attest-not-conditional",
                  "scripts-checkout-ref",
                  # reordering needs a rewrite of two steps: test_steps_moved_out_of_order_are_caught
                  "upload-before-gate", "removal-before-signing", "removal-after-gate", "removal-after-upload", "gate-after-upload"}
        self.assertEqual(sorted(ids - covered - ignore), [])

    def test_an_upload_moved_ahead_of_its_gate_is_caught_in_each_job(self):
        text = read()
        for upload_marker, next_marker, jname in (
                ("      - name: Keep what was built as a run artifact\n", "  publish:\n", "build"),
                ("      - name: Keep what was uploaded as a run artifact\n", "  attest:\n", "publish")):
            with self.subTest(jname):
                gate_step = self.step_containing(text, "check_release_readiness.py", jname)
                a, b = gate_step
                upload_start = text.index(upload_marker)
                upload_end = text.index(next_marker, upload_start)
                upload = text[upload_start:upload_end]
                swapped = text[:a] + upload.rstrip("\n") + "\n\n" + text[a:b] + text[b:upload_start] + text[upload_end:]
                self.assertNotEqual(swapped, text)
                self.assertIn(f"upload-before-gate:{jname}", w.violations(swapped))

    @staticmethod
    def step_containing(text, needle, jname):
        """(start, end) of the workflow step that holds NEEDLE in the job JNAME ('build' or 'publish')."""
        job_start = text.index(f"\n  {jname}:\n")
        at = text.index(needle, job_start)
        start = text.rindex("\n      - ", job_start, at) + 1
        end = text.find("\n      - ", at)
        return start, end + 1

    @staticmethod
    def blocks(text, jname):
        """(start, end, name) of every step of the job JNAME, cut at the step markers of its indentation."""
        job_start = text.index(f"\n  {jname}:\n") + 1
        nxt = re.search(r"^  [\w-]+:\s*$|^# ", text[job_start + 1:], re.M)
        job_end = job_start + 1 + nxt.start() if nxt else len(text)
        starts = [m.start() for m in re.finditer(r"^      - ", text[job_start:job_end], re.M)]
        out = []
        for i, a in enumerate(starts):
            b = starts[i + 1] if i + 1 < len(starts) else job_end - job_start
            name = re.match(r"      - (?:name|uses): (.*)", text[job_start + a:job_start + b]).group(1)
            out.append((job_start + a, job_start + b, name))
        return out

    def move(self, text, jname, name, before):
        """The workflow with the step NAME of job JNAME moved to stand directly before the step BEFORE."""
        blocks = self.blocks(text, jname)
        a, b, _ = next(x for x in blocks if x[2] == name)
        step = text[a:b]
        rest = text[:a] + text[b:]
        blocks = self.blocks(rest, jname)
        at = next(x for x in blocks if x[2] == before)[0]
        return rest[:at] + step.rstrip("\n") + "\n\n" + rest[at:]

    def test_steps_moved_out_of_order_are_caught(self):
        text = read()
        cases = (("Remove the signing key", "Build and sign", "removal-before-signing"),
                 ("Remove the signing key", "Upload the gated files", "removal-after-gate"),
                 ("Remove the signing key", "Keep what was uploaded as a run artifact", "removal-after-upload"),
                 ("Upload the gated files", "Gate what was built", "gate-after-upload"),
                 ("Gate what was built", "Keep what was uploaded as a run artifact", "gate-after-upload"))
        for name, before, expected in cases:
            with self.subTest(f"{name} before {before}"):
                moved = self.move(text, "publish", name, before)
                self.assertNotEqual(moved, text)
                self.assertIn(expected, w.violations(moved))
        self.assertEqual(w.violations(self.move(text, "publish", "Write the Maven settings", "Import the signing key")), set(),
                         "a move that breaks nothing is not reported")

    def test_the_upload_step_is_what_the_comments_say(self):
        """The upload runs one goal of the deploy plugin per pom, from the staging directory, with the settings the workflow wrote."""
        steps = w.parse(read())["jobs"]["publish"]["steps"]
        upload = [s for s in steps if s["name"] == "Upload the gated files"]
        self.assertEqual(len(upload), 1)
        run = upload[0]["run"]
        self.assertRegex(run, r'cd "\$RUNNER_TEMP/gated-files"\n')
        self.assertIn('-Durl="https://maven.pkg.github.com/${GITHUB_REPOSITORY}"', run)
        self.assertEqual(re.findall(r"[a-z]+://[^\s\"']+", run), ["https://maven.pkg.github.com/${GITHUB_REPOSITORY}"])
        self.assertNotRegex(run, r"(?<![\w-])-P|--activate-profiles|(?<![\w-])-f\b|--file\b")
        self.assertEqual(upload[0]["env"], {"GITHUB_TOKEN": "${{ github.token }}"})

    def test_no_step_holds_the_token_and_the_passphrase_and_each_is_held_once(self):
        steps = w.parse(read())["jobs"]["publish"]["steps"]
        token = [s["name"] for s in steps if w.holds_token(s)]
        passphrase = [s["name"] for s in steps if w.holds_passphrase(s)]
        self.assertEqual(token, ["Upload the gated files"])
        self.assertEqual(passphrase, ["Build and sign"])
        self.assertFalse(any(w.holds_token(s) for s in w.parse(read())["jobs"]["attest"]["steps"]))

    def test_the_permissions_of_each_job_are_exactly_these(self):
        jobs = w.parse(read())["jobs"]
        self.assertEqual(w.permissions(jobs["build"]), {"contents": "read"})
        self.assertEqual(w.permissions(jobs["publish"]), {"contents": "read", "packages": "write"})
        self.assertEqual(w.permissions(jobs["attest"]), {"contents": "read", "id-token": "write", "attestations": "write"})

    def test_the_file_names_no_other_target_and_no_bundle(self):
        text = read().lower()
        for word in ("central", "central_token", "expect_bundle", "--expect-bundle", "sonatype", "ossrh", "maven central"):
            self.assertNotIn(word, text)

    def test_the_parse_notices_a_secret_moved_into_a_comment_only_when_it_is_shell(self):
        text = read()
        yaml_comment = mutate(text, "      - name: Write the Maven settings", "      # ${{ secrets.X }}\n      - name: Write the Maven settings")
        self.assertEqual(w.violations(yaml_comment), set())     # a YAML comment is not evaluated
        shell_comment = mutate(text, "          home=\"$RUNNER_TEMP/dry-run-gnupg\"\n",
                               "          # ${{ secrets.X }}\n          home=\"$RUNNER_TEMP/dry-run-gnupg\"\n")
        self.assertIn("secrets-outside-publish:build", w.violations(shell_comment))   # evaluated by GitHub even there


if __name__ == "__main__":
    unittest.main()
