#!/usr/bin/env python3
"""Bring a repository's labels in line with the organisation taxonomy (labels.yml).

Additive by design: creates what is missing and corrects the colour and description of labels the
taxonomy names. It never deletes, so a repository's own `area:` labels survive and GitHub's default
set is left alone rather than fought with.

Environment: GH_TOKEN, REPO (owner/name), DRY_RUN ("true" to report only).
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    a = ap.parse_args()
    token, repo = os.environ["GH_TOKEN"], os.environ["REPO"]
    dry = os.environ.get("DRY_RUN", "").lower() == "true"

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
            updated.append(f"{name} ({cur.get('color')} -> {color})")
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
