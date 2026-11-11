"""The mutation table: one source change per entry, each of which some test must notice.

Every entry is `(script, old, new, selectors)`. `old` occurs in the script exactly once, so a refactor
cannot turn a mutation into a no-op. Every refusal branch and every security-relevant constant of every
script has at least one entry: the condition inverted, the branch deleted, the pattern or the bound loosened.

A defence that is stated twice (git's `--literal-pathspecs` and `GIT_LITERAL_PATHSPECS`) is mutated at both
places in one entry, because removing either alone changes nothing.
"""
from __future__ import annotations

M: list = []


def m(script, old, new, selectors):
    M.append((script, old, new, selectors))


# --- selectors ---------------------------------------------------------------------------------------------------------
UNEXPECTED = ["test_unexpected.Injected.test_a_runtime_error_inside_the_script_is_one_error_line_and_exit_one"]
RR = ["test_resolve_release.Refuses", "test_resolve_release.Accepts", "test_resolve_release.Output",
      "test_resolve_release.NonPrinting", "test_resolve_release.Usage", "test_resolve_release.RealComparison",
      "test_resolve_release.ControlCharacters.test_every_control_character_in_every_field_in_process",
      "test_resolve_release.ControlCharacters.test_undecodable_byte_is_refused_by_the_subprocess_and_in_process",
      "test_resolve_release.ControlCharacters.test_two_key_value_lines_cannot_be_smuggled_through_the_output_file",
      "test_resolve_release.ControlCharacters.test_unicode_separators_and_bidi_cannot_become_a_version"] + UNEXPECTED
PROFILE = ["test_pom_scripts.ReleaseProfile", "test_pom_adversarial.MalformedPoms", "test_pom_adversarial.ProfileMisplacedPlugin", "test_pom_adversarial.Doctype",
           "test_pom_scripts.XmlHostile", "test_unexpected.Seams.test_an_unwritable_output_is_one_error_line_for_the_profile_check"] + UNEXPECTED
VERSION = ["test_pom_scripts.PomVersion", "test_pom_adversarial.MalformedPoms", "test_pom_adversarial.Doctype", "test_pom_scripts.XmlHostile"] + UNEXPECTED
SCAN = ["test_pom_scripts.ScanSnapshots", "test_pom_adversarial.ScanGaps", "test_pom_adversarial.MalformedPoms", "test_pom_adversarial.SnapshotVersions", "test_pom_adversarial.FloatingVersions",
        "test_pom_adversarial.MavenRule", "test_pom_adversarial.Doctype", "test_pom_scripts.XmlHostile",
        "test_unexpected.Seams.test_an_unwritable_summary_is_one_error_line_for_the_snapshot_scan"] + UNEXPECTED
AUTO = ["test_pom_scripts.AutoPublish", "test_pom_adversarial.MalformedPoms", "test_pom_adversarial.AutoPublishProperties", "test_pom_adversarial.Doctype",
        "test_pom_scripts.XmlHostile"] + UNEXPECTED
LOG = ["test_log_drift_secrets.DryRunLog"]
DRIFT = ["test_log_drift_secrets.Drift"] + UNEXPECTED
SECRETS = ["test_log_drift_secrets.Secrets"]
READY = ["test_release_readiness.Complete", "test_readiness_adversarial.ReleasedSet", "test_bundle_adversarial.Binding",
         "test_bundle_adversarial.Names", "test_bundle_adversarial.Gaps", "test_readiness_adversarial.Staging",
         "test_release_readiness.RealBundle", "test_release_readiness.Bundle", "test_bundle_adversarial.Headers",
         "test_bundle_adversarial.Links", "test_pom_adversarial.MavenRule", "test_readiness_adversarial.UnboundGroup",
         "test_unexpected.Readiness", "test_bundle_adversarial.Bounds"]
REMOVE = ["test_remove_signing_key.Removal", "test_key_removal_adversarial.Inspection", "test_key_removal_adversarial.HostilePaths",
          "test_key_removal_adversarial.Real", "test_unexpected.Injected.test_key_removal_ends_an_unexpected_exception_with_one_line_and_cleans_up"]
RUNNER = ["test_runner.Runner"]

# --- resolve_release.py ------------------------------------------------------------------------------------------------
r = "resolve_release"
NUM = 'NUMBER = r"(?:0|[1-9][0-9]{0,8})"'
for new in ('NUMBER = r"[0-9]+"', 'NUMBER = r"(?:0|[1-9][0-9]*)"', 'NUMBER = r"(?:0|[1-9][0-9]{0,9})"',
            'NUMBER = r"(?:0|[1-9][0-9]{0,7})"', 'NUMBER = r"[0-9]{1,9}"', 'NUMBER = r"(?:0|0?[1-9][0-9]{0,8})"',
            'NUMBER = r"(?:0|[1-9][0-9]{0,8})*"', 'NUMBER = r"(?:[1-9][0-9]{0,8})"'):
    m(r, NUM, new, RR)
m(r, 'SEMVER = re.compile(rf"{NUMBER}\\.{NUMBER}\\.{NUMBER}")', 'SEMVER = re.compile(rf"{NUMBER}\\.{NUMBER}")', RR)
m(r, 'SEMVER = re.compile(rf"{NUMBER}\\.{NUMBER}\\.{NUMBER}")', 'SEMVER = re.compile(rf"{NUMBER}.{NUMBER}.{NUMBER}")', RR)
m(r, 'TAG = re.compile(rf"v{NUMBER}\\.{NUMBER}\\.{NUMBER}")', 'TAG = re.compile(rf"v?{NUMBER}\\.{NUMBER}\\.{NUMBER}")', RR)
m(r, 'TAG = re.compile(rf"v{NUMBER}\\.{NUMBER}\\.{NUMBER}")', 'TAG = re.compile(rf"[vV]{NUMBER}\\.{NUMBER}\\.{NUMBER}")', RR)
m(r, "SEMVER.fullmatch(version)", "SEMVER.match(version)", RR)
m(r, "TAG.fullmatch(tag)", "TAG.match(tag)", RR)
m(r, 'PATH_SEPARATORS = re.compile(r"[/\\\\]")', 'PATH_SEPARATORS = re.compile(r"[/]")', RR)
m(r, 'PATH_SEPARATORS = re.compile(r"[/\\\\]")', 'PATH_SEPARATORS = re.compile(r"[\\\\]")', RR)
m(r, 'ON_DEFAULT = ("identical", "behind")', 'ON_DEFAULT = ("identical", "behind", "ahead")', RR)
m(r, 'ON_DEFAULT = ("identical", "behind")', 'ON_DEFAULT = ("identical",)', RR)
m(r, 'ON_DEFAULT = ("identical", "behind")', 'ON_DEFAULT = ("behind",)', RR)
m(r, "if 0xD800 <= o <= 0xDFFF:", "if False:", RR)
m(r, "if 0xD800 <= o <= 0xDFFF:", "if 0xDC00 <= o <= 0xDFFF:", RR)
m(r, "if 0xD800 <= o <= 0xDFFF:", "if 0xD800 <= o <= 0xDBFF:", RR)
m(r, 'if category == "Cc":', "if False:", RR)
for cat in ("Cf", "Zl", "Zp", "Cn"):
    rest = ", ".join(f'"{c}"' for c in ("Cf", "Zl", "Zp", "Cn") if c != cat)
    m(r, 'if category in ("Cf", "Zl", "Zp", "Cn"):', f"if category in ({rest}):", RR)
m(r, "    if found:\n        raise Refused", "    if not found:\n        raise Refused", RR)
LABELS = ["target", "upload", "version", "generated_path", "ref_type", "ref_name", "ref", "default_branch", "repository", "sha",
          "compare_status", "output"]
TUPLE = ('("target", "upload", "version", "generated_path", "ref_type", "ref_name", "ref",\n'
         '                  "default_branch", "repository", "sha", "compare_status", "output")')
for label in LABELS:
    kept = ", ".join(f'"{x}"' for x in LABELS if x != label)
    m(r, TUPLE, f"({kept})", RR)
m(r, 'whole("compare status", status)', "pass", RR)
m(r, 'if a.target not in ("none", "central", "github-packages"):', "if False:", RR)
for drop in ('"none", ', '"central", ', ', "github-packages"'):
    m(r, 'if a.target not in ("none", "central", "github-packages"):',
      'if a.target not in ("none", "central", "github-packages"):'.replace(drop, "", 1), RR)
m(r, 'if a.upload not in ("true", "false"):', "if False:", RR)
m(r, 'if a.upload not in ("true", "false"):', 'if a.upload not in ("true", "false", "True"):', RR)
m(r, "    if (not g or g.startswith", "    if (False or g.startswith", RR)
m(r, 'g.startswith("/") or g.startswith(":")', 'g.startswith(":")', RR)
m(r, 'g.startswith("/") or g.startswith(":")', 'g.startswith("/")', RR)
for chars in ('"?[]"', '"*[]"', '"*?]"', '"*?["'):
    m(r, 'any(c in g for c in "*?[]")', f"any(c in g for c in {chars})", RR)
