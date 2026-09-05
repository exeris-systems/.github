#!/usr/bin/env python3
"""Frontmatter and doc-structure validator — ADR-085 §B.7–9, docs-style-guide.md rules 2, 3, 5, 7.

Usage:
  frontmatter_check.py [--root .] [--exclude 'docs/vendor'] [--mode ramp|strict] [--base origin/main]
                       [--repo-visibility public|enterprise-private]

Modes:
  strict — every Markdown file under --root must pass; errors fail the build.
  ramp   — files changed vs --base must pass (errors); unchanged files only produce warnings.
           This is the Phase 5 rollout mode: no backfill mandate, no silent debt either.

Exempt: the README family anywhere (they render on GitHub first, which shows frontmatter as literal
text), directories starting with '_', and everything scripts/_common.py names as not-documentation —
generated output, the guardrail bundle, and agent trees, which agents_file_check.py checks instead.
The default root is the repository: what is not linted is named, never left off an opt-in list.
"""
from __future__ import annotations
import argparse, datetime, glob, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import (Report, read_frontmatter, changed_files, walk_md, DOC_TYPES, STATUSES, VISIBILITY,
                     ADR_FILE, ADR_LINK, RFC_FILE, RESEARCH_FILE, PRIVATE_REPOS, repo_name)

REQUIRED = ["title", "type", "visibility", "owning-repo", "last-verified"]
RECORD_TYPES = {"adr", "adr-link", "rfc", "research"}
REQUIRED_SECTIONS = {
    "tutorial": ["## Prerequisites", "## Where this does not apply"],
    "howto": ["## Prerequisites", "## Where this does not apply"],
    "subsystem": ["## Contract", "## Hot path", "## Failure modes", "## Owning ADRs"],
    "module": ["## Contract", "## Hot path", "## Failure modes", "## Owning ADRs"],
}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEBAB = re.compile(r"^(\d{2}-)?[a-z0-9]+(?:[-.][a-z0-9]+)*\.md$")
# A template is the file a real document is copied from, so its frontmatter must carry every required
# key but cannot carry a real value: "last-verified: YYYY-MM-DD" is the correct content there, not a
# defect. Keys are still checked; values that are visibly placeholders are not.
TEMPLATE_FILE = re.compile(r"-TEMPLATE\.md$")
PLACEHOLDER = re.compile(r"^(<.*>|YYYY-MM-DD|ADR-NNN|NNN|TBD|\.\.\.)$")


