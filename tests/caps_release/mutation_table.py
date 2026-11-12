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
      "test_resolve_release.Targets",
      "test_resolve_release.ControlCharacters.test_every_control_character_in_every_field_in_process",
      "test_resolve_release.ControlCharacters.test_undecodable_byte_is_refused_by_the_subprocess_and_in_process",
      "test_resolve_release.ControlCharacters.test_two_key_value_lines_cannot_be_smuggled_through_the_output_file",
      "test_resolve_release.ControlCharacters.test_unicode_separators_and_bidi_cannot_become_a_version",
      "test_ascii_versions.Resolve", "test_timeouts.Gh", "test_timeouts.Bounds"] + UNEXPECTED
PROFILE = ["test_xml_bounds.Readers", "test_xml_bounds.Scripts", "test_release_profile", "test_pom_adversarial.MalformedPoms",
           "test_pom_adversarial.Doctype", "test_pom_scripts.XmlHostile"] + UNEXPECTED
VERSION = ["test_xml_bounds.Readers", "test_xml_bounds.Scripts", "test_pom_scripts.PomVersion", "test_pom_adversarial.MalformedPoms", "test_pom_adversarial.Doctype", "test_pom_scripts.XmlHostile"] + UNEXPECTED
SCAN = ["test_xml_bounds.Readers", "test_xml_bounds.Scripts", "test_ascii_versions.Scan", "test_pom_scripts.ScanSnapshots", "test_pom_adversarial.ScanGaps", "test_pom_adversarial.MalformedPoms", "test_pom_adversarial.SnapshotVersions", "test_pom_adversarial.FloatingVersions",
        "test_pom_adversarial.MavenRule", "test_pom_adversarial.Doctype", "test_pom_scripts.XmlHostile",
        "test_unexpected.Seams.test_an_unwritable_summary_is_one_error_line_for_the_snapshot_scan"] + UNEXPECTED
DRIFT = ["test_drift.Drift", "test_timeouts.Git", "test_timeouts.Bounds", "test_unexpected.Usage"] + UNEXPECTED
SECRETS = ["test_secrets", "test_unexpected.Usage"] + UNEXPECTED
READY = ["test_release_readiness", "test_readiness_adversarial", "test_readiness_closed_set", "test_staging_binding",
         "test_gate_internals", "test_unexpected.Readiness", "test_unexpected.Usage", "test_xml_bounds.Gate", "test_xml_bounds.Readers",
         "test_timeouts.Bounds", "test_timeouts.GateGpg", "test_ascii_versions.Gate", "test_pom_adversarial.MavenRule"] + UNEXPECTED
REMOVE = ["test_remove_signing_key.Removal", "test_key_removal_adversarial.Inspection", "test_key_removal_adversarial.HostilePaths",
          "test_key_removal_adversarial.Real", "test_unexpected.Injected.test_key_removal_ends_an_unexpected_exception_with_one_line_and_cleans_up",
          "test_key_removal_finally.PathCharacters", "test_key_removal_finally.Links", "test_key_removal_finally.Endings",
          "test_literal_paths", "test_verify_home_link", "test_timeouts.KeyRemoval", "test_timeouts.KeyBounds"]
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

# --- check_dry_run_log.py ----------------------------------------------------------------------------------------------

m(s, 'return version[-8:].upper().lower() == "snapshot" or', 'return version[-8:] == "SNAPSHOT" or', SCAN)
m(s, 'return version[-8:].upper().lower() == "snapshot" or', 'return version[-8:].lower() == "snapshot" or', SCAN)
m(s, 'return version[-8:].upper().lower() == "snapshot" or', 'return version[-9:].upper().lower() == "snapshot" or', SCAN)
m(s, 'return version[-8:].upper().lower() == "snapshot" or', 'return "snapshot" in version.upper().lower() or', SCAN)
m(s, '[-8:].upper().lower() == "snapshot" or SNAPSHOT', '[-8:].upper().lower() == "snapshot" and SNAPSHOT', SCAN)
m(s, "MAX_XML_BYTES = 16 * 1024 * 1024", "MAX_XML_BYTES = 16 * 1024 * 1024 + 1", SCAN)
m(s, "MAX_XML_DEPTH = 200", "MAX_XML_DEPTH = 201", SCAN)
m(s, "MAX_XML_DEPTH = 200", "MAX_XML_DEPTH = 199", SCAN)
m(s, "        if depth > MAX_XML_DEPTH:", "        if False:", SCAN)
m(s, "        nonlocal depth\n        depth -= 1", "        nonlocal depth\n        pass", SCAN)
m(s, '        if local(el.tag) == "version" and not el.text.isascii():', "        if False:", SCAN)
m(s, '        if local(el.tag) == "version" and not el.text.isascii():', '        if local(el.tag) == "version" and el.text.isascii():', SCAN)
m(s, '        if local(el.tag) == "version" and not el.text.isascii():', '        if local(el.tag) == "version" and not el.text.strip().isascii() and False:', SCAN)
m(s, "            if not all(f.isascii() for f in fields):", "            if False:", SCAN)
m(s, "            if not all(f.isascii() for f in fields):", "            if not any(f.isascii() for f in fields):", SCAN)
m(s, "            if not all(f.isascii() for f in fields):", "            if not all(f.isascii() for f in fields[1:]):", SCAN)

# --- check_drift.py ----------------------------------------------------------------------------------------------------
d = "check_drift"
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
m(d, "        return 1\n    print(f\"ok", "        return 0\n    print(f\"ok", DRIFT)
m(d, "    except Exception as exc:\n        print(f\"::error::the drift check", "    except ValueError as exc:\n        print(f\"::error::the drift check", DRIFT)

# --- check_secrets.py --------------------------------------------------------------------------------------------------
c = "check_secrets"

m("check_drift", "GIT_TIMEOUT = 300", "GIT_TIMEOUT = 301", DRIFT)
m("check_drift", "GIT_TIMEOUT = 300", "GIT_TIMEOUT = 30", DRIFT)
m("check_drift", "                              timeout=GIT_TIMEOUT)\n    except subprocess.TimeoutExpired:", "                              )\n    except subprocess.TimeoutExpired:", DRIFT)
m("check_drift", "    except subprocess.TimeoutExpired:\n        return subprocess.CompletedProcess(args, 124,", "    except subprocess.TimeoutExpired:\n        return subprocess.CompletedProcess(args, 0,", DRIFT)
m("check_drift", '    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1"}\n    try:\n        return subprocess.run(["git", "--literal-pathspecs", "-C", repo, *args], capture_output=True, text=True, env=env,',
  '    env = {**os.environ}\n    try:\n        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=env,', DRIFT)
m("resolve_release", "GH_TIMEOUT = 120", "GH_TIMEOUT = 121", RR)
m("resolve_release", "GH_TIMEOUT = 120", "GH_TIMEOUT = 12", RR)
m("resolve_release", "check=True, capture_output=True, text=True, timeout=GH_TIMEOUT)", "check=True, capture_output=True, text=True)", RR)
m("resolve_release", "        if not SEMVER.fullmatch(version):", "        if False:", RR)
m("resolve_release", "        if not version.isascii():", "        if False:", RR)
m("resolve_release", "        if not a.version.isascii():", "        if False:", RR)
m("resolve_release", "        if not a.version.isascii():", "        if a.version.isascii():", RR)
m("resolve_release", "        if not version.isascii():", "        if version.isascii():", RR)

# --- check_release_readiness.py ----------------------------------------------------------------------------------------
y = "check_release_readiness"
R = READY
for suffix in ('"-sources.jar", ', '"-javadoc.jar", ', ', "-tests.jar"'):
    m(y, 'CLASSIFIER_SUFFIXES = ("-sources.jar", "-javadoc.jar", "-tests.jar")',
      'CLASSIFIER_SUFFIXES = ("-sources.jar", "-javadoc.jar", "-tests.jar")'.replace(suffix, "", 1), R)
