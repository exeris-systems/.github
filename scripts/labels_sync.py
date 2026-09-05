#!/usr/bin/env python3
"""Bring a repository's labels in line with the organisation taxonomy (labels.yml).

Additive by design: creates what is missing and corrects the colour and description of labels the
taxonomy names. It never deletes, so a repository's own `area:` labels survive and GitHub's default
set is left alone rather than fought with.

Environment: GH_TOKEN, REPO (owner/name), DRY_RUN (1/true/yes/on to report only; an
unrecognised value is an error, never a write).
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.error, urllib.request
import yaml

API = "https://api.github.com"


def call(method: str, path: str, token: str, body: dict | None = None):
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body else None)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or "null")


# This script writes to a repository, so an unreadable DRY_RUN must not mean "write". It used to
# compare against the literal string "true", which made `DRY_RUN=1` a full, silent apply — the run
# that added 18 labels to exeris-kernel was invoked that way and reported them as "created" with no
# "(dry run)" marker. Recognise the usual spellings both ways and refuse anything else.
TRUE = {"1", "true", "yes", "on", "y", "t"}
FALSE = {"", "0", "false", "no", "off", "n", "f"}


def parse_dry(raw: str) -> bool:
    v = raw.strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    raise SystemExit(f"DRY_RUN={raw!r} is neither true nor false; refusing to guess, and refusing "
                     f"to write. Use one of {sorted(TRUE)} or {sorted(FALSE - {''})}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    a = ap.parse_args()
    token, repo = os.environ["GH_TOKEN"], os.environ["REPO"]
    dry = parse_dry(os.environ.get("DRY_RUN", ""))

    want = yaml.safe_load(open(a.labels, encoding="utf-8"))
    have, page = {}, 1
    while True:
        batch = call("GET", f"/repos/{repo}/labels?per_page=100&page={page}", token)
        if not batch:
            break
        have.update({l["name"]: l for l in batch})
        page += 1

    created, updated, ok = [], [], 0
    for spec in want:
        name, color, desc = spec["name"], spec["color"].lstrip("#"), spec.get("description", "")
        cur = have.get(name)
        if cur is None:
            created.append(name)
            if not dry:
                call("POST", f"/repos/{repo}/labels", token,
                     {"name": name, "color": color, "description": desc})
        elif cur.get("color", "").lower() != color.lower() or (cur.get("description") or "") != desc:
            diffs = []
            if (cur.get("color") or "").lower() != color.lower():
                diffs.append(f"colour {cur.get('color')} -> {color}")
            if (cur.get("description") or "") != desc:
                diffs.append("description")
            updated.append(f"{name} ({', '.join(diffs)})")
            if not dry:
                call("PATCH", f"/repos/{repo}/labels/{urllib.request.quote(name)}", token,
                     {"new_name": name, "color": color, "description": desc})
        else:
            ok += 1

    lines = [f"## labels-sync — {repo}{' (dry run)' if dry else ''}", "",
             f"{ok} already correct, {len(created)} created, {len(updated)} corrected. "
             f"{len(have)} label(s) existed; none were deleted."]
    if created:
        lines += ["", "**Created**"] + [f"- `{n}`" for n in created]
    if updated:
        lines += ["", "**Corrected**"] + [f"- {n}" for n in updated]
    out = "\n".join(lines)
    print(out)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        open(summary, "a", encoding="utf-8").write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
