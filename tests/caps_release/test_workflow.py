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
    "removal-not-after-deploy": [(REMOVAL, "      - name: Interlude\n        run: echo hi\n\n" + REMOVAL, 0)],
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
    "target-default": [('default: "none"', 'default: "central"', 0)],
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
        self.assertIn("Build, sign and upload", names)
        self.assertEqual(names.index("Remove the signing key"), names.index("Build, sign and upload") + 1)

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
            "Build, sign and upload": ["CENTRAL_TOKEN_PASSWORD", "CENTRAL_TOKEN_USERNAME", "GPG_PASSPHRASE"],
        })

    def test_every_uses_is_a_40_hex_pin(self):
        uses = re.findall(r"^\s*(?:- )?uses:\s*(\S+)", "\n".join(w.strip_comments(read())), re.M)
        self.assertGreaterEqual(len(uses), 8)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

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
        ignore = {"job-missing", "import-step-not-unique", "deploy-step-not-unique", "removal-step-not-unique",
                  "publish-reads-no-secret", "top-level-write-permission", "build-not-read-only",
                  "attestations-outside-attest", "packages-outside-publish", "attest-not-conditional",
                  "scripts-checkout-ref"}
        self.assertEqual(sorted(ids - covered - ignore), [])

    def test_the_parse_notices_a_secret_moved_into_a_comment_only_when_it_is_shell(self):
        text = read()
        yaml_comment = mutate(text, "      - name: Write the Maven settings", "      # ${{ secrets.X }}\n      - name: Write the Maven settings")
        self.assertEqual(w.violations(yaml_comment), set())     # a YAML comment is not evaluated
        shell_comment = mutate(text, "          home=\"$RUNNER_TEMP/dry-run-gnupg\"\n",
                               "          # ${{ secrets.X }}\n          home=\"$RUNNER_TEMP/dry-run-gnupg\"\n")
        self.assertIn("secrets-outside-publish:build", w.violations(shell_comment))   # evaluated by GitHub even there


if __name__ == "__main__":
    unittest.main()