TSR = 'TIMESTAMPED = re.compile(r"(.*)-([0-9]{8}\\.[0-9]{6})-([0-9]+)")'
for new in ('r"(.*)-([0-9]{7}\\.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{5})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{6})-([0-9]*)"',
            'r"(.+)-([0-9]{8}\\.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}.[0-9]{6})-([0-9]+)"', 'r"(.*)-([0-9]{8}\\.[0-9]{6})"'):
    m(y, TSR, f"TIMESTAMPED = re.compile({new})", R)
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
m(y, "return stat.S_ISREG(os.lstat(path).st_mode)", "return not stat.S_ISDIR(os.lstat(path).st_mode)", R)
m(y, "return stat.S_ISREG(os.lstat(path).st_mode)", "return True", R)
m(y, "    except Exception as exc:\n        print(f\"::error::release-readiness failed unexpectedly", "    except ValueError as exc:\n        print(f\"::error::release-readiness failed unexpectedly", R)
m(y, 'selected = [n for n in names if n.endswith((".jar", ".pom", ".asc"))]', 'selected = [n for n in names if n.endswith((".jar", ".pom"))]', R)
m(y, 'selected = [n for n in names if n.endswith((".jar", ".pom", ".asc"))]', 'selected = [n for n in names if n.endswith((".jar", ".asc"))]', R)
m(y, 'selected = [n for n in names if n.endswith((".jar", ".pom", ".asc"))]', 'selected = [n for n in names if n.endswith((".pom", ".asc"))]', R)
m(y, "             and not stat.S_ISDIR(os.lstat(os.path.join(t, n)).st_mode)]", "             ]", R)
m(y, "    if not mains:\n", "    if False:\n", R)
m(y, '            return subprocess.run([a.gpg, "--verify", asc, f], stdout=subprocess.DEVNULL,', '            return subprocess.run([a.gpg, "--verify", f, asc], stdout=subprocess.DEVNULL,', R)
m(y, "        allowed.update(files)\n", "", R)
m(y, '        allowed.update(f + ".asc" for f in files)\n', "", R)
m(y, "            if os.path.islink(path):\n", "            if False:\n", R)
m(y, "            elif want != main_jar and not os.path.lexists(path):", "            elif False:", R)
m(y, "            elif os.path.lexists(path) and not regular(path):", "            elif False:", R)
m(y, '        if f"{base}-javadoc.jar" in intact:', "        if False:", R)
m(y, 'if "index.html" not in zf.namelist():', "if False:", R)
m(y, 'if "index.html" not in zf.namelist():', 'if not any(n.endswith("index.html") for n in zf.namelist()):', R)
m(y, "            except zipfile.BadZipFile:\n                err(f\"{shown_base}-javadoc.jar is not a zip file\")", "            except KeyError:\n                err(f\"{shown_base}-javadoc.jar is not a zip file\")", R)
m(y, '        if f"{base}.pom" in intact:', "        if False:", R)
m(y, "if artifact and version and f\"{artifact}-{version}\" != base:", "if False:", R)
m(y, "if artifact and version and f\"{artifact}-{version}\" != base:", "if artifact and version and f\"{artifact}-{version}\" == base:", R)
m(y, "if artifact and version and f\"{artifact}-{version}\" != base:", "if version and f\"{artifact}-{version}\" != base:", R)
m(y, "if artifact and version and f\"{artifact}-{version}\" != base:", "if artifact and f\"{artifact}-{version}\" != base:", R)
m(y, "        built[base] = coordinate\n", "        built[base] = (None, None, None)\n", R)
m(y, "        if len(findings) == before:", "        if True:", R)
m(y, "        if len(findings) == before:", "        if False:", R)
m(y, "        if n not in allowed:\n            err(", "        if False:\n            err(", R)
m(y, "        if n.endswith((\".jar\", \".pom\", \".asc\")) and any(unusual(c) for c in n):", "        if False:", R)
m(y, "        if n.endswith((\".jar\", \".pom\", \".asc\")) and any(unusual(c) for c in n):", "        if any(unusual(c) for c in n):", R)
m(y, "        if n.endswith((\".jar\", \".pom\", \".asc\")) and any(unusual(c) for c in n):", "        if n.endswith((\".jar\", \".pom\")) and any(unusual(c) for c in n):", R)
m(y, "    if a.stage:\n", "    if False:\n", R)
m(y, "        return 1\n    print(\"release-readiness: ok\")", "        return 0\n    print(\"release-readiness: ok\")", R)
m(y, "    if os.path.lexists(dest) and (os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "    if False:", R)
m(y, "os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "not os.path.isdir(dest) or os.listdir(dest)):", R)
m(y, "os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "os.path.islink(dest) or os.listdir(dest)):", R)
m(y, "os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "os.path.islink(dest) or not os.path.isdir(dest)):", R)
m(y, "    if os.path.lexists(dest) and (", "    if (", R)
m(y, "os.makedirs(dest, mode=0o700, exist_ok=True)", "os.makedirs(dest, mode=0o755, exist_ok=True)", R)
m(y, "os.makedirs(dest, mode=0o700, exist_ok=True)", "os.makedirs(dest, mode=0o700, exist_ok=False)", R)
m(y, "os.O_RDONLY | os.O_NOFOLLOW", "os.O_RDONLY", R)

# the bound-coordinate gate: one read point, private copies, a staged set that is what was verified, the exact file set
SNAP = 'return version[-8:].upper().lower() == "snapshot" or TIMESTAMPED.fullmatch(version) is not None'
for new in ('return version[-8:] == "SNAPSHOT" or TIMESTAMPED.fullmatch(version) is not None',
            'return version[-8:].lower() == "snapshot" or TIMESTAMPED.fullmatch(version) is not None',
            'return version[-8:].upper().lower() == "snapshot"', 'return TIMESTAMPED.fullmatch(version) is not None',
            'return version[-9:].upper().lower() == "snapshot" or TIMESTAMPED.fullmatch(version) is not None'):
    m(y, SNAP, new, R)
m(y, "    except OSError:\n        return False\n\n\ndef open_regular", "    except OSError:\n        return True\n\n\ndef open_regular", R)
m(y, "SUBPROCESS_TIMEOUT = 120", "SUBPROCESS_TIMEOUT = 121", R)
m(y, "SUBPROCESS_TIMEOUT = 120", "SUBPROCESS_TIMEOUT = 12", R)
m(y, "MAX_XML_BYTES = 16 * 1024 * 1024", "MAX_XML_BYTES = 16 * 1024 * 1024 + 1", R)
m(y, "MAX_XML_BYTES = 16 * 1024 * 1024", "MAX_XML_BYTES = 16 * 1024 * 1024 - 1", R)
m(y, "MAX_XML_DEPTH = 200", "MAX_XML_DEPTH = 201", R)
m(y, "MAX_XML_DEPTH = 200", "MAX_XML_DEPTH = 199", R)
XB = "        data = fh.read(MAX_XML_BYTES + 1)\n    if len(data) > MAX_XML_BYTES:"
m(y, XB, "        data = fh.read(MAX_XML_BYTES + 1)\n    if len(data) > MAX_XML_BYTES + 1:", R)
m(y, XB, "        data = fh.read(MAX_XML_BYTES + 1)\n    if len(data) >= MAX_XML_BYTES:", R)
m(y, XB, "        data = fh.read()\n    if False:", R)
m(y, "        if depth > MAX_XML_DEPTH:", "        if depth >= MAX_XML_DEPTH:", R)
m(y, "        if depth > MAX_XML_DEPTH:", "        if depth > MAX_XML_DEPTH + 1:", R)
m(y, "        if depth > MAX_XML_DEPTH:", "        if False:", R)
m(y, "        nonlocal depth\n        depth -= 1", "        nonlocal depth\n        pass", R)
m(y, "        nonlocal depth\n        depth += 1", "        nonlocal depth\n        depth += 2", R)
m(y, "    parser.StartElementHandler = start\n", "", R)
m(y, "    parser.EndElementHandler = end\n", "", R)
m(y, "        raise ET.ParseError(str(exc)) from exc\n    return ET.fromstring(data)", "        raise ET.ParseError(str(exc)) from exc\n    return None", R)
# the single read point
OPEN = "    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)"
for new in ("os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC", "os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC",
            "os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC", "os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK"):
    m(y, OPEN, f"    fd = os.open(path, {new})", R)
REG = "        if not stat.S_ISREG(os.fstat(fd).st_mode):\n            raise OSError(\"not a regular file\")"
m(y, REG, "        if False:\n            raise OSError(\"not a regular file\")", R)
m(y, REG, "        if stat.S_ISDIR(os.fstat(fd).st_mode):\n            raise OSError(\"not a regular file\")", R)
m(y, "    except BaseException:\n        os.close(fd)\n        raise\n    return fd", "    except BaseException:\n        raise\n    return fd", R)
PRIV = "        private = os.path.join(tempfile.mkdtemp(dir=scratch), os.path.basename(src) or \"file\")"
m(y, PRIV, "        private = os.path.join(scratch, os.path.basename(src) or \"file\")", R)
m(y, PRIV, "        private = os.path.join(tempfile.mkdtemp(dir=scratch), \"file\")", R)
m(y, "        with open(private, \"xb\") as fout:", "        with open(private, \"wb\") as fout:", R)
TAKE = "                h.update(chunk)\n                fout.write(chunk)\n    return private, h.hexdigest()"
m(y, TAKE, "                fout.write(chunk)\n    return private, h.hexdigest()", R)
m(y, TAKE, "                h.update(chunk[:-1])\n                fout.write(chunk)\n    return private, h.hexdigest()", R)
m(y, "def digest_of_file(path: str) -> str:\n    h = hashlib.sha256()", "def digest_of_file(path: str) -> str:\n    h = hashlib.sha1()", R)
m(y, "        held[name] = take(os.path.join(t, name), scratch)\n        return True", "        held[name] = take(os.path.join(t, name), scratch)\n        return False", R)
m(y, "    except SystemExit:\n        raise\n    except Exception as exc:\n        print(f\"::error::release-readiness failed unexpectedly", "    except SystemExit:\n        raise\n    except OSError as exc:\n        print(f\"::error::release-readiness failed unexpectedly", R)
# the ASCII rule and the coordinate
m(y, "        if not base.isascii():\n            err(", "        if False:\n            err(", R)
m(y, "        if not base.isascii():\n            err(", "        if base.isascii():\n            err(", R)
m(y, "        elif is_snapshot(base):\n", "        elif False:\n", R)
m(y, "        elif is_snapshot(base):\n", "        if is_snapshot(base):\n", R)
CO = "            if readable and not (group and artifact and version):"
for new in ("            if False:", "            if not (group and artifact and version):", "            if readable and not (artifact and version):",
            "            if readable and not (group and artifact):", "            if readable and not (group and version):",
            "            if readable and not (group or artifact or version):"):
    m(y, CO, new, R)
AS = "            if not all(v.isascii() for v in (group, artifact, version) if v):"
for new in ("            if False:", "            if not all(v.isascii() for v in (artifact, version) if v):",
            "            if not all(v.isascii() for v in (group, artifact) if v):", "            if not all(v.isascii() for v in (group, version) if v):"):
    m(y, AS, new, R)
SV = "            if version and version.isascii() and is_snapshot(version):"
for new in ("            if False:", "            if version and is_snapshot(version):", "            if version and not version.isascii() and is_snapshot(version):"):
    m(y, SV, new, R)
NA = "            elif artifact and version and f\"{artifact}-{version}\" != base:"
for new in ("            elif False:", "            elif artifact and version and f\"{artifact}-{version}\" == base:", "            elif version and f\"{artifact}-{version}\" != base:",
            "            elif artifact and f\"{artifact}-{version}\" != base:", "            elif artifact and version and f\"{version}-{artifact}\" != base:"):
    m(y, NA, new, R)
HP = "                if want == f\"{base}.pom\":\n                    try:\n                        hold(want)"
m(y, HP, "                if False:\n                    try:\n                        hold(want)", R)
POMERR = "                    except OSError as exc:\n                        err(f\"{shown_base}.pom cannot be read as a POM ({shown(' '.join(str(exc).split()))})\")\n                        continue"
m(y, POMERR, POMERR.replace("except OSError", "except ValueError"), R)
m(y, POMERR, POMERR.replace("continue", "pass"), R)
m(y, "                else:\n                    hold(want)\n                intact.append(want)", "                else:\n                    pass\n                intact.append(want)", R)
m(y, "            except (OSError, ET.ParseError) as exc:\n                readable = False", "            except OSError as exc:\n                readable = False", R)
m(y, "            except (OSError, ET.ParseError) as exc:\n                readable = False", "            except (OSError, ET.ParseError) as exc:\n                readable = True", R)
m(y, "                with zipfile.ZipFile(held[f\"{base}-javadoc.jar\"][0]) as zf:", "                with zipfile.ZipFile(os.path.join(t, f\"{base}-javadoc.jar\")) as zf:", R)
m(y, "        coordinate: tuple[str | None, str | None, str | None] = (None, None, None)\n        if f\"{base}.pom\" in intact:", "        coordinate: tuple[str | None, str | None, str | None] = (None, None, None)\n        if False:", R)
m(y, "                coordinate = pom_coordinate(read_pom(held[f\"{base}.pom\"][0]))", "                coordinate = pom_coordinate(read_pom(os.path.join(t, f\"{base}.pom\")))", R)
m(y, "            if os.path.islink(os.path.join(t, asc)):", "            if False:", R)
m(y, "            elif not regular(os.path.join(t, asc)):", "            elif False:", R)
SG = "            elif hold(asc) and not good_signature(held[asc][0], held[f][0]):"
for new in ("            elif False:", "            elif hold(asc) and not good_signature(held[f][0], held[asc][0]):",
            "            elif hold(asc) and not good_signature(os.path.join(t, asc), os.path.join(t, f)):",
            "            elif hold(asc) and not good_signature(held[asc][0], os.path.join(t, f)):",
            "            elif hold(asc) and good_signature(held[asc][0], held[f][0]):"):
    m(y, SG, new, R)
VER = "            return subprocess.run([a.gpg, \"--verify\", asc, f], stdout=subprocess.DEVNULL,\n                                  stderr=subprocess.DEVNULL, timeout=SUBPROCESS_TIMEOUT).returncode == 0"
m(y, VER, VER.replace("timeout=SUBPROCESS_TIMEOUT).returncode == 0", "timeout=SUBPROCESS_TIMEOUT).returncode != 127"), R)
m(y, VER, VER.replace(", timeout=SUBPROCESS_TIMEOUT", ""), R)
m(y, VER, VER.replace("timeout=SUBPROCESS_TIMEOUT", "timeout=SUBPROCESS_TIMEOUT * 100"), R)
EXC = "        except (OSError, subprocess.TimeoutExpired):\n            return False\n\n    held:"
m(y, EXC, EXC.replace("return False", "return True"), R)
m(y, EXC, EXC.replace("(OSError, subprocess.TimeoutExpired)", "OSError"), R)
m(y, EXC, EXC.replace("(OSError, subprocess.TimeoutExpired)", "subprocess.TimeoutExpired"), R)
# staging: only on a clean run, from the verified copies
m(y, "        if findings:\n            if wrote:\n                shutil.rmtree(a.stage, ignore_errors=True)", "        if False:\n            if wrote:\n                shutil.rmtree(a.stage, ignore_errors=True)", R)
m(y, "            if wrote:\n                shutil.rmtree(a.stage, ignore_errors=True)", "            if not wrote:\n                shutil.rmtree(a.stage, ignore_errors=True)", R)
m(y, "            if wrote:\n                shutil.rmtree(a.stage, ignore_errors=True)", "            if wrote:\n                pass", R)
m(y, "the gated files could not be staged\", file=sys.stderr)\n            return 1", "the gated files could not be staged\", file=sys.stderr)\n            return 0", R)
m(y, "    held = held or {}\n    if os.path.lexists(dest)", "    held = held or {}\n    if False and os.path.lexists(dest)", R)
m(y, "    copies = [(f, os.path.join(t, f), os.path.join(dest, f)) for f in files]", "    copies = [(f, os.path.join(t, f), os.path.join(dest, f)) for f in files[:-1]]", R)
m(y, "            copy_gated(src, dst, held.get(key))", "            copy_gated(src, dst, None)", R)
m(y, "            copy_gated(src, dst, held.get(key))", "            copy_gated(src, dst, held.get(f\"{key}.x\"))", R)
m(y, "    return True\n\n\ndef copy_gated", "    return False\n\n\ndef copy_gated", R)
m(y, "    if gated is None:\n        with os.fdopen(open_regular(src), \"rb\") as fin, open(dst, \"xb\") as fout:", "    if gated is None:\n        with os.fdopen(open_regular(src), \"rb\") as fin, open(dst, \"wb\") as fout:", R)
m(y, "    private, digest = gated\n    if digest_of_file(src) != digest:", "    private, digest = gated\n    if False:", R)
m(y, "    private, digest = gated\n    if digest_of_file(src) != digest:", "    private, digest = gated\n    if digest_of_file(src) == digest:", R)
CP = "    with os.fdopen(open_regular(private), \"rb\") as fin, open(dst, \"xb\") as fout:"
m(y, CP, CP.replace("open_regular(private)", "open_regular(src)"), R)
m(y, CP, CP.replace('"xb"', '"wb"'), R)
m(y, "            h.update(chunk)\n            fout.write(chunk)\n    if h.hexdigest() != digest:", "            fout.write(chunk)\n    if h.hexdigest() != digest:", R)
CH = "    if h.hexdigest() != digest:\n        os.unlink(dst)\n        raise OSError(\"the verified copy changed\")"
m(y, CH, CH.replace("h.hexdigest() != digest", "False"), R)
m(y, CH, CH.replace("        os.unlink(dst)\n", ""), R)
m(y, CH, CH.replace("\n        raise OSError(\"the verified copy changed\")", ""), R)
# the bundle: read once, judged on the copy
# the layout of the archive
# names, folds and the exact file set

# --- remove_signing_key.py ---------------------------------------------------------------------------------------------
k = "remove_signing_key"
for cat in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs"):
    allc = ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")
    kept = ", ".join(f'"{x}"' for x in allc if x != cat)
    m(k, 'return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cn", "Cs")', f"return unicodedata.category(ch) in ({kept})", REMOVE)
m(k, "    if os.path.islink(path):\n        os.unlink(path)", "    if False:\n        os.unlink(path)", REMOVE)
m(k, "    elif os.path.lexists(path):\n        shutil.rmtree(path, ignore_errors=True)", "    elif False:\n        shutil.rmtree(path, ignore_errors=True)", REMOVE)
m(k, "    for flag in (\"secret_home\", \"verify_home\", \"public_key\", \"env_file\"):", "    for flag in (\"verify_home\", \"public_key\", \"env_file\"):", REMOVE)
m(k, "    for flag in (\"secret_home\", \"verify_home\", \"public_key\", \"env_file\"):", "    for flag in (\"secret_home\", \"public_key\", \"env_file\"):", REMOVE)
m(k, "    for flag in (\"secret_home\", \"verify_home\", \"public_key\", \"env_file\"):", "    for flag in (\"secret_home\", \"verify_home\", \"env_file\"):", REMOVE)
m(k, "    for flag in (\"secret_home\", \"verify_home\", \"public_key\", \"env_file\"):", "    for flag in (\"secret_home\", \"verify_home\", \"public_key\"):", REMOVE)
m(k, "        bad = [c for c in getattr(a, flag) if unusual(c)]\n        if bad:", "        bad = [c for c in getattr(a, flag) if unusual(c)]\n        if False:", REMOVE)
m(k, '    if problems and any("--secret-home" in m for m in problems):\n        return', "    if False:\n        return", REMOVE)
m(k, "    if os.path.islink(secret_home):\n        fail(", "    if False:\n        fail(", REMOVE)
m(k, "    elif os.path.isdir(secret_home):\n        try:", "    elif False:\n        try:", REMOVE)
m(k, '[a.gpgconf, "--kill", "gpg-agent"]', '[a.gpgconf, "--reload", "gpg-agent"]', REMOVE)
m(k, 'env={**os.environ, "GNUPGHOME": secret_home},\n                           stdout=subprocess.DEVNULL', 'env={**os.environ, "GNUPGHOME": a.verify_home},\n                           stdout=subprocess.DEVNULL', REMOVE)
m(k, "        shutil.rmtree(secret_home, ignore_errors=True)\n    if os.path.islink(verify_home):", "        pass\n    if os.path.islink(verify_home):", REMOVE)
m(k, '"changed or imported through it.")\n    if problems:\n        return', '"changed or imported through it.")\n    if False:\n        return', REMOVE)
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
m(k, '            os.makedirs(verify_home, mode=0o700, exist_ok=True)\n            os.chmod(verify_home, 0o700)\n            done', '            os.makedirs(verify_home, mode=0o700, exist_ok=True)\n            done', REMOVE)
m(k, '[a.gpg, "--batch", "--import", a.public_key], env=verify_env', '[a.gpg, "--batch", "--import", a.public_key + ".x"], env=verify_env', REMOVE)
m(k, '[a.gpg, "--batch", "--import", a.public_key], env=verify_env', '[a.gpg, "--batch", "--import", a.public_key], env={**os.environ, "GNUPGHOME": a.secret_home}', REMOVE)
m(k, "            if done.returncode != 0:", "            if False:", REMOVE)
m(k, "    try:\n        os.remove(a.public_key)\n    except FileNotFoundError:\n        pass", "    try:\n        pass\n    except FileNotFoundError:\n        pass", REMOVE)
m(k, "    try:\n        os.remove(a.public_key)\n    except FileNotFoundError:\n        pass\n    if problems:\n        return", "    try:\n        os.remove(a.public_key)\n    except FileNotFoundError:\n        pass\n    if False:\n        return", REMOVE)
m(k, '    os.makedirs(verify_home, mode=0o700, exist_ok=True)\n    os.chmod(verify_home, 0o700)\n    if os.path.lexists', '    os.makedirs(verify_home, mode=0o700, exist_ok=True)\n    if os.path.lexists', REMOVE)
m(k, "    if os.path.lexists(secret_home):\n        fail(", "    if False:\n        fail(", REMOVE)
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
m(k, "{' '.join(str(exc).split())}).\")", "{exc}).\")", REMOVE)

# the verify home that is a symbolic link: refused on its literal spelling, before anything is created, changed or imported
VL = '    if os.path.islink(verify_home):\n        fail("the verify home is a symbolic link, which is reported and not followed: nothing is created, "\n             "changed or imported through it.")\n'
m(k, VL, VL.replace("if os.path.islink(verify_home):", "if False:"), REMOVE)
m(k, VL, VL.replace("if os.path.islink(verify_home):", "if not os.path.islink(verify_home):"), REMOVE)
m(k, VL, VL.replace("os.path.islink(verify_home)", "os.path.islink(a.verify_home)"), REMOVE)
m(k, VL, VL.replace("os.path.islink(verify_home)", "os.path.islink(a.verify_home.rstrip(os.sep))"), REMOVE)
m(k, VL, VL.replace("        fail(", "        problems.append("), REMOVE)
m(k, VL, VL.replace("the verify home is a symbolic link, which", "the home is a link, which"), REMOVE)
m(k, VL, "    if os.path.islink(verify_home):\n        pass\n", REMOVE)
VL_CHECK_THEN_RETURN = VL + "    if problems:\n        return\n"
m(k, VL_CHECK_THEN_RETURN, "    if problems:\n        return\n" + VL, REMOVE)      # judged only when the secret home had no problem
VL_TO_CHMOD = '    if os.path.islink(verify_home):\n        fail("the verify home is a symbolic link, which is reported and not followed: nothing is created, "\n             "changed or imported through it.")\n    if problems:\n        return\n\n    verify_env = {**os.environ, "GNUPGHOME": a.verify_home}\n    if os.path.isfile(a.public_key) and os.path.getsize(a.public_key) > 0:\n        inspect = tempfile.mkdtemp(prefix="gnupg-inspect-")\n        try:\n            shown = subprocess.run([a.gpg, "--batch", "--show-keys", "--with-colons", a.public_key],\n                                   env={**os.environ, "GNUPGHOME": inspect}, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)\n        finally:\n            shutil.rmtree(inspect, ignore_errors=True)\n        if shown.returncode != 0:\n            fail(f"the public key could not be imported: it could not be inspected: {shown.stderr.strip()}")\n        elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):\n            fail("the file named as the public key holds a secret key and was not imported; "\n                 "a secret key is still on the runner in that file until it is deleted.")\n        else:\n            os.makedirs(verify_home, mode=0o700, exist_ok=True)\n            os.chmod(verify_home, 0o700)\n            done = subprocess.run([a.gpg, "--batch", "--import", a.public_key], env=verify_env,\n                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,\n                                  timeout=SUBPROCESS_TIMEOUT)\n            if done.returncode != 0:\n                fail(f"the public key could not be imported: {done.stderr.strip()}")\n    try:\n        os.remove(a.public_key)\n    except FileNotFoundError:\n        pass\n    if problems:\n        return\n\n    os.makedirs(verify_home, mode=0o700, exist_ok=True)\n    os.chmod(verify_home, 0o700)\n    if os.path.lexists(secret_home):'
m(k, VL_TO_CHMOD, '    if problems:\n        return\n\n    verify_env = {**os.environ, "GNUPGHOME": a.verify_home}\n    if os.path.isfile(a.public_key) and os.path.getsize(a.public_key) > 0:\n        inspect = tempfile.mkdtemp(prefix="gnupg-inspect-")\n        try:\n            shown = subprocess.run([a.gpg, "--batch", "--show-keys", "--with-colons", a.public_key],\n                                   env={**os.environ, "GNUPGHOME": inspect}, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)\n        finally:\n            shutil.rmtree(inspect, ignore_errors=True)\n        if shown.returncode != 0:\n            fail(f"the public key could not be imported: it could not be inspected: {shown.stderr.strip()}")\n        elif any(ln.split(":", 1)[0] in ("sec", "ssb") for ln in shown.stdout.splitlines()):\n            fail("the file named as the public key holds a secret key and was not imported; "\n                 "a secret key is still on the runner in that file until it is deleted.")\n        else:\n            os.makedirs(verify_home, mode=0o700, exist_ok=True)\n            os.chmod(verify_home, 0o700)\n            done = subprocess.run([a.gpg, "--batch", "--import", a.public_key], env=verify_env,\n                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,\n                                  timeout=SUBPROCESS_TIMEOUT)\n            if done.returncode != 0:\n                fail(f"the public key could not be imported: {done.stderr.strip()}")\n    try:\n        os.remove(a.public_key)\n    except FileNotFoundError:\n        pass\n    if problems:\n        return\n\n    os.makedirs(verify_home, mode=0o700, exist_ok=True)\n    os.chmod(verify_home, 0o700)\n    if os.path.islink(verify_home):\n        fail("the verify home is a symbolic link, which is reported and not followed: nothing is created, "\n             "changed or imported through it.")\n    if os.path.lexists(secret_home):', REMOVE)   # judged after the directory has been created and tightened

# the finally: literal removal on every way out, and the bound on every tool
m(k, "SUBPROCESS_TIMEOUT = 120", "SUBPROCESS_TIMEOUT = 121", REMOVE)
m(k, "SUBPROCESS_TIMEOUT = 120", "SUBPROCESS_TIMEOUT = 12", REMOVE)
RL = "    try:\n        if stat.S_ISDIR(os.lstat(path).st_mode):\n            if tree:\n                shutil.rmtree(path, ignore_errors=True)         # descriptor-relative, does not follow links\n        elif not tree:\n            os.unlink(path)\n    except (OSError, ValueError):\n        pass"
m(k, RL, RL.replace("stat.S_ISDIR(os.lstat(path).st_mode)", "os.path.isdir(path)"), REMOVE)
m(k, RL, RL.replace("if tree:\n                shutil", "if True:\n                shutil"), REMOVE)
m(k, RL, RL.replace("if tree:\n                shutil", "if not tree:\n                shutil"), REMOVE)
m(k, RL, RL.replace("                shutil.rmtree(path, ignore_errors=True)         # descriptor-relative, does not follow links", "                pass"), REMOVE)
m(k, RL, RL.replace("elif not tree:", "elif True:"), REMOVE)
m(k, RL, RL.replace("elif not tree:", "elif tree:"), REMOVE)
m(k, RL, RL.replace("            os.unlink(path)", "            pass"), REMOVE)
m(k, RL, RL.replace("except (OSError, ValueError):", "except ValueError:"), REMOVE)
m(k, RL, RL.replace("except (OSError, ValueError):", "except OSError:"), REMOVE)
m(k, RL, RL.replace("stat.S_ISDIR(os.lstat(path).st_mode)", "stat.S_ISDIR(os.stat(path).st_mode)"), REMOVE)
m(k, "        remove_literally(a.secret_home, tree=True)\n", "", REMOVE)
m(k, "        remove_literally(a.public_key, tree=False)\n", "", REMOVE)
m(k, "        remove_literally(a.secret_home, tree=True)\n", "        remove_literally(a.secret_home, tree=False)\n", REMOVE)
m(k, "        remove_literally(a.public_key, tree=False)\n", "        remove_literally(a.public_key, tree=True)\n", REMOVE)
m(k, "        if problems or not finished:", "        if problems:", REMOVE)
m(k, "        if problems or not finished:", "        if not finished:", REMOVE)
m(k, "        if problems or not finished:", "        if False:", REMOVE)
m(k, "        finished = True\n", "        finished = False\n", REMOVE)
m(k, "    finished = False\n    try:", "    finished = True\n    try:", REMOVE)
m(k, "                remove_tree(a.verify_home)\n            except (OSError, ValueError):\n                pass", "                pass\n            except (OSError, ValueError):\n                pass", REMOVE)
m(k, "                remove_tree(a.verify_home)\n            except (OSError, ValueError):\n                pass", "                remove_tree(a.verify_home)\n            except ValueError:\n                pass", REMOVE)
m(k, "        try:\n            removal(a, fail, problems)\n        except Exception as exc:", "        try:\n            removal(a, fail, problems)\n        except ValueError as exc:", REMOVE)
m(k, "        try:\n            removal(a, fail, problems)\n        except Exception as exc:", "        try:\n            removal(a, fail, problems)\n        except BaseException as exc:", REMOVE)
m(k, "    if problems:\n        return 1\n    print(", "    if problems:\n        return 0\n    print(", REMOVE)
m(k, "    if problems:\n        return 1\n    print(", "    if not problems:\n        return 1\n    print(", REMOVE)
GC = "            subprocess.run([a.gpgconf, \"--kill\", \"gpg-agent\"], env={**os.environ, \"GNUPGHOME\": secret_home},\n                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=SUBPROCESS_TIMEOUT)\n        except (OSError, subprocess.TimeoutExpired):\n            pass"
m(k, GC, GC.replace(", timeout=SUBPROCESS_TIMEOUT", ""), REMOVE)
m(k, GC, GC.replace("(OSError, subprocess.TimeoutExpired)", "OSError"), REMOVE)
m(k, GC, GC.replace("(OSError, subprocess.TimeoutExpired)", "subprocess.TimeoutExpired"), REMOVE)
m(k, GC, GC.replace("timeout=SUBPROCESS_TIMEOUT", "timeout=SUBPROCESS_TIMEOUT * 100"), REMOVE)
SK = "env={**os.environ, \"GNUPGHOME\": inspect}, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)"
m(k, SK, SK.replace(", timeout=SUBPROCESS_TIMEOUT", ""), REMOVE)
IM = "stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,\n                                  timeout=SUBPROCESS_TIMEOUT)"
m(k, IM, IM.replace(",\n                                  timeout=SUBPROCESS_TIMEOUT", ""), REMOVE)
LS = "env=verify_env,\n                            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)"
m(k, LS, LS.replace(", timeout=SUBPROCESS_TIMEOUT", ""), REMOVE)

# --- run_caps_release_tests.py -----------------------------------------------------------------------------------------
q = "../run_caps_release_tests"
m(q, "    if n == 0:", "    if False:", RUNNER)
m(q, "return 0 if result.wasSuccessful() else 1", "return 0", RUNNER)
m(q, 'pattern="test*.py"', 'pattern="tst*.py"', RUNNER)
m(q, "return 0 if result.wasSuccessful() else 1", "return 0 if not result.failures else 1", RUNNER)
m(q, "        return 1\n    result", "        return 0\n    result", RUNNER)
m(q, 'start = os.path.join(ap.parse_args().root, "tests", "caps_release")', 'start = os.path.join(ap.parse_args().root, "tests")', RUNNER)


# --- additions for the two targets, the release profile, the drift refusal and the secrets check -------------------------
TARGET = 'if a.target not in ("none", "github-packages"):'
m(r, TARGET, "if False:", RR)
m(r, TARGET, 'if a.target not in ("none", "github-packages", "central"):', RR)
m(r, TARGET, 'if a.target not in ("github-packages",):', RR)
m(r, TARGET, 'if a.target not in ("none",):', RR)
m(r, TARGET, 'if a.target.strip() not in ("none", "github-packages"):', RR)
m(r, TARGET, 'if a.target.lower() not in ("none", "github-packages"):', RR)
m(r, TARGET, 'if a.target and a.target not in ("none", "github-packages"):', RR)
m(r, "raise Refused(f\"target must be 'none' or 'github-packages', got '{a.target}'.\")", "return None", RR)
UP = '    if a.upload == "true" and a.target == "none":'
m(r, UP, '    if a.upload == "true" and a.target != "github-packages":', RR)
m(r, UP, '    if a.upload == "true" and a.target == "github-packages":', RR)
m(r, "        print(\"::warning::upload was requested with target 'none': nothing is uploaded. Name a target to upload.\")",
  "        pass", RR)
m(r, "    elif a.upload == \"true\":\n        publish = True", "    elif a.upload == \"true\" and a.target == \"none\":\n        publish = True", RR)

# --- check_release_profile.py (after the XML reader) -------------------------------------------------------------------
p = "check_release_profile"
m(p, "MAX_XML_BYTES = 16 * 1024 * 1024", "MAX_XML_BYTES = 16 * 1024 * 1024 + 1", PROFILE)
m(p, "MAX_XML_DEPTH = 200", "MAX_XML_DEPTH = 201", PROFILE)
m(p, "        if depth > MAX_XML_DEPTH:", "        if False:", PROFILE)
m(p, "    if len(data) > MAX_XML_BYTES:", "    if False:", PROFILE)
m(p, "    parser.StartElementHandler = start\n", "", PROFILE)
m(p, "    parser.EndElementHandler = end\n", "", PROFILE)
m(p, "        depth -= 1", "        pass", PROFILE)
m(p, "PLUGIN_GROUP = \"org.apache.maven.plugins\"", "PLUGIN_GROUP = \"org.apache.maven\"", PROFILE)
for dropped in ("maven-gpg-plugin", "maven-source-plugin", "maven-javadoc-plugin"):
    line = {"maven-gpg-plugin": '    "maven-gpg-plugin": "the signatures",\n', "maven-source-plugin": '    "maven-source-plugin": "the sources jar",\n',
            "maven-javadoc-plugin": '    "maven-javadoc-plugin": "the javadoc jar",\n'}[dropped]
    m(p, line, "", PROFILE)
m(p, 'FORBIDDEN_GROUP = "org.sonatype.central"', 'FORBIDDEN_GROUP = "org.sonatype"', PROFILE)
m(p, 'FORBIDDEN = "central-publishing-maven-plugin"', 'FORBIDDEN = "central-publishing"', PROFILE)
m(p, "    return tag.rsplit(\"}\", 1)[-1]", "    return tag", PROFILE)
m(p, "    return [c for c in el if local(c.tag) == name]", "    return [c for c in el if c.tag == name]", PROFILE)
m(p, "    return \" \".join(c.text.strip() for c in children(el, name) if c.text)", "    return \" \".join(c.text for c in children(el, name) if c.text)", PROFILE)
m(p, "    return \" \".join(c.text.strip() for c in children(el, name) if c.text)", "    return \"\".join(c.text.strip() for c in children(el, name) if c.text)", PROFILE)
m(p, "    profiles = [profile for container in children(root, \"profiles\") for profile in children(container, \"profile\")]",
  "    profiles = [profile for profile in children(root, \"profile\")]", PROFILE)
m(p, "    profiles = [profile for container in children(root, \"profiles\") for profile in children(container, \"profile\")]",
  "    profiles = [profile for container in root.iter() for profile in children(container, \"profile\")]", PROFILE)
m(p, "if (text(profile, \"id\")) == \"release\"]", "if (text(profile, \"id\")) in (\"release\", \"\")]", PROFILE)
m(p, "if (text(profile, \"id\")) == \"release\"]", "if (text(profile, \"id\")).lower() == \"release\"]", PROFILE)
m(p, "if (text(profile, \"id\")) == \"release\"]", "if (text(profile, \"id\")).startswith(\"release\")]", PROFILE)
m(p, "    if not release:\n        problems.append", "    if False:\n        problems.append", PROFILE)
MODS = "    if children(root, \"modules\") or any(children(profile, \"modules\") for profile in profiles):"
m(p, MODS, "    if False:", PROFILE)
m(p, MODS, "    if any(children(profile, \"modules\") for profile in profiles):", PROFILE)
m(p, MODS, "    if children(root, \"modules\"):", PROFILE)
m(p, MODS, "    if children(root, \"modules\") or any(children(profile, \"modules\") for profile in release):", PROFILE)
m(p, "    builds = [build for profile in release for build in children(profile, \"build\")]", "    builds = [build for profile in profiles for build in children(profile, \"build\")]", PROFILE)
m(p, "    builds = [build for profile in release for build in children(profile, \"build\")]", "    builds = [build for build in children(root, \"build\")]", PROFILE)
PLUGINS = "    plugins = [plugin for build in builds for container in children(build, \"plugins\")\n               for plugin in children(container, \"plugin\")]"
m(p, PLUGINS, "    plugins = [plugin for build in builds for plugin in children(build, \"plugin\")]", PROFILE)
m(p, PLUGINS, "    plugins = [plugin for build in builds for container in build.iter(\"plugins\")\n               for plugin in children(container, \"plugin\")]", PROFILE)
MANAGED = "    managed = [plugin for build in builds for management in children(build, \"pluginManagement\")\n               for container in children(management, \"plugins\") for plugin in children(container, \"plugin\")]"
m(p, MANAGED, "    managed = []", PROFILE)
m(p, MANAGED, "    managed = [plugin for build in builds for management in children(build, \"pluginManagement\")\n               for plugin in children(management, \"plugin\")]", PROFILE)
m(p, "    if release:\n        for artifact, what in REQUIRED.items():", "    if True:\n        for artifact, what in REQUIRED.items():", PROFILE)
m(p, "    if release:\n        for artifact, what in REQUIRED.items():", "    if False:\n        for artifact, what in REQUIRED.items():", PROFILE)
REQCHK = "            if not any(text(p, \"groupId\") in (\"\", PLUGIN_GROUP) and text(p, \"artifactId\") == artifact for p in plugins):"
m(p, REQCHK, "            if False:", PROFILE)
m(p, REQCHK, "            if not any(text(p, \"artifactId\") == artifact for p in plugins):", PROFILE)
m(p, REQCHK, "            if not any(text(p, \"groupId\") == PLUGIN_GROUP and text(p, \"artifactId\") == artifact for p in plugins):", PROFILE)
m(p, REQCHK, "            if not any(text(p, \"groupId\") in (\"\", PLUGIN_GROUP) and artifact in text(p, \"artifactId\") for p in plugins):", PROFILE)
m(p, REQCHK, "            if not any(text(p, \"groupId\") in (\"\", PLUGIN_GROUP) and text(p, \"artifactId\") == artifact for p in plugins + managed):", PROFILE)
FORB = "    if any(text(p, \"artifactId\") == FORBIDDEN and text(p, \"groupId\") in (\"\", FORBIDDEN_GROUP)\n           for p in plugins + managed):"
m(p, FORB, "    if False:", PROFILE)
m(p, FORB, "    if any(text(p, \"artifactId\") == FORBIDDEN and text(p, \"groupId\") in (\"\", FORBIDDEN_GROUP)\n           for p in plugins):", PROFILE)
m(p, FORB, "    if any(text(p, \"artifactId\") == FORBIDDEN and text(p, \"groupId\") in (\"\", FORBIDDEN_GROUP)\n           for p in managed):", PROFILE)
m(p, FORB, "    if any(text(p, \"artifactId\") == FORBIDDEN and text(p, \"groupId\") == FORBIDDEN_GROUP\n           for p in plugins + managed):", PROFILE)
m(p, FORB, "    if any(text(p, \"artifactId\") == FORBIDDEN for p in plugins + managed):", PROFILE)
m(p, FORB, "    if any(text(p, \"artifactId\") == FORBIDDEN and text(p, \"groupId\") in (\"\", FORBIDDEN_GROUP)\n           for p in plugins + managed + builds):", PROFILE)
m(p, "    except (OSError, ET.ParseError) as exc:\n        print(f\"::error::{a.pom} cannot be read", "    except OSError as exc:\n        print(f\"::error::{a.pom} cannot be read", PROFILE)
m(p, "    except (OSError, ET.ParseError) as exc:\n        print(f\"::error::{a.pom} cannot be read", "    except ET.ParseError as exc:\n        print(f\"::error::{a.pom} cannot be read", PROFILE)
m(p, "    if problems:\n        print(", "    if not problems:\n        print(", PROFILE)
m(p, "'; '.join(problems)", "'\\n::error::'.join(problems)", PROFILE)
m(p, "'; '.join(problems)", "', '.join(problems[:1])", PROFILE)
m(p, "machinery.\", file=sys.stderr)\n        return 1\n    print(\"ok", "machinery.\", file=sys.stderr)\n        return 0\n    print(\"ok", PROFILE)
m(p, "    p.add_argument(\"--pom\", required=True)", "    p.add_argument(\"--pom\")", PROFILE)
m(p, "    except Exception as exc:\n        print(f\"::error::the release-profile check failed unexpectedly", "    except ValueError as exc:\n        print(f\"::error::the release-profile check failed unexpectedly", PROFILE)

# --- check_drift.py: the refusal names the fix and no deployment -------------------------------------------------------
d = "check_drift"
m(d, "\"Run the two-pass build and commit the result.\"", "\"Run the two-pass build.\"", DRIFT)
m(d, "\"Run the two-pass build and commit the result.\"", "\"Run the two-pass build and commit the result. If a deployment was uploaded, DROP it.\"", DRIFT)
m(d, "    p.add_argument(\"--generated\", required=True)", "    p.add_argument(\"--generated\")", DRIFT)
m(d, "    p.add_argument(\"--repo\", required=True)", "    p.add_argument(\"--repo\")", DRIFT)

# --- check_secrets.py --------------------------------------------------------------------------------------------------
c = "check_secrets"
NEED = '    need = [("HAVE_GPG_KEY", "GPG_PRIVATE_KEY"), ("HAVE_GPG_PASSPHRASE", "GPG_PASSPHRASE")]'
m(c, NEED, '    need = [("HAVE_GPG_PASSPHRASE", "GPG_PASSPHRASE")]', SECRETS)
m(c, NEED, '    need = [("HAVE_GPG_KEY", "GPG_PRIVATE_KEY")]', SECRETS)
m(c, NEED, '    need = [("HAVE_GPG_KEY", "GPG_PASSPHRASE"), ("HAVE_GPG_PASSPHRASE", "GPG_PRIVATE_KEY")]', SECRETS)
m(c, NEED, '    need = [("HAVE_GPG_KEY", "GPG_PRIVATE_KEY"), ("HAVE_GPG_PASSPHRASE", "GPG_PASSPHRASE"), ("HAVE_CENTRAL_USER", "CENTRAL_TOKEN_USERNAME")]', SECRETS)
for new in ('os.environ.get(var, "").lower() != "true"', 'os.environ.get(var) == "false"', 'os.environ.get(var, "").strip() != "true"',
            'not os.environ.get(var)', 'os.environ.get(var) not in ("true", "True")', '"true" not in (os.environ.get(var) or "")'):
    m(c, 'os.environ.get(var) != "true"', new, SECRETS)
m(c, "    if missing:\n", "    if False:\n", SECRETS)
m(c, "    if missing:\n", "    if len(missing) > 1:\n", SECRETS)
m(c, "', '.join(missing)", "', '.join(missing[:1])", SECRETS)
m(c, "', '.join(missing)", "', '.join(var for var, _ in need)", SECRETS)
m(c, "an upload needs secrets the caller did not pass: {', '.join(missing)}\",\n              file=sys.stderr)\n        return 1", "an upload needs secrets the caller did not pass: {', '.join(missing)}\",\n              file=sys.stderr)\n        return 0", SECRETS)
m(c, "    p.parse_args(argv)", "    p.parse_args(argv)\n    print(os.environ.get('HAVE_GPG_KEY'))", SECRETS)
m(c, "    p.parse_args(argv)", "    p.parse_known_args(argv)", SECRETS)
m(c, "    except Exception as exc:\n        print(f\"::error::the secrets check failed unexpectedly", "    except ValueError as exc:\n        print(f\"::error::the secrets check failed unexpectedly", SECRETS)
m(c, "{' '.join(str(exc).split())}", "{str(exc)}", SECRETS)
m(c, "    print(\"ok - the signing secrets were passed\")\n    return 0", "    print(\"ok - the signing secrets were passed\")\n    return 1", SECRETS)

# --- check_release_readiness.py: the closed set of files per coordinate -------------------------------------------------
y = "check_release_readiness"
R = READY
m(y, "    scratch = tempfile.mkdtemp(prefix=\"release-verify-\")", "    scratch = tempfile.mkdtemp(prefix=\"release-verify-\", dir=os.getcwd())", R)
m(y, "    finally:\n        shutil.rmtree(scratch, ignore_errors=True)", "    finally:\n        pass", R)
m(y, "        return gate(a, scratch)", "        return gate(a, a.target_dir)", R)
m(y, "    p.add_argument(\"--target-dir\", required=True)", "    p.add_argument(\"--target-dir\", default=\"target\")", R)
m(y, "    p.add_argument(\"--gpg\", default=\"gpg\")", "    p.add_argument(\"--gpg\", default=\"\")", R)
m(y, "    p.add_argument(\"--stage\", default=\"\")", "    p.add_argument(\"--stage\", default=\"stage\")", R)
m(y, "    except OSError as exc:\n        print(f\"::error::{shown(a.target_dir)} cannot be read ({exc}).\", file=sys.stderr)\n        return 1",
  "    except OSError as exc:\n        print(f\"::error::{shown(a.target_dir)} cannot be read ({exc}).\", file=sys.stderr)\n        return 0", R)
m(y, "        print(\"::error::the build produced no main jar\", file=sys.stderr)\n        return 1", "        print(\"::error::the build produced no main jar\", file=sys.stderr)\n        return 0", R)
m(y, "        names = sorted(os.listdir(a.target_dir))", "        names = sorted(os.listdir(a.target_dir))[:1]", R)
FILES = '        files = [main_jar, f"{base}-sources.jar", f"{base}-javadoc.jar", f"{base}.pom"]\n        allowed.update(files)'
m(y, FILES, '        files = [main_jar, f"{base}-sources.jar", f"{base}-javadoc.jar"]\n        allowed.update(files)', R)
m(y, FILES, '        files = [main_jar, f"{base}-sources.jar", f"{base}.pom"]\n        allowed.update(files)', R)
m(y, FILES, '        files = [main_jar, f"{base}-javadoc.jar", f"{base}.pom"]\n        allowed.update(files)', R)
m(y, FILES, '        files = [main_jar, f"{base}-sources.jar", f"{base}-javadoc.jar", f"{base}.pom", f"{base}-tests.jar"]\n        allowed.update(files)', R)
FILES2 = '        shown_base = shown(base)\n'
m(y, "        shown_base = shown(base)\n        if not base.isascii():", "        shown_base = base\n        if not base.isascii():", R)
m(y, "                err(f\"{shown_base} is missing {shown(want)} - a release holds all four files\")", "                pass", R)
m(y, "            elif want != main_jar and not os.path.lexists(path):", "            elif not os.path.lexists(path):", R)
m(y, "                err(f\"{shown(want)} is a symbolic link; only regular files are released\")", "                pass", R)
m(y, "                err(f\"{shown(want)} is not a regular file; only regular files are released\")", "                pass", R)
m(y, "            elif os.path.lexists(path):\n                if want", "            else:\n                if want", R)
m(y, "                err(f\"{shown(f)} has no detached signature\")", "                pass", R)
m(y, "                err(f\"{shown(f)}.asc is a symbolic link; only regular files are released\")", "                pass", R)
m(y, "                err(f\"{shown(f)}.asc is not a good signature\")", "                pass", R)
m(y, "        for f in intact:\n            asc = f + \".asc\"", "        for f in intact[:1]:\n            asc = f + \".asc\"", R)
m(y, "        for f in intact:\n            asc = f + \".asc\"", "        for f in intact:\n            asc = f + \".sig\"", R)
m(y, "                    if \"index.html\" not in zf.namelist():\n                        err(f\"{shown_base}-javadoc.jar holds no index.html\")", "                    if \"index.html\" not in zf.namelist():\n                        pass", R)
m(y, "                err(f\"{shown_base}-javadoc.jar is not a zip file\")", "                pass", R)
m(y, "                err(f\"{shown_base}.pom declares {shown(artifact)}:{shown(version)}, which the files are not named after\")", "                pass", R)
m(y, "                err(f\"{shown_base}.pom declares the SNAPSHOT version {shown(version)}; a release is final\")", "                pass", R)
m(y, "                err(f\"{shown_base}.pom names a coordinate that is not ASCII; a release version is ASCII only\")", "                pass", R)
m(y, "        elif is_snapshot(base):\n            err(f\"{shown_base} is a SNAPSHOT; a release is final\")", "        elif is_snapshot(base):\n            pass", R)
m(y, "            err(f\"{shown_base} is not ASCII; a release version is ASCII only\")", "            pass", R)
m(y, "        if len(findings) == before:\n            print(", "        if len(findings) == before:\n            print(f\"x\")\n            print(", R)
m(y, "            print(f\"coordinate: {shown_base} - main, sources, javadoc, pom, signatures\")", "            pass", R)
m(y, "    if findings:\n        print(\"::error::release-readiness failed\", file=sys.stderr)\n        return 1", "    if findings:\n        print(\"::error::release-readiness failed\", file=sys.stderr)\n        return 0", R)
m(y, "    if findings:\n        print(\"::error::release-readiness failed\", file=sys.stderr)", "    if findings:\n        pass", R)
m(y, "            err(f\"{shown(n)} is not part of a release: only a main jar, its -sources and -javadoc jars, the pom \"", "            pass\n            _ = (f\"{shown(n)} is not part of a release: only a main jar, its -sources and -javadoc jars, the pom \"", R)
m(y, "            err(f\"{shown(n)} has a control or unassigned character in its name\")", "            pass", R)
m(y, "        wrote = stage(a.stage, t, sorted(f for f in held if f in allowed), err, held)", "        wrote = stage(a.stage, t, sorted(f for f in held if f in allowed), err, None)", R)
m(y, "        wrote = stage(a.stage, t, sorted(f for f in held if f in allowed), err, held)", "        wrote = stage(a.stage, t, sorted(f for f in held if f in allowed)[:-1], err, held)", R)
m(y, "        wrote = stage(a.stage, t, sorted(f for f in held if f in allowed), err, held)", "        wrote = stage(a.stage, t, sorted(f for f in os.listdir(t)), err, held)", R)
m(y, "        err(f\"{shown(dest)} is not an empty directory; the gated files cannot be staged there\")\n        return False", "        err(f\"{shown(dest)} is not an empty directory; the gated files cannot be staged there\")\n        return True", R)
m(y, "        err(f\"{shown(dest)} is not an empty directory; the gated files cannot be staged there\")", "        pass", R)
m(y, "    except BaseException:\n        shutil.rmtree(dest, ignore_errors=True)         # an interrupted stage is not left behind\n        raise", "    except BaseException:\n        raise", R)
m(y, "    except BaseException:\n        shutil.rmtree(dest, ignore_errors=True)         # an interrupted stage is not left behind\n        raise", "    except Exception:\n        shutil.rmtree(dest, ignore_errors=True)         # an interrupted stage is not left behind\n        raise", R)
m(y, "                err(f\"{shown(src)} cannot be staged ({shown(' '.join(str(exc).split()))})\")", "                pass", R)
m(y, "        raise OSError(\"it is not the file that was verified\")", "        pass", R)
m(y, "        raise OSError(\"the verified copy changed\")", "        pass", R)
m(y, "    if os.path.lexists(dest) and (os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", "    if os.path.exists(dest) and (os.path.islink(dest) or not os.path.isdir(dest) or os.listdir(dest)):", R)


# --- staged_manifest.py ------------------------------------------------------------------------------------------------
sm = "staged_manifest"
SM = ["test_staged_manifest", "test_manifest_gate_agreement"]
LINE = 'LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")'
for new in ('LINE = re.compile(r"^([0-9a-fA-F]{64})  (.+)$")', 'LINE = re.compile(r"^([0-9a-f]{63})  (.+)$")',
            'LINE = re.compile(r"^([0-9a-f]{64,})  (.+)$")', 'LINE = re.compile(r"^([0-9a-f]{64}) (.+)$")',
            'LINE = re.compile(r"^([0-9a-f]{64})\\s+(.+)$")', 'LINE = re.compile(r"^([0-9a-f]{64})  (.*)$")',
            'LINE = re.compile(r"^([0-9a-f]{64})  (.+)$", re.I)', 'LINE = re.compile(r"([0-9a-f]{64})  (.+)$")',
            'LINE = re.compile(r"^([0-9a-z]{64})  (.+)$")'):
    m(sm, LINE, new, SM)
m(sm, "CHUNK = 1 << 20", "CHUNK = 0", SM)
m(sm, "CHUNK = 1 << 20", "CHUNK = 1 << 2", SM)
# shown(): a name is printed without a control character, but with its spaces
SH = 'return "".join(c if c.isprintable() and unicodedata.category(c)[0] not in "CZ" or c == " " else'
m(sm, SH, 'return "".join(c if True else', SM)
m(sm, SH, 'return "".join(c if c.isprintable() and unicodedata.category(c)[0] not in "CZ" else', SM)
m(sm, SH, 'return "".join(c if unicodedata.category(c)[0] not in "CZ" or c == " " else', SM)
m(sm, SH, 'return "".join(c if c.isprintable() or c == " " else', SM)
m(sm, SH, 'return "".join(c if c.isprintable() and unicodedata.category(c)[0] not in "C" or c == " " else', SM)
m(sm, SH, 'return "".join(c if c.isprintable() and unicodedata.category(c)[0] in "CZ" or c == " " else', SM)
# plain_name(): the names of the closed set are plain file names
PN = r'if name in (".", "..") or name.startswith(".") or "/" in name or "\\" in name or "\x00" in name:'
m(sm, PN, r'if name.startswith(".") or "/" in name or "\\" in name or "\x00" in name:', SM)
m(sm, PN, r'if name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:', SM)
m(sm, PN, r'if name in (".", "..") or name.startswith(".") or "\\" in name or "\x00" in name:', SM)
m(sm, PN, r'if name in (".", "..") or name.startswith(".") or "/" in name or "\x00" in name:', SM)
m(sm, PN, r'if name in (".", "..") or name.startswith(".") or "/" in name or "\\" in name:', SM)
m(sm, PN, r'if name in (".", "..") or name.startswith("..") or "/" in name or "\\" in name or "\x00" in name:', SM)
m(sm, PN, r'if name in ("..",) or name.startswith(".") or "/" in name or "\\" in name or "\x00" in name:', SM)
PR = 'return not any(unicodedata.category(c)[0] in "CZ" and c != " " for c in name) and name == name.strip()'
m(sm, PR, 'return not any(unicodedata.category(c)[0] in "C" and c != " " for c in name) and name == name.strip()', SM)
m(sm, PR, 'return not any(unicodedata.category(c)[0] in "Z" and c != " " for c in name) and name == name.strip()', SM)
m(sm, PR, 'return not any(unicodedata.category(c)[0] in "CZ" for c in name) and name == name.strip()', SM)
m(sm, PR, 'return not any(unicodedata.category(c)[0] in "CZ" and c != " " for c in name)', SM)
m(sm, PR, 'return not any(unicodedata.category(c)[0] in "CZ" and c != " " for c in name) and name == name.lstrip()', SM)
m(sm, PR, 'return not any(unicodedata.category(c)[0] in "CZ" and c != " " for c in name) and name == name.rstrip()', SM)
m(sm, PR, 'return not any(unicodedata.category(c)[0] in "CZ" and c != " " for c in name) or name == name.strip()', SM)
m(sm, PR, 'return any(unicodedata.category(c)[0] in "CZ" and c != " " for c in name) and name == name.strip()', SM)
# digest(): one open, no link followed, never blocks, the descriptor says what the file is, all of it is read
OP = "fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)"
m(sm, OP, "fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)", SM)
m(sm, OP, "fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)", SM)
m(sm, OP, "fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK)", SM)
m(sm, OP, "fd = os.open(path, os.O_NOFOLLOW | os.O_NONBLOCK)", SM)
m(sm, "        if not stat.S_ISREG(os.fstat(fd).st_mode):\n            raise OSError(\"not a regular file\")",
  "        if False:\n            raise OSError(\"not a regular file\")", SM)
m(sm, "        if not stat.S_ISREG(os.fstat(fd).st_mode):", "        if stat.S_ISREG(os.fstat(fd).st_mode):", SM)
m(sm, "        if not stat.S_ISREG(os.fstat(fd).st_mode):", "        if not stat.S_ISDIR(os.fstat(fd).st_mode):", SM)
m(sm, "            h.update(block)", "            pass", SM)
m(sm, "            h.update(block)", "            h.update(block[:-1])", SM)
m(sm, "            if not block:\n                return h.hexdigest()", "            if not block:\n                return \"\"", SM)
m(sm, "        h = hashlib.sha256()", "        h = hashlib.sha1()", SM)
m(sm, "    finally:\n        os.close(fd)", "    finally:\n        pass", SM)
m(sm, "            block = os.read(fd, CHUNK)", "            block = os.read(fd, CHUNK)[:100]", SM)
# scan(): the directory is a real directory, and every entry is a plain regular file with a plain name
ISDIR = "        if os.path.islink(directory) or not os.path.isdir(directory):"
m(sm, ISDIR, "        if not os.path.isdir(directory):", SM)
m(sm, ISDIR, "        if os.path.islink(directory):", SM)
m(sm, ISDIR, "        if os.path.islink(directory) and not os.path.isdir(directory):", SM)
m(sm, "            err(f\"{shown(directory)} is not a directory\")\n            return None", "            err(f\"{shown(directory)} is not a directory\")\n            return {}", SM)
m(sm, "            err(f\"{shown(directory)} is not a directory\")", "            pass", SM)
m(sm, "        err(f\"{shown(directory)} cannot be read ({exc})\")\n        return None", "        err(f\"{shown(directory)} cannot be read ({exc})\")\n        return {}", SM)
m(sm, "        info = os.lstat(path)", "        info = os.stat(path)", SM)
NOTREG = "        if not stat.S_ISREG(info.st_mode):\n            err(f\"{shown(name)} is not a regular file; only regular files are released\")"
m(sm, NOTREG + "\n            bad = True", NOTREG, SM)
m(sm, NOTREG, NOTREG.replace("if not stat.S_ISREG(info.st_mode):", "if False:"), SM)
m(sm, NOTREG, NOTREG.replace("if not stat.S_ISREG(info.st_mode):", "if stat.S_ISDIR(info.st_mode):"), SM)
m(sm, "        elif info.st_nlink != 1:", "        elif info.st_nlink > 2:", SM)
m(sm, "        elif info.st_nlink != 1:", "        elif False:", SM)
m(sm, "        elif info.st_nlink != 1:", "        elif info.st_nlink < 1:", SM)
HARD = "            err(f\"{shown(name)} is a hard link; only plain files are released\")"
m(sm, HARD + "\n            bad = True", HARD, SM)
m(sm, "        elif not plain_name(name):", "        elif plain_name(name):", SM)
m(sm, "        elif not plain_name(name):", "        elif False:", SM)
PLAIN = "            err(f\"{shown(name)} is not a plain file name\")"
m(sm, PLAIN + "\n            bad = True", PLAIN, SM)
m(sm, "                found[name] = digest(path)", "                found[name] = \"\"", SM)
CANNOT = "                err(f\"{shown(name)} cannot be read ({exc})\")"
m(sm, CANNOT + "\n                bad = True", CANNOT, SM)
m(sm, "    return None if bad else found", "    return found", SM)
m(sm, "    return None if bad else found", "    return None", SM)
m(sm, "    return None if bad else found", "    return None if not bad else found", SM)
# closed_set(): every name belongs to a coordinate, and every coordinate is whole
BASES = '    bases = {n[:-len(".jar")] for n in names\n             if n.endswith(".jar") and not n.endswith(("-sources.jar", "-javadoc.jar"))}'
m(sm, BASES, BASES.replace('n.endswith(".jar") and not', 'n.endswith(".jar") or not'), SM)
m(sm, BASES, BASES.replace('("-sources.jar", "-javadoc.jar")', '("-javadoc.jar",)'), SM)
m(sm, BASES, BASES.replace('("-sources.jar", "-javadoc.jar")', '("-sources.jar",)'), SM)
m(sm, BASES, BASES.replace('n[:-len(".jar")]', 'n[:-3]'), SM)
m(sm, BASES, BASES.replace('n.endswith(".jar") and not n.endswith(("-sources.jar", "-javadoc.jar"))', 'n.endswith(".pom")'), SM)
m(sm, BASES, BASES.replace(' and not n.endswith(("-sources.jar", "-javadoc.jar"))', ''), SM)
EXP = 'for f in (f"{base}.jar", f"{base}-sources.jar", f"{base}-javadoc.jar", f"{base}.pom"):'
m(sm, EXP, 'for f in (f"{base}.jar", f"{base}-sources.jar", f"{base}.pom"):', SM)
m(sm, EXP, 'for f in (f"{base}.jar", f"{base}-javadoc.jar", f"{base}.pom"):', SM)
m(sm, EXP, 'for f in (f"{base}.jar", f"{base}-sources.jar", f"{base}-javadoc.jar"):', SM)
m(sm, EXP, 'for f in (f"{base}.jar", f"{base}-sources.jar", f"{base}-javadoc.jar", f"{base}.pom", f"{base}-tests.jar"):', SM)
m(sm, "            expected.update((f, f + \".asc\"))", "            expected.update((f,))", SM)
m(sm, "            expected.update((f, f + \".asc\"))", "            expected.update((f, f + \".sig\"))", SM)
m(sm, "            expected.update((f, f + \".asc\"))", "            expected.update((f, f + \".asc\", f + \".sha1\"))", SM)
m(sm, "        if n == \"pom.xml\":", "        if n == \"pom.xml\" and False:", SM)
POMX = "            err(\"pom.xml is not part of a release: nothing a project would build from is staged\")"
m(sm, POMX + "\n            ok = False", POMX, SM)
m(sm, "        elif n not in expected:", "        elif n in expected:", SM)
m(sm, "        elif n not in expected:", "        elif False:", SM)
NOTPART = "\"the pom and their .asc signatures are released\")"
m(sm, NOTPART + "\n            ok = False", NOTPART, SM)
m(sm, "    for want in sorted(expected - set(names)):", "    for want in sorted(expected & set(names)):", SM)
MISSING = "        err(f\"{shown(want)} is missing - a release holds all eight files of a coordinate\")"
m(sm, MISSING + "\n        ok = False", MISSING, SM)
m(sm, "    if not bases:", "    if bases:", SM)
m(sm, "    if not bases:", "    if False:", SM)
m(sm, "        err(\"no main jar is staged\")\n        ok = False", "        err(\"no main jar is staged\")", SM)
# parse(): the manifest text is the canonical lines and nothing else
m(sm, "    if not text.strip():", "    if not text:", SM)
m(sm, "    if not text.strip():", "    if False:", SM)
m(sm, "        err(\"the manifest is empty\")\n        return None", "        err(\"the manifest is empty\")\n        return {}", SM)
m(sm, "    for raw in text.split(\"\\n\"):", "    for raw in text.splitlines():", SM)
m(sm, "    for raw in text.split(\"\\n\"):", "    for raw in text.strip().split(\"\\n\"):", SM)
m(sm, "        if not m or not plain_name(m.group(2)):", "        if not m:", SM)
m(sm, "        if not m or not plain_name(m.group(2)):", "        if not plain_name(m.group(2)):", SM)
m(sm, "        if not m or not plain_name(m.group(2)):", "        if not m and not plain_name(m.group(2)):", SM)
MAL = "            err(f\"manifest line is malformed: {shown(raw)[:120]}\")"
m(sm, MAL + "\n            return None", MAL + "\n            continue", SM)
m(sm, "{shown(raw)[:120]}", "{shown(raw)[:0]}", SM)
m(sm, "{shown(raw)[:120]}", "{shown(raw)[:1200]}", SM)
m(sm, "{shown(raw)[:120]}", "{raw[:120]}", SM)
m(sm, "        if m.group(2) in out:", "        if False:", SM)
m(sm, "        if m.group(2) in out:", "        if m.group(2) not in out:", SM)
TWICE = "            err(f\"manifest lists {shown(m.group(2))} twice\")"
m(sm, TWICE + "\n            return None", TWICE, SM)
m(sm, "        out[m.group(2)] = m.group(1)", "        out[m.group(2)] = m.group(1).upper()", SM)
m(sm, "        out[m.group(2)] = m.group(1)", "        out[m.group(1)] = m.group(2)", SM)
# render() and main()
REND = "    return \"\".join(f\"{h}  {n}\\n\" for n, h in sorted(found.items()))"
m(sm, REND, REND.replace("{h}  {n}", "{h} {n}"), SM)
m(sm, REND, REND.replace("{n}\\n", "{n}"), SM)
m(sm, REND, REND.replace("{h}  {n}", "{n}  {h}"), SM)
m(sm, REND, REND.replace("sorted(found.items())", "sorted(found.items(), reverse=True)"), SM)
m(sm, REND, REND.replace("sorted(found.items())", "list(found.items())[::-1]"), SM)
m(sm, "    sub = p.add_subparsers(dest=\"cmd\", required=True)", "    sub = p.add_subparsers(dest=\"cmd\")", SM)
m(sm, "    c.add_argument(\"--dir\", required=True)", "    c.add_argument(\"--dir\", default=\".\")", SM)
m(sm, "    c.add_argument(\"--output\", required=True)", "    c.add_argument(\"--output\", default=\"/dev/null\")", SM)
m(sm, "    c.add_argument(\"--name\", default=\"manifest\")", "    c.add_argument(\"--name\", default=\"m\")", SM)
m(sm, "    v.add_argument(\"--dir\", required=True)", "    v.add_argument(\"--dir\", default=\".\")", SM)
m(sm, "    v.add_argument(\"--manifest-env\", required=True)", "    v.add_argument(\"--manifest-env\", default=\"MANIFEST\")", SM)
m(sm, "    if found is None:\n        return 1", "    if found is None:\n        return 0", SM)
m(sm, "    if found is None:\n        return 1", "    if False:\n        return 1", SM)
m(sm, "        if not found:\n            err(\"nothing is staged\")\n            return 1", "        if found:\n            err(\"nothing is staged\")\n            return 1", SM)
m(sm, "            err(\"nothing is staged\")\n            return 1", "            err(\"nothing is staged\")\n            return 0", SM)
m(sm, "        if not found:\n            err(\"nothing is staged\")", "        if False:\n            err(\"nothing is staged\")", SM)
DELIM = "        delimiter = \"MANIFEST_\" + hashlib.sha256(text.encode()).hexdigest()[:16]"
m(sm, DELIM, "        delimiter = \"MANIFEST_\"", SM)
m(sm, DELIM, DELIM.replace("[:16]", "[:4]"), SM)
m(sm, DELIM, "        delimiter = \"EOF\"", SM)
m(sm, DELIM, DELIM.replace("text.encode()", "b\"\""), SM)
m(sm, "        with open(a.output, \"a\", encoding=\"utf-8\") as out:", "        with open(a.output, \"w\", encoding=\"utf-8\") as out:", SM)
WRITE = "            out.write(f\"{a.name}<<{delimiter}\\n{text}{delimiter}\\n\")"
m(sm, WRITE, WRITE.replace("{delimiter}\\n\")", "{delimiter}\")"), SM)
m(sm, WRITE, "            out.write(f\"{a.name}={text}\")", SM)
m(sm, WRITE, WRITE.replace("{text}{delimiter}", "{text}\\n{delimiter}"), SM)
m(sm, WRITE, WRITE.replace("{a.name}<<", "{a.name}="), SM)
DIG = "            out.write(f\"{a.name}-digest={whole}\\n{a.name}-id={whole[:12]}\\n\")"
m(sm, DIG, DIG.replace("[:12]", "[:11]"), SM)
m(sm, DIG, DIG.replace("[:12]", "[:13]"), SM)
m(sm, DIG, DIG.replace("{whole}", "{whole[:63]}"), SM)
m(sm, DIG, DIG.replace("[:12]", "[-12:]"), SM)
m(sm, DIG, DIG.replace("-digest=", "_digest=").replace("-id=", "_id="), SM)
m(sm, "            whole = hashlib.sha256(text.encode()).hexdigest()", "            whole = hashlib.sha256(text.encode()[:-1]).hexdigest()", SM)
m(sm, "        sys.stdout.write(text)\n        return 0", "        return 0", SM)
m(sm, "        sys.stdout.write(text)\n        return 0", "        sys.stdout.write(text)\n        return 1", SM)
m(sm, "    want = parse(os.environ.get(a.manifest_env, \"\"), err)", "    want = parse(os.environ[a.manifest_env], err)", SM)
m(sm, "    want = parse(os.environ.get(a.manifest_env, \"\"), err)", "    want = parse(os.environ.get(a.manifest_env, \"x\"), err)", SM)
m(sm, "    want = parse(os.environ.get(a.manifest_env, \"\"), err)", "    want = parse(os.environ.get(\"MANIFEST\", \"\"), err)", SM)
m(sm, "    if want is None:\n        return 1", "    if want is None:\n        return 0", SM)
SETOP = "    for n in sorted(set(found) | set(want)):"
m(sm, SETOP, "    for n in sorted(set(found) & set(want)):", SM)
m(sm, SETOP, "    for n in sorted(set(found)):", SM)
m(sm, SETOP, "    for n in sorted(set(want)):", SM)
NOTIN = "            err(f\"{shown(n)} is not in the manifest\")"
m(sm, NOTIN + "\n            problems += 1", NOTIN, SM)
NOTDIR = "            err(f\"{shown(n)} is in the manifest and not in the directory\")"
m(sm, NOTDIR + "\n            problems += 1", NOTDIR, SM)
DIFFERS = "            err(f\"{shown(n)} differs from the manifest\")"
m(sm, DIFFERS + "\n            problems += 1", DIFFERS, SM)
m(sm, "        elif found[n] != want[n]:", "        elif found[n] == want[n]:", SM)
m(sm, "        elif found[n] != want[n]:", "        elif found[n].lower() != want[n].lower():", SM)
m(sm, "        elif found[n] != want[n]:", "        elif found[n][:32] != want[n][:32]:", SM)
m(sm, "        elif found[n] != want[n]:", "        elif found[n][32:] != want[n][32:]:", SM)
m(sm, "        if n not in want:\n            err(", "        if n in want:\n            err(", SM)
m(sm, "    if not closed_set(sorted(found), err):\n        problems += 1", "    if not closed_set(sorted(found), err):\n        pass", SM)
m(sm, "    if not closed_set(sorted(found), err):\n        problems += 1", "    if closed_set(sorted(found), err):\n        problems += 1", SM)
m(sm, "    if not closed_set(sorted(found), err):", "    if not closed_set(sorted(want), err):", SM)
FIN = "        print(\"::error::the staged files are not what the gate staged\", file=sys.stderr)"
m(sm, FIN + "\n        return 1", FIN + "\n        return 0", SM)
m(sm, "    if problems:\n" + FIN, "    if problems:\n        pass", SM)
m(sm, "    if problems:\n        print(", "    if not problems:\n        print(", SM)
m(sm, "    if problems:\n        print(", "    if problems > 1:\n        print(", SM)
m(sm, "    print(f\"ok - {len(found)} files match the manifest\")", "    print(f\"ok - {len(want)} files match the manifest\")", SM)
m(sm, "    print(f\"ok - {len(found)} files match the manifest\")", "    print(f\"ok - {len(found) + 1} files match the manifest\")", SM)
m(sm, "    print(f\"ok - {len(found)} files match the manifest\")\n    return 0", "    print(f\"ok - {len(found)} files match the manifest\")\n    return 1", SM)
m(sm, "        print(f\"::error::{msg}\", file=sys.stderr)", "        print(f\"::warning::{msg}\", file=sys.stderr)", SM)
m(sm, "        print(f\"::error::{msg}\", file=sys.stderr)", "        print(f\"::error::{msg}\")", SM)


# --- mutants that are equivalent to the script ---------------------------------------------------------------------------
# A change that no input can make observable is not a guard to protect. Each is dropped from M with the reason it cannot be
# told from the original; `test_mutations` checks that each still applies to the script exactly once, so a refactor that
# changes the code under one of these puts it back in front of a reviewer.
EQUIVALENT: list = []                                            # (script, old, new, why)


def equivalent(script, old_has, new_has, why):
    hits = [e for e in M if e[0] == script and old_has in e[1] and new_has in e[2]]
    assert len(hits) == 1, (script, old_has, new_has, len(hits))
    M.remove(hits[0])
    EQUIVALENT.append((*hits[0][:3], why))
equivalent("check_release_readiness", "        built[base] = coordinate\n", "(None, None, None)",
           "`built` is written once per coordinate and never read afterwards, so what is stored in it cannot reach an output")
equivalent("check_release_readiness", "    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)", "    fd = os.open(path, os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)",
           "os.O_RDONLY is 0 on every platform the workflow runs on")
equivalent("check_release_readiness", "            elif want != main_jar and not os.path.lexists(path):", "            elif not os.path.lexists(path):",
           "a main jar was listed from the directory a moment before, so it exists unless it vanishes in between; the sources, javadoc and pom "
           "names are the only ones that can be absent")
equivalent("check_release_readiness", "            elif os.path.lexists(path):\n                if want", "            else:\n                if want",
           "the branch before it takes every path that does not exist, so what reaches this one exists")
equivalent("resolve_release", '    if a.upload == "true" and a.target == "none":', '    if a.upload == "true" and a.target != "github-packages":',
           "the target is validated to be `none` or `github-packages` before this line, so `== none` and `!= github-packages` select the same case")
equivalent("check_release_profile", "           for p in plugins + managed):", "           for p in plugins + managed + builds):",
           "a <build> element has no <artifactId> child, so adding the build elements to the sequence adds nothing that can match")

equivalent("staged_manifest", 'LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")', 'LINE = re.compile(r"([0-9a-f]{64})  (.+)$")',
           "`re.match` anchors at the start of the string already, so the leading `^` changes nothing")
equivalent("staged_manifest", "CHUNK = 1 << 20", "CHUNK = 1 << 2",
           "the chunk size only changes how many reads a file takes; the digest of the bytes is the same")
equivalent("staged_manifest", 'return "".join(c if c.isprintable() and', 'not in "C" or c == " " else',
           "`str.isprintable` is already false for every character of category Z but the ASCII space, so the category test adds nothing for Z")
equivalent("staged_manifest", 'return "".join(c if c.isprintable() and', 'return "".join(c if c.isprintable() or c == " " else',
           "`str.isprintable` is false for every character of category C and Z but the ASCII space, so the category test is redundant with it")
equivalent("staged_manifest", 'return "".join(c if c.isprintable() and', 'return "".join(c if unicodedata.category(c)[0] not in "CZ" or c == " " else',
           "the characters `str.isprintable` rejects are exactly those of category C or Z other than the ASCII space, so either test alone is enough")
equivalent("staged_manifest", 'if name in (".", "..") or name.startswith(".")', 'if name.startswith(".") or "/" in name',
           "`..` starts with a dot, so the explicit `.` and `..` members are covered by the leading-dot test")
equivalent("staged_manifest", 'if name in (".", "..") or name.startswith(".")', 'if name in ("..",) or name.startswith(".")',
           "`.` starts with a dot, so dropping it from the explicit members changes nothing")
equivalent("staged_manifest", 'if name in (".", "..") or name.startswith(".")', 'or "\\\\" in name:',
           "a NUL cannot be in a name read from a directory or in an environment variable")
equivalent("staged_manifest", "fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)", "fd = os.open(path, os.O_NOFOLLOW | os.O_NONBLOCK)",
           "os.O_RDONLY is 0 on every platform the workflow runs on")
equivalent("staged_manifest", 'err("no main jar is staged")\n        ok = False', 'err("no main jar is staged")',
           "no main jar is only possible with no name at all, which the manifest (never empty) always contradicts first, or with names that "
           "are each already refused as not part of a release, so the result of closed_set is false either way")
equivalent("staged_manifest", "        elif found[n] != want[n]:", "elif found[n].lower() != want[n].lower():",
           "both digests are lowercase hexadecimal, the manifest parser refusing anything else, so folding case changes no comparison")
equivalent("staged_manifest", 'print(f"ok - {len(found)} files match the manifest")', "{len(want)} files match",
           "the line is printed only when every name is in both mappings, so they have the same length")