m(r, '".." in PATH_SEPARATORS.split(g)', "False", RR)
m(r, '".." in PATH_SEPARATORS.split(g)', '".." in g', RR)
m(r, '".." in PATH_SEPARATORS.split(g)', '".." in g.split("/")', RR)
m(r, 'on_tag = a.ref_type == "tag"', 'on_tag = a.ref_type != "tag"', RR)
m(r, 'on_tag = a.ref_type == "tag"', 'on_tag = a.ref_type.lower() == "tag"', RR)
m(r, "if not TAG.fullmatch(tag):", "if False:", RR)
m(r, "version = tag[1:]", "version = tag", RR)
m(r, "if a.version and a.version != version:", "if False:", RR)
m(r, "if a.version and a.version != version:", "if a.version and a.version == version:", RR)
m(r, "if a.version and a.version != version:", "if a.version != version:", RR)
m(r, "        if not a.default_branch:\n            raise Refused(\"the default", "        if False:\n            raise Refused(\"the default", RR)
m(r, "        if not status:\n", "        if False:\n", RR)
m(r, "if not (a.repository and a.sha):", "if False:", RR)
m(r, "if not (a.repository and a.sha):", "if not (a.repository or a.sha):", RR)
m(r, "            except Exception as exc:\n                raise Refused", "            except subprocess.CalledProcessError as exc:\n                raise Refused", RR)
m(r, "            except Exception as exc:\n                raise Refused", "            except OSError as exc:\n                raise Refused", RR)
m(r, "if status not in ON_DEFAULT:", "if False:", RR)
m(r, "        version = a.version\n        if not SEMVER.fullmatch(version):", "        version = a.version\n        if False:", RR)
m(r, 'if a.upload == "true" and a.target == "none":', "if False:", RR)
m(r, 'if a.upload == "true" and a.target == "none":', 'if a.target == "none":', RR)
m(r, '    elif a.upload == "true":\n        publish = True', '    elif a.upload == "true":\n        publish = False', RR)
m(r, '    elif a.upload == "true":\n        publish = True', '    elif a.upload != "true":\n        publish = True', RR)
m(r, 'if not on_tag and (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):', "if False:", RR)
m(r, 'if not on_tag and (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):',
  'if (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):', RR)
m(r, 'if not on_tag and (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):',
  'if not on_tag and (a.ref != f"refs/heads/{a.default_branch}"):', RR)
m(r, 'if not on_tag and (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):',
  'if not on_tag and (not a.default_branch or not a.ref.startswith(f"refs/heads/{a.default_branch}")):', RR)
m(r, "    except Exception as exc:\n        print(f\"::error::the release resolution", "    except ValueError as exc:\n        print(f\"::error::the release resolution", RR)
m(r, "{' '.join(str(exc).split())}).\", file=sys.stderr)\n        return 1", "{str(exc)}).\", file=sys.stderr)\n        return 1", RR)
m(r, "{type(exc).__name__}: ", "", RR)
m(r, "    except Refused as exc:\n        print(f\"::error::{exc}\", file=sys.stderr)\n        return 1", "    except Refused as exc:\n        print(f\"::error::{exc}\", file=sys.stderr)\n        return 0", RR)
m(r, "    if a.output:\n", "    if True:\n", RR)
m(r, 'open(a.output, "a", encoding="utf-8")', 'open(a.output, "w", encoding="utf-8")', RR)
m(r, "fh.write(f\"version={version}\\npublish={'true' if publish else 'false'}\\n\")", "fh.write(f\"version={version}\\npublish={'false' if publish else 'true'}\\n\")", RR)
m(r, "fh.write(f\"version={version}\\npublish={'true' if publish else 'false'}\\n\")", "fh.write(f\"version={version}\\n\")", RR)
m(r, "check=True, capture_output=True", "check=False, capture_output=True", ["test_resolve_release.RealComparison"])

# --- check_release_profile.py ------------------------------------------------------------------------------------------
p = "check_release_profile"
m(p, "        parser.Parse(data, True)", "        pass", PROFILE)
m(p, "    parser.StartDoctypeDeclHandler = refuse\n", "", PROFILE)
m(p, 'CENTRAL_GROUP = "org.sonatype.central"', 'CENTRAL_GROUP = "org.sonatype"', PROFILE)
m(p, 'CENTRAL_PLUGIN = "central-publishing-maven-plugin"', 'CENTRAL_PLUGIN = "central-publishing"', PROFILE)
m(p, 'return tag.rsplit("}", 1)[-1]', "return tag", PROFILE)
m(p, '" ".join(c.text.strip() for c in children(el, name) if c.text)', '" ".join(c.text for c in children(el, name) if c.text)', PROFILE)
m(p, '" ".join(c.text.strip() for c in children(el, name) if c.text)', '" ".join(c.text.strip() for c in children(el, name))', PROFILE)
m(p, 'if (text(profile, "id")) == "release"', 'if (text(profile, "id")) != "release"', PROFILE)
m(p, 'if (text(profile, "id")) == "release"', 'if "release" in (text(profile, "id"))', PROFILE)
m(p, "    if not release:\n", "    if False:\n", PROFILE)
m(p, 'if children(root, "modules") or any(children(profile, "modules") for profile in profiles):',
  'if any(children(profile, "modules") for profile in profiles):', PROFILE)
m(p, 'if children(root, "modules") or any(children(profile, "modules") for profile in profiles):',
  'if children(root, "modules"):', PROFILE)
m(p, 'if children(root, "modules") or any(children(profile, "modules") for profile in profiles):',
  'if children(root, "modules") or any(children(profile, "modules") for profile in release):', PROFILE)
m(p, 'if children(root, "modules") or any(children(profile, "modules") for profile in profiles):', "if False:", PROFILE)
m(p, 'profiles = [profile for container in children(root, "profiles") for profile in children(container, "profile")]',
  'profiles = [profile for container in children(root, "profiles") for profile in children(container, "profile")][:1]', PROFILE)
m(p, "if text(plugin, \"groupId\") == CENTRAL_GROUP and text(plugin, \"artifactId\") == CENTRAL_PLUGIN]",
  "if text(plugin, \"artifactId\") == CENTRAL_PLUGIN]", PROFILE)
m(p, "if text(plugin, \"groupId\") == CENTRAL_GROUP and text(plugin, \"artifactId\") == CENTRAL_PLUGIN]",
  "if text(plugin, \"groupId\") == CENTRAL_GROUP]", PROFILE)
m(p, 'plugins = [plugin for profile in release for build in children(profile, "build")',
  'plugins = [plugin for profile in profiles for build in children(profile, "build")', PROFILE)
m(p, 'for container in children(build, "plugins") for plugin in children(container, "plugin")',
  'for container in build.iter() for plugin in children(container, "plugin")', PROFILE)
m(p, '    if target == "central":\n', "    if False:\n", PROFILE)
m(p, '        if not central:\n', "        if False:\n", PROFILE)
m(p, 'if not any(text(configuration, "publishingServerId") == "central"', 'if not any(text(configuration, "publishingServerId") != "central"', PROFILE)
m(p, 'if not any(text(configuration, "publishingServerId") == "central"', 'if not any("central" in text(configuration, "publishingServerId")', PROFILE)
m(p, 'for plugin in plugins for configuration in children(plugin, "configuration")):', 'for plugin in plugins for configuration in [plugin]):', PROFILE)
m(p, 'for plugin in plugins for configuration in children(plugin, "configuration")):', 'for plugin in plugins for configuration in plugin.iter()):', PROFILE)
m(p, "    return missing, central", "    return missing, True", PROFILE)
m(p, "    central = bool(plugins)", "    central = bool(plugins) or bool(profiles)", PROFILE)
m(p, "    except (OSError, ET.ParseError) as exc:", "    except OSError as exc:", PROFILE)
m(p, "    if missing:\n        print", "    if False:\n        print", PROFILE)
m(p, "{'; '.join(missing)}", "{missing[:1]}", PROFILE)
m(p, "    if a.output:\n", "    if True:\n", PROFILE)
m(p, "f\"has_central_plugin={'true' if central else 'false'}\\n\"", "f\"has_central_plugin={'false' if central else 'true'}\\n\"", PROFILE)
m(p, 'open(a.output, "a", encoding="utf-8")', 'open(a.output, "w", encoding="utf-8")', PROFILE)
m(p, "    except Exception as exc:\n        print(f\"::error::the release-profile check", "    except ValueError as exc:\n        print(f\"::error::the release-profile check", PROFILE)

