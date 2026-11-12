"""The structure of caps-release.yml, and mutations that prove each invariant can fail.

`workflow_invariants.violations` reads the workflow as data. Here the real workflow must break nothing,
every identifier the checker can report must have a mutation that makes it report that identifier, and
the questions about what a capability controls (the inputs, the artifact, the manifest) are asserted on
the real text.
"""
from __future__ import annotations

import inspect
import os
import re
import unittest

import caps_release_helpers as h
import workflow_invariants as w
from manifest_support import SCRIPT, make_coordinate, parse_github_output, put


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


def mutate_in(text: str, job: str, old: str, new: str, nth: int = 0) -> str:
    """The same inside the text of one job, so a step that every job repeats is changed in that job alone."""
    a, b = w.region(text, job)
    return text[:a] + mutate(text[a:b], old, new, nth) + text[b:]


def apply(text: str, edits) -> str:
    for edit in edits:
        job, old, new, *nth = edit
        text = mutate(text, old, new, *nth) if job is None else mutate_in(text, job, old, new, *nth)
    return text


SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
STEP = "      - name: Extra\n        run: echo hi\n"
CHECKOUT_CALLER = f"      - uses: actions/checkout@{SHA}\n        with:\n          persist-credentials: false\n"
GATE_DIGEST = '= "$SCRIPTS_DIGEST" ]'
COMPARE = "      - name: Compare the downloaded files with the manifest\n"
SETTINGS = "      - name: Write the Maven settings\n        run: |\n"
UPLOAD = "      - name: Upload the gated files\n"
DOWNLOAD_BLOCK = "          name: ${{ needs.publish.outputs.artifact }}\n"
TOKEN = "${{ github.token }}"
GATE_RUN = "          /usr/bin/python3 -I -B \"$S/staged_manifest.py\" create"

MUTATIONS: dict[str, list[list[tuple]]] = {}


def mut(ident, *variants):
    MUTATIONS.setdefault(ident, []).extend(v if isinstance(v, list) else [v] for v in variants)


# --- words, defaults, the job graph ---------------------------------------------------------------------------------------
for word in ("central", "sonatype", "expect_bundle", "central_token", "--expect-bundle"):
    mut(f"forbidden-word:{word}", [(None, "name: caps-release\n", f"name: caps-release\n# {word}\n")])
mut("target-values", [(None, "(nothing is uploaded) or 'github-packages'", "(nothing is uploaded) or 'ghcr'")])
mut("upload-default", [(None, "upload:         { type: boolean, default: false", "upload:         { type: boolean, default: true")])
mut("target-default", [(None, 'target:         { type: string,  default: "none"', 'target:         { type: string,  default: "github-packages"')])
mut("publish-output-not-resolved", [("build", "publish: ${{ steps.rel.outputs.publish }}", "publish: ${{ inputs.upload }}")])
mut("publish-not-resolved-from-inputs", [("build", "IN_TARGET: ${{ inputs.target }}", "IN_TARGET: github-packages")],
    [("build", "IN_UPLOAD: ${{ inputs.upload }}", "IN_UPLOAD: true")])
mut("jobs-unexpected", [(None, "  attest:\n    name: attest build provenance\n", "  extra:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n  attest:\n    name: attest build provenance\n")])
for job in ("build", "publish", "upload", "attest"):
    mut(f"job-missing:{job}", [(None, f"\n  {job}:\n", f"\n  {job}x:\n")])
mut("job-graph:build", [("build", "    runs-on: ubuntu-latest\n", "    runs-on: ubuntu-latest\n    if: ${{ always() }}\n")])
mut("job-graph:publish", [("publish", "    needs: build\n", "    needs: [build]\n")])
mut("job-graph:upload", [("upload", "needs: [build, publish]", "needs: [publish]")])
mut("job-graph:attest", [("attest", "needs: [publish, upload]", "needs: [publish]")])
mut("publish-not-conditional", [("publish", "if: ${{ needs.build.outputs.publish == 'true' }}", "if: ${{ always() }}")])
mut("upload-not-conditional", [("upload", " && needs.publish.result == 'success' }}", " }}")],
    [("upload", " && needs.publish.result == 'success' }}", " || always() }}")])
mut("attest-not-conditional", [("attest", "if: ${{ needs.upload.result == 'success' }}", "if: ${{ needs.upload.result != 'failure' }}")],
    [("attest", "if: ${{ needs.upload.result == 'success' }}", "if: ${{ always() }}")],
    [("attest", "if: ${{ needs.upload.result == 'success' }}", "if: ${{ needs.publish.result == 'success' }}")])

# --- permissions -----------------------------------------------------------------------------------------------------------
PERMS = "    permissions:\n      contents: read\n"
mut("permissions:build", [("build", PERMS, PERMS + "      packages: write\n")], [("build", PERMS, PERMS + "      contents: write\n")])
mut("permissions:publish", [("publish", PERMS, PERMS + "      packages: write\n")], [("publish", PERMS, "    permissions: write-all\n")],
    [("publish", PERMS, "    permissions:\n      contents: write\n")], [("publish", PERMS, "    permissions:\n      contents: read\n      actions: write\n")])
mut("permissions:upload", [("upload", "      packages: write\n", "      packages: read\n")], [("upload", "      packages: write\n", "      packages: write\n      contents: write\n")],
    [("upload", "      packages: write\n", "      packages: write\n      id-token: write\n")])
mut("permissions:attest", [("attest", "attestations: write", "attestations: read")], [("attest", "      id-token: write", "      id-token: none")])
mut("packages-write-outside-upload:build", [("build", PERMS, PERMS + "      packages: write\n")])
mut("packages-write-outside-upload:publish", [("publish", PERMS, PERMS + "      packages: write\n")])
mut("packages-write-outside-upload:attest", [("attest", "      contents: read\n", "      contents: read\n      packages: write\n")])
for job in ("build", "publish", "upload"):
    mut(f"id-token-outside-attest:{job}", [(job, PERMS if job != "upload" else "      packages: write\n", (PERMS if job != "upload" else "      packages: write\n") + "      id-token: write\n")])
    mut(f"attestations-outside-attest:{job}", [(job, PERMS if job != "upload" else "      packages: write\n", (PERMS if job != "upload" else "      packages: write\n") + "      attestations: write\n")])
mut("top-level-write-permission", [(None, "permissions:\n  contents: read\njobs:", "permissions:\n  contents: write\njobs:")],
    [(None, "permissions:\n  contents: read\njobs:", "permissions:\n  contents: read\n  packages: write\njobs:")])

# --- who holds the job token and the signing secrets -----------------------------------------------------------------------
SPELLINGS = ("${{ github.token }}", "${{ secrets.GITHUB_TOKEN }}", "${{ GITHUB.TOKEN }}", "${{ github['token'] }}", '${{ github["token"] }}',
             "${{ secrets['GITHUB_TOKEN'] }}", "${{ toJSON(github) }}", "${{ env.GITHUB_TOKEN }}")
PUBLISH_SEED = "      - name: Seed capability metadata (first pass, codegen skipped)\n"
for spelling in SPELLINGS:
    mut("token-holders:publish", [("publish", PUBLISH_SEED, PUBLISH_SEED + f"        env:\n          X: {spelling}\n")])
    mut("token-holders:attest", [("attest", "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n", f"          MANIFEST: ${{{{ needs.publish.outputs.manifest }}}}\n          X: {spelling}\n")])
    mut("token-holders:upload", [("upload", "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n", f"          MANIFEST: ${{{{ needs.publish.outputs.manifest }}}}\n          X: {spelling}\n")])
    mut("token-holders:build", [("build", "      - name: Seed capability metadata (first pass, codegen skipped)\n", f"      - name: Seed capability metadata (first pass, codegen skipped)\n        env:\n          X: {spelling}\n")])
