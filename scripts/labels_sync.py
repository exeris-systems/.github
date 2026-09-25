#!/usr/bin/env python3
"""Bring a repository's labels in line with the organisation taxonomy (labels.yml).

Additive by design: creates what is missing and corrects the colour and description of labels the
taxonomy names. It never deletes, so a repository's own `area:` labels survive and GitHub's default
set is left alone rather than fought with.

A label whose entry carries `renamed-from` is renamed in place when the repository has an old name
and not the new one. Creating the new label instead would leave every issue and pull request still
carrying the old one, and a label the workflows no longer read is a request nobody answers. Where
both names exist the old one is reported and left: deleting it would take it off whatever carries it.

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


def plan(want: list[dict], have: dict[str, dict]) -> list[tuple[str, str, dict | None, str]]:
    """What the sync does, as `(kind, name, body, line)`: `kind` is create, rename, correct, ok or
    left; `name` is the label the request addresses; `body` is what is sent, `None` for no request;
    `line` is what the summary prints."""
    actions = []
    for spec in want:
        name, color, desc = spec["name"], spec["color"].lstrip("#"), spec.get("description", "")
        body = {"name": name, "color": color, "description": desc}
        patch = {"new_name": name, "color": color, "description": desc}
        cur = have.get(name)
        old = [o for o in spec.get("renamed-from", []) if o in have]
        if cur is None and old:
            actions.append(("rename", old[0], patch, f"`{old[0]}` -> `{name}`"))
            old = old[1:]
        elif cur is None:
            actions.append(("create", name, body, f"`{name}`"))
        elif (cur.get("color") or "").lower() != color.lower() or (cur.get("description") or "") != desc:
            diffs = []
            if (cur.get("color") or "").lower() != color.lower():
                diffs.append(f"colour {cur.get('color')} -> {color}")
            if (cur.get("description") or "") != desc:
                diffs.append("description")
            actions.append(("correct", name, patch, f"{name} ({', '.join(diffs)})"))
        else:
            actions.append(("ok", name, None, name))
        actions += [("left", o, None, f"`{o}` (now `{name}`)") for o in old]
    return actions


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

    actions = plan(want, have)
    for kind, name, body, _ in actions:
        if dry or kind in ("ok", "left"):
            continue
        if kind == "create":
            call("POST", f"/repos/{repo}/labels", token, body)
        else:
            call("PATCH", f"/repos/{repo}/labels/{urllib.request.quote(name)}", token, body)
    created = [n for k, n, _, _ in actions if k == "create"]
    renamed = [d for k, _, _, d in actions if k == "rename"]
    updated = [d for k, _, _, d in actions if k == "correct"]
    left = [d for k, _, _, d in actions if k == "left"]
    ok = sum(1 for k, *_ in actions if k == "ok")

    lines = [f"## labels-sync — {repo}{' (dry run)' if dry else ''}", "",
             f"{ok} already correct, {len(created)} created, {len(renamed)} renamed, "
             f"{len(updated)} corrected. {len(have)} label(s) existed; none were deleted."]
    if created:
        lines += ["", "**Created**"] + [f"- `{n}`" for n in created]
    if renamed:
        lines += ["", "**Renamed**"] + [f"- {n}" for n in renamed]
    if updated:
        lines += ["", "**Corrected**"] + [f"- {n}" for n in updated]
    if left:
        lines += ["", "**Old name left beside the new one — delete it by hand once nothing needs it**"]
        lines += [f"- {n}" for n in left]
    out = "\n".join(lines)
    print(out)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        open(summary, "a", encoding="utf-8").write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
