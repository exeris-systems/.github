#!/usr/bin/env python3
"""ADR registry validator — ADR-085 §G.22–24, adr-conventions.md rules 1–4.

Two modes, chosen by what the checkout contains:

  * Consumer repo (has docs/adr/, no adr-index.md): every ADR-NNN-*.md and ADR-NNN.link.md under docs/adr/
    must have a registry row. The registry is fetched from --index (a local path or a raw GitHub URL; default:
    exeris-docs main). Filenames must match the regex.

  * Registry repo (has adr-index.md): rows are validated — unique numbers, status grammar, no relative link into a
    private repo, every 'accepted' row has a link. With --siblings-root (local run or federation build where the
    repos are cloned side by side) each row's link must resolve on disk; otherwise resolution is skipped and a
    note is emitted.

Exit 1 on errors.
"""
from __future__ import annotations
import argparse, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from _common import Report, ADR_FILE, ADR_LINK, PRIVATE_REPOS

ROW = re.compile(r"^\|\s*(\d{3})\s*\|(.*)$")
STATUS = re.compile(r"\b(accepted|proposed|reserved|superseded|withdrawn|pending merge)\b", re.I)
LINK = re.compile(r"\]\(([^)]+)\)")
DEFAULT_INDEX = "https://raw.githubusercontent.com/exeris-systems/exeris-docs/main/adr-index.md"


def load_index(src: str) -> str:
    if os.path.exists(src):
        return open(src, encoding="utf-8").read()
    with urllib.request.urlopen(src, timeout=20) as r:  # noqa: S310 — fixed, allow-listed host
        return r.read().decode("utf-8")


def parse_rows(text: str):
    rows = {}
    in_index = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith("## Index"):
            in_index = True
            continue
        if line.startswith("## ") and in_index:
            in_index = False
        if not in_index:
            continue
        m = ROW.match(line)
        if m:
            cells = [c.strip() for c in m.group(2).split("|")]
            rows.setdefault(m.group(1), []).append((i, line, cells))
    return rows


def check_registry(text: str, rep: Report, siblings_root: str | None, index_path: str):
    rows = parse_rows(text)
    rep.checked = len(rows)
    for num, entries in rows.items():
        if len(entries) > 1:
            rep.error(index_path, f"ADR-{num} has {len(entries)} rows", line=entries[1][0], rule="duplicate-number")
        for ln, line, cells in entries:
            status_cell = next((c for c in cells if STATUS.search(c)), "")
            if not status_cell:
                rep.error(index_path, f"ADR-{num}: no recognisable status (accepted|proposed|reserved|superseded|withdrawn|pending merge)", line=ln, rule="status")
            links = LINK.findall(line)
            for target in links:
                for pr in PRIVATE_REPOS:
                    if f"/{pr}/" in target or target.startswith(f"../{pr}/"):
                        rep.error(index_path, f"ADR-{num}: relative link into private repo '{pr}' — write '(content private)' instead", line=ln, rule="private-link")
            if status_cell.lower().startswith("accepted") and not links and "content private" not in line and "enterprise-private" not in line:
                rep.error(index_path, f"ADR-{num}: accepted without a link", line=ln, rule="link")
            if siblings_root:
                for target in links:
                    if target.startswith("http"):
                        continue
                    local = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(index_path)), target.split("#")[0].replace("%20", " ")))
                    if not os.path.exists(local):
                        lvl = rep.warning if "pending merge" in status_cell.lower() else rep.error
                        lvl(index_path, f"ADR-{num}: link target not found on disk: {target} — merge the branch or mark the row 'pending merge (<branch>)'", line=ln, rule="resolve")
    # cross-repo stubs table: private repos may be *named* (as text) but never *linked*
    for i, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| ") or "](" not in line:
            continue
        for target in LINK.findall(line):
            for pr in PRIVATE_REPOS:
                if f"/{pr}/" in target or target.startswith(f"../{pr}/"):
                    rep.error(index_path, f"relative link into private repo '{pr}' — name it in backticks with *(private repo)* instead (ADR-020)", line=i, rule="private-link")
    if not siblings_root:
        rep.warning(index_path, "link resolution skipped (no --siblings-root); run from the federation build to verify targets", rule="resolve")


def check_consumer(adr_dir: str, index_text: str, rep: Report):
    rows = parse_rows(index_text)
    for f in sorted(os.listdir(adr_dir)):
        if not f.endswith(".md"):
            continue
        rep.checked += 1
        rel = os.path.join(adr_dir, f)
        m = ADR_FILE.match(f) or ADR_LINK.match(f)
        if not m:
            rep.error(rel, f"filename must match ADR-NNN-<kebab>.md or ADR-NNN.link.md (got '{f}')", rule="filename")
            continue
        num = m.group(1)
        if num not in rows:
            rep.error(rel, f"ADR-{num} has no row in adr-index.md — reserve the number first (registry-row-first rule)", rule="registry-row")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--adr-dir", default="docs/adr")
    ap.add_argument("--siblings-root", default=None)
    a = ap.parse_args()
    rep = Report("registry_check")
    if os.path.exists("adr-index.md"):
        check_registry(open("adr-index.md", encoding="utf-8").read(), rep, a.siblings_root, "adr-index.md")
        if os.path.isdir("adr"):
            check_consumer("adr", open("adr-index.md", encoding="utf-8").read(), rep)
    elif os.path.isdir(a.adr_dir):
        try:
            idx = load_index(a.index)
        except Exception as e:  # network or path failure is an error: the check cannot run
            rep.error(a.adr_dir, f"cannot load registry from {a.index}: {e}", rule="registry")
            sys.exit(rep.emit())
        check_consumer(a.adr_dir, idx, rep)
    else:
        print("::notice::registry_check: no docs/adr/ and no adr-index.md — nothing to check")
    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