mut("token-holders:publish", [("publish", "        run: mvn -B -ntp compile -Dexeris.codegen.skip=true", "        env:\n          GITHUB_TOKEN: x\n        run: mvn -B -ntp compile -Dexeris.codegen.skip=true")],
    [("publish", "        run: mvn -B -ntp compile -Dexeris.codegen.skip=true", '        run: curl -H "Authorization: ${{ github.token }}" x')],
    [("publish", "        run: mvn -B -ntp compile -Dexeris.codegen.skip=true", '        run: curl -H "Authorization: $GITHUB_TOKEN" x')],
    [("publish", PUBLISH_SEED, PUBLISH_SEED + "        if: ${{ github.token != '' }}\n")],
    [("publish", "          distribution: ${{ inputs.java-distribution }}\n", "          distribution: ${{ inputs.java-distribution }}\n          token: ${{ github.token }}\n")])
mut("token-holders:attest", [("attest", "      - name: Attest build provenance (SLSA)\n", "      - name: Attest build provenance (SLSA)\n        env:\n          GH_TOKEN: x\n")])
mut("token-holders:upload", [("upload", SETTINGS, SETTINGS.replace("        run: |\n", "        env:\n          GITHUB_TOKEN: x\n        run: |\n"))],
    [("upload", "          distribution: ${{ inputs.java-distribution }}\n", "          distribution: ${{ inputs.java-distribution }}\n          token: ${{ github.token }}\n")],
    [("upload", "          cat > \"$RUNNER_TEMP/release-settings.xml\" <<'XML'", "          echo \"${{ github.token }}\"\n          cat > \"$RUNNER_TEMP/release-settings.xml\" <<'XML'")],
    [("upload", "                <password>${env.GITHUB_TOKEN}</password>", "                <password>${{ github.token }}</password>")],
    [("upload", UPLOAD + "        env:\n          GITHUB_TOKEN: ${{ github.token }}\n", UPLOAD)])
mut("token-holders:build", [("build", "          GH_TOKEN: ${{ github.token }}\n", "")])
mut("token-form:build", [("build", "GH_TOKEN: ${{ github.token }}", "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}")],
    [("build", "          GH_TOKEN: ${{ github.token }}\n", "          GH_TOKEN: ${{ github.token }}\n          GITHUB_TOKEN: ${{ github.token }}\n")])
mut("token-form:upload", [("upload", "GITHUB_TOKEN: ${{ github.token }}", "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}")],
    [("upload", "GITHUB_TOKEN: ${{ github.token }}", "GITHUB_TOKEN: ${{ github.token }}\n          GH_TOKEN: ${{ github.token }}")],
    [("upload", "          cd \"$RUNNER_TEMP/gated-download\"", "          cd \"$RUNNER_TEMP/gated-download\"\n          echo \"${{ github.token }}\" > /dev/null")])
mut("upload-token-step-not-last", [("upload", "              -Dtypes=\"jar.asc,pom.asc,jar.asc,jar.asc\"\n          done\n", "              -Dtypes=\"jar.asc,pom.asc,jar.asc,jar.asc\"\n          done\n\n" + STEP)])
mut("token-before-last-step", [("upload", SETTINGS, SETTINGS.replace("        run: |\n", "        env:\n          GITHUB_TOKEN: ${{ github.token }}\n        run: |\n"))])
mut("secrets-outside-publish:build", [("build", "GH_TOKEN: ${{ github.token }}", "GH_TOKEN: ${{ secrets.GPG_PASSPHRASE }}")],
    [("build", "          home=\"$RUNNER_TEMP/dry-run-gnupg\"\n", "          # ${{ secrets.X }}\n          home=\"$RUNNER_TEMP/dry-run-gnupg\"\n")])
mut("secrets-outside-publish:upload", [("upload", "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n", "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n          K: ${{ secrets.GPG_PRIVATE_KEY }}\n")],
    [("upload", "          cat > \"$RUNNER_TEMP/release-settings.xml\" <<'XML'", "          # ${{ secrets.GPG_PASSPHRASE }}\n          cat > \"$RUNNER_TEMP/release-settings.xml\" <<'XML'")])
mut("secrets-outside-publish:attest", [("attest", "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n", "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n          K: ${{ secrets.GPG_PASSPHRASE }}\n")])
mut("publish-reads-no-secret", [("publish", "secrets.GPG_PRIVATE_KEY != ''", "false"), ("publish", "secrets.GPG_PASSPHRASE != ''", "false"),
                                 ("publish", "${{ secrets.GPG_PRIVATE_KEY }}", "x"), ("publish", "${{ secrets.GPG_PASSPHRASE }}", "x")])
KEYSTEP = "      - name: Import the signing key\n"
SIGNSTEP = "      - name: Build and sign\n"
mut("private-key-holders", [("publish", SIGNSTEP + "        env:\n", SIGNSTEP + "        env:\n          GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}\n")],
    [("publish", "          GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}\n", "          GPG_PRIVATE_KEY: x\n")])
mut("passphrase-holders", [("publish", KEYSTEP + "        env:\n", KEYSTEP + "        env:\n          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n")],
    [("publish", "          MAVEN_GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}\n", "          NOTHING: x\n")],
    [("publish", PUBLISH_SEED, PUBLISH_SEED + "        env:\n          P: ${{ secrets.GPG_PASSPHRASE }}\n")])
mut("secret-value-outside-allowed-step", [("publish", "HAVE_GPG_KEY: ${{ secrets.GPG_PRIVATE_KEY != '' }}", "HAVE_GPG_KEY: ${{ secrets.GPG_PRIVATE_KEY }}")],
    [("publish", PUBLISH_SEED, PUBLISH_SEED + "        env:\n          P: ${{ secrets.GPG_PRIVATE_KEY }}\n")])
mut("step-holds-token-and-secret", [("publish", SIGNSTEP + "        env:\n", SIGNSTEP + "        env:\n          GH_TOKEN: ${{ github.token }}\n")])
mut("import-step-not-unique", [("publish", "gpg --batch --import", "gpg --import")])
mut("import-step-runs-more", [("publish", "          printf '%s' \"$GPG_PRIVATE_KEY\" |", "          curl -s example.invalid\n          printf '%s' \"$GPG_PRIVATE_KEY\" |")])
mut("deploy-in-publish", [("publish", "run: mvn -B -ntp -P release verify -DskipTests", "run: mvn -B -ntp -P release verify -DskipTests && mvn org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file")])