# --- check_pom_version.py ----------------------------------------------------------------------------------------------
v = "check_pom_version"
m(v, "    parser.StartDoctypeDeclHandler = refuse\n", "", VERSION)
m(v, "        parser.Parse(data, True)", "        pass", VERSION)
m(v, "    for el in read_xml(pom):", "    for el in read_xml(pom).iter():", VERSION)
m(v, 'if el.tag.rsplit("}", 1)[-1] == "version":', 'if el.tag == "version":', VERSION)
m(v, 'return (el.text or "").strip()', 'return (el.text or "")', VERSION)
m(v, "    if have != a.want:", "    if False:", VERSION)
m(v, "    if have != a.want:", "    if have == a.want:", VERSION)
m(v, "    except (OSError, ET.ParseError) as exc:", "    except OSError as exc:", VERSION)
m(v, "    except Exception as exc:\n        print(f\"::error::the POM version check", "    except ValueError as exc:\n        print(f\"::error::the POM version check", VERSION)
m(v, "        return 1\n    print(f\"pom version", "        return 0\n    print(f\"pom version", VERSION)

# --- scan_snapshots.py -------------------------------------------------------------------------------------------------
s = "scan_snapshots"
TS = 'SNAPSHOT_TIMESTAMP = re.compile(r"(.*)-([0-9]{8}\\.[0-9]{6})-([0-9]+)")'
for new in ('r"(.*)-([0-9]{7}\\.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{5})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{6})-([0-9]*)"',
            'r"(.+)-([0-9]{8}\\.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{6})-(\\d+)"',
            'r"(.*)-([0-9]{8}\\.[0-9]{6,})-([0-9]+)"', 'r"(.*)-([0-9]{8,}\\.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{6})"',
            'r"(.*)([0-9]{8}\\.[0-9]{6})-([0-9]+)"'):
    m(s, TS, f"SNAPSHOT_TIMESTAMP = re.compile({new})", SCAN)
m(s, "SNAPSHOT_TIMESTAMP.fullmatch(version) is not None", "SNAPSHOT_TIMESTAMP.match(version) is not None", SCAN)
m(s, "SNAPSHOT_TIMESTAMP.fullmatch(version) is not None", "SNAPSHOT_TIMESTAMP.search(version) is not None", SCAN)
m(s, 'return version[-8:].lower() == "snapshot" or', 'return version[-8:] == "SNAPSHOT" or', SCAN)
m(s, 'return version[-8:].lower() == "snapshot" or', 'return version[-9:].lower() == "snapshot" or', SCAN)
m(s, 'return version[-8:].lower() == "snapshot" or', 'return version[-8:].lower() in ("snapshot", "") or', SCAN)
m(s, 'return version[-8:].lower() == "snapshot" or', 'return "snapshot" in version.lower() or', SCAN)
m(s, '[-8:].lower() == "snapshot" or SNAPSHOT', '[-8:].lower() == "snapshot" and SNAPSHOT', SCAN)
for member in ("project", "parent", "dependency", "plugin", "extension", "path"):
    kept = ", ".join(f'"{x}"' for x in ("project", "parent", "dependency", "plugin", "extension", "path") if x != member)
    m(s, 'VERSION_PARENTS = {"project", "parent", "dependency", "plugin", "extension", "path"}', "VERSION_PARENTS = {" + kept + "}", SCAN)
m(s, 'TOKEN = re.compile(r"[\\s,\\[\\]()]+")', 'TOKEN = re.compile(r"[\\s\\[\\]()]+")', SCAN)
m(s, 'TOKEN = re.compile(r"[\\s,\\[\\]()]+")', 'TOKEN = re.compile(r"[\\s,\\[\\]]+")', SCAN)
m(s, 'TOKEN = re.compile(r"[\\s,\\[\\]()]+")', 'TOKEN = re.compile(r"[\\s,()]+")', SCAN)
m(s, 'TOKEN = re.compile(r"[\\s,\\[\\]()]+")', 'TOKEN = re.compile(r"[,\\[\\]()]+")', SCAN)
m(s, 'FLOATING = {"LATEST", "RELEASE"}', 'FLOATING = {"LATEST"}', SCAN)
m(s, 'FLOATING = {"LATEST", "RELEASE"}', 'FLOATING = {"RELEASE"}', SCAN)
m(s, "    v = version.strip()\n", "    v = version\n", SCAN)
m(s, 'return v in FLOATING or v[:1] in ("[", "(") or "," in v', 'return v[:1] in ("[", "(") or "," in v', SCAN)
m(s, 'return v in FLOATING or v[:1] in ("[", "(") or "," in v', 'return v in FLOATING or v[:1] in ("(") or "," in v', SCAN)
m(s, 'return v in FLOATING or v[:1] in ("[", "(") or "," in v', 'return v in FLOATING or v[:1] in ("[") or "," in v', SCAN)
m(s, 'return v in FLOATING or v[:1] in ("[", "(") or "," in v', 'return v in FLOATING or v[:1] in ("[", "(")', SCAN)
m(s, "    parser.StartDoctypeDeclHandler = refuse\n", "", SCAN)
m(s, "        parser.Parse(data, True)", "        pass", SCAN)
m(s, "        if not el.text:\n            continue\n", "", SCAN)
m(s, '        if "properties" in up:\n            continue\n', "", SCAN)
m(s, "        is_version = local(el.tag) == \"version\" and up[:1] and up[0] in VERSION_PARENTS", "        is_version = local(el.tag) == \"version\"", SCAN)
m(s, "        is_version = local(el.tag) == \"version\" and up[:1] and up[0] in VERSION_PARENTS", "        is_version = False", SCAN)
m(s, "        if is_version and floating(el.text):", "        if floating(el.text):", SCAN)
m(s, "        if is_version and floating(el.text):", "        if False:", SCAN)
m(s, "if \"-SNAPSHOT\" not in el.text and not (is_version and any(\n                is_snapshot(tok) for tok in TOKEN.split(el.text) if tok)):",
  "if False:", SCAN)
m(s, "if \"-SNAPSHOT\" not in el.text and not (is_version and any(\n                is_snapshot(tok) for tok in TOKEN.split(el.text) if tok)):",
  "if \"-SNAPSHOT\" not in el.text and not (is_version and all(\n                is_snapshot(tok) for tok in TOKEN.split(el.text) if tok)):", SCAN)
m(s, "if \"-SNAPSHOT\" not in el.text and not (is_version and any(\n                is_snapshot(tok) for tok in TOKEN.split(el.text) if tok)):",
  "if not (is_version and any(\n                is_snapshot(tok) for tok in TOKEN.split(el.text) if tok)):", SCAN)
m(s, "if \"-SNAPSHOT\" not in el.text and not (is_version and any(\n                is_snapshot(tok) for tok in TOKEN.split(el.text) if tok)):",
  "if \"-SNAPSHOT\" not in el.text and not (any(\n                is_snapshot(tok) for tok in TOKEN.split(el.text) if tok)):", SCAN)
