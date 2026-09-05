"""Shared helpers for the Exeris docs-guardrails validators (ADR-085 §J).

Dependency-free except PyYAML. Every validator:
  * emits GitHub workflow annotations (::error / ::warning) so findings show on the PR diff,
  * appends a Markdown table to $GITHUB_STEP_SUMMARY when set,
  * exits 1 only on errors (warnings never fail a build).
"""
from __future__ import annotations
import os, re, subprocess, sys
from dataclasses import dataclass, field

# Organisation repositories whose content is enterprise-private under ADR-020. A public file must never
# link into these. The set names GitHub repositories only: local working directories are out of scope
# here, because nothing that never reaches a remote can be linked to from a published document, and this
# file ships in a public repository where the set itself would otherwise disclose them.
PRIVATE_REPOS = {
    "exeris-kernel-enterprise", "exeris-benchmarks-enterprise", "exeris-enterprise-observability",
    "exeris-telemetry-spec",
}

DOC_TYPES = {
    "adr", "adr-link", "rfc", "research", "design-note", "subsystem", "module", "tutorial", "howto",
    "reference", "explanation", "operations", "release-notes", "changelog", "roadmap",
    "benchmark-report", "claims", "methodology", "refactor-note", "working-note", "migration-guide",
}
STATUSES = {"draft", "active", "stale", "superseded", "retracted"}
VISIBILITY = {"public", "enterprise-private"}

ADR_FILE = re.compile(r"^ADR-(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
ADR_LINK = re.compile(r"^ADR-(\d{3})\.link\.md$")
RFC_FILE = re.compile(r"^RFC-\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
RESEARCH_FILE = re.compile(r"^RESEARCH-\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


@dataclass
class Finding:
    level: str          # "error" | "warning"
    path: str
    msg: str
    line: int = 1
    rule: str = ""


@dataclass
class Report:
    name: str
    findings: list[Finding] = field(default_factory=list)
    checked: int = 0

    def error(self, path, msg, line=1, rule=""):
        self.findings.append(Finding("error", path, msg, line, rule))

    def warning(self, path, msg, line=1, rule=""):
        self.findings.append(Finding("warning", path, msg, line, rule))

    @property
    def errors(self):
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.level == "warning"]

    def emit(self) -> int:
        for f in self.findings:
            print(f"::{f.level} file={f.path},line={f.line},title={self.name}{(' ' + f.rule) if f.rule else ''}::{f.msg}")
        summary = [f"## {self.name}", "",
                   f"Checked **{self.checked}** files — **{len(self.errors)} errors**, {len(self.warnings)} warnings.", ""]
        if self.findings:
            summary += ["| Level | File | Line | Rule | Message |", "|:--|:--|--:|:--|:--|"]
            for f in sorted(self.findings, key=lambda x: (x.level != "error", x.path, x.line)):
                summary.append(f"| {f.level} | `{f.path}` | {f.line} | {f.rule} | {f.msg} |")
        text = "\n".join(summary) + "\n"
        step = os.environ.get("GITHUB_STEP_SUMMARY")
        if step:
            with open(step, "a", encoding="utf-8") as fh:
                fh.write(text)
        else:
            print(text)
        return 1 if self.errors else 0


def read_frontmatter(path: str):
    """Return (dict | None, body_start_line). None when the file has no leading '---' block."""
    import yaml
    try:
        text = open(path, encoding="utf-8").read()
    except UnicodeDecodeError:
        return None, 1
    if not text.startswith("---\n"):
        return None, 1
    end = text.find("\n---", 4)
    if end < 0:
        return None, 1
    try:
        data = yaml.safe_load(text[4:end]) or {}
    except Exception:
        return {"__invalid__": True}, 1
    return data, text[:end].count("\n") + 2


def changed_files(base: str | None) -> set[str] | None:
    """Files changed vs base ref (for ramp mode). None when no base is given."""
    if not base:
        return None
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True, text=True)
    if out.returncode != 0:
        out = subprocess.run(["git", "diff", "--name-only", base], capture_output=True, text=True)
    return {l.strip() for l in out.stdout.splitlines() if l.strip()}


# Documentation is every Markdown file in the repository except the four kinds below. The default
# lint root is the repository, so what is *not* documentation has to be named here rather than left
# out of an opt-in path list — a path forgotten from such a list is silently unchecked, which is how
# exeris-docs/standards/ went unlinted while the standard it holds was being made binding.
GENERATED_DIRS = ("node_modules", "target", "build", "dist", ".docusaurus", ".next", "out")
# The guardrail bundle is checked out into the workspace it lints; .git is not content.
TOOLING_DIRS = (".git", ".guardrails")
# Agent trees carry their own schema (agents-md-schema.md) and are checked by agents_file_check.py.
# A SKILL.md cannot also carry the docs frontmatter without breaking the agent runtime that reads it.
AGENT_DIRS = (".agents", ".claude", ".codex", ".cursor", ".gemini", ".clinerules")
# .github is not wholly an agent tree: it holds CONTRIBUTING.md and the PR template, which are
# documentation, alongside the semantic subdirectories agents_file_check.py governs (its
# SEMANTIC_SUBDIRS). Skip those by path, not the whole provider directory.
SKIP_PATHS = tuple(os.path.join(".github", d) for d in
                   ("agents", "prompts", "skills", "rules", "policies", "instructions"))
# Local-only working material beyond the "_" prefix (handled below): exeris-kernel keeps untracked
# private drafts in docs/local-only/. Excluded so a local run sees what CI sees.
LOCAL_ONLY_DIRS = ("local-only",)

SKIP_DIRS = GENERATED_DIRS + TOOLING_DIRS + AGENT_DIRS + LOCAL_ONLY_DIRS
# Links are checked everywhere content is published, agent trees and .github included: a rotted link
# in CONTRIBUTING.md is a rotted link. Only generated output and non-content are skipped.
LINK_SKIP_DIRS = GENERATED_DIRS + TOOLING_DIRS


def walk_md(root: str, skip=SKIP_DIRS, skip_paths=SKIP_PATHS):
    for d, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in skip and not x.startswith("_")]  # _inventory, _research, _org-github are exempt
        rel = os.path.relpath(d, root)
        if skip_paths and any(rel == p or rel.startswith(p + os.sep) for p in skip_paths):
            continue
        for f in fn:
            if f.endswith(".md"):
                yield os.path.join(d, f)


def repo_name() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] or os.path.basename(os.getcwd())