# --- upload and attest never run the capability's code ---------------------------------------------------------------------
REPO_LINE = "          repository: exeris-systems/.github\n"
REF_LINE = "          ref: ${{ github.job_workflow_sha }}\n"
for job in ("upload", "attest"):
    mut(f"caller-checkout:{job}", [(job, "    steps:\n", "    steps:\n" + CHECKOUT_CALLER)], [(job, REPO_LINE, "")],
        [(job, REPO_LINE, "          repository: ${{ github.repository }}\n")])
    mut(f"scripts-checkout-ref:{job}", [(job, REF_LINE, "          ref: ${{ inputs.version }}\n")], [(job, REF_LINE, "          ref: ${{ github.sha }}\n")],
        [(job, REF_LINE, "          ref: main\n")])
    mut(f"scripts-checkout-credentials:{job}", [(job, "persist-credentials: false", "persist-credentials: true")])
    mut(f"uses-allowlist:{job}", [(job, "    steps:\n", "    steps:\n      - uses: actions/cache@" + SHA + "\n        with:\n          path: x\n          key: y\n")],
        [(job, "    steps:\n", f"    steps:\n      - uses: actions/upload-artifact@{SHA}\n        with:\n          path: x\n")])
    mut(f"cache:{job}", [(job, "    steps:\n", "    steps:\n      - uses: actions/cache@" + SHA + "\n        with:\n          path: x\n          key: y\n")],
        [(job, "          persist-credentials: false\n", "          persist-credentials: false\n          cache: maven\n")])
    mut(f"download:{job}", [(job, "          path: ${{ runner.temp }}/gated-download", "          path: ${{ github.workspace }}/gated-download")],
        [(job, "          path: ${{ runner.temp }}/gated-download", "          path: ~/gated-download")],
        [(job, "          path: ${{ runner.temp }}/gated-download", "          path: ${{ runner.temp }}/gated-download\n          merge-multiple: true")],
        [(job, "          path: ${{ runner.temp }}/gated-download", "          path: ${{ runner.temp }}/gated-download\n          run-id: 1")],
        [(job, DOWNLOAD_BLOCK, "          name: gated\n")])
    mut(f"env-file:{job}", [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          echo \"PATH=/tmp\" >> \"$GITHUB_ENV\"\n")],
        [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          echo /tmp >> \"$GITHUB_PATH\"\n")],
        [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          echo x=y >> \"$GITHUB_OUTPUT\"\n")])
    for cond in ("if: ${{ always() }}", "if: failure()", "if: ${{ !cancelled() }}", "if: ${{ success() }}", "if: ${{ true }}"):
        mut(f"step-condition:{job}", [(job, COMPARE, COMPARE + f"        {cond}\n")])
    mut(f"continue-on-error:{job}", [(job, COMPARE, COMPARE + "        continue-on-error: true\n")],
        [(job, "      - name: Download the gated files\n", "      - name: Download the gated files\n        continue-on-error: true\n")])
    mut(f"step-environment:{job}", [(job, COMPARE, COMPARE + "        working-directory: /tmp\n")], [(job, COMPARE, COMPARE + "        shell: bash\n")])
    mut(f"run-interpolation:{job}", [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          echo ${{ needs.publish.outputs.manifest }}\n")],
        [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          echo ${{ inputs.version }}\n")],
        [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          echo ${{ runner.temp }}\n")])
    mut(f"input-reaches-job:{job}", [(job, DOWNLOAD_BLOCK, "          name: ${{ inputs.version }}\n")],
        [(job, "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n", "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n          V: ${{ inputs.generated-path }}\n")])
    mut(f"interpolation-inventory:{job}", [(job, DOWNLOAD_BLOCK, "          name: ${{ needs.publish.outputs.manifest }}\n")],
        [(job, "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n", "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n          V: ${{ github.sha }}\n")],
        [(job, "          MANIFEST: ${{ needs.publish.outputs.manifest }}\n", "          MANIFEST: ${{ needs.build.outputs.version }}\n")])
    mut(f"commands:{job}:compare", [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          curl example.invalid\n")],
        [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          mvn -v\n")])
    mut(f"download-dir-misused:{job}", [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          bash \"$RUNNER_TEMP/gated-download/run.sh\"\n")],
        [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          . \"$RUNNER_TEMP/gated-download/env\"\n")],
        [(job, "--dir \"$RUNNER_TEMP/gated-download\"", "--dir \"$RUNNER_TEMP/gated-download/\"")])
    mut(f"commands:{job}:unexpected-step", [(job, "    steps:\n", "    steps:\n" + STEP)])
mut("scripts-install-differs", [("upload", "chmod 500 \"$dest\"\n", "chmod 755 \"$dest\"\n")], [("attest", "mkdir -m 700", "mkdir -m 755")])
mut("commands:upload:settings", [("upload", "<<'XML'", "<<XML")], [("upload", "          cat > \"$RUNNER_TEMP/release-settings.xml\" <<'XML'", "          echo hi\n          cat > \"$RUNNER_TEMP/release-settings.xml\" <<'XML'")])
mut("commands:upload:upload", [("upload", "          cd \"$RUNNER_TEMP/gated-download\"\n", "          bash \"$RUNNER_TEMP/gated-download/run.sh\"\n          cd \"$RUNNER_TEMP/gated-download\"\n")],
    [("upload", "          cd \"$RUNNER_TEMP/gated-download\"\n", "          cd \"$RUNNER_TEMP/gated-download\"\n          source ./env\n")],
    [("upload", "          cd \"$RUNNER_TEMP/gated-download\"\n", "          cd \"$RUNNER_TEMP/gated-download\"\n          ./gradlew build\n")],
    [("upload", "          set -euo pipefail\n          cd ", "          cd ")])
mut("download-dir-misused:upload", [("upload", "          cd \"$RUNNER_TEMP/gated-download\"\n", "          cd \"$RUNNER_TEMP/gated-download\"\n          sh \"$RUNNER_TEMP/gated-download/x.sh\"\n")])
mut("upload-mvn-flags", [("upload", "mvn -B -ntp org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file", "mvn -B -ntp -f \"$RUNNER_TEMP/gated-download/pom.xml\" org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file")],
    [("upload", "mvn -B -ntp org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file", "mvn -B -ntp -s x org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file")],
    [("upload", "mvn -B -ntp org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file", "mvn -B -ntp -gs x org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file")])
mut("upload-with-profile", [("upload", "mvn -B -ntp org.apache.maven.plugins", "mvn -B -ntp -P release org.apache.maven.plugins")])
mut("upload-mvn-properties", [("upload", "-DrepositoryId=github", "-DrepositoryId=github -Dmaven.ext.class.path=x")],
    [("upload", "-Dfile=\"$base.jar\"", "-Dfile=\"/tmp/$base.jar\"")], [("upload", "-DrepositoryId=github", "-DrepositoryId=github -DgeneratePom=false")])
mut("upload-settings", [("upload", "--settings \"$RUNNER_TEMP/release-settings.xml\"", "--settings \"$RUNNER_TEMP/gated-download/settings.xml\"")],
    [("upload", "--settings \"$RUNNER_TEMP/release-settings.xml\"", "-Dx=y")])
mut("upload-directory", [("upload", "          cd \"$RUNNER_TEMP/gated-download\"\n", "")], [("upload", "cd \"$RUNNER_TEMP/gated-download\"", "cd \"$RUNNER_TEMP\"")],
    [("upload", "              -Dtypes=\"jar.asc,pom.asc,jar.asc,jar.asc\"\n          done\n", "              -Dtypes=\"jar.asc,pom.asc,jar.asc,jar.asc\"\n          done\n          cd \"$RUNNER_TEMP/gated-download\"\n")])
mut("upload-url", [("upload", "-Durl=\"https://maven.pkg.github.com/${GITHUB_REPOSITORY}\"", "-Durl=\"https://example.invalid/${GITHUB_REPOSITORY}\"")],
    [("upload", "-DrepositoryId=github", "-DrepositoryId=github -DaltDeploymentRepository=x::default::https://example.invalid")])
mut("upload-server-id", [("upload", "-DrepositoryId=github", "-DrepositoryId=other")], [("upload", "<id>github</id>", "<id>other</id>")])
mut("upload-goal", [("upload", "maven-deploy-plugin:3.1.4:deploy-file", "maven-deploy-plugin:3.1.4:deploy")])
mut("settings-placeholders", [("upload", "<<'XML'", "<<XML")], [("upload", "<password>${env.GITHUB_TOKEN}</password>", "<password>abc</password>")],
    [("upload", SETTINGS, SETTINGS.replace("        run: |\n", "        env:\n          X: y\n        run: |\n"))])
mut("upload-step-not-unique", [("upload", UPLOAD, "      - name: Send the gated files\n")])
mut("input-reaches-job:upload", [("upload", "          java-version: ${{ inputs.java-version }}\n", "          java-version: ${{ inputs.version }}\n")])

# --- the order of the steps ------------------------------------------------------------------------------------------------
MOVES: dict[str, list[tuple]] = {}


def move_case(ident, job, name, before):
    MOVES.setdefault(ident, []).append((job, name, before))


move_case("upload-order:jdk-after-download", "upload", "Set up JDK", "Compare the downloaded files")
move_case("upload-order:download-after-compare", "upload", "Download the gated files", "Write the Maven settings")
move_case("upload-order:compare-after-settings", "upload", "Compare the downloaded files", "Upload the gated files")
move_case("upload-order:settings-after-upload", "upload", "Upload the gated files", "Write the Maven settings")
move_case("upload-order:compare-after-upload", "upload", "Upload the gated files", "Compare the downloaded files")
move_case("upload-order:digest-after-jdk", "upload", "Install the gate scripts", "Download the gated files")
move_case("upload-order:fetch-after-digest", "upload", "Install the gate scripts", "actions/checkout@")
move_case("upload-order:upload-not-last", "upload", "Upload the gated files", "Write the Maven settings")
move_case("publish-order:sign-before-import", "publish", "Import the signing key", "Remove the signing key")
move_case("removal-before-signing", "publish", "Remove the signing key", "Build and sign")
move_case("removal-not-directly-after-signing", "publish", "Remove the signing key", "Keep the gated files")
move_case("removal-after-gate", "publish", "Remove the signing key", "Keep the gated files")
move_case("publish-order:artifact-before-gate", "publish", "Keep the gated files", "Gate what was built")
move_case("upload-before-gate:build", "build", "Keep what was built", "Gate what was built")
move_case("upload-before-gate:publish", "publish", "Keep the gated files", "Gate what was built")
move_case("attest-before-manifest-check", "attest", "Compare the downloaded files", "Download the gated files")
move_case("attest-before-manifest-check", "attest", "Attest build provenance", "Compare the downloaded files")
mut("mvn-before-manifest-check:upload", [("upload", "      - name: Download the gated files\n", "      - name: Warm up\n        run: mvn -B -ntp -v\n\n      - name: Download the gated files\n")])
mut("upload-steps-unexpected", [("upload", "      - name: Download the gated files\n", STEP + "\n      - name: Download the gated files\n")])
mut("upload-step-not-unique:download", [("upload", "uses: actions/download-artifact@", "uses: actions/upload-artifact@")])
mut("upload-step-not-unique:jdk", [("upload", "uses: actions/setup-java@", "uses: actions/checkout@")])
mut("upload-step-not-unique:compare", [("upload", "staged_manifest.py\" verify", "staged_manifest_x.py\" verify")])
mut("upload-step-not-unique:settings", [("upload", "release-settings.xml\" <<'XML'", "release.xml\" <<'XML'")])
mut("upload-step-not-unique:fetch", [("upload", "uses: actions/checkout@", "uses: actions/download-artifact@")])
mut("upload-step-not-unique:digest", [("upload", "        id: scripts\n", "        id: scriptz\n")])
mut("upload-step-not-unique:upload", [("upload", ":deploy-file", ":deploy-fil")])
mut("digest-not-reverified:upload", [("upload", GATE_DIGEST, '= "$SCRIPTS_DIGEST_X" ]')])
mut("digest-not-reverified:attest", [("attest", GATE_DIGEST, '= "$SCRIPTS_DIGEST_X" ]')])
mut("digest-not-passed:upload", [("upload", "SCRIPTS_DIGEST: ${{ steps.scripts.outputs.digest }}", "SCRIPTS_DIGEST: abc")])
mut("digest-not-passed:attest", [("attest", "SCRIPTS_DIGEST: ${{ steps.scripts.outputs.digest }}", "SCRIPTS_DIGEST: abc")])
mut("digest-not-reverified:publish", [("publish", "!= \"$SCRIPTS_DIGEST\" ]", "!= \"$SCRIPTS_DIGEST_X\" ]")])
mut("digest-not-reverified:build", [("build", GATE_DIGEST, '= "$SCRIPTS_DIGEST_X" ]', 1)])
mut("digest-not-passed:publish", [("publish", "SCRIPTS_DIGEST: ${{ steps.scripts.outputs.digest }}", "SCRIPTS_DIGEST: abc")])
mut("manifest-check:upload", [("upload", "--manifest-env MANIFEST", "--manifest-env MANIFEST_X")])
mut("publish-step-not-unique:import", [("publish", "gpg --batch --import", "gpg --import")])
mut("publish-step-not-unique:sign", [("publish", "run: mvn -B -ntp -P release verify -DskipTests", "run: mvn -B -ntp -P release verify")])
mut("publish-step-not-unique:remove", [("publish", "remove_signing_key.py\" --secret-home", "remove_signing_keys.py\" --secret-home")])
mut("publish-step-not-unique:gate", [("publish", "check_release_readiness.py\" --target-dir", "check_release_readiness_x.py\" --target-dir")])
mut("publish-step-not-unique:artifact", [("publish", "uses: actions/upload-artifact@", "uses: actions/download-artifact@")])
mut("removal-not-always", [("publish", "if: ${{ always() }}", "if: ${{ success() }}")], [("publish", "        if: ${{ always() }}\n", "")])
mut("gate-manifest-step", [("publish", "        id: gate\n", "        id: gated\n")], [("publish", "create --dir", "create --name x --dir")],
    [("publish", "\"$RUNNER_TEMP/gated-files\" \\\n            --output \"$GITHUB_OUTPUT\"", "\"$RUNNER_TEMP/gated-files\" \\\n            --output \"$RUNNER_TEMP/out\"")],
    [("publish", "          /usr/bin/python3 -I -B \"$S/staged_manifest.py\" create --dir \"$RUNNER_TEMP/gated-files\" \\\n            --output \"$GITHUB_OUTPUT\"\n", "")])
mut("publish-artifact-path", [("publish", "          path: ${{ runner.temp }}/gated-files\n          if-no-files-found: error", "          path: target\n          if-no-files-found: error")],
    [("publish", "          path: ${{ runner.temp }}/gated-files\n          if-no-files-found: error", "          path: ${{ runner.temp }}\n          if-no-files-found: error")])
mut("publish-artifact-empty-allowed", [("publish", "          path: ${{ runner.temp }}/gated-files\n          if-no-files-found: error", "          path: ${{ runner.temp }}/gated-files\n          if-no-files-found: warn")])
mut("publish-artifact-not-on-success", [("publish", "      - name: Keep the gated files as the run artifact\n", "      - name: Keep the gated files as the run artifact\n        if: ${{ always() }}\n")])
mut("gated-files-written-elsewhere:publish", [("publish", PUBLISH_SEED + "        run: mvn", PUBLISH_SEED + "        run: mkdir \"$RUNNER_TEMP/gated-files\" && mvn")])
mut("gated-files-written-elsewhere:upload", [("upload", "          cd \"$RUNNER_TEMP/gated-download\"\n", "          cp x \"$RUNNER_TEMP/gated-files\"\n          cd \"$RUNNER_TEMP/gated-download\"\n")])
mut("gated-files-written-elsewhere:attest", [("attest", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          ls \"$RUNNER_TEMP/gated-files\"\n")])

# --- how the manifest and the artifact name travel ------------------------------------------------------------------------
ARTIFACT_NAME = "gated-${{ needs.build.outputs.version }}-${{ github.run_attempt }}-${{ steps.gate.outputs.manifest-id }}"
mut("manifest-output", [("publish", "manifest: ${{ steps.gate.outputs.manifest }}", "manifest: ${{ steps.gate.outputs.manifest-id }}")],
    [("publish", "manifest: ${{ steps.gate.outputs.manifest }}", "manifest: ${{ steps.rel.outputs.manifest }}")],
    [("publish", "    outputs:\n      manifest:", "    outputs:\n      extra: ${{ steps.gate.outputs.manifest }}\n      manifest:")])
mut("artifact-output", [("publish", "      artifact: " + ARTIFACT_NAME, "      artifact: gated-${{ needs.build.outputs.version }}")])
mut("artifact-name-mismatch", [("publish", "          name: " + ARTIFACT_NAME, "          name: gated-${{ needs.build.outputs.version }}-${{ github.run_attempt }}")])
mut("artifact-name-parts", [("publish", ARTIFACT_NAME, "gated-${{ needs.build.outputs.version }}-${{ steps.gate.outputs.manifest-id }}", 0),
                             ("publish", ARTIFACT_NAME, "gated-${{ needs.build.outputs.version }}-${{ steps.gate.outputs.manifest-id }}", 0)],
    [("publish", ARTIFACT_NAME, "gated-${{ needs.build.outputs.version }}-${{ github.run_attempt }}", 0),
     ("publish", ARTIFACT_NAME, "gated-${{ needs.build.outputs.version }}-${{ github.run_attempt }}", 0)])
mut("build-artifact-name", [("build", "name: build-gate-${{ steps.rel.outputs.version }}-${{ github.run_attempt }}", "name: gated-${{ steps.rel.outputs.version }}-${{ github.run_attempt }}")])
for job in ("upload", "attest"):
    mut(f"manifest-env:{job}", [(job, "MANIFEST: ${{ needs.publish.outputs.manifest }}", "MANIFEST: abc")],
        [(job, "MANIFEST: ${{ needs.publish.outputs.manifest }}", "MANIFEST: ${{ needs.build.outputs.version }}")])
    mut(f"manifest-expression-elsewhere:{job}", [(job, DOWNLOAD_BLOCK, "          name: ${{ needs.publish.outputs.manifest }}\n")],
        [(job, "SCRIPTS_DIGEST: ${{ steps.scripts.outputs.digest }}", "SCRIPTS_DIGEST: ${{ steps.scripts.outputs.digest }}\n          M2: ${{ needs.publish.outputs.manifest }}")])
    mut(f"manifest-read-from-file:{job}", [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          cat \"$RUNNER_TEMP/gated-download/manifest.txt\"\n")],
        [(job, "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          sha256sum -c MANIFEST.sha256\n")])
mut("build-artifact-name", [("build", "name: build-gate-", "name: gated-")])

# --- attest ----------------------------------------------------------------------------------------------------------------
mut("attest-runs-code", [("attest", "      - name: Attest build provenance (SLSA)", STEP + "\n      - name: Attest build provenance (SLSA)")],
    [("attest", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n", "          S=\"$RUNNER_TEMP/caps-release-scripts\"\n          mvn -v\n")])
mut("attest-steps-unexpected", [("attest", "uses: actions/download-artifact@", "uses: actions/upload-artifact@")],
    [("attest", "      - name: Attest build provenance (SLSA)", STEP + "\n      - name: Attest build provenance (SLSA)")])
mut("attest-subjects", [("attest", "            ${{ runner.temp }}/gated-download/*.asc\n", "")],
    [("attest", "            ${{ runner.temp }}/gated-download/*.asc\n", "            ${{ runner.temp }}/gated-download/*.asc\n            ${{ runner.temp }}/gated-download/*.txt\n")],
    [("attest", "gated-download/*.jar", "gated-files/*.jar")], [("attest", "gated-download/*.pom", "gated-download/**")],
    [("attest", "            ${{ runner.temp }}/gated-download/*.asc\n", "            ${{ runner.temp }}/gated-download/*.asc\n            ${{ github.workspace }}/target/*.jar\n")])

# --- checkouts, digests, the gate and the build ---------------------------------------------------------------------------
for job in ("build", "publish"):
    mut(f"scripts-checkout-missing:{job}", [(job, REPO_LINE, "          repository: exeris-systems/other\n")])
    mut(f"scripts-checkout-ref:{job}", [(job, REF_LINE, "          ref: ${{ github.sha }}\n")], [(job, REF_LINE, "          ref: ${{ inputs.version }}\n")])
    mut(f"scripts-checkout-credentials:{job}", [(job, "          persist-credentials: false\n", "          persist-credentials: true\n")])
    mut(f"caller-checkout:{job}", [(job, "    steps:\n", "    steps:\n" + CHECKOUT_CALLER)])
    mut(f"gate-step-not-unique:{job}", [(job, "check_release_readiness.py\" --target-dir", "check_release_readiness_x.py\" --target-dir")])
    mut(f"gate-not-staging:{job}", [(job, "--stage \"$RUNNER_TEMP/gated-files\"", "--stage \"$RUNNER_TEMP/other\"")])
    mut(f"upload-missing:{job}", [(job, "uses: actions/upload-artifact@", "uses: actions/download-artifact@")])
    mut(f"upload-not-on-success:{job}", [(job, "        with:\n          name: " + ("build-gate" if job == "build" else "gated"), "        if: ${{ always() }}\n        with:\n          name: " + ("build-gate" if job == "build" else "gated"))])
    mut(f"upload-from-target:{job}", [(job, "          path: ${{ runner.temp }}/gated-files\n", "          path: target\n")])
    mut(f"upload-path-not-gated:{job}", [(job, "          path: ${{ runner.temp }}/gated-files\n", "          path: ${{ runner.temp }}\n")])
    mut(f"upload-empty-allowed:{job}", [(job, "if-no-files-found: error", "if-no-files-found: warn")], [(job, "          if-no-files-found: error\n", "")])
    mut(f"continue-on-error:{job}", [(job, "      - name: Seed capability metadata (first pass, codegen skipped)\n", "      - name: Seed capability metadata (first pass, codegen skipped)\n        continue-on-error: true\n")])
    mut(f"step-condition:{job}", [(job, "      - name: Seed capability metadata (first pass, codegen skipped)\n", "      - name: Seed capability metadata (first pass, codegen skipped)\n        if: ${{ always() }}\n")])
mut("uses-not-pinned", [(None, f"actions/checkout@{SHA}", "actions/checkout@v4"), ])
mut("uses-not-pinned", [("upload", "actions/setup-java@b843ebf9b913146b38da2eaa7aeddf76074ae1ad", "actions/setup-java@b843ebf")])


# --- moving steps -------------------------------------------------------------------------------------------------------
def blocks(text: str, jname: str):
    """(start, end, name) of every step of the job JNAME, cut at the step markers of its indentation."""
    a, b = w.region(text, jname)
    starts = [m.start() for m in re.finditer(r"^      - ", text[a:b], re.M)]
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else b - a
        name = re.match(r"      - (?:name|uses): (.*)", text[a + s:a + e]).group(1)
        out.append((a + s, a + e, name))
    return out


def move(text: str, jname: str, name: str, before: str) -> str:
    """The workflow with the step whose name starts with NAME moved to stand directly before the step starting with BEFORE."""
    a, b, _ = next(x for x in blocks(text, jname) if x[2].startswith(name))
    step = text[a:b]
    rest = text[:a] + text[b:]
    at = next(x for x in blocks(rest, jname) if x[2].startswith(before))[0]
    return rest[:at] + step.rstrip("\n") + "\n\n" + rest[at:]


# --- the real workflow ---------------------------------------------------------------------------------------------------
class Real(h.Case):
    def jobs(self):
        return w.parse(read())["jobs"]

    def test_the_workflow_breaks_no_invariant(self):
        self.assertEqual(w.violations(read()), set())

    def test_the_parse_sees_what_the_invariants_assume(self):
        jobs = self.jobs()
        self.assertEqual(set(jobs), {"build", "publish", "upload", "attest"})
        self.assertEqual([s["name"] or s["uses"][:16] for s in jobs["upload"]["steps"]],
                         ["actions/checkout", w.INSTALL_STEP, "Set up JDK ${{ inputs.java-version }}", "Download the gated files",
                          "Compare the downloaded files with the manifest", "Write the Maven settings", "Upload the gated files"])
        self.assertEqual(len(jobs["attest"]["steps"]), 5)
        names = [s["name"] for s in jobs["publish"]["steps"]]
        self.assertEqual(names.index("Remove the signing key"), names.index("Build and sign") + 1)
        self.assertEqual(names[-2:], ["Gate what was built and make the manifest", "Keep the gated files as the run artifact"])

    def test_the_permissions_of_each_job_are_exactly_these(self):
        jobs = self.jobs()
        self.assertEqual(w.permissions(jobs["build"]), {"contents": "read"})
        self.assertEqual(w.permissions(jobs["publish"]), {"contents": "read"})
        self.assertEqual(w.permissions(jobs["upload"]), {"contents": "read", "packages": "write"})
        self.assertEqual(w.permissions(jobs["attest"]), {"contents": "read", "id-token": "write", "attestations": "write"})
        self.assertEqual([n for n, j in jobs.items() if "packages: write" in "\n".join(j["header"])], ["upload"])

    def test_the_job_token_is_in_one_step_of_upload_and_the_read_only_resolve_step_of_build_and_nowhere_else(self):
        jobs = self.jobs()
        held = {n: [w.short(s) for s in j["steps"] if w.holds_token(s)] for n, j in jobs.items()}
        self.assertEqual(held, {"build": [w.RESOLVE_STEP], "publish": [], "upload": ["Upload the gated files"], "attest": []})
        build = next(s for s in jobs["build"]["steps"] if w.holds_token(s))
        self.assertEqual(w.permissions(jobs["build"]), {"contents": "read"}, "the build's token can only read")
        self.assertEqual(build["env"]["GH_TOKEN"], "${{ github.token }}")
        upload = next(s for s in jobs["upload"]["steps"] if w.holds_token(s))
        self.assertEqual(upload["env"], {"GITHUB_TOKEN": "${{ github.token }}"})
        self.assertIs(upload, jobs["upload"]["steps"][-1], "no step of upload but the last holds the token")

    def test_the_signing_secrets_each_step_holds(self):
        steps = self.jobs()["publish"]["steps"]
        held = {s["name"]: sorted({n for _, n, boolean in w.secret_refs(s) if not boolean}) for s in steps}
        self.assertEqual({k: v for k, v in held.items() if v}, {"Import the signing key": ["GPG_PRIVATE_KEY"], "Build and sign": ["GPG_PASSPHRASE"]})
        for name in ("build", "upload", "attest"):
            self.assertNotRegex("\n".join(self.jobs()[name]["lines"]), r"\bsecrets\b", name)

    def test_no_step_holds_a_signing_secret_and_the_token(self):
        for name, j in self.jobs().items():
            for s in j["steps"]:
                self.assertFalse(w.holds_token(s) and (w.holds_passphrase(s) or w.holds_private_key(s)), f"{name}: {w.short(s)}")

    def test_every_uses_is_a_40_hex_pin(self):
        uses = re.findall(r"^\s*(?:- )?uses:\s*(\S+)", "\n".join(w.strip_comments(read())), re.M)
        self.assertGreaterEqual(len(uses), 14)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

    def test_upload_checks_out_only_this_repositorys_scripts_at_the_workflows_commit(self):
        for name in ("upload", "attest"):
            co = [s for s in self.jobs()[name]["steps"] if s["uses"].startswith("actions/checkout@")]
            self.assertEqual(len(co), 1, name)
            self.assertEqual(co[0]["with"], {"repository": "exeris-systems/.github", "ref": "${{ github.job_workflow_sha }}",
                                              "path": ".caps-release-src", "persist-credentials": "false"})

    def test_upload_restores_no_cache_and_sets_the_jdk_up_without_one(self):
        steps = self.jobs()["upload"]["steps"]
        jdk = next(s for s in steps if s["uses"].startswith("actions/setup-java@"))
        self.assertEqual(set(jdk["with"]), {"distribution", "java-version"})
        self.assertNotRegex("\n".join(s["raw"] for s in steps), r"actions/cache|cache:")
        self.assertIn("cache: maven", "\n".join(s["raw"] for s in self.jobs()["build"]["steps"]), "the rehearsal keeps its cache")

    def test_upload_downloads_into_the_runner_temp_directory_only(self):
        for name in ("upload", "attest"):
            dl = next(s for s in self.jobs()[name]["steps"] if s["uses"].startswith("actions/download-artifact@"))
            self.assertEqual(dl["with"], {"name": "${{ needs.publish.outputs.artifact }}", "path": "${{ runner.temp }}/gated-download"})

    def test_the_directory_that_was_downloaded_is_named_only_as_data(self):
        """It is an argument of the manifest check, the directory the deploy command changes into, and the download path."""
        mentions = []
        for name in ("upload", "attest"):
            for s in self.jobs()[name]["steps"]:
                for line in (s["run"] + "\n" + "\n".join(s["with"].values())).splitlines():
                    if "gated-download" in line:
                        mentions.append((name, w.short(s), line.strip()))
        self.assertEqual(sorted(set(mentions)), sorted([
            ("upload", "Download the gated files", "${{ runner.temp }}/gated-download"),
            ("upload", "Compare the downloaded files with the manifest", w.VERIFY_CALL),
            ("upload", "Upload the gated files", 'cd "$RUNNER_TEMP/gated-download"'),
            ("attest", "Download the gated files", "${{ runner.temp }}/gated-download"),
            ("attest", "Compare the downloaded files with the manifest", w.VERIFY_CALL),
            ("attest", "Attest build provenance (SLSA)", "${{ runner.temp }}/gated-download/*.jar"),
            ("attest", "Attest build provenance (SLSA)", "${{ runner.temp }}/gated-download/*.pom"),
            ("attest", "Attest build provenance (SLSA)", "${{ runner.temp }}/gated-download/*.asc")]))

    def test_the_order_of_the_steps_of_upload(self):
        names = [w.kind(s) for s in self.jobs()["upload"]["steps"]]
        self.assertEqual(names, ["checkout", w.INSTALL_STEP, "Set up JDK", "Download the gated files", w.COMPARE_STEP, "Write the Maven settings",
                                 "Upload the gated files"])
        first_token = [i for i, s in enumerate(self.jobs()["upload"]["steps"]) if w.holds_token(s)]
        self.assertEqual(first_token, [len(names) - 1], "the token is absent from every step before the last")

    def test_the_digest_of_the_scripts_is_compared_before_the_manifest_check_runs(self):
        run = next(s for s in self.jobs()["upload"]["steps"] if s["name"] == w.COMPARE_STEP)["run"]
        self.assertLess(w.DIGEST_COMPARE.search(run).start(), run.index("staged_manifest.py"))

    def test_the_order_of_the_steps_of_publish(self):
        steps = self.jobs()["publish"]["steps"]
        idx = {k: next(i for i, s in enumerate(steps) if pred(s)) for k, pred in {
            "import": lambda s: "gpg --batch --import" in s["run"], "sign": lambda s: s["name"] == "Build and sign",
            "remove": lambda s: "remove_signing_key.py" in s["run"], "gate": lambda s: s["id"] == "gate",
            "artifact": lambda s: s["uses"].startswith("actions/upload-artifact@")}.items()}
        self.assertEqual(sorted(idx, key=idx.get), ["import", "sign", "remove", "gate", "artifact"])
        self.assertEqual(steps[idx["remove"]]["if"], "${{ always() }}")
        art = steps[idx["artifact"]]
        self.assertEqual(w.block_lines(art, "path"), [w.GATED])
        self.assertEqual(art["with"]["if-no-files-found"], "error")
        self.assertEqual(art["if"], "")

    def test_the_manifest_travels_only_as_a_job_output(self):
        jobs = self.jobs()
        self.assertEqual(w.job_outputs(jobs["publish"]), {"manifest": "${{ steps.gate.outputs.manifest }}", "artifact": w.ARTIFACT})
        gate = next(s for s in jobs["publish"]["steps"] if s["id"] == "gate")
        self.assertIn('staged_manifest.py" create --dir "$RUNNER_TEMP/gated-files"', gate["run"])
        for name in ("upload", "attest"):
            steps = jobs[name]["steps"]
            self.assertEqual(sum(s["raw"].count("outputs.manifest") for s in steps), 1)
            cmp_ = next(s for s in steps if "staged_manifest.py" in s["run"])
            self.assertEqual(cmp_["env"]["MANIFEST"], "${{ needs.publish.outputs.manifest }}")
            self.assertIn("--manifest-env MANIFEST", cmp_["run"])
            self.assertFalse(any(re.search(r"manifest", s["run"].replace(w.VERIFY_CALL, ""), re.I) for s in steps), "no manifest is read from a file")

    def test_the_artifact_is_named_by_the_publish_job_once_for_everyone(self):
        jobs = self.jobs()
        name = w.job_outputs(jobs["publish"])["artifact"]
        art = next(s for s in jobs["publish"]["steps"] if s["uses"].startswith("actions/upload-artifact@"))
        self.assertEqual(art["with"]["name"], name)
        self.assertIn("github.run_attempt", name)
        self.assertIn("steps.gate.outputs.manifest-id", name)
        build = next(s for s in jobs["build"]["steps"] if s["uses"].startswith("actions/upload-artifact@"))
        self.assertNotEqual(build["with"]["name"], name)
        self.assertTrue(build["with"]["name"].startswith("build-gate-"))
        for j in ("upload", "attest"):
            dl = next(s for s in jobs[j]["steps"] if s["uses"].startswith("actions/download-artifact@"))
            self.assertEqual(dl["with"]["name"], "${{ needs.publish.outputs.artifact }}")

    def test_attest_follows_a_successful_upload_and_takes_the_downloaded_signatures_too(self):
        jobs = self.jobs()
        self.assertEqual(w.job_value(jobs["attest"], "needs"), "[publish, upload]")
        self.assertEqual(w.job_value(jobs["attest"], "if"), "${{ needs.upload.result == 'success' }}")
        steps = jobs["attest"]["steps"]
        at = next(i for i, s in enumerate(steps) if s["uses"].startswith("actions/attest-build-provenance@"))
        cmp_ = next(i for i, s in enumerate(steps) if "staged_manifest.py" in s["run"])
        self.assertLess(cmp_, at)
        self.assertEqual(w.block_lines(steps[at], "subject-path"), [w.DOWNLOAD + "/*.jar", w.DOWNLOAD + "/*.pom", w.DOWNLOAD + "/*.asc"])
        self.assertFalse(any(re.search(r"\bmvn\b", s["run"]) for s in steps), "no project code")

    def test_the_inputs_default_to_no_upload(self):
        text = "\n".join(w.strip_comments(read()))
        self.assertRegex(text, r"upload:\s*\{[^}]*type:\s*boolean,\s*default:\s*false")
        self.assertRegex(text, r'target:\s*\{[^}]*default:\s*"none"')

    def test_the_file_names_no_other_target_and_no_bundle(self):
        text = read().lower()
        for word in ("central", "central_token", "expect_bundle", "--expect-bundle", "sonatype", "ossrh", "maven central"):
            self.assertNotIn(word, text)

    def test_the_block_reader_reads_blocks_and_one_line_values(self):
        step = w.step(["      - uses: x/y@" + "0" * 40, "        with:", "          path: |", "            a/b", "            c", "          name: n"])
        self.assertEqual(w.block_lines(step, "path"), ["a/b", "c"])
        self.assertEqual(w.block_lines(step, "name"), ["n"])
        self.assertEqual(w.block_lines(step, "absent"), [])
        self.assertEqual(step["with"], {"path": "a/b\nc", "name": "n"})

    def test_the_parse_notices_a_secret_moved_into_a_comment_only_when_it_is_shell(self):
        text = read()
        yaml_comment = mutate_in(text, "upload", SETTINGS, "      # ${{ secrets.X }}\n" + SETTINGS)
        self.assertEqual(w.violations(yaml_comment), set())                 # a YAML comment is not evaluated
        shell_comment = mutate_in(text, "build", "          home=\"$RUNNER_TEMP/dry-run-gnupg\"\n",
                                  "          # ${{ secrets.X }}\n          home=\"$RUNNER_TEMP/dry-run-gnupg\"\n")
        self.assertIn("secrets-outside-publish:build", w.violations(shell_comment))   # evaluated by GitHub even there


# --- the mutations -------------------------------------------------------------------------------------------------------
def covered_prefixes():
    return {k.split(":")[0] for k in list(MUTATIONS) + list(MOVES)}


class Mutations(h.Case):
    def test_every_invariant_is_killed_by_its_mutations(self):
        text = read()
        self.assertEqual(w.violations(text), set())
        survivors = []
        for ident, variants in sorted(MUTATIONS.items()):
            for edits in variants:
                broken = apply(text, edits)
                self.assertNotEqual(broken, text, ident)
                got = w.violations(broken)
                if ident not in got:
                    survivors.append((ident, [e[1][:60] for e in edits], sorted(got)))
        self.assertEqual(survivors, [], "mutations the invariants did not notice")

    def test_a_step_moved_out_of_order_is_caught(self):
        text = read()
        misses = []
        for ident, cases in sorted(MOVES.items()):
            for jname, name, before in cases:
                moved = move(text, jname, name, before)
                self.assertNotEqual(moved, text)
                if ident not in w.violations(moved):
                    misses.append((ident, name, before, sorted(w.violations(moved))))
        self.assertEqual(misses, [])

    def test_a_move_that_breaks_nothing_is_not_reported(self):
        text = read()
        moved = move(text, "build", "Refuse a ref without the release profile", "Set the release version")
        self.assertNotEqual(moved, text)
        self.assertEqual(w.violations(moved), set())

    def test_every_invariant_the_checker_can_report_has_a_mutation(self):
        source = inspect.getsource(w)
        ids = set(re.findall(r'out\.add\(f?"([\w:{}.()\-]+)"\)', source))
        exact = {i for i in ids if "{" not in i}
        templated = {re.split(r"[:{]", i)[0] for i in ids if "{" in i}
        known = set(MUTATIONS) | set(MOVES)
        self.assertEqual(sorted(exact - known), [], "an identifier without a mutation")
        self.assertEqual(sorted(templated - covered_prefixes()), [], "a templated identifier without a mutation")

    def test_every_job_parametrised_identifier_is_mutated_in_each_job_it_names(self):
        wanted = {"permissions": ("build", "publish", "upload", "attest"), "token-holders": ("build", "publish", "upload", "attest"),
                  "secrets-outside-publish": ("build", "upload", "attest"), "caller-checkout": ("build", "publish", "upload", "attest"),
                  "scripts-checkout-ref": ("build", "publish", "upload", "attest"), "step-condition": ("build", "publish", "upload", "attest"),
                  "continue-on-error": ("build", "publish", "upload", "attest"), "job-missing": ("build", "publish", "upload", "attest"),
                  "digest-not-reverified": ("build", "publish", "upload", "attest")}
        known = set(MUTATIONS) | set(MOVES)
        for prefix, jobs in wanted.items():
            for job_name in jobs:
                self.assertIn(f"{prefix}:{job_name}", known)


# --- what a capability controls, and what reaches the job that holds the upload token ------------------------------------------
class Adversarial(h.Case):
    """Questions about the `upload` and `attest` jobs, answered on the text of the real workflow."""

    def jobs(self):
        return w.parse(read())["jobs"]

    def test_everything_interpolated_into_upload_and_attest_is_listed_and_none_of_it_is_shell_text(self):
        """The inventory of `${{ }}` per step and place. Nothing in a `run:` block; the inputs only select the JDK."""
        found = {}
        for name in ("upload", "attest"):
            for s in self.jobs()[name]["steps"]:
                for (kind, place), exprs in w.interpolations(s).items():
                    found.setdefault(name, {})[(kind, place)] = sorted(set(exprs))
        self.assertEqual({n: {k: v[0] for k, v in d.items()} for n, d in found.items()}, w.INTERPOLATIONS)
        for name, d in found.items():
            self.assertFalse([k for k in d if k[1] == "run"], f"{name}: an expression inside a run block")
        inputs = {(n, k): v for n, d in found.items() for k, v in d.items() if any(e.startswith("inputs.") for e in v)}
        self.assertEqual(sorted(inputs), [("upload", ("Set up JDK", "name")), ("upload", ("Set up JDK", "with:distribution")),
                                          ("upload", ("Set up JDK", "with:java-version"))])

    def test_the_inputs_that_reach_upload_are_the_jdk_selection_and_nothing_else(self):
        """`version`, `generated-path`, `upload` and `target` reach no step of upload or attest; the JDK inputs reach `setup-java` as `with:` values.

        The JDK a caller selects is what `setup-java` downloads and puts on the PATH of the job that holds the token. A caller
        is the capability's own workflow and is trusted to the extent it can choose a JDK; `resolve_release.py` validates neither
        input (see `test_the_jdk_inputs_are_not_validated_by_the_resolver`).
        """
        for name in ("upload", "attest"):
            blob = "\n".join(s["raw"] for s in self.jobs()[name]["steps"])
            for forbidden in ("inputs.version", "inputs.generated-path", "inputs.upload", "inputs.target"):
                self.assertNotIn(forbidden, blob, f"{name} reads {forbidden}")
        self.assertNotIn("inputs.", "\n".join(s["raw"] for s in self.jobs()["attest"]["steps"]))

    def test_the_jdk_inputs_are_not_validated_by_the_resolver(self):
        """A recorded fact: the resolve step is not given the JDK inputs, so nothing constrains them before `setup-java` receives them."""
        resolve = next(s for s in self.jobs()["build"]["steps"] if "resolve_release.py" in s["run"])
        self.assertNotIn("java", "\n".join([resolve["run"], *resolve["env"].values()]))
        with open(h.script_path("resolve_release"), encoding="utf-8") as fh:
            self.assertNotRegex(fh.read().lower(), r"java[-_](version|distribution)|distribution")

    def test_the_artifact_name_is_made_of_a_validated_version_a_counter_and_twelve_hex_digits(self):
        """Nothing a capability writes reaches the name: the version is the resolver's (MAJOR.MINOR.PATCH), the attempt is a number."""
        name = w.job_outputs(self.jobs()["publish"])["artifact"]
        self.assertEqual(re.findall(r"\$\{\{ (.*?) \}\}", name), ["needs.build.outputs.version", "github.run_attempt", "steps.gate.outputs.manifest-id"])
        self.assertEqual(w.job_outputs(self.jobs()["build"])["version"], "${{ steps.rel.outputs.version }}")
        for hostile in ("1.0.0\n", "1.0.0 ${{ secrets.X }}", "1.0.0/../x", "1.0.0*", "1.0", "v1.0.0", "1.0.0-x"):
            res = h.run_main("resolve_release", ["--target", "none", "--upload", "false", "--version", hostile, "--generated-path", "g",
                                                 "--ref-type", "branch"])
            self.assertEqual(res.rc, 1, f"{hostile!r}: {res}")

    def test_the_manifest_id_in_the_name_is_twelve_hex_digits_whatever_the_file_names_are(self):
        d = self.path("staged")
        make_coordinate(d)
        for name in ("a=b.jar", "::error::x.jar", "$(id).jar", "a%0Ab.jar"):
            put(d, name)
        out = self.path("github-output")
        self.assertEqual(h.run_main(SCRIPT, ["create", "--dir", d, "--output", out]).rc, 0)
        with open(out, encoding="utf-8") as fh:
            self.assertRegex(parse_github_output(fh.read())["manifest-id"], r"^[0-9a-f]{12}$")

    def test_an_empty_manifest_output_is_a_refusal_and_the_comparison_step_cannot_be_skipped(self):
        """GitHub drops an output that holds a registered secret, and an output can be empty: the step receives an empty variable."""
        steps = self.jobs()["upload"]["steps"]
        cmp_ = next(s for s in steps if s["name"] == w.COMPARE_STEP)
        self.assertEqual(cmp_["if"], "")
        self.assertNotIn("continue-on-error", cmp_["keys"])
        self.assertIn("set -euo pipefail", cmp_["run"])
        d = self.path("staged")
        make_coordinate(d)
        for manifest in ("", "\n", "   "):
            res = h.run_main(SCRIPT, ["verify", "--dir", d, "--manifest-env", "MANIFEST"], env=h.clean_env(MANIFEST=manifest))
            self.assertEqual(res.rc, 1, res)
            self.assertIn("the manifest is empty", res.err)
            self.assertNotIn("ok", res.out)

    def test_the_settings_and_the_upload_cannot_run_without_the_comparison_having_passed(self):
        """Steps run in order and a failed step ends the job: no step after the comparison has a condition or continues on error."""
        steps = self.jobs()["upload"]["steps"]
        after = steps[[w.kind(s) for s in steps].index(w.COMPARE_STEP):]
        for s in after:
            self.assertEqual(s["if"], "", w.short(s))
            self.assertNotIn("continue-on-error", s["keys"], w.short(s))
            self.assertNotIn("if", s["keys"], w.short(s))
        self.assertEqual(w.job_value(self.jobs()["upload"], "if"),
                         "${{ needs.build.outputs.publish == 'true' && needs.publish.result == 'success' }}")

    def test_attest_cannot_run_when_upload_was_skipped_or_failed(self):
        jobs = self.jobs()
        self.assertEqual(w.job_value(jobs["attest"], "needs"), "[publish, upload]")
        self.assertEqual(w.job_value(jobs["attest"], "if"), "${{ needs.upload.result == 'success' }}")
        self.assertNotRegex(w.job_value(jobs["attest"], "if"), r"always|cancelled|failure|\|\|")
        # upload's own condition names publish's success, so a skipped publish skips upload and then attest
        self.assertIn("needs.publish.result == 'success'", w.job_value(jobs["upload"], "if"))

    def test_upload_and_attest_take_the_artifact_and_the_manifest_from_the_same_publish_job(self):
        """A re-run of a job reads the outputs `publish` kept; a re-run of `publish` is a new attempt, so a new artifact name."""
        jobs = self.jobs()
        refs = set()
        for name in ("upload", "attest"):
            for s in jobs[name]["steps"]:
                for blob in (*s["env"].values(), *s["with"].values()):
                    refs.update(re.findall(r"needs\.[\w-]+\.outputs\.[\w-]+", blob))
        self.assertEqual(refs, {"needs.publish.outputs.artifact", "needs.publish.outputs.manifest"})
        self.assertIn("github.run_attempt", w.job_outputs(jobs["publish"])["artifact"])

    def test_no_step_continues_on_error_and_none_runs_after_a_failure_but_the_key_removal(self):
        """Scanned over the whole file: the only outcome-conditional step is the removal of the signing key."""
        flagged = []
        for name, j in self.jobs().items():
            for s in j["steps"]:
                if "continue-on-error" in s["keys"] or w.OUTCOME_CONDITION.search(s["if"]) or "!cancelled" in s["raw"]:
                    flagged.append((name, w.short(s)))
        self.assertEqual(flagged, [("publish", "Remove the signing key")])

    def test_the_comparison_runs_in_upload_before_any_mvn_and_in_a_step_of_its_own(self):
        steps = self.jobs()["upload"]["steps"]
        first_mvn = next(i for i, s in enumerate(steps) if re.search(r"\bmvn\b", s["run"]))
        cmp_ = next(i for i, s in enumerate(steps) if "staged_manifest.py" in s["run"])
        self.assertLess(cmp_, first_mvn)
        self.assertEqual(sum(1 for s in steps if "staged_manifest.py" in s["run"]), 1)


if __name__ == "__main__":
    unittest.main()
