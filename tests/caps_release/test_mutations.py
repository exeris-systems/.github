"""The suite protects the guards: every mutation of a script is detected by the tests of that script.

Each entry is `(script, old, new, selectors)`. `old` must occur in the script exactly once, so a
refactor cannot turn a mutation into a no-op; the script is copied (with its siblings) to a
temporary directory, the single replacement is applied, and the selected tests run against that
copy with failfast. The mutant is KILLED when a test fails or errors. A surviving mutant fails this
test and is listed.
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest

import caps_release_helpers as h

RR = ["test_resolve_release.Refuses", "test_resolve_release.Accepts", "test_resolve_release.Output",
      "test_resolve_release.ControlCharacters.test_every_control_character_in_every_field_in_process",
      "test_resolve_release.ControlCharacters.test_undecodable_byte_is_refused_by_the_subprocess_and_in_process",
      "test_resolve_release.ControlCharacters.test_two_key_value_lines_cannot_be_smuggled_through_the_output_file",
      "test_resolve_release.ControlCharacters.test_unicode_separators_and_bidi_cannot_become_a_version"]
PROFILE = ["test_pom_scripts.ReleaseProfile"]
VERSION = ["test_pom_scripts.PomVersion"]
SCAN = ["test_pom_scripts.ScanSnapshots"]
AUTO = ["test_pom_scripts.AutoPublish"]
LOG = ["test_log_drift_secrets.DryRunLog"]
DRIFT = ["test_log_drift_secrets.Drift"]
SECRETS = ["test_log_drift_secrets.Secrets"]
READY = ["test_release_readiness.Complete", "test_release_readiness.Bundle"]
READY_B = ["test_release_readiness.Bundle", "test_release_readiness.Complete"]
REMOVE = ["test_remove_signing_key.Removal"]
REMOVE_REAL = ["test_remove_signing_key.RealGpg"]
RUNNER = ["test_runner.Runner"]

M = []


def m(script, old, new, selectors):
    M.append((script, old, new, selectors))


# resolve_release.py
r = "resolve_release"
m(r, 'SEMVER = re.compile(r"[0-9]+\\.[0-9]+\\.[0-9]+")', 'SEMVER = re.compile(r"\\d+\\.\\d+\\.\\d+")', RR)
m(r, 'TAG = re.compile(r"v[0-9]+\\.[0-9]+\\.[0-9]+")', 'TAG = re.compile(r"v\\d+\\.\\d+\\.\\d+")', RR)
m(r, "SEMVER.fullmatch(version)", "SEMVER.match(version)", RR)
m(r, "TAG.fullmatch(tag)", "TAG.match(tag)", RR)
m(r, "if o < 0x20 or 0x7F <= o <= 0x9F:", "if o < 0x20:", RR)
m(r, "if o < 0x20 or 0x7F <= o <= 0x9F:", "if o < 0x20 or 0x7F <= o <= 0x7F:", RR)
m(r, "if o < 0x20 or 0x7F <= o <= 0x9F:", "if o < 0x20 or 0x80 <= o <= 0x9F:", RR)
m(r, "if o < 0x20 or 0x7F <= o <= 0x9F:", "if 0x01 <= o < 0x20 or 0x7F <= o <= 0x9F:", RR)
m(r, "if 0xD800 <= o <= 0xDFFF:", "if False:", RR)
m(r, 'whole(label.replace("_", "-"), getattr(a, label) or "")', "pass", RR)
m(r, 'whole("compare status", status)', "pass", RR)
m(r, 'if a.target not in ("none", "central", "github-packages"):', "if False:", RR)
m(r, 'if a.upload not in ("true", "false"):', "if False:", RR)
m(r, 'if not g or g.startswith("/") or ".." in g:', "if False:", RR)
m(r, 'if not g or g.startswith("/") or ".." in g:', 'if not g or ".." in g:', RR)
m(r, 'if not g or g.startswith("/") or ".." in g:', 'if not g or g.startswith("/"):', RR)
m(r, 'if not g or g.startswith("/") or ".." in g:', 'if g.startswith("/") or ".." in g:', RR)
m(r, "if not TAG.fullmatch(tag):", "if False:", RR)
m(r, "if a.version and a.version != version:", "if False:", RR)
m(r, 'if not a.default_branch:\n            raise Refused("the default branch is unknown', "if False:\n            raise Refused(\"the default branch is unknown", RR)
m(r, "if status not in ON_DEFAULT:", "if False:", RR)
m(r, 'ON_DEFAULT = ("identical", "behind")', 'ON_DEFAULT = ("identical", "behind", "ahead")', RR)
m(r, 'ON_DEFAULT = ("identical", "behind")', 'ON_DEFAULT = ("identical",)', RR)
m(r, "except (subprocess.CalledProcessError, OSError) as exc:", "except subprocess.CalledProcessError as exc:", RR)
m(r, "if not (a.repository and a.sha):", "if False:", RR)
m(r, 'a.ref != f"refs/heads/{a.default_branch}"', 'not a.ref.startswith(f"refs/heads/{a.default_branch}")', RR)
m(r, 'if not on_tag and (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):',
  'if (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):', RR)
m(r, 'if not on_tag and (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):', "if False:", RR)
m(r, 'if not on_tag and (not a.default_branch or', "if not on_tag and (", RR)
m(r, 'if a.upload == "true" and a.target == "none":', "if False:", RR)
m(r, "        publish = True\n", "        publish = False\n", RR)
m(r, "print(f\"::error::{exc}\", file=sys.stderr)\n        return 1", "print(f\"::error::{exc}\", file=sys.stderr)\n        return 0", RR)
m(r, 'open(a.output, "a", encoding="utf-8")', 'open(a.output, "w", encoding="utf-8")', RR)
m(r, "version = tag[1:]", "version = tag", RR)
m(r, "if a.output:", "if True:", RR)

# check_release_profile.py
p = "check_release_profile"
m(p, 'if "release" not in ids:', "if False:", PROFILE)
m(p, 'ids = [(c.text or "").strip()', 'ids = [(c.text or "")', PROFILE)
m(p, 'if any(local(c.tag) == "modules" for c in root):', "if False:", PROFILE)
m(p, 'if target == "central":', "if False:", PROFILE)
m(p, "        if not central:\n", "        if False:\n", PROFILE)
m(p, 'if "central" not in values.get("publishingServerId", []):', "if False:", PROFILE)
m(p, 'return tag.rsplit("}", 1)[-1]', "return tag", PROFILE)
m(p, "except (OSError, ET.ParseError) as exc:", "except OSError as exc:", PROFILE + ["test_pom_scripts.XmlHostile"])
m(p, "    if missing:\n        print", "    if False:\n        print", PROFILE)
m(p, "return missing, central", "return missing, False", PROFILE)
m(p, 'values.setdefault(local(el.tag), []).append((el.text or "").strip())', 'values.setdefault(local(el.tag), []).append((el.text or ""))', PROFILE)

# check_pom_version.py
v = "check_pom_version"
m(v, "if have != a.want:", "if False:", VERSION)
m(v, "for el in ET.parse(pom).getroot():", "for el in ET.parse(pom).getroot().iter():", VERSION)
m(v, 'return (el.text or "").strip()', 'return (el.text or "")', VERSION)
m(v, "except (OSError, ET.ParseError) as exc:", "except OSError as exc:", VERSION + ["test_pom_scripts.XmlHostile"])
m(v, 'if el.tag.rsplit("}", 1)[-1] == "version":', 'if el.tag == "version":', VERSION)

# scan_snapshots.py
s = "scan_snapshots"
m(s, 'if "properties" in up:', "if False:", SCAN)
m(s, 'if "dependency" in up and "plugin" not in up:', 'if "dependency" in up:', SCAN)
m(s, 'if "dependency" in up and "plugin" not in up:', "if False:", SCAN)
m(s, "    if hard:\n", "    if False:\n", SCAN)
m(s, '        if a.upload == "true":\n', "        if False:\n", SCAN)
m(s, "        if a.summary:\n", "        if False:\n", SCAN)
m(s, 'open(a.summary, "a", encoding="utf-8")', 'open(a.summary, "w", encoding="utf-8")', SCAN)
m(s, 'if "-SNAPSHOT" in raw:', "if False:", SCAN)
m(s, 'if not (el.text and "-SNAPSHOT" in el.text):', 'if not (el.text and "-SNAPSHOT" in el.text.strip()[-9:]):', SCAN)
m(s, "except (OSError, ET.ParseError) as exc:", "except OSError as exc:", SCAN + ["test_pom_scripts.XmlHostile"])
m(s, 'errors="replace"', 'errors="strict"', SCAN)
m(s, "        return 0\n    print(\"ok", "        return 1\n    print(\"ok", SCAN)
m(s, "            if \"-SNAPSHOT\" in raw", "            if \"-SNAPSHOT\" in raw and False", SCAN)
m(s, "up.append(local(e.tag))", "up.append(local(e.tag)) if len(up) < 1 else None", SCAN)

# check_auto_publish.py
a = "check_auto_publish"
m(a, 'local(el.tag) == "autoPublish" and value != "false"', "False", AUTO)
m(a, 'local(el.tag) == "waitUntil" and value.lower() != "validated"', "False", AUTO)
m(a, 'value != "false"', 'value.lower() != "false"', AUTO)
m(a, 'value.lower() != "validated"', 'value != "validated"', AUTO)
m(a, 'value.lower() != "validated"', 'value.lower() not in ("validated", "uploaded")', AUTO)
m(a, '(c.text or "").strip() == PLUGIN', '(c.text or "") == PLUGIN', AUTO)
m(a, "for el in plugin.iter():", "for el in plugin:", AUTO)
m(a, "    if problems:\n        return 1", "    if False:\n        return 1", AUTO)
m(a, "except (OSError, ET.ParseError) as exc:", "except OSError as exc:", AUTO + ["test_pom_scripts.XmlHostile"])
m(a, "if local(plugin.tag) != \"plugin\":\n            continue", "if False:\n            continue", AUTO)
m(a, 'value = (el.text or "").strip()', 'value = (el.text or "")', AUTO)
m(a, "problems.append(f\"<waitUntil>", "pass  # problems.append(f\"<waitUntil>", AUTO)

# check_dry_run_log.py
l = "check_dry_run_log"
m(l, "if BEGAN in text:", "if False:", LOG)
m(l, "if SKIPPED not in text:", "if False:", LOG)
m(l, 'BEGAN = "Going to upload"', 'BEGAN = "Going to uploadX"', LOG)
m(l, "Skipping the upload of the bundle at user's request\"", "Skipping the upload of the bundle\"", LOG)
m(l, 'errors="replace"', 'errors="strict"', LOG)
m(l, "except OSError as exc:", "except FileNotFoundError as exc:", LOG)
m(l, "        return 1\n    if SKIPPED", "        return 0\n    if SKIPPED", LOG)

# check_drift.py
d = "check_drift"
m(d, '"--untracked-files=all", ', "", DRIFT)
m(d, '"--porcelain", ', "", DRIFT)
m(d, "if status.returncode != 0:", "if False:", DRIFT)
m(d, "if not a.generated:", "if False:", DRIFT)
m(d, '"--", a.generated).stdout.rstrip())', "a.generated).stdout.rstrip())", DRIFT)
m(d, '"status", "--porcelain", "--untracked-files=all", "--", a.generated)', '"status", "--porcelain", "--untracked-files=all", a.generated)', DRIFT)
m(d, 'tail = " If a deployment was uploaded, DROP it." if a.uploaded else', 'tail = " If a deployment was uploaded, DROP it." if not a.uploaded else', DRIFT)
m(d, "if status.stdout.strip():", "if False:", DRIFT)
m(d, "        return 1\n    print(f\"ok", "        return 0\n    print(f\"ok", DRIFT)

# check_secrets.py
c = "check_secrets"
m(c, 'os.environ.get(var) != "true"', 'os.environ.get(var, "").lower() != "true"', SECRETS)
m(c, 'os.environ.get(var) != "true"', 'os.environ.get(var) == "false"', SECRETS)
m(c, 'os.environ.get(var) != "true"', 'os.environ.get(var, "").strip() != "true"', SECRETS)
m(c, 'if a.target == "central":', "if False:", SECRETS)
m(c, ', ("HAVE_GPG_PASSPHRASE", "GPG_PASSPHRASE")]', "]", SECRETS)
m(c, 'need = [("HAVE_GPG_KEY", "GPG_PRIVATE_KEY"), ', "need = [", SECRETS)
m(c, "    if missing:\n", "    if False:\n", SECRETS)
m(c, 'choices=["central", "github-packages"]', 'choices=["central", "github-packages", "none"]', SECRETS)
m(c, '("HAVE_CENTRAL_USER", "CENTRAL_TOKEN_USERNAME"), ', "", SECRETS)

# check_release_readiness.py
y = "check_release_readiness"
m(y, "    if not mains:\n", "    if False:\n", READY)
m(y, 'not n.endswith(("-sources.jar", "-javadoc.jar", "-tests.jar"))', 'not n.endswith(("-sources.jar", "-javadoc.jar"))', READY)
m(y, 'not n.endswith(("-sources.jar", "-javadoc.jar", "-tests.jar"))', 'not n.endswith(("-javadoc.jar", "-tests.jar"))', READY)
m(y, "and os.path.isfile(os.path.join(t, n))", "", READY)
m(y, 'if base.endswith("-SNAPSHOT"):', "if False:", READY)
m(y, "            if not os.path.isfile(os.path.join(t, want)):", "            if False:", READY)
m(y, 'if "index.html" not in zipfile.ZipFile(javadoc).namelist():', 'if not any(n.endswith("index.html") for n in zipfile.ZipFile(javadoc).namelist()):', READY)
m(y, 'if "index.html" not in zipfile.ZipFile(javadoc).namelist():', "if False:", READY)
m(y, "            except zipfile.BadZipFile:\n                err(f\"{base}-javadoc.jar", "            except KeyError:\n                err(f\"{base}-javadoc.jar", READY)
m(y, 'if not os.path.isfile(path + ".asc"):', "if False:", READY)
m(y, 'elif not good_signature(path + ".asc", path):', "elif False:", READY)
m(y, '[a.gpg, "--verify", asc, f]', '[a.gpg, "--verify", f, asc]', READY)
m(y, ").returncode == 0", ").returncode != 127", READY)
m(y, "        except OSError:\n            return False", "        except OSError:\n            return True", READY)
m(y, 'if a.expect_bundle == "true":', "if False:", READY_B)
m(y, "        if not os.path.isfile(bundle):", "        if False:", READY_B)
m(y, "            except zipfile.BadZipFile:\n                err(f\"{bundle}", "            except KeyError:\n                err(f\"{bundle}", READY_B)
m(y, 'or not filename.startswith((stem + ".", stem + "-"))', "", READY_B)
m(y, 'filename.startswith((stem + ".", stem + "-"))', "filename.startswith((stem,))", READY_B)
m(y, 'f"{directory}/{stem}.pom" not in entries', "False", READY_B)
m(y, "len(parts) >= 3", "len(parts) >= 2", READY_B)
m(y, "    if findings:\n", "    if False:\n", READY)
m(y, "if a.uploaded else", "if not a.uploaded else", READY)
m(y, "files = [main_jar, f\"{base}-sources.jar\", f\"{base}-javadoc.jar\", f\"{base}.pom\"]",
  "files = [main_jar, f\"{base}-sources.jar\", f\"{base}-javadoc.jar\"]", READY)
m(y, "files = [main_jar, f\"{base}-sources.jar\", f\"{base}-javadoc.jar\", f\"{base}.pom\"]",
  "files = [main_jar, f\"{base}-javadoc.jar\", f\"{base}.pom\"]", READY)
m(y, "for want in files[1:]:", "for want in files[1:2]:", READY)
m(y, "        if len(findings) == before:", "        if True:", READY)
m(y, "stray = stray_entries(listed)", "stray = []", READY_B)

# remove_signing_key.py
k = "remove_signing_key"
m(k, "shutil.rmtree(a.secret_home, ignore_errors=True)", "pass", REMOVE)
m(k, '[a.gpgconf, "--kill", "gpg-agent"]', '[a.gpgconf, "--reload", "gpg-agent"]', REMOVE)
m(k, '"GNUPGHOME": a.secret_home}', '"GNUPGHOME": a.verify_home}', REMOVE)
m(k, "if os.path.isdir(a.secret_home):", "if False:", REMOVE)
m(k, "os.chmod(a.verify_home, 0o700)", "pass", REMOVE)
m(k, 'fh.write(f"GNUPGHOME={a.verify_home}\\n")', 'fh.write(f"GNUPGHOME={a.verify_home}")', REMOVE)
m(k, 'open(a.env_file, "a", encoding="utf-8")', 'open(a.env_file, "w", encoding="utf-8")', REMOVE)
m(k, "        if done.returncode != 0:", "        if False:", REMOVE)
m(k, "os.remove(a.public_key)", "pass", REMOVE)
m(k, "    if os.path.exists(a.secret_home):", "    if False:", REMOVE)
m(k, 'ln.startswith("sec")', 'ln.startswith("pub")', REMOVE)
m(k, "if listed.returncode not in (0, 2) or secret:", "if listed.returncode not in (0, 2):", REMOVE)
m(k, "if listed.returncode not in (0, 2) or secret:", "if secret:", REMOVE)
m(k, "if listed.returncode not in (0, 2) or secret:", "if listed.returncode not in (0, 1, 2) or secret:", REMOVE)
m(k, "    if failed:\n        return 1", "    if failed:\n        return 0", REMOVE)
m(k, '"--import", a.public_key]', '"--import", a.public_key + ".x"]', REMOVE)
m(k, "os.path.getsize(a.public_key) > 0", "os.path.getsize(a.public_key) >= 0", REMOVE)
m(k, 'env = {**os.environ, "GNUPGHOME": a.verify_home}', 'env = {**os.environ, "GNUPGHOME": a.secret_home}', REMOVE)
m(k, '"--list-secret-keys", "--with-colons"', '"--list-keys", "--with-colons"', REMOVE)

# run_caps_release_tests.py
m("../run_caps_release_tests", "    if n == 0:", "    if False:", RUNNER)
m("../run_caps_release_tests", "return 0 if result.wasSuccessful() else 1", "return 0", RUNNER)
m("../run_caps_release_tests", 'pattern="test*.py"', 'pattern="tst*.py"', RUNNER)
m("../run_caps_release_tests", "return 0 if result.wasSuccessful() else 1", "return 0 if not result.failures else 1", RUNNER)
m("../run_caps_release_tests", "        return 1\n    result", "        return 0\n    result", RUNNER)


def source_of(script):
    return os.path.join(h.REPO, "scripts", "caps_release", script + ".py") if not script.startswith("../") else \
        os.path.join(h.REPO, "scripts", script[3:] + ".py")


def killed(script, old, new, selectors):
    with open(source_of(script), encoding="utf-8") as fh:
        text = fh.read()
    if text.count(old) != 1:
        return None, f"pattern occurs {text.count(old)} times, not once"
    work = tempfile.mkdtemp(prefix="caps-mutant-")
    try:
        for name in os.listdir(h.SCRIPT_DIR):
            if name.endswith(".py"):
                shutil.copy(os.path.join(h.SCRIPT_DIR, name), os.path.join(work, name))
        shutil.copy(h.RUNNER, os.path.join(work, "run_caps_release_tests.py"))
        target = os.path.join(work, os.path.basename(source_of(script)))
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))
        h.SCRIPT_DIR_OVERRIDE = work
        suite = unittest.defaultTestLoader.loadTestsFromNames(selectors)
        result = unittest.TextTestRunner(stream=io.StringIO(), failfast=True).run(suite)
        return bool(result.failures or result.errors), ""
    finally:
        h.SCRIPT_DIR_OVERRIDE = None
        shutil.rmtree(work, ignore_errors=True)


class Mutants(unittest.TestCase):
    def test_every_mutation_is_killed(self):
        survivors, broken = [], []
        for script, old, new, selectors in M:
            was_killed, why = killed(script, old, new, selectors)
            if was_killed is None:
                broken.append(f"{script}: {old[:60]!r}: {why}")
            elif not was_killed:
                survivors.append(f"{script}: {old[:70]!r} -> {new[:60]!r}")
        self.assertEqual(broken, [], "mutations whose pattern no longer applies exactly once")
        self.assertEqual(survivors, [], "SURVIVING MUTANTS: the tests do not notice these changes to a guard")

    def test_the_harness_reports_a_mutant_the_tests_cannot_see(self):
        """A replacement that changes nothing must survive, and a pattern that does not apply once is reported."""
        self.assertIs(killed("check_secrets", "if missing:", "if missing:", SECRETS)[0], False)
        self.assertIsNone(killed("check_secrets", "a.target", "a.target", SECRETS)[0])
        self.assertIsNone(killed("check_secrets", "no such text anywhere", "x", SECRETS)[0])

    def test_there_is_a_mutation_for_every_script(self):
        scripts = {s for s, *_ in M}
        on_disk = {n[:-3] for n in os.listdir(h.SCRIPT_DIR) if n.endswith(".py")}
        self.assertEqual(on_disk - scripts, set())
        self.assertGreaterEqual(len(M), 150)


if __name__ == "__main__":
    unittest.main()