m(s, "        if \"dependency\" in up and \"plugin\" not in up:", "        if \"dependency\" in up:", SCAN)
m(s, "        if \"dependency\" in up and \"plugin\" not in up:", "        if False:", SCAN)
m(s, "        if \"dependency\" in up and \"plugin\" not in up:", "        if \"dependency\" not in up and \"plugin\" not in up:", SCAN)
m(s, "fields = [f.split()[0] for f in raw.split(\":\")[3:] if f.split()]", "fields = [f.split()[0] for f in raw.split(\":\")[4:] if f.split()]", SCAN)
m(s, "fields = [f.split()[0] for f in raw.split(\":\")[3:] if f.split()]", "fields = [f.split()[0] for f in raw.split(\":\")[0:] if f.split()]", SCAN)
m(s, "fields = [f.split()[0] for f in raw.split(\":\")[3:] if f.split()]", "fields = [f.split()[0] for f in raw.split(\":\")[3:]]", SCAN)
m(s, "fields = [f.split()[0] for f in raw.split(\":\")[3:] if f.split()]", "fields = [f for f in raw.split(\":\")[3:] if f.split()]", SCAN)
m(s, 'if "-SNAPSHOT" in raw or any(is_snapshot(f) for f in fields):', "if any(is_snapshot(f) for f in fields):", SCAN)
m(s, 'if "-SNAPSHOT" in raw or any(is_snapshot(f) for f in fields):', 'if "-SNAPSHOT" in raw:', SCAN)
m(s, 'if "-SNAPSHOT" in raw or any(is_snapshot(f) for f in fields):', 'if "-SNAPSHOT" in raw and any(is_snapshot(f) for f in fields):', SCAN)
m(s, 'errors="replace"', 'errors="strict"', SCAN)
m(s, "    except (OSError, ET.ParseError) as exc:", "    except OSError as exc:", SCAN)
m(s, "    if hard:\n", "    if False:\n", SCAN)
m(s, '    if soft or floats:\n', "    if soft:\n", SCAN)
m(s, '    if soft or floats:\n', "    if floats:\n", SCAN)
m(s, '        if a.upload == "true":\n', "        if False:\n", SCAN)
m(s, '        if a.upload == "true":\n', '        if a.upload != "true":\n', SCAN)
m(s, "            if soft:\n                print(\"::error::SNAPSHOT dependencies", "            if True:\n                print(\"::error::SNAPSHOT dependencies", SCAN)
m(s, "            if floats:\n                print(\"::error::Floating versions", "            if True:\n                print(\"::error::Floating versions", SCAN)
m(s, "            if floats:\n                print(\"::error::Floating versions", "            if False:\n                print(\"::error::Floating versions", SCAN)
m(s, "            if soft:\n                print(\"::error::SNAPSHOT dependencies", "            if False:\n                print(\"::error::SNAPSHOT dependencies", SCAN)
m(s, "            return 1\n        print(\"::warning::This dry run", "            return 0\n        print(\"::warning::This dry run", SCAN)
m(s, '        if a.summary:\n', "        if False:\n", SCAN)
m(s, '        if a.summary:\n', "        if True:\n", SCAN)
m(s, 'with open(a.summary, "a", encoding="utf-8") as fh:', 'with open(a.summary, "w", encoding="utf-8") as fh:', SCAN)
m(s, "                if soft:\n                    fh.write", "                if True:\n                    fh.write", SCAN)
m(s, "                if floats:\n                    fh.write", "                if True:\n                    fh.write", SCAN)
m(s, "                if soft:\n                    fh.write", "                if False:\n                    fh.write", SCAN)
m(s, "                if floats:\n                    fh.write", "                if False:\n                    fh.write", SCAN)
m(s, "        return 0\n    print(\"ok", "        return 1\n    print(\"ok", SCAN)
m(s, 'print("\\n".join(hard))', "pass", SCAN)
m(s, 'print("\\n".join(soft + floats))', "pass", SCAN)
m(s, "    return hard, sorted(soft), sorted(floats)", "    return hard, sorted(soft), []", SCAN)
m(s, "    except Exception as exc:\n        print(f\"::error::the SNAPSHOT scan failed", "    except ValueError as exc:\n        print(f\"::error::the SNAPSHOT scan failed", SCAN)

# --- check_auto_publish.py ---------------------------------------------------------------------------------------------
a = "check_auto_publish"
m(a, "    parser.StartDoctypeDeclHandler = refuse\n", "", AUTO)
m(a, "        parser.Parse(data, True)", "        pass", AUTO)
m(a, 'PLUGIN = "central-publishing-maven-plugin"', 'PLUGIN = "central-publishing"', AUTO)
m(a, 'return tag.rsplit("}", 1)[-1]', "return tag", AUTO)
m(a, '        if local(plugin.tag) != "plugin":\n            continue\n', "", AUTO)
m(a, '(c.text or "").strip() == PLUGIN', '(c.text or "") == PLUGIN', AUTO)
m(a, 'local(c.tag) == "artifactId" and', "", AUTO)
m(a, "        for el in plugin.iter():", "        for el in plugin:", AUTO)
m(a, "        plugins += 1\n", "", AUTO)
m(a, 'if local(el.tag) == "autoPublish" and value != "false":\n                problems.append(f"<autoPublish>',
  'if local(el.tag) == "autoPublish" and value.lower() != "false":\n                problems.append(f"<autoPublish>', AUTO)
m(a, 'if local(el.tag) == "autoPublish" and value != "false":\n                problems.append(f"<autoPublish>', "if False:\n                problems.append(f\"<autoPublish>", AUTO)
m(a, 'if local(el.tag) == "waitUntil" and value.lower() != "validated":\n                problems.append(f"<waitUntil>',
  'if local(el.tag) == "waitUntil" and value != "validated":\n                problems.append(f"<waitUntil>', AUTO)
m(a, 'if local(el.tag) == "waitUntil" and value.lower() != "validated":\n                problems.append(f"<waitUntil>',
  'if local(el.tag) == "waitUntil" and value.lower() not in ("validated", "uploaded"):\n                problems.append(f"<waitUntil>', AUTO)
m(a, 'if local(el.tag) == "waitUntil" and value.lower() != "validated":\n                problems.append(f"<waitUntil>', "if False:\n                problems.append(f\"<waitUntil>", AUTO)
m(a, '            value = (el.text or "").strip()\n            if local(el.tag) == "autoPublish" and value != "false":\n                problems.append(f"<properties>',
  '            value = (el.text or "")\n            if local(el.tag) == "autoPublish" and value != "false":\n                problems.append(f"<properties>', AUTO)
m(a, 'if local(el.tag) == "autoPublish" and value != "false":\n                problems.append(f"<properties>', "if False:\n                problems.append(f\"<properties>", AUTO)
m(a, 'if local(el.tag) == "autoPublish" and value != "false":\n                problems.append(f"<properties>',
  'if local(el.tag) == "autoPublish" and value.lower() != "false":\n                problems.append(f"<properties>', AUTO)
m(a, 'if local(el.tag) == "waitUntil" and value.lower() != "validated":\n                problems.append(f"<properties>', "if False:\n                problems.append(f\"<properties>", AUTO)
m(a, 'if local(el.tag) == "waitUntil" and value.lower() != "validated":\n                problems.append(f"<properties>',
  'if local(el.tag) == "waitUntil" and value != "validated":\n                problems.append(f"<properties>', AUTO)
m(a, '        if local(properties.tag) != "properties":\n            continue\n', "", AUTO)
m(a, "        for el in properties:", "        for el in properties.iter():", AUTO)
m(a, "    if problems:\n        return 1", "    if False:\n        return 1", AUTO)
m(a, "    if problems:\n        return 1", "    if problems:\n        return 0", AUTO)
m(a, "    except (OSError, ET.ParseError) as exc:", "    except OSError as exc:", AUTO)
m(a, "    except Exception as exc:\n        print(f\"::error::the auto-publish guard", "    except ValueError as exc:\n        print(f\"::error::the auto-publish guard", AUTO)

# --- check_dry_run_log.py ----------------------------------------------------------------------------------------------
l = "check_dry_run_log"
m(l, "if BEGAN in text:", "if False:", LOG)
m(l, "if SKIPPED not in text:", "if False:", LOG)
m(l, 'BEGAN = "Going to upload"', 'BEGAN = "Going to uploadX"', LOG)
m(l, "Skipping the upload of the bundle at user's request\"", "Skipping the upload of the bundle\"", LOG)
m(l, 'errors="replace"', 'errors="strict"', LOG)
m(l, "except OSError as exc:", "except FileNotFoundError as exc:", LOG)
m(l, "        return 1\n    if BEGAN", "        return 0\n    if BEGAN", LOG)
m(l, "        return 1\n    print(\"ok", "        return 0\n    print(\"ok", LOG)

# --- check_drift.py ----------------------------------------------------------------------------------------------------
d = "check_drift"
m(d, '    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1"}\n    return subprocess.run(["git", "--literal-pathspecs", "-C", repo, *args], capture_output=True, text=True, env=env)',
  '    env = {**os.environ}\n    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=env)', DRIFT)
m(d, "    if not a.generated:\n", "    if False:\n", DRIFT)
m(d, 'shown = a.generated.encode("unicode_escape").decode("ascii")', "shown = a.generated", DRIFT)
m(d, "    if inside.returncode != 0:", "    if False:", DRIFT)
m(d, "    root = os.path.realpath(a.repo)\n    resolved = os.path.realpath(os.path.join(root, a.generated))",
  "    root = os.path.realpath(a.repo)\n    resolved = os.path.join(root, a.generated)", DRIFT)
m(d, "if os.path.commonpath([root, resolved]) != root:", "if False:", DRIFT)
m(d, "if os.path.commonpath([root, resolved]) != root:", "if os.path.commonpath([root, resolved]) == root:", DRIFT)
m(d, "    if not os.path.isdir(resolved):", "    if False:", DRIFT)
m(d, "    if not os.path.isdir(resolved):", "    if not os.path.exists(resolved):", DRIFT)
m(d, "    rel = os.path.relpath(resolved, root)", "    rel = a.generated", DRIFT)
m(d, 'tracked = git(a.repo, "ls-files", "-z", "--", rel)', 'tracked = git(a.repo, "ls-files", "-z", rel)', DRIFT)
m(d, "    if tracked.returncode != 0:", "    if False:", DRIFT)
m(d, "    if not tracked.stdout:", "    if False:", DRIFT)
m(d, '"status", "--porcelain", "--untracked-files=all", "--", rel)', '"status", "--porcelain", "--untracked-files=all", rel)', DRIFT)
m(d, '"status", "--porcelain", "--untracked-files=all", "--", rel)', '"status", "--porcelain", "--", rel)', DRIFT)
m(d, '"status", "--porcelain", "--untracked-files=all", "--", rel)', '"status", "--untracked-files=all", "--", rel)', DRIFT)
m(d, "    if status.returncode != 0:", "    if False:", DRIFT)
m(d, "    if status.stdout.strip():", "    if False:", DRIFT)
m(d, "    if status.stdout.strip():", "    if not status.stdout.strip():", DRIFT)
m(d, 'print(git(a.repo, "diff", "--", rel).stdout.rstrip())', 'print(git(a.repo, "diff", rel).stdout.rstrip())', DRIFT)
m(d, "tail = \" If a deployment was uploaded, DROP it.\" if a.uploaded else \\", "tail = \" If a deployment was uploaded, DROP it.\" if not a.uploaded else \\", DRIFT)
m(d, "        return 1\n    print(f\"ok", "        return 0\n    print(f\"ok", DRIFT)
m(d, "    except Exception as exc:\n        print(f\"::error::the drift check", "    except ValueError as exc:\n        print(f\"::error::the drift check", DRIFT)

