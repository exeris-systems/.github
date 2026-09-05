#!/usr/bin/env python3
"""Propose frontmatter for pages that have none — the mechanical half of the Phase 5 backfill.

528 Markdown files across the ecosystem carry no frontmatter block at all. Writing five keys by
hand on each is transcription, not judgement: four of the five are derivable from the file and its
history, and the fifth (`type`) is derivable from where the file sits often enough that the
exceptions are worth reviewing on their own. This turns the backfill from authoring into reading a
diff.

Dry-run by default. `--apply` writes; nothing else does.

What it will not do:
  * touch a file that already has a frontmatter block — a wrong existing value is a human's call;
  * touch the README family, which is exempt from the schema (frontmatter_check.py);
  * invent `type` silently — a file it cannot place is reported as low confidence and left alone
    unless --include-unplaced is given, in which case it gets the fallback and appears in the report.

`last-verified` is set from the file's last commit date, which is NOT what the field means.
docs-style-guide.md rule 3 defines it as the date a human last confirmed the page matches the code;
a commit date only says when the text last moved. Every file this script touches is therefore listed
in the report as owing a verification pass. Treat the report as the worklist, not as a receipt.

Usage:
  frontmatter_backfill.py [--root .] [--apply] [--report backfill-report.md]
                          [--visibility public|enterprise-private] [--include-unplaced]
"""
from __future__ import annotations
import argparse, datetime, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import walk_md, read_frontmatter, repo_name, PRIVATE_REPOS

EXEMPT_NAMES = {"README.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
                "LICENSE.md", "NOTICE.md", "PULL_REQUEST_TEMPLATE.md"}

