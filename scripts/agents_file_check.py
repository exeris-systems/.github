#!/usr/bin/env python3
"""Agent-file checker — ADR-085 §I.29, agents-md-schema.md hard rules 1, 2, 4, 5, 8.

Replaces claude_md_check.py, which enforced the superseded CLAUDE.md schema: a fixed list of
verbatim headings. The current schema puts the canonical entry point at AGENTS.md, the canonical
semantics under .agents/, and leaves the prose and heading names to the repository — so this
checker verifies structure, size, skill layout, manifest pinning and adapter discipline, and
deliberately checks nothing about wording.

Not mechanically checkable, and therefore left to review ([L2] in the schema): whether AGENTS.md
covers its six concerns in order, whether a rule is encoded as the right kind of artefact, and
whether a reference is linked rather than copied.
"""
from __future__ import annotations
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import Report, read_frontmatter

ROOT_LIMIT = 8 * 1024          # rule 1: AGENTS.md is an index and a safety boundary
NESTED_LIMIT = 4 * 1024        # nested AGENTS.md add scope-specific rules only
ADAPTER_MAX_LINES = 20         # a provider entry file points at the canonical source

# Provider directories are adapters (rule 7). Semantic content must not be authored here (rule 2).
PROVIDER_DIRS = [".claude", ".github", ".codex", ".cursor", ".gemini", ".clinerules"]
# Subtrees inside them that carry semantics rather than operational configuration.
SEMANTIC_SUBDIRS = ["agents", "prompts", "skills", "rules", "policies", "workflows"]
# Rule 7 keeps operational configuration provider-owned: GitHub Actions are not a semantic adapter,
# and .github/workflows collides by name with the semantic .agents/workflows.
OPERATIONAL = {os.path.join(".github", "workflows")}
# Provider entry files that may exist only as thin adapters.
ADAPTER_FILES = ["CLAUDE.md", "GEMINI.md", ".cursorrules", ".github/copilot-instructions.md"]
# A generated adapter says so and says where it came from (rule 7).
GENERATED = re.compile(r"do[- ]not[- ]edit|generated from|@generated", re.I)

SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# rule 8: an import is pinned to a version, never to a moving target.
FLOATING = re.compile(r"^(latest|main|master|head|\*|~|\^)", re.I)


def check_agents_md(path: str, rep: Report, limit: int, kind: str):
    size = os.path.getsize(path)
    if size > limit:
        rep.error(path, f"{kind} AGENTS.md is {size // 1024} KB (limit {limit // 1024} KB) — "
                        f"move detail into .agents/ or docs/ and link it", rule="size")
    text = open(path, encoding="utf-8", errors="replace").read()
    if not text.strip():
        rep.error(path, "AGENTS.md is empty", rule="content")
    return text


def check_skill(d: str, rep: Report):
    """rule 4 — .agents/skills/<name>/SKILL.md, with name and a precise description."""
    name = os.path.basename(d)
    path = os.path.join(d, "SKILL.md")
    rel = os.path.relpath(path)
    if not os.path.exists(path):
        rep.error(os.path.relpath(d), f"skill directory '{name}' has no SKILL.md", rule="skill-path")
        return
    if not SKILL_NAME.match(name):
        rep.error(rel, f"skill directory '{name}' is not lowercase kebab-case", rule="skill-path")
    fm, _ = read_frontmatter(path)
    if fm is None or fm.get("__invalid__"):
        rep.error(rel, "SKILL.md needs YAML frontmatter with 'name' and 'description'", rule="skill-metadata")
        return
    if fm.get("name") != name:
        rep.error(rel, f"frontmatter name '{fm.get('name')}' does not match the directory '{name}'",
                  rule="skill-metadata")
    desc = (fm.get("description") or "").strip()
    if not desc:
        rep.error(rel, "SKILL.md frontmatter needs a 'description'", rule="skill-metadata")
    elif len(desc) < 40:
        rep.warning(rel, "description should name both what the skill does and when it applies "
                         f"(got {len(desc)} characters)", rule="skill-metadata")