# --- check_secrets.py --------------------------------------------------------------------------------------------------
c = "check_secrets"
m(c, 'os.environ.get(var) != "true"', 'os.environ.get(var, "").lower() != "true"', SECRETS)
m(c, 'os.environ.get(var) != "true"', 'os.environ.get(var) == "false"', SECRETS)
m(c, 'os.environ.get(var) != "true"', 'os.environ.get(var, "").strip() != "true"', SECRETS)
m(c, 'os.environ.get(var) != "true"', 'not os.environ.get(var)', SECRETS)
m(c, '    if a.target == "central":', "    if False:", SECRETS)
m(c, '    if a.target == "central":', "    if True:", SECRETS)
m(c, ', ("HAVE_GPG_PASSPHRASE", "GPG_PASSPHRASE")]', "]", SECRETS)
m(c, 'need = [("HAVE_GPG_KEY", "GPG_PRIVATE_KEY"), ', "need = [", SECRETS)
m(c, "    if missing:\n", "    if False:\n", SECRETS)
m(c, 'choices=["central", "github-packages"]', 'choices=["central", "github-packages", "none"]', SECRETS)
m(c, '("HAVE_CENTRAL_USER", "CENTRAL_TOKEN_USERNAME"), ', "", SECRETS)
m(c, ', ("HAVE_CENTRAL_PASSWORD", "CENTRAL_TOKEN_PASSWORD")]', "]", SECRETS)

# --- check_release_readiness.py ----------------------------------------------------------------------------------------
y = "check_release_readiness"
R = READY
m(y, "MAX_ENTRIES = 2000", "MAX_ENTRIES = 2001", R)
m(y, "MAX_ENTRIES = 2000", "MAX_ENTRIES = 1999", R)
m(y, "MAX_ENTRIES = 2000", "MAX_ENTRIES = 200000", R)
m(y, "MAX_TOTAL_BYTES = 256 * 1024 * 1024", "MAX_TOTAL_BYTES = 257 * 1024 * 1024", R)
m(y, "MAX_TOTAL_BYTES = 256 * 1024 * 1024", "MAX_TOTAL_BYTES = 255 * 1024 * 1024", R)
m(y, "MAX_RATIO = 200", "MAX_RATIO = 201", R)
m(y, "MAX_RATIO = 200", "MAX_RATIO = 199", R)
m(y, "MIN_RATIO_BYTES = 1024 * 1024", "MIN_RATIO_BYTES = 1024 * 1024 + 1", R)
m(y, "MIN_RATIO_BYTES = 1024 * 1024", "MIN_RATIO_BYTES = 1024 * 1024 - 1", R)
for ext in (".md5", ".sha1", ".sha256", ".sha512"):
    old = 'CHECKSUMS = {".md5": "md5", ".sha1": "sha1", ".sha256": "sha256", ".sha512": "sha512"}'
    kept = ", ".join(f'"{e}": "{e[1:]}"' for e in (".md5", ".sha1", ".sha256", ".sha512") if e != ext)
    m(y, old, "CHECKSUMS = {" + kept + "}", R)
m(y, '".md5": "md5"', '".md5": "sha1"', R)
m(y, '".sha256": "sha256"', '".sha256": "sha1"', R)
m(y, '".sha512": "sha512"', '".sha512": "sha256"', R)
for suffix in ('"-sources.jar", ', '"-javadoc.jar", ', ', "-tests.jar"'):
    m(y, 'CLASSIFIER_SUFFIXES = ("-sources.jar", "-javadoc.jar", "-tests.jar")',
      'CLASSIFIER_SUFFIXES = ("-sources.jar", "-javadoc.jar", "-tests.jar")'.replace(suffix, "", 1), R)
TSR = 'TIMESTAMPED = re.compile(r"(.*)-([0-9]{8}\\.[0-9]{6})-([0-9]+)")'
for new in ('r"(.*)-([0-9]{7}\\.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{5})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{6})-([0-9]*)"',
            'r"(.+)-([0-9]{8}\\.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{6})"'):
    m(y, TSR, f"TIMESTAMPED = re.compile({new})", R)
m(y, 'return version[-8:].lower() == "snapshot" or TIMESTAMPED.fullmatch(version) is not None', 'return version[-8:] == "SNAPSHOT" or TIMESTAMPED.fullmatch(version) is not None', R)
m(y, 'return version[-8:].lower() == "snapshot" or TIMESTAMPED.fullmatch(version) is not None', 'return version[-8:].lower() == "snapshot"', R)
m(y, 'return version[-8:].lower() == "snapshot" or TIMESTAMPED.fullmatch(version) is not None', 'return TIMESTAMPED.fullmatch(version) is not None', R)
m(y, "TIMESTAMPED.fullmatch(version) is not None", "TIMESTAMPED.match(version) is not None", R)
for cat in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs"):
    allc = ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")
    kept = ", ".join(f'"{x}"' for x in allc if x != cat)
    m(y, 'return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")', f"return unicodedata.category(ch) in ({kept})", R)
m(y, 'return "".join(f"\\\\u{ord(c):04x}" if unusual(c) else c for c in name)', "return name", R)
m(y, "    parser.StartDoctypeDeclHandler = refuse\n", "", R)
m(y, "        parser.Parse(data, True)", "        pass", R)
m(y, 'if c.tag.rsplit("}", 1)[-1] == name:', "if c.tag == name:", R)
m(y, 'value = (c.text or "").strip() if c is not None else ""', 'value = (c.text or "") if c is not None else ""', R)
m(y, "    return (text(root, \"groupId\") or text(parent, \"groupId\"), text(root, \"artifactId\"),\n            text(root, \"version\") or text(parent, \"version\"))",
  "    return (text(root, \"groupId\"), text(root, \"artifactId\"),\n            text(root, \"version\") or text(parent, \"version\"))", R)
m(y, "    return (text(root, \"groupId\") or text(parent, \"groupId\"), text(root, \"artifactId\"),\n            text(root, \"version\") or text(parent, \"version\"))",
  "    return (text(root, \"groupId\") or text(parent, \"groupId\"), text(root, \"artifactId\"),\n            text(root, \"version\"))", R)
m(y, "    return (text(root, \"groupId\") or text(parent, \"groupId\"), text(root, \"artifactId\"),\n            text(root, \"version\") or text(parent, \"version\"))",
  "    return (text(parent, \"groupId\") or text(root, \"groupId\"), text(root, \"artifactId\"),\n            text(root, \"version\") or text(parent, \"version\"))", R)
m(y, '    body = name[:-1] if directory else name', '    body = name', R)
m(y, 'if not body or "\\\\" in body or any(unusual(c) for c in body):', 'if not body or any(unusual(c) for c in body):', R)
m(y, 'if not body or "\\\\" in body or any(unusual(c) for c in body):', 'if not body or "\\\\" in body:', R)
for seg in ('""', '"."', '".."'):
    kept = ", ".join(x for x in ('""', '"."', '".."') if x != seg)
    m(y, 'if any(s in ("", ".", "..") for s in segments):', f"if any(s in ({kept},) for s in segments):", R)