# Directory name -> doc type. Only unambiguous mappings; anything else is reported, not guessed.
DIR_TYPE = {
    "adr": "adr", "rfc": "rfc", "research": "research",
    "subsystems": "subsystem", "modules": "module",
    "guides": "howto", "how-to": "howto", "howto": "howto", "tutorials": "tutorial",
    "operations": "operations", "runbooks": "operations",
    "explanations": "explanation", "reference": "reference",
    "release-notes": "release-notes", "results": "benchmark-report",
    "methodology": "methodology", "design-notes": "design-note",
}
# Filename -> doc type, checked before the directory.
NAME_TYPE = {
    "CHANGELOG.md": "changelog", "ROADMAP.md": "roadmap", "CLAIMS.md": "claims",
    "MIGRATION.md": "migration-guide", "AGENTS.md": "reference", "CLAUDE.md": "reference",
}
# Release notes are named, not placed: exeris-kernel keeps them in `docs/release/` next to
# `1.0-scope.md` and `upgrade-0.5-to-0.10.md`, which are reference and a migration guide. Typing the
# directory would mislabel those two, so match the filename and leave the neighbours unplaced.
RELEASE_NOTES = re.compile(r"-release-notes\.md$")
ADR_N = re.compile(r"^ADR-(\d{3})")
LINK_N = re.compile(r"^ADR-(\d{3})\.link\.md$")
RECORD = {"adr", "adr-link", "rfc", "research"}
# "# Title", minus links, inline code, trailing anchors and a leading emoji.
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
CLEAN = [(re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"), (re.compile(r"[`*_]"), ""),
         (re.compile(r"^[^\w\"'(]+\s*"), "")]


def infer_title(text: str, path: str) -> tuple[str, bool]:
    m = H1.search(text)
    if m:
        t = m.group(1)
        for rx, rep in CLEAN:
            t = rx.sub(rep, t)
        t = t.strip()
        if t:
            return t, True
    stem = os.path.basename(path)[:-3].replace("-", " ").replace("_", " ")
    return stem[:1].upper() + stem[1:], False


def infer_type(path: str) -> tuple[str | None, bool]:
    name = os.path.basename(path)
    if name in NAME_TYPE:
        return NAME_TYPE[name], True
    if LINK_N.match(name):
        return "adr-link", True
    if ADR_N.match(name):
        return "adr", True
    if name.startswith("RFC-"):
        return "rfc", True
    if name.startswith("RESEARCH-") or name == "RESEARCH.md":
        return "research", True
    if RELEASE_NOTES.search(name):
        return "release-notes", True
    for part in reversed(os.path.normpath(path).split(os.sep)[:-1]):
        if part in DIR_TYPE:
            return DIR_TYPE[part], True
    return None, False


def infer_status(text: str, typ: str) -> str | None:
    if typ not in RECORD:
        return None
    m = re.search(r"^\|?\s*\**Status\**\s*\|?\s*\|?\s*([A-Za-z]+)", text, re.M)
    if m and m.group(1).lower() in {"draft", "active", "stale", "superseded", "retracted"}:
        return m.group(1).lower()
    if m and m.group(1).lower() in {"accepted", "proposed"}:
        return "active" if m.group(1).lower() == "accepted" else "draft"
    return "draft"


def last_commit_date(path: str) -> tuple[str, bool]:
    out = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=short", "--", path],
                         capture_output=True, text=True)
    d = out.stdout.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return d, True
    return datetime.date.today().isoformat(), False


def block(fields: dict) -> str:
    lines = ["---"]
    for k in ("title", "type", "visibility", "owning-repo", "status", "last-verified", "slug"):
        if fields.get(k) is not None:
            v = fields[k]
            lines.append(f'{k}: "{v}"' if k == "title" and (":" in v or v.startswith(("[", "{"))) else f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    ap.add_argument("--visibility", default=None, help="default visibility for this repo")
    ap.add_argument("--include-unplaced", action="store_true",
                    help="also write files whose type could not be inferred, using 'reference'")
    ap.add_argument("--report", default=None, help="write the verification worklist here")
    a = ap.parse_args()

    repo = repo_name()
    vis = a.visibility or ("enterprise-private" if repo in PRIVATE_REPOS else "public")
    rows, unplaced, written = [], [], 0

    for path in sorted(walk_md(a.root)):
        if os.path.basename(path) in EXEMPT_NAMES:
            continue
        fm, _ = read_frontmatter(path)
        if fm is not None and not fm.get("__invalid__"):
            continue
        text = open(path, encoding="utf-8").read()
        typ, typ_sure = infer_type(path)
        if typ is None:
            if not a.include_unplaced:
                unplaced.append(path)
                continue
            typ = "reference"
        title, title_sure = infer_title(text, path)
        date, date_sure = last_commit_date(path)
        fields = {"title": title, "type": typ, "visibility": vis, "owning-repo": repo,
                  "status": infer_status(text, typ), "last-verified": date}
        m = ADR_N.match(os.path.basename(path))
        if typ in ("adr", "adr-link") and m:
            fields["slug"] = f"adr/ADR-{m.group(1)}"
        rows.append((path, typ, typ_sure, title_sure, date_sure))
        if a.apply:
            open(path, "w", encoding="utf-8").write(block(fields) + text)
            written += 1
        else:
            print(f"--- {path}\n{block(fields)}", end="")

    print(f"\n{'wrote' if a.apply else 'would write'} {len(rows)} file(s); "
          f"{len(unplaced)} unplaced (type not inferable) and left untouched", file=sys.stderr)
    low = [r for r in rows if not (r[2] and r[3])]
    if low:
        print(f"{len(low)} need a human look: title or type was a fallback", file=sys.stderr)

    if a.report:
        with open(a.report, "w", encoding="utf-8") as fh:
            fh.write(f"# Frontmatter backfill — {repo}\n\n")
            fh.write(f"{len(rows)} file(s) received a generated frontmatter block on "
                     f"{datetime.date.today().isoformat()}.\n\n"
                     "`last-verified` on every one of them is the file's **last commit date**, not a "
                     "verification date: nobody has yet confirmed these pages match the code. This "
                     "list is the worklist for that pass (docs-style-guide.md rule 3).\n\n"
                     "| File | type | type inferred | title from H1 | date from git |\n"
                     "|:--|:--|:--|:--|:--|\n")
            for p, t, ts, tis, ds in rows:
                fh.write(f"| `{p}` | {t} | {'yes' if ts else 'FALLBACK'} | "
                         f"{'yes' if tis else 'FALLBACK'} | {'yes' if ds else 'today'} |\n")
            if unplaced:
                fh.write("\n## Not touched — type could not be inferred\n\n"
                         "These need a type chosen by hand, or a directory this script should learn.\n\n")
                for p in unplaced:
                    fh.write(f"- `{p}`\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