def check_manifest(path: str, rep: Report):
    """rules 5 and 8 — the manifest composes, and imports are pinned to an approved bundle."""
    import yaml
    rel = os.path.relpath(path)
    try:
        data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception as e:
        rep.error(rel, f"manifest.yaml is not valid YAML ({type(e).__name__})", rule="manifest")
        return
    if not isinstance(data, dict):
        rep.error(rel, "manifest.yaml must be a mapping", rule="manifest")
        return
    for key in ("version", "imports"):
        if key not in data:
            rep.warning(rel, f"manifest.yaml has no '{key}' key", rule="manifest")
    imports = data.get("imports") or []
    if isinstance(imports, dict):
        imports = [{"name": k, **(v if isinstance(v, dict) else {"version": v})} for k, v in imports.items()]
    for imp in imports if isinstance(imports, list) else []:
        if not isinstance(imp, dict):
            rep.error(rel, f"import entry is not a mapping: {imp!r}", rule="pinned-import")
            continue
        nm = imp.get("name", "?")
        ver = str(imp.get("version", "")).strip()
        if not ver:
            rep.error(rel, f"import '{nm}' has no version — rule 8 requires a version-pinned bundle",
                      rule="pinned-import")
        elif FLOATING.match(ver):
            rep.error(rel, f"import '{nm}' is pinned to a moving target ('{ver}')", rule="pinned-import")
        src = str(imp.get("url", "") or imp.get("source", ""))
        if src.startswith(("http://", "https://")) and not (imp.get("checksum") or imp.get("sha256")):
            rep.error(rel, f"import '{nm}' fetches from {src} without a checksum", rule="pinned-import")


def check_adapters(rep: Report, strict: bool):
    """rules 2 and 7 — provider directories adapt; they do not author."""
    level = rep.error if strict else rep.warning
    for pf in ADAPTER_FILES:
        if not os.path.exists(pf):
            continue
        lines = [l for l in open(pf, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
        if len(lines) > ADAPTER_MAX_LINES and not GENERATED.search("\n".join(lines[:10])):
            level(pf, f"{pf} has {len(lines)} non-empty lines — a provider entry file is a thin adapter "
                      f"(<= {ADAPTER_MAX_LINES} lines) pointing at AGENTS.md, or is generated and says so",
                  rule="adapter")
    for pd in PROVIDER_DIRS:
        for sub in SEMANTIC_SUBDIRS:
            d = os.path.join(pd, sub)
            if not os.path.isdir(d) or d in OPERATIONAL:
                continue
            authored = []
            for dirpath, _, files in os.walk(d):
                for f in files:
                    if not f.endswith((".md", ".mdc", ".yaml", ".yml")):
                        continue
                    p = os.path.join(dirpath, f)
                    head = open(p, encoding="utf-8", errors="replace").read(600)
                    if not GENERATED.search(head):
                        authored.append(os.path.relpath(p))
            if authored:
                level(d, f"{len(authored)} file(s) under {d}/ carry no generated-from marker — "
                         f"semantic content belongs in .agents/ (first: {authored[0]})", rule="adapter")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--strict-adapters", action="store_true",
                    help="fail on provider-authored semantics (schema rule 2 — error once the renderer is adopted)")
    a = ap.parse_args()
    os.chdir(a.root)
    rep = Report("agents_file_check")

    if not os.path.exists("AGENTS.md"):
        rep.error("AGENTS.md", "AGENTS.md is required at the repository root and is the canonical "
                               "agent entry point (agents-md-schema.md rule 1)", rule="present")
    else:
        rep.checked += 1
        text = check_agents_md("AGENTS.md", rep, ROOT_LIMIT, "root")
        if os.path.isdir(".agents") and ".agents" not in text:
            rep.warning("AGENTS.md", "AGENTS.md does not point at .agents/, which holds this repo's "
                                     "canonical semantics", rule="discovery")

    for dirpath, dirnames, files in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "target", "build", "dist")]
        if "AGENTS.md" in files and os.path.relpath(dirpath) != ".":
            rep.checked += 1
            check_agents_md(os.path.join(dirpath, "AGENTS.md"), rep, NESTED_LIMIT, "nested")

    if os.path.isdir(".agents"):
        skills = os.path.join(".agents", "skills")
        if os.path.isdir(skills):
            for name in sorted(os.listdir(skills)):
                d = os.path.join(skills, name)
                if os.path.isdir(d):
                    rep.checked += 1
                    check_skill(d, rep)
        for dirpath, _, files in os.walk(".agents"):
            for f in files:
                if f == "SKILL.md":
                    p = os.path.join(dirpath, f)
                    parent = os.path.dirname(os.path.dirname(p))
                    if os.path.normpath(parent) != os.path.normpath(skills):
                        rep.error(os.path.relpath(p),
                                  "a skill lives at .agents/skills/<name>/SKILL.md", rule="skill-path")
        manifest = os.path.join(".agents", "manifest.yaml")
        if os.path.exists(manifest):
            rep.checked += 1
            check_manifest(manifest, rep)
        else:
            rep.error(manifest, ".agents/ has no manifest.yaml — it records composition and the "
                                "version-pinned bundles the repo imports (rules 5, 8)", rule="manifest")

    check_adapters(rep, a.strict_adapters)
    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
