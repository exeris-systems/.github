"""Structural invariants of `.github/workflows/caps-release.yml`, read as data.

No script can enforce these: they are properties of where a secret, a permission or a pin sits in
the workflow text. PyYAML is not assumed, so the file is read line by line: YAML comments are
dropped (a block scalar, which is shell, is kept whole, because an expression in a shell comment is
still evaluated), jobs and steps are cut by indentation, and each step keeps its scalar keys and the
`env:` / `with:` maps.

`violations(text)` returns the identifiers of every invariant the text breaks; the real workflow
must return none, and the mutation tests prove that each identifier is reachable.
"""
from __future__ import annotations

import re

KEY = re.compile(r"^(\s*)(?:- )?([\w.-]+):\s*(.*)$")
BLOCK = re.compile(r"^\s*(?:- )?[\w.-]+:\s*[|>][-+]?\s*$")
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
SECRET = re.compile(r"\bsecrets\b")
SECRET_NAME = re.compile(r"(?<!\w)secrets\.(\w+)(\s*!=\s*'')?")
DIGEST_COMPARE = re.compile(r'[!=]=?\s*"\$SCRIPTS_DIGEST"')
SCRIPT_CALL = re.compile(r"python3 -I -B ")
VALUE_SECRETS_IMPORT = {"GPG_PRIVATE_KEY"}
VALUE_SECRETS_DEPLOY = {"GPG_PASSPHRASE", "CENTRAL_TOKEN_USERNAME", "CENTRAL_TOKEN_PASSWORD"}


def strip_comments(text: str) -> list[str]:
    out, block_indent = [], None
    for raw in text.splitlines():
        indent = len(raw) - len(raw.lstrip())
        if block_indent is not None:
            if not raw.strip() or indent > block_indent:
                out.append(raw)
                continue
            block_indent = None
        if raw.lstrip().startswith("#"):
            continue
        if BLOCK.match(raw):
            m = KEY.match(raw)
            block_indent = len(m.group(1)) + (2 if raw.lstrip().startswith("- ") else 0)
            out.append(raw)
            continue
        line = raw
        m = re.search(r"\s+#(\s.*)?$", line)
        if m and (line[:m.start()].count('"') % 2 == 0) and (line[:m.start()].count("'") % 2 == 0):
            line = line[:m.start()]
        out.append(line)
    return out


def parse(text: str) -> dict:
    lines = strip_comments(text)
    jobs: dict[str, dict] = {}
    in_jobs, job = False, None
    for line in lines:
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        m = re.match(r"^  ([\w-]+):\s*$", line)
        if m:
            job = jobs.setdefault(m.group(1), {"lines": [], "header": [], "steps": []})
            continue
        if job is not None:
            job["lines"].append(line)
    for j in jobs.values():
        header, steps, cur = [], [], None
        for line in j["lines"]:
            if re.match(r"^      - ", line):
                cur = [line]
                steps.append(cur)
            elif cur is not None and (line.startswith("        ") or not line.strip()):
                cur.append(line)
            elif cur is None:
                header.append(line)
            else:
                header.append(line)
        j["header"] = header
        j["steps"] = [step(s) for s in steps]
    return {"jobs": jobs, "lines": lines}