def check_file(path: str, rep: Report, repo_vis: str, section_check: bool):
    name = os.path.basename(path)
    rel = os.path.relpath(path)
    # These render on github.com before they render on the site, and GitHub shows the frontmatter
    # block as literal text. They are reviewed ([L2]), never schema-checked.
    if name in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
                "LICENSE.md", "NOTICE.md", "PULL_REQUEST_TEMPLATE.md"):
        return
    rep.checked += 1
    # filename discipline (docs-style-guide rule 7, adr-conventions rule 1)
    d = os.path.basename(os.path.dirname(path))
    if d == "adr":
        if not (ADR_FILE.match(name) or ADR_LINK.match(name)):
            rep.error(rel, f"ADR filename must match ADR-NNN-<kebab>.md or ADR-NNN.link.md (got '{name}')", rule="filename")
    elif d == "rfc":
        if not RFC_FILE.match(name):
            rep.error(rel, "RFC filename must match RFC-YYYY-MM-DD-<kebab>.md", rule="filename")
    elif d == "research":
        if not (RESEARCH_FILE.match(name) or name == "RESEARCH.md"):
            rep.error(rel, "Research filename must match RESEARCH-YYYY-MM-DD-<kebab>.md", rule="filename")
    elif not KEBAB.match(name) and not TEMPLATE_FILE.search(name) and name not in (
            "ROADMAP.md", "CLAIMS.md", "MISSION.md", "CHANGELOG.md", "AGENTS.md", "CLAUDE.md", "SKILL.md",
            "MIGRATION.md", "LICENSING.md", "TRADEMARK.md"):
        rep.warning(rel, "filename is not lowercase kebab-case", rule="filename")

    fm, body_line = read_frontmatter(path)
    if fm is None:
        rep.error(rel, "missing frontmatter block (--- … ---) at top of file", rule="frontmatter")
        return
    if fm.get("__invalid__"):
        rep.error(rel, "frontmatter is not valid YAML", rule="frontmatter")
        return
    for k in REQUIRED:
        if k not in fm or fm[k] in (None, ""):
            rep.error(rel, f"frontmatter key '{k}' is required", rule="frontmatter")
    is_template = bool(TEMPLATE_FILE.search(name))

    def placeholder(val) -> bool:
        """In a template the value *is* the instruction for filling it in; the key is still required."""
        return is_template and PLACEHOLDER.match(str(val or "")) is not None

    t = fm.get("type")
    if t and t not in DOC_TYPES and not placeholder(t):
        rep.error(rel, f"type '{t}' is not in the ADR-085 §B.8 enumeration", rule="type")
    v = fm.get("visibility")
    if v and v not in VISIBILITY and not placeholder(v):
        rep.error(rel, f"visibility must be public | enterprise-private (got '{v}')", rule="visibility")
    if v == "enterprise-private" and repo_vis == "public":
        rep.error(rel, "enterprise-private document inside a public repository (ADR-020)", rule="visibility")
    st = fm.get("status")
    if t in RECORD_TYPES and not st:
        rep.error(rel, "records (adr/rfc/research) must carry 'status'", rule="status")
    if st and st not in STATUSES and not placeholder(st):
        rep.error(rel, f"status must be one of {sorted(STATUSES)} (got '{st}')", rule="status")
    lv = str(fm.get("last-verified", ""))
    if lv and not DATE.match(lv):
        if not placeholder(lv):
            rep.error(rel, f"last-verified must be YYYY-MM-DD (got '{lv}')", rule="last-verified")
    elif lv:
        try:
            if datetime.date.fromisoformat(lv) > datetime.date.today():
                rep.error(rel, "last-verified is in the future", rule="last-verified")
        except ValueError:
            rep.error(rel, f"last-verified is not a real date ('{lv}')", rule="last-verified")
    if t == "adr" and not fm.get("slug"):
        rep.error(rel, "ADRs must set slug: adr/ADR-NNN so the site URL is stable", rule="slug")
    # required sections by type (docs-style-guide rule 5)
    if section_check and t in REQUIRED_SECTIONS:
        text = open(path, encoding="utf-8").read()
        for h in REQUIRED_SECTIONS[t]:
            if not re.search(rf"^{re.escape(h)}\s*$", text, re.M):
                rep.error(rel, f"type '{t}' requires section '{h}'", rule="sections")
    # public → private path links (docs-style-guide rule 6)
    text = open(path, encoding="utf-8").read()
    for m in re.finditer(r"\]\(([^)]+)\)", text):
        target = m.group(1)
        for pr in PRIVATE_REPOS:
            if f"/{pr}/" in target or target.startswith(f"../{pr}/") or target.startswith(f"../../{pr}/"):
                rep.error(rel, f"link into private repository '{pr}' — use a '(content private)' marker (ADR-020)",
                          line=text[:m.start()].count("\n") + 1, rule="private-link")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--exclude", default=os.environ.get("GUARDRAILS_EXCLUDE", ""),
                    help="space-separated paths this repo does not lint")
    ap.add_argument("--mode", choices=["ramp", "strict"], default="ramp")
    ap.add_argument("--base", default=os.environ.get("GUARDRAILS_BASE"))
    ap.add_argument("--repo-visibility", default=None)
    ap.add_argument("--no-section-check", action="store_true", help="skip required-section checks (until subsystem pages are rewritten)")
    ap.add_argument("paths", nargs="*", help="explicit files (overrides --root)")
    a = ap.parse_args()
    repo_vis = a.repo_visibility or ("enterprise-private" if repo_name() in PRIVATE_REPOS else "public")
    # Positional paths may be files, directories or globs — the documented `extra-paths` for a
    # root-records repo is "adr rfc *.md", two directories and a pattern. Expand each to files.
    files: list[str] = []
    for spec in a.paths:
        if os.path.isdir(spec):
            files.extend(walk_md(spec))
        elif os.path.isfile(spec):
            files.append(spec)
        else:
            for hit in sorted(glob.glob(spec)):
                if os.path.isdir(hit):
                    files.extend(walk_md(hit))
                elif hit.endswith(".md"):
                    files.append(hit)
    if not files and os.path.isdir(a.root):
        files = list(walk_md(a.root))
    files = sorted(dict.fromkeys(os.path.normpath(f) for f in files))
    if a.exclude:
        skip = tuple(os.path.normpath(x) + os.sep for x in a.exclude.split())
        files = [f for f in files if not f.startswith(skip)]
    changed = changed_files(a.base) if a.mode == "ramp" else None
    rep = Report("frontmatter_check")
    strict_rep = rep
    for p in files:
        rel = os.path.relpath(p)
        if a.mode == "ramp" and changed is not None and rel not in changed:
            sub = Report("x")
            check_file(p, sub, repo_vis, not a.no_section_check)
            rep.checked += sub.checked
            for f in sub.findings:  # downgrade: unchanged files only warn
                rep.warning(f.path, f.msg + " (unchanged file — warning in ramp mode)", f.line, f.rule)
        else:
            check_file(p, rep, repo_vis, not a.no_section_check)
    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