m(y, "return stat.S_ISREG(os.lstat(path).st_mode)", "return not stat.S_ISDIR(os.lstat(path).st_mode)", R)
m(y, "return stat.S_ISREG(os.lstat(path).st_mode)", "return True", R)
m(y, "    except OSError:\n        return False\n\n\ndef sha256_of", "    except OSError:\n        return True\n\n\ndef sha256_of", R)
m(y, "    except Exception as exc:\n        print(f\"::error::release-readiness failed unexpectedly", "    except ValueError as exc:\n        print(f\"::error::release-readiness failed unexpectedly", R)
m(y, 'selected = [n for n in names if n.endswith((".jar", ".pom", ".asc"))]', 'selected = [n for n in names if n.endswith((".jar", ".pom"))]', R)
m(y, 'selected = [n for n in names if n.endswith((".jar", ".pom", ".asc"))]', 'selected = [n for n in names if n.endswith((".jar", ".asc"))]', R)
m(y, 'selected = [n for n in names if n.endswith((".jar", ".pom", ".asc"))]', 'selected = [n for n in names if n.endswith((".pom", ".asc"))]', R)
m(y, "             and not stat.S_ISDIR(os.lstat(os.path.join(t, n)).st_mode)]", "             ]", R)
m(y, "    if not mains:\n", "    if False:\n", R)
m(y, '            return subprocess.run([a.gpg, "--verify", asc, f], stdout=subprocess.DEVNULL,', '            return subprocess.run([a.gpg, "--verify", f, asc], stdout=subprocess.DEVNULL,', R)
m(y, "stderr=subprocess.DEVNULL).returncode == 0", "stderr=subprocess.DEVNULL).returncode != 127", R)
m(y, "        except OSError:\n            return False\n\n    allowed", "        except OSError:\n            return True\n\n    allowed", R)
m(y, "        allowed.update(files)\n", "", R)
m(y, '        allowed.update(f + ".asc" for f in files)\n', "", R)
m(y, '        if is_snapshot(base):\n', "        if False:\n", R)
m(y, "            if os.path.islink(path):\n", "            if False:\n", R)
m(y, "            elif want != main_jar and not os.path.lexists(path):", "            elif False:", R)
m(y, "            elif os.path.lexists(path) and not regular(path):", "            elif False:", R)
m(y, "            elif os.path.lexists(path):\n                intact.append(want)", "            elif False:\n                intact.append(want)", R)
m(y, '        if f"{base}-javadoc.jar" in intact:', "        if False:", R)
m(y, 'if "index.html" not in zf.namelist():', "if False:", R)
m(y, 'if "index.html" not in zf.namelist():', 'if not any(n.endswith("index.html") for n in zf.namelist()):', R)
m(y, "            except zipfile.BadZipFile:\n                err(f\"{shown_base}-javadoc.jar is not a zip file\")", "            except KeyError:\n                err(f\"{shown_base}-javadoc.jar is not a zip file\")", R)
m(y, '        if f"{base}.pom" in intact:', "        if False:", R)
m(y, "            except (OSError, ET.ParseError) as exc:\n                err(f\"{shown_base}.pom", "            except OSError as exc:\n                err(f\"{shown_base}.pom", R)
m(y, "if artifact and version and f\"{artifact}-{version}\" != base:", "if False:", R)
m(y, "if artifact and version and f\"{artifact}-{version}\" != base:", "if artifact and version and f\"{artifact}-{version}\" == base:", R)
m(y, "if artifact and version and f\"{artifact}-{version}\" != base:", "if version and f\"{artifact}-{version}\" != base:", R)
m(y, "if artifact and version and f\"{artifact}-{version}\" != base:", "if artifact and f\"{artifact}-{version}\" != base:", R)
m(y, "            if version and is_snapshot(version):", "            if False:", R)
m(y, "            if version and is_snapshot(version):", "            if is_snapshot(version):", R)
m(y, "        built[base] = coordinate\n", "        built[base] = (None, None, None)\n", R)
m(y, "            if os.path.islink(asc):", "            if False:", R)
m(y, "            elif not regular(asc):", "            elif False:", R)
m(y, "            elif not good_signature(asc, os.path.join(t, f)):", "            elif False:", R)
m(y, "        if len(findings) == before:", "        if True:", R)
m(y, "        if len(findings) == before:", "        if False:", R)
m(y, "        if n not in allowed:\n            err(", "        if False:\n            err(", R)
m(y, "        if n.endswith((\".jar\", \".pom\", \".asc\")) and any(unusual(c) for c in n):", "        if False:", R)
m(y, "        if n.endswith((\".jar\", \".pom\", \".asc\")) and any(unusual(c) for c in n):", "        if any(unusual(c) for c in n):", R)
m(y, "        if n.endswith((\".jar\", \".pom\", \".asc\")) and any(unusual(c) for c in n):", "        if n.endswith((\".jar\", \".pom\")) and any(unusual(c) for c in n):", R)
m(y, '    if a.expect_bundle == "true":', "    if False:", R)
m(y, '    if a.expect_bundle == "true":', '    if a.expect_bundle != "true":', R)
m(y, "    if a.stage:\n", "    if False:\n", R)
m(y, "sorted(f for f in allowed if regular(os.path.join(t, f))),", "sorted(allowed),", R)
m(y, "bundle_path if bundle_ok else None, err)", "bundle_path, err)", R)
m(y, "bundle_path if bundle_ok else None, err)", "None, err)", R)
m(y, "        tail = \"; if a deployment was uploaded, DROP it in the portal.\" if a.uploaded else \"\"", "        tail = \"; if a deployment was uploaded, DROP it in the portal.\" if not a.uploaded else \"\"", R)
m(y, "    if findings:\n", "    if False:\n", R)
m(y, "        return 1\n    print(\"release-readiness: ok\")", "        return 0\n    print(\"release-readiness: ok\")", R)
m(y, "    if os.path.lexists(dest) and (os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "    if False:", R)
m(y, "os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "not os.path.isdir(dest) or os.listdir(dest)):", R)
m(y, "os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "os.path.islink(dest) or os.listdir(dest)):", R)
m(y, "os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "os.path.islink(dest) or not os.path.isdir(dest)):", R)
m(y, "    if os.path.lexists(dest) and (", "    if (", R)
m(y, "os.makedirs(dest, mode=0o700, exist_ok=True)", "os.makedirs(dest, mode=0o755, exist_ok=True)", R)
m(y, "os.makedirs(dest, mode=0o700, exist_ok=True)", "os.makedirs(dest, mode=0o700, exist_ok=False)", R)
m(y, 'os.makedirs(os.path.join(dest, "central-publishing"), mode=0o700, exist_ok=True)', 'os.makedirs(os.path.join(dest, "central-publishing"), mode=0o755, exist_ok=True)', R)
m(y, '    if bundle:\n        os.makedirs', '    if False:\n        os.makedirs', R)
m(y, "os.O_RDONLY | os.O_NOFOLLOW", "os.O_RDONLY", R)
m(y, '                if not stat.S_ISREG(os.fstat(fin.fileno()).st_mode):\n                    raise OSError("not a regular file")', "                if False:\n                    raise OSError(\"not a regular file\")", R)
m(y, 'with open(dst, "xb") as fout:', 'with open(dst, "wb") as fout:', R)
m(y, "        except OSError as exc:\n            err(f\"{shown(src)} cannot be staged", "        except ValueError as exc:\n            err(f\"{shown(src)} cannot be staged", R)
m(y, "if os.path.islink(directory) or os.path.islink(bundle) or not os.path.lexists(bundle):", "if os.path.islink(bundle) or not os.path.lexists(bundle):", R)
m(y, "if os.path.islink(directory) or os.path.islink(bundle) or not os.path.lexists(bundle):", "if os.path.islink(directory) or not os.path.lexists(bundle):", R)
m(y, "if os.path.islink(directory) or os.path.islink(bundle) or not os.path.lexists(bundle):", "if os.path.islink(directory) or os.path.islink(bundle):", R)
m(y, "    if not regular(bundle):\n", "    if False:\n", R)
m(y, "    except zipfile.BadZipFile:\n        err(f\"{shown(bundle)} is not a zip file\")", "    except KeyError:\n        err(f\"{shown(bundle)} is not a zip file\")", R)
m(y, "        if len(infos) > MAX_ENTRIES:", "        if len(infos) >= MAX_ENTRIES:", R)
m(y, "        if len(infos) > MAX_ENTRIES:", "        if False:", R)
m(y, "        if total > MAX_TOTAL_BYTES:", "        if total >= MAX_TOTAL_BYTES:", R)
m(y, "        if total > MAX_TOTAL_BYTES:", "        if False:", R)
m(y, "        total = sum(i.file_size for i in infos)", "        total = max(i.file_size for i in infos)", R)
m(y, "            if i.file_size >= MIN_RATIO_BYTES and i.file_size > MAX_RATIO * max(i.compress_size, 1):", "            if i.file_size > MIN_RATIO_BYTES and i.file_size > MAX_RATIO * max(i.compress_size, 1):", R)
m(y, "            if i.file_size >= MIN_RATIO_BYTES and i.file_size > MAX_RATIO * max(i.compress_size, 1):", "            if i.file_size >= MIN_RATIO_BYTES and i.file_size >= MAX_RATIO * max(i.compress_size, 1):", R)
m(y, "            if i.file_size >= MIN_RATIO_BYTES and i.file_size > MAX_RATIO * max(i.compress_size, 1):", "            if i.file_size >= MIN_RATIO_BYTES or i.file_size > MAX_RATIO * max(i.compress_size, 1):", R)
m(y, "            if i.file_size >= MIN_RATIO_BYTES and i.file_size > MAX_RATIO * max(i.compress_size, 1):", "            if i.file_size >= MIN_RATIO_BYTES and i.file_size > MAX_RATIO * i.compress_size * 1000:", R)
m(y, "            err(f\"central bundle: {len(infos)} entries exceed the limit of {MAX_ENTRIES}\")\n            return False", "            err(f\"central bundle: {len(infos)} entries exceed the limit of {MAX_ENTRIES}\")\n            return True", R)
m(y, "                err(f\"central bundle: {shown(i.filename)} expands by more than {MAX_RATIO} times\")\n                return False", "                err(f\"central bundle: {shown(i.filename)} expands by more than {MAX_RATIO} times\")\n                return True", R)
m(y, "        judge_bundle(t, zf, infos, built, err, good_signature)\n        return True", "        judge_bundle(t, zf, infos, built, err, good_signature)\n        return False", R)
m(y, "    for name in sorted(n for n, c in counts.items() if c > 1):", "    for name in sorted(n for n, c in counts.items() if c > 2):", R)
m(y, "    for name in sorted(n for n, c in counts.items() if c > 1):", "    for name in sorted(n for n, c in counts.items() if c >= 1):", R)
m(y, '        if name.endswith("/"):\n            if valid_segments(name, True) is None:', '        if False:\n            if valid_segments(name, True) is None:', R)
m(y, "            if valid_segments(name, True) is None:", "            if False:", R)
m(y, "        if (i.external_attr >> 16) & 0o170000 == 0o120000:", "        if False:", R)
m(y, "        if (i.external_attr >> 16) & 0o170000 == 0o120000:", "        if (i.external_attr >> 16) & 0o170000 != 0o120000:", R)
m(y, "        if (i.external_attr >> 16) & 0o170000 == 0o120000:", "        if (i.external_attr >> 16) & 0o120000 == 0o120000:", R)
m(y, "        if segments is None or len(segments) < 4:", "        if segments is None or len(segments) < 3:", R)
m(y, "        if segments is None or len(segments) < 4:", "        if segments is None or len(segments) < 5:", R)
m(y, "        if segments is None or len(segments) < 4:", "        if segments is None:", R)
m(y, '        stem = f"{parts[-2]}-{parts[-1]}"', '        stem = f"{parts[-1]}"', R)
m(y, '        if f"{d}/{stem}.pom" in files and filename.startswith((stem + ".", stem + "-")):', '        if filename.startswith((stem + ".", stem + "-")):', R)
m(y, '        if f"{d}/{stem}.pom" in files and filename.startswith((stem + ".", stem + "-")):', '        if f"{d}/{stem}.pom" in files:', R)
m(y, '        if f"{d}/{stem}.pom" in files and filename.startswith((stem + ".", stem + "-")):', '        if f"{d}/{stem}.pom" in files and filename.startswith(stem):', R)
m(y, '        if f"{d}/{stem}.pom" in files and filename.startswith((stem + ".", stem + "-")):', '        if f"{d}/{stem}.pom" in files and filename.startswith((stem + "-",)):', R)
m(y, '        if f"{d}/{stem}.pom" in files and filename.startswith((stem + ".", stem + "-")):', '        if f"{d}/{stem}.pom" in files and filename.startswith((stem + ".",)):', R)
m(y, "        if stem not in built:\n", "        if False:\n", R)
m(y, "        elif len(where) > 1:\n", "        elif False:\n", R)
m(y, '            if group and "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):', "            if False:", R)
m(y, '            if group and "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):', '            if "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):', R)
m(y, '            if group and "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):', '            if group and "/".join(where[0].split("/")[:-1]) != group.replace(".", "/"):', R)
m(y, '            if group and "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):', '            if group and "/".join(where[0].split("/")[:-2]) != group:', R)
m(y, '            if group and "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):', '            if group and "/".join(where[0].split("/")[:-2]).lower() != group.replace(".", "/").lower():', R)
m(y, '            if group and "/".join(where[0].split("/")[:-2]) != group.replace(".", "/"):', '            if group and not "/".join(where[0].split("/")[:-2]).startswith(group.replace(".", "/")):', R)
m(y, "        if stem not in by_stem:\n            err", "        if False:\n            err", R)
m(y, '        for suffix in (".pom", ".jar", "-sources.jar", "-javadoc.jar"):', '        for suffix in (".jar", "-sources.jar", "-javadoc.jar"):', R)
m(y, '        for suffix in (".pom", ".jar", "-sources.jar", "-javadoc.jar"):', '        for suffix in (".pom", "-sources.jar", "-javadoc.jar"):', R)
m(y, '        for suffix in (".pom", ".jar", "-sources.jar", "-javadoc.jar"):', '        for suffix in (".pom", ".jar", "-javadoc.jar"):', R)
m(y, '        for suffix in (".pom", ".jar", "-sources.jar", "-javadoc.jar"):', '        for suffix in (".pom", ".jar", "-sources.jar"):', R)
m(y, '            for extra in ("", ".asc"):', '            for extra in (".asc",):', R)
m(y, '            for extra in ("", ".asc"):', '            for extra in ("",):', R)
m(y, "        if name.rpartition(\"/\")[0] in dirs and regular(counterpart):", "        if regular(counterpart):", R)
m(y, "        if name.rpartition(\"/\")[0] in dirs and regular(counterpart):", "        if name.rpartition(\"/\")[0] in dirs:", R)
m(y, "            if digest_of(zf, files[name]) != sha256_of(counterpart):", "            if digest_of(zf, files[name]) == sha256_of(counterpart):", R)
m(y, "            if digest_of(zf, files[name]) != sha256_of(counterpart):", "            if False:", R)
m(y, "            if name.rpartition(\"/\")[0] not in dirs:\n                continue", "            if False:\n                continue", R)
m(y, "            if name.endswith(\".asc\"):\n                subject", "            if False:\n                subject", R)
m(y, "                if subject not in files:\n                    err(f\"central bundle: {shown(name)} signs", "                if False:\n                    err(f\"central bundle: {shown(name)} signs", R)
m(y, "                for member in (name, subject):", "                for member in (subject, name):", R)
m(y, "                if not good_signature(pair[0], pair[1]):", "                if not good_signature(pair[1], pair[0]):", R)
m(y, "                if not good_signature(pair[0], pair[1]):", "                if False:", R)
m(y, "                    if subject not in files:\n                        err(f\"central bundle: {shown(name)} is a checksum", "                    if False:\n                        err(f\"central bundle: {shown(name)} is a checksum", R)
m(y, "                    h = hashlib.new(algorithm)", "                    h = hashlib.new(\"sha1\")", R)
m(y, "stated = src.read(4096).decode(\"ascii\", \"replace\").split()", "stated = src.read(2).decode(\"ascii\", \"replace\").split()", R)
m(y, "if not stated or stated[0].lower() != h.hexdigest():", "if not stated or stated[0] != h.hexdigest():", R)
m(y, "if not stated or stated[0].lower() != h.hexdigest():", "if stated[0].lower() != h.hexdigest():", R)
m(y, "if not stated or stated[0].lower() != h.hexdigest():", "if False:", R)
m(y, "if not stated or stated[0].lower() != h.hexdigest():", "if not stated or stated[-1].lower() != h.hexdigest():", R)
m(y, "    finally:\n        shutil.rmtree(scratch, ignore_errors=True)", "    finally:\n        pass", R)

# --- remove_signing_key.py ---------------------------------------------------------------------------------------------
k = "remove_signing_key"
for cat in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs"):
    allc = ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")
    kept = ", ".join(f'"{x}"' for x in allc if x != cat)
    m(k, 'return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")', f"return unicodedata.category(ch) in ({kept})", REMOVE)
m(k, "    if os.path.islink(path):\n        os.unlink(path)", "    if False:\n        os.unlink(path)", REMOVE)
m(k, "    elif os.path.lexists(path):\n        shutil.rmtree(path, ignore_errors=True)", "    elif False:\n        shutil.rmtree(path, ignore_errors=True)", REMOVE)
m(k, "    if problems:\n        cleanup(a)\n        return 1", "    if problems:\n        return 1", REMOVE)
m(k, "    if problems:\n        cleanup(a)\n        return 1", "    if problems:\n        cleanup(a)\n        return 0", REMOVE)
m(k, "                if path == a.public_key:\n                    os.remove(path)", "                if path == a.public_key:\n                    pass", REMOVE)
m(k, "                else:\n                    remove_tree(path)", "                else:\n                    pass", REMOVE)
m(k, "    for path in (a.verify_home, a.public_key):", "    for path in (a.public_key,):", REMOVE)
m(k, "    for path in (a.verify_home, a.public_key):", "    for path in (a.verify_home,):", REMOVE)
m(k, "    if not any(unusual(c) for c in a.secret_home) and not os.path.islink(a.secret_home):\n        shutil.rmtree(a.secret_home, ignore_errors=True)", "    pass", REMOVE)
m(k, "    for flag in (\"secret_home\", \"verify_home\", \"public_key\", \"env_file\"):", "    for flag in (\"verify_home\", \"public_key\", \"env_file\"):", REMOVE)
m(k, "    for flag in (\"secret_home\", \"verify_home\", \"public_key\", \"env_file\"):", "    for flag in (\"secret_home\", \"public_key\", \"env_file\"):", REMOVE)
m(k, "    for flag in (\"secret_home\", \"verify_home\", \"public_key\", \"env_file\"):", "    for flag in (\"secret_home\", \"verify_home\", \"env_file\"):", REMOVE)
m(k, "    for flag in (\"secret_home\", \"verify_home\", \"public_key\", \"env_file\"):", "    for flag in (\"secret_home\", \"verify_home\", \"public_key\"):", REMOVE)
m(k, "        bad = [c for c in getattr(a, flag) if unusual(c)]\n        if bad:", "        bad = [c for c in getattr(a, flag) if unusual(c)]\n        if False:", REMOVE)
m(k, '    if problems and any("--secret-home" in m for m in problems):\n        return', "    if False:\n        return", REMOVE)
m(k, "    if os.path.islink(a.secret_home):\n        fail(", "    if False:\n        fail(", REMOVE)
m(k, "    elif os.path.isdir(a.secret_home):\n        try:", "    elif False:\n        try:", REMOVE)
m(k, '[a.gpgconf, "--kill", "gpg-agent"]', '[a.gpgconf, "--reload", "gpg-agent"]', REMOVE)
m(k, 'env={**os.environ, "GNUPGHOME": a.secret_home},\n                           stdout=subprocess.DEVNULL', 'env={**os.environ, "GNUPGHOME": a.verify_home},\n                           stdout=subprocess.DEVNULL', REMOVE)
m(k, "        except OSError:\n            pass\n        shutil.rmtree(a.secret_home, ignore_errors=True)\n    if problems:", "        except ValueError:\n            pass\n        shutil.rmtree(a.secret_home, ignore_errors=True)\n    if problems:", REMOVE)
m(k, "        shutil.rmtree(a.secret_home, ignore_errors=True)\n    if problems:\n        return", "        pass\n    if problems:\n        return", REMOVE)
m(k, "        shutil.rmtree(a.secret_home, ignore_errors=True)\n    if problems:\n        return", "        shutil.rmtree(a.secret_home, ignore_errors=True)\n    if False:\n        return", REMOVE)
m(k, "if os.path.isfile(a.public_key) and os.path.getsize(a.public_key) > 0:", "if os.path.isfile(a.public_key) and os.path.getsize(a.public_key) >= 0:", REMOVE)
m(k, "if os.path.isfile(a.public_key) and os.path.getsize(a.public_key) > 0:", "if False:", REMOVE)
m(k, 'inspect = tempfile.mkdtemp(prefix="gnupg-inspect-")', 'inspect = a.verify_home', REMOVE)
m(k, '[a.gpg, "--batch", "--show-keys", "--with-colons", a.public_key]', '[a.gpg, "--batch", "--show-keys", a.public_key]', REMOVE)
m(k, '[a.gpg, "--batch", "--show-keys", "--with-colons", a.public_key]', '[a.gpg, "--show-keys", "--with-colons", a.public_key]', REMOVE)
m(k, 'env={**os.environ, "GNUPGHOME": inspect}', 'env={**os.environ, "GNUPGHOME": a.secret_home}', REMOVE)
m(k, "        finally:\n            shutil.rmtree(inspect, ignore_errors=True)", "        finally:\n            pass", REMOVE)
m(k, "        if shown.returncode != 0:", "        if False:", REMOVE)
m(k, "        if shown.returncode != 0:", "        if shown.returncode == 0:", REMOVE)
m(k, 'elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):', "elif False:", REMOVE)
m(k, 'elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):', 'elif any(ln.split(":", 1)[0] in ("ssb",) for ln in shown.stdout.splitlines()):', REMOVE)
m(k, 'elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):', 'elif any(ln.split(":", 1)[0] in ("sec",) for ln in shown.stdout.splitlines()):', REMOVE)
m(k, 'elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):', 'elif any(ln.startswith(("sec", "ssb")) for ln in shown.stdout.splitlines()[:1]):', REMOVE)
m(k, 'elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):', 'elif any(ln.startswith("sec") for ln in shown.stdout.splitlines()):', REMOVE)
m(k, '            os.makedirs(a.verify_home, mode=0o700, exist_ok=True)\n            os.chmod(a.verify_home, 0o700)\n            done', '            os.makedirs(a.verify_home, mode=0o700, exist_ok=True)\n            done', REMOVE)
m(k, '[a.gpg, "--batch", "--import", a.public_key], env=verify_env', '[a.gpg, "--batch", "--import", a.public_key + ".x"], env=verify_env', REMOVE)
m(k, '[a.gpg, "--batch", "--import", a.public_key], env=verify_env', '[a.gpg, "--batch", "--import", a.public_key], env={**os.environ, "GNUPGHOME": a.secret_home}', REMOVE)
m(k, "            if done.returncode != 0:", "            if False:", REMOVE)
m(k, "    try:\n        os.remove(a.public_key)\n    except FileNotFoundError:\n        pass", "    try:\n        pass\n    except FileNotFoundError:\n        pass", REMOVE)
m(k, "    try:\n        os.remove(a.public_key)\n    except FileNotFoundError:\n        pass\n    if problems:\n        return", "    try:\n        os.remove(a.public_key)\n    except FileNotFoundError:\n        pass\n    if False:\n        return", REMOVE)
m(k, '    os.makedirs(a.verify_home, mode=0o700, exist_ok=True)\n    os.chmod(a.verify_home, 0o700)\n    if os.path.lexists', '    os.makedirs(a.verify_home, mode=0o700, exist_ok=True)\n    if os.path.lexists', REMOVE)
m(k, "    if os.path.lexists(a.secret_home):\n        fail(", "    if False:\n        fail(", REMOVE)
m(k, '"--list-secret-keys", "--with-colons"', '"--list-keys", "--with-colons"', REMOVE)
m(k, "    secret = [ln for ln in listed.stdout.splitlines() if ln.split(\":\", 1)[0] in (\"sec\", \"ssb\")]", "    secret = [ln for ln in listed.stdout.splitlines() if ln.split(\":\", 1)[0] in (\"sec\",)]", REMOVE)
m(k, "    secret = [ln for ln in listed.stdout.splitlines() if ln.split(\":\", 1)[0] in (\"sec\", \"ssb\")]", "    secret = [ln for ln in listed.stdout.splitlines() if ln.split(\":\", 1)[0] in (\"ssb\",)]", REMOVE)
m(k, "if listed.returncode not in (0, 2) or secret:", "if listed.returncode not in (0, 2):", REMOVE)
m(k, "if listed.returncode not in (0, 2) or secret:", "if secret:", REMOVE)
m(k, "if listed.returncode not in (0, 2) or secret:", "if listed.returncode not in (0, 1, 2) or secret:", REMOVE)
m(k, "if listed.returncode not in (0, 2) or secret:", "if listed.returncode not in (0,) or secret:", REMOVE)
m(k, "    if problems:\n        return\n\n    with open(a.env_file", "    if False:\n        return\n\n    with open(a.env_file", REMOVE)
m(k, 'with open(a.env_file, "a", encoding="utf-8") as fh:', 'with open(a.env_file, "w", encoding="utf-8") as fh:', REMOVE)
m(k, 'fh.write(f"GNUPGHOME={a.verify_home}\\n")', 'fh.write(f"GNUPGHOME={a.verify_home}")', REMOVE)
m(k, 'fh.write(f"GNUPGHOME={a.verify_home}\\n")', 'fh.write(f"GNUPGHOME={a.secret_home}\\n")', REMOVE)
m(k, "    except Exception as exc:\n        fail(f\"the key removal failed unexpectedly", "    except ValueError as exc:\n        fail(f\"the key removal failed unexpectedly", REMOVE)
m(k, "{' '.join(str(exc).split())}).\")", "{exc}).\")", REMOVE)

# --- run_caps_release_tests.py -----------------------------------------------------------------------------------------
q = "../run_caps_release_tests"
m(q, "    if n == 0:", "    if False:", RUNNER)
m(q, "return 0 if result.wasSuccessful() else 1", "return 0", RUNNER)
m(q, 'pattern="test*.py"', 'pattern="tst*.py"', RUNNER)
m(q, "return 0 if result.wasSuccessful() else 1", "return 0 if not result.failures else 1", RUNNER)
m(q, "        return 1\n    result", "        return 0\n    result", RUNNER)
m(q, 'start = os.path.join(ap.parse_args().root, "tests", "caps_release")', 'start = os.path.join(ap.parse_args().root, "tests")', RUNNER)