def step(lines: list[str]) -> dict:
    norm = ["        " + lines[0][8:]] + lines[1:]
    d = {"raw": "\n".join(lines), "name": "", "uses": "", "if": "", "env": {}, "with": {}, "run": ""}
    i = 0
    while i < len(norm):
        m = re.match(r"^        ([\w.-]+):\s*(.*)$", norm[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        children = []
        j = i + 1
        while j < len(norm) and (not norm[j].strip() or len(norm[j]) - len(norm[j].lstrip()) > 8):
            children.append(norm[j])
            j += 1
        if key in ("env", "with"):
            for c in children:
                mm = re.match(r"^\s+([\w.-]+):\s*(.*)$", c)
                if mm:
                    d[key][mm.group(1)] = mm.group(2).strip()
        elif key == "run":
            d["run"] = val + "\n" + "\n".join(children) if val not in ("|", "|-", ">", ">-") else "\n".join(children)
        elif key in ("name", "uses", "if"):
            d[key] = val.strip("'\"")
        i = j
    return d


def secret_refs(s: dict) -> list[tuple[str, str, bool]]:
    """(where, name, boolean-only) for every secrets.X in the step."""
    found = []
    for where, blob in [("run", s["run"]), ("if", s["if"]), ("uses", s["uses"])] + \
            [("env", v) for v in s["env"].values()] + [("with", v) for v in s["with"].values()]:
        for m in SECRET_NAME.finditer(blob):
            found.append((where, m.group(1), bool(m.group(2))))
    return found


def violations(text: str) -> set[str]:
    out: set[str] = set()
    wf = parse(text)
    jobs = wf["jobs"]
    for need in ("build", "publish", "attest"):
        if need not in jobs:
            out.add(f"job-missing:{need}")
    if out:
        return out

    for name, j in jobs.items():
        body = "\n".join(j["lines"])
        if name != "publish" and (SECRET.search(body)):
            out.add(f"secrets-outside-publish:{name}")
    if not SECRET.search("\n".join(jobs["publish"]["lines"])):
        out.add("publish-reads-no-secret")

    perms = lambda j: [ln.strip() for ln in j["header"] if "permissions" in ln or re.match(r"^      \w", ln)]
    for name, j in jobs.items():
        head = "\n".join(j["header"])
        if re.search(r"id-token:\s*write", head) and name != "attest":
            out.add(f"id-token-outside-attest:{name}")
        if re.search(r"attestations:\s*write", head) and name != "attest":
            out.add(f"attestations-outside-attest:{name}")
        if re.search(r"packages:\s*write", head) and name != "publish":
            out.add(f"packages-outside-publish:{name}")
    top = "\n".join(l for l in wf["lines"][: next(i for i, l in enumerate(wf["lines"]) if l.startswith("jobs:"))])
    if re.search(r"id-token:\s*write|packages:\s*write|attestations:\s*write|contents:\s*write", top):
        out.add("top-level-write-permission")
    if not re.search(r"id-token:\s*write", "\n".join(jobs["attest"]["header"])):
        out.add("attest-lacks-id-token")
    if [p for p in perms(jobs["build"]) if p.startswith(("id-token", "packages", "attestations", "contents: write"))]:
        out.add("build-permissions")
    if "contents: read" not in "\n".join(jobs["build"]["header"]):
        out.add("build-not-read-only")
    if any(s["run"] for s in jobs["attest"]["steps"]):
        out.add("attest-runs-code")
    if "needs.build.outputs.publish == 'true'" not in "\n".join(jobs["publish"]["header"]):
        out.add("publish-not-conditional")
    if "needs.publish.result == 'success'" not in "\n".join(jobs["attest"]["header"]):
        out.add("attest-not-conditional")

    # who holds a secret value
    steps = jobs["publish"]["steps"]
    imports = [i for i, s in enumerate(steps) if "gpg --batch --import" in s["run"]]
    deploys = [i for i, s in enumerate(steps) if "mvn" in s["run"] and re.search(r"\bdeploy\b", s["run"]) and "-DskipTests" in s["run"]]
    if len(imports) != 1:
        out.add("import-step-not-unique")
    if len(deploys) != 1:
        out.add("deploy-step-not-unique")
    for i, s in enumerate(steps):
        for where, nm, boolean in secret_refs(s):
            if boolean:
                continue
            if i in imports and where == "env" and nm in VALUE_SECRETS_IMPORT:
                continue
            if i in deploys and where == "env" and nm in VALUE_SECRETS_DEPLOY:
                continue
            out.add("secret-value-outside-allowed-step")
    for i in imports:
        if re.search(r"\b(mvn|python3?|curl|wget|bash|sh)\b(?! -c)", steps[i]["run"].replace("pipefail", "")):
            out.add("import-step-runs-more")
    for j in ("build", "attest"):
        for s in jobs[j]["steps"]:
            if SECRET.search(s["raw"]):
                out.add(f"secrets-outside-publish:{j}")

    # key removal
    removals = [i for i, s in enumerate(steps) if "remove_signing_key.py" in s["run"]]
    if len(removals) != 1 or len(deploys) != 1:
        out.add("removal-step-not-unique")
    else:
        if removals[0] != deploys[0] + 1:
            out.add("removal-not-after-deploy")
        if not re.fullmatch(r"(\$\{\{\s*)?always\(\)(\s*\}\})?", steps[removals[0]]["if"].strip()):
            out.add("removal-not-always")

    # digest re-verification after project code
    for jname, j in jobs.items():
        seen_mvn = False
        for s in j["steps"]:
            run = s["run"]
            call = SCRIPT_CALL.search(run)
            if call and ("caps-release-scripts" in run or '"$S/' in run):
                mvn_before = [m.start() for m in re.finditer(r"\bmvn\b", run) if m.start() < call.start()]
                if seen_mvn or mvn_before:
                    cmp_ = DIGEST_COMPARE.search(run)
                    if not cmp_ or cmp_.start() > call.start() or (mvn_before and cmp_.start() < max(mvn_before)):
                        out.add(f"digest-not-reverified:{jname}")
                    if "SCRIPTS_DIGEST" not in s["env"] or "steps.scripts.outputs.digest" not in s["env"].get("SCRIPTS_DIGEST", ""):
                        out.add(f"digest-not-passed:{jname}")
            if re.search(r"\bmvn\b", run):
                seen_mvn = True

    # the scripts come from the commit of this workflow
    for jname in ("build", "publish"):
        own = [s for s in jobs[jname]["steps"] if s["uses"].startswith("actions/checkout") and
               s["with"].get("repository") == "exeris-systems/.github"]
        if len(own) != 1:
            out.add(f"scripts-checkout-missing:{jname}")
        for s in own:
            if s["with"].get("ref") != "${{ github.job_workflow_sha }}":
                out.add(f"scripts-checkout-ref:{jname}")
    for j in jobs.values():
        for s in j["steps"]:
            if s["uses"].startswith("actions/checkout") and s["with"].get("repository") and \
                    s["with"].get("ref") != "${{ github.job_workflow_sha }}":
                out.add("scripts-checkout-ref")

    # defaults
    up = [l for l in wf["lines"] if re.match(r"^      upload:", l)]
    tg = [l for l in wf["lines"] if re.match(r"^      target:", l)]
    if len(up) != 1 or not re.search(r"type:\s*boolean\s*,\s*default:\s*false\b", up[0]):
        out.add("upload-default")
    if len(tg) != 1 or not re.search(r"""default:\s*["']none["']""", tg[0]):
        out.add("target-default")

    # pins
    for j in jobs.values():
        for s in j["steps"]:
            if s["uses"] and not SHA_PIN.match(s["uses"]):
                out.add("uses-not-pinned")
    return out
