#!/usr/bin/env python3
"""PR body checker — ADR-085 §E.16–17, pr-conventions.md rules 2–4.

Reads the PR from the GitHub event payload ($GITHUB_EVENT_PATH) or from --body-file. Verifies that the template
headings are present in order with content, that the classification lines parse, and that trailer lines use the
grammar. Presence and parseability only — substance is for review. Drafts and bot authors are exempt.
"""
from __future__ import annotations
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import Report

HEADINGS = ["Motivation:", "Modification:", "Result:", "## Classification", "## Verification"]
FIELDS = {
    "Scope class": r"^(runtime hot path|runtime non-hot|test-tooling|docs-only)$",
    "Wall impact": r"^(none|[\w.-]+\s*(→|->)\s*[\w.-]+)$",
    "Generated files touched": r"^(yes|no|n/a)$",
    "TCK obligation": r"^(satisfied|debt #\d+|n/a)$",
    "Compatibility impact": r"^(none|additive|breaking \(ADR-\d{3}\))$",
    # The repository half accepts a slash: the org's own bundle is `exeris-systems/.github`, and the
    # pattern that did not allow one forced it to be written as bare `.github`, which names no repo.
    "Cross-repo impact": r"^(none|[\w./-]+:\s*.+)$",
    "ADRs referenced": r"^(none|ADR-\d{3}(\s*,\s*ADR-\d{3})*)$",
    "Evidence state": r"^(citable|unartifacted|n/a)$",
}
TRAILERS = {
    "Closes": r"^Closes #\d+(\s*,\s*#\d+)*$",
    "Fixes": r"^Fixes #\d+(\s*,\s*#\d+)*$",
    "Refs": r"^Refs: ADR-\d{3}(\s*,\s*ADR-\d{3})*$",
    "Claim": r"^Claim: [A-Z]-\d+$",
}
BOTS = {"dependabot[bot]", "renovate[bot]", "github-actions[bot]"}


def strip_comments(s: str) -> str:
    return re.sub(r"<!--.*?-->", "", s, flags=re.S)


def section_text(body: str, start: str, nexts: list[str]) -> str:
    i = body.find(start)
    if i < 0:
        return ""
    j = len(body)
    for n in nexts:
        k = body.find(n, i + len(start))
        if 0 <= k < j:
            j = k
    return body[i + len(start):j].strip()


def check(body: str, rep: Report, path="PR body", labels: set | None = None):
    body = strip_comments(body)
    rep.checked = 1
    # headings present and ordered
    pos = -1
    for h in HEADINGS:
        i = body.find(h)
        if i < 0:
            rep.error(path, f"missing template section '{h}'", rule="headings")
        elif i < pos:
            rep.error(path, f"section '{h}' is out of template order", rule="headings")
        else:
            pos = i
    for h in ["Motivation:", "Modification:", "Result:"]:
        txt = section_text(body, h, [x for x in HEADINGS if x != h])
        txt = re.sub(r"^<.*?>$", "", txt, flags=re.M).strip()  # placeholder lines
        if not txt or txt.lower() == "n/a" and h != "Result:":
            rep.error(path, f"section '{h}' is empty", rule="content")
    # classification fields
    for k, rx in FIELDS.items():
        m = re.search(rf"^{re.escape(k)}:\s*(.+?)\s*$", body, re.M)
        if not m:
            rep.error(path, f"missing classification line '{k}:'", rule="classification")
            continue
        val = m.group(1)
        if val.startswith("<") and val.endswith(">"):
            rep.error(path, f"'{k}:' still holds the placeholder", rule="classification")
        elif not re.match(rx, val):
            rep.error(path, f"'{k}: {val}' does not parse (expected /{rx}/)", rule="classification")
    # verification section non-empty
    ver = section_text(body, "## Verification", ["Release note:", "Closes", "Refs:"])
    if not re.sub(r"^<.*?>$", "", ver, flags=re.M).strip():
        rep.error(path, "'## Verification' is empty — name the commands run after the last push", rule="verification")
    # trailers
    for line in body.splitlines():
        s = line.strip()
        for key, rx in TRAILERS.items():
            if s.startswith(key) and s not in (f"{key} #", f"{key}: ADR-", f"{key} ADR-"):
                if not re.match(rx, s):
                    rep.error(path, f"trailer '{s}' does not match {rx}", rule="trailer")
    # ADR touched ⇒ both halves of adr-conventions.md rule 9: the Refs trailer and the `adr` label.
    # The caller sets GUARDRAILS_ADR_TOUCHED=1. Labels come from the event payload; they are None
    # when the body was supplied with --body-file, and the label half is then not judged rather
    # than failed.
    if os.environ.get("GUARDRAILS_ADR_TOUCHED") == "1":
        if not re.search(r"^Refs: ADR-\d{3}", body, re.M):
            rep.error(path, "PR adds or amends an ADR but has no 'Refs: ADR-NNN' trailer",
                      rule="trailer")
        if labels is not None and "adr" not in labels:
            rep.error(path, "PR adds or amends an ADR but does not carry the 'adr' label "
                            "(adr-conventions.md rule 9)", rule="label")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file")
    a = ap.parse_args()
    rep = Report("pr_body_check")
    labels = None
    if a.body_file:
        body = open(a.body_file, encoding="utf-8").read()
    else:
        ev = json.load(open(os.environ["GITHUB_EVENT_PATH"]))
        pr = ev.get("pull_request", {})
        if pr.get("draft"):
            print("::notice::pr_body_check: draft PR — skipped")
            return
        if pr.get("user", {}).get("login") in BOTS:
            print("::notice::pr_body_check: bot PR — skipped")
            return
        body = pr.get("body") or ""
        labels = {(l or {}).get("name", "") for l in pr.get("labels") or []}
    check(body, rep, labels=labels)
    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
