#!/usr/bin/env python3
"""PR body checker — ADR-085 §E.16–17, §J.31, pr-conventions.md rules 2–4, ai-provenance.md rule 3b.

Reads the PR from the GitHub event payload ($GITHUB_EVENT_PATH) or from --body-file. Verifies that the template
headings are present in order with content, that the classification lines parse, that trailer lines use the
grammar, and that the `Owner: @<login>` body line is present exactly once and well-formed when the PR author is
the organisation's execution identity, and absent for every other author. Presence and parseability only —
substance is for review. Drafts and bot authors (the BOTS set) are exempt.

Whether the named owner IS an organisation member is not decided here: this script holds no token and makes no
network call, so the rule below checks only that the line is present, singular, and shaped like a GitHub handle
— membership is checkable from that shape, not checked against GitHub's membership API, and the reviewer
confirms it before merge.
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
# The organisation's execution identity (ADR-087 §A.1) — deliberately not in BOTS: a bot in that set
# is exempted from this whole checker, and a pull request this identity opens is exactly the one
# the owner rule below exists to check.
AGENT_LOGIN = "exeris-agent[bot]"
# A line in the pull-request body, not a git trailer (ADR-085 §D.15): the grammar is one '@' and a
# GitHub login (1-39 chars, alphanumeric or hyphen, no leading/trailing/doubled hyphen requirement
# beyond first/last character), and nothing else on the line.
OWNER_LINE = re.compile(r"^Owner:\s*(.+?)\s*$", re.M)
OWNER_GRAMMAR = re.compile(r"^Owner: @[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


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


def check(body: str, rep: Report, path="PR body", labels: set | None = None, author: str | None = None):
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
    # Owner line — ADR-085 §J.31, ai-provenance.md rule 3b. Required, exactly once, well-formed,
    # when the execution identity is the author; forbidden otherwise, because the accountable
    # human of a human-authored pull request is already its author, and a second name would split
    # accountability rather than state it. Author identity is not in the body, so it comes from
    # the caller; when the caller has none (a bare --body-file run) the rule is not judged, the
    # same way the label half of the adr rule above is not judged without labels.
    if author is not None:
        owner_lines = [m.group(0).strip() for m in OWNER_LINE.finditer(body)]
        if author == AGENT_LOGIN:
            if not owner_lines:
                rep.error(path, "PR author is exeris-agent[bot] but the body has no "
                                "'Owner: @<login>' line", rule="owner")
            elif len(owner_lines) > 1:
                rep.error(path, f"PR author is exeris-agent[bot] but the body has "
                                f"{len(owner_lines)} 'Owner:' lines — exactly one is required",
                          rule="owner")
            elif not OWNER_GRAMMAR.match(owner_lines[0]):
                rep.error(path, f"'{owner_lines[0]}' does not match 'Owner: @<login>' — one "
                                f"'@' and a single GitHub handle, nothing else on the line",
                          rule="owner")
        elif owner_lines:
            rep.error(path, f"PR author is {author}, not exeris-agent[bot], but the body has an "
                            f"'Owner:' line — the accountable human of a human-authored pull "
                            f"request is its author, and a second name would split "
                            f"accountability", rule="owner")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file")
    ap.add_argument("--author",
                     help="PR author login, for a --body-file run — exercises the owner rule "
                          "the way the event payload does; without it the rule is not judged")
    a = ap.parse_args()
    rep = Report("pr_body_check")
    labels = None
    author = a.author
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
        author = pr.get("user", {}).get("login")
    check(body, rep, labels=labels, author=author)
    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
