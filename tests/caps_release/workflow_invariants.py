"""Structural invariants of `.github/workflows/caps-release.yml`, read as data.

No script can enforce these: they are properties of where a secret, a permission or a pin sits in
the workflow text. PyYAML is not assumed, so the file is read line by line: YAML comments are
dropped (a block scalar, which is shell, is kept whole, because an expression in a shell comment is
still evaluated), jobs and steps are cut by indentation, and each step keeps its scalar keys and the
`env:` / `with:` maps.

The workflow has four jobs and the split is the security model:

  build    rehearsal; `contents: read`; the only credential is the read-only token of the resolve step
  publish  builds and signs with the real key, gates, makes a manifest; `contents: read`; no token
  upload   the only job with `packages: write`; never runs the capability's code
  attest   provenance after a successful upload; `id-token` and `attestations`, no project code

`violations(text)` returns the identifiers of every invariant the text breaks; the real workflow
must return none, and the mutation tests prove that each identifier is reachable.
"""
from __future__ import annotations

import re
import shlex

KEY = re.compile(r"^(\s*)(?:- )?([\w.-]+):\s*(.*)$")
BLOCK = re.compile(r"^\s*(?:- )?[\w.-]+:\s*[|>][-+]?\s*$")
BLOCK_VALUES = ("|", "|-", "|+", ">", ">-", ">+")
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.S)
SECRET = re.compile(r"\bsecrets\b", re.I)
SECRET_NAME = re.compile(r"(?<!\w)secrets\.(\w+)(\s*!=\s*'')?")
DIGEST_COMPARE = re.compile(r'[!=]=?\s*"\$SCRIPTS_DIGEST"')
SCRIPT_CALL = re.compile(r"python3 -I -B ")
OUTCOME_CONDITION = re.compile(r"\b(always|failure|cancelled|success)\s*\(", re.I)

# Every spelling of the job token that a step could name: the context in either notation (property
# names are case-insensitive in expressions), the environment names, and a dump of a whole context.
TOKEN_SPELLINGS = re.compile(
    r"github\s*(?:\.\s*token\b|\[\s*['\"]token['\"]\s*\])"
    r"|secrets\s*(?:\.\s*github_token\b|\[\s*['\"]github_token['\"]\s*\])"
    r"|(?<!env\.)\bGITHUB_TOKEN\b|\bGH_TOKEN\b|\bGITHUB_PAT\b"
    r"|tojson\(\s*(?:github|secrets|env)\b|\$\{\{[^}]*\benv\s*\.\s*(?:GITHUB|GH)_TOKEN\b", re.I)
TOKEN_ENV = ("GITHUB_TOKEN", "GH_TOKEN")

TARGETS = ("none", "github-packages")
FORBIDDEN_WORDS = ("central", "CENTRAL_TOKEN", "EXPECT_BUNDLE", "--expect-bundle", "sonatype")
SCRIPTS_REPOSITORY = "exeris-systems/.github"
SCRIPTS_REF = "${{ github.job_workflow_sha }}"
UPLOAD_URL = "https://maven.pkg.github.com/${GITHUB_REPOSITORY}"
DEPLOY_GOAL = re.compile(r"org\.apache\.maven\.plugins:maven-deploy-plugin:\d+\.\d+\.\d+:deploy-file\b")
GATED = "${{ runner.temp }}/gated-files"
DOWNLOAD = "${{ runner.temp }}/gated-download"
DOWNLOAD_SHELL = '"$RUNNER_TEMP/gated-download"'
STAGE_FLAG = re.compile(r'--stage "\$RUNNER_TEMP/gated-files"')
VERIFY_CALL = ('/usr/bin/python3 -I -B "$S/staged_manifest.py" verify --dir "$RUNNER_TEMP/gated-download" '
               "--manifest-env MANIFEST")
ARTIFACT = "gated-${{ needs.build.outputs.version }}-${{ github.run_attempt }}-${{ steps.gate.outputs.manifest-id }}"
UPLOAD_STEP = "Upload the gated files"
RESOLVE_STEP = "Resolve the version and refuse an unreleasable ref"
BUILD_STEP = "Build and sign"
IMPORT_STEP = "Import the signing key"
ALLOWED_USES = {
    "upload": ("actions/checkout@", "actions/setup-java@", "actions/download-artifact@"),
    "attest": ("actions/checkout@", "actions/download-artifact@", "actions/attest-build-provenance@"),
}
MVN_FLAGS = {"-B", "-ntp", "--settings"}
MVN_PROPERTIES = {"repositoryId", "url", "pomFile", "file", "sources", "javadoc", "files", "classifiers", "types"}
EXECUTORS = re.compile(r"(?:^|[\s;&|(`])(?:bash|sh|dash|zsh|ksh|source|eval|exec|python3?|perl|ruby|node|java|xargs|env|\.)(?=\s)|(?:^|\s)\./")

# What `${{ }}` may hold in each step of `upload` and `attest`, by (step, place). Anything else is
# a way for something outside the job's own constants to reach it.
INTERPOLATIONS = {
    "upload": {
        ("checkout", "with:ref"): "github.job_workflow_sha",
        ("Install the gate scripts outside the workspace", "env:SCRIPTS_COMMIT"): "github.job_workflow_sha",
        ("Set up JDK", "name"): "inputs.java-version",
        ("Set up JDK", "with:distribution"): "inputs.java-distribution",
        ("Set up JDK", "with:java-version"): "inputs.java-version",
        ("Download the gated files", "with:name"): "needs.publish.outputs.artifact",
        ("Download the gated files", "with:path"): "runner.temp",
        ("Compare the downloaded files with the manifest", "env:MANIFEST"): "needs.publish.outputs.manifest",
        ("Compare the downloaded files with the manifest", "env:SCRIPTS_DIGEST"): "steps.scripts.outputs.digest",
        (UPLOAD_STEP, "env:GITHUB_TOKEN"): "github.token",
    },
    "attest": {
        ("checkout", "with:ref"): "github.job_workflow_sha",
        ("Install the gate scripts outside the workspace", "env:SCRIPTS_COMMIT"): "github.job_workflow_sha",
        ("Download the gated files", "with:name"): "needs.publish.outputs.artifact",
        ("Download the gated files", "with:path"): "runner.temp",
        ("Compare the downloaded files with the manifest", "env:MANIFEST"): "needs.publish.outputs.manifest",
        ("Compare the downloaded files with the manifest", "env:SCRIPTS_DIGEST"): "steps.scripts.outputs.digest",
        ("Attest build provenance (SLSA)", "with:subject-path"): "runner.temp",
    },
}


# --- reading the file --------------------------------------------------------------------------------------------------
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
            else:
                header.append(line)
        j["header"] = header
        j["steps"] = [step(s) for s in steps]
    return {"jobs": jobs, "lines": lines}


def _map(children: list[str]) -> dict[str, str]:
    """The `key: value` pairs of a map; a block-scalar value is the joined lines of the block."""
    out: dict[str, str] = {}
    i = 0
    while i < len(children):
        m = re.match(r"^(\s+)([\w.-]+):\s*(.*)$", children[i])
        if not m:
            i += 1
            continue
        value = m.group(3).strip()
        if value in BLOCK_VALUES:
            base, block = len(m.group(1)), []
            i += 1
            while i < len(children) and (not children[i].strip() or len(children[i]) - len(children[i].lstrip()) > base):
                if children[i].strip():
                    block.append(children[i].strip())
                i += 1
            out[m.group(2)] = "\n".join(block)
            continue
        out[m.group(2)] = value
        i += 1
    return out


def step(lines: list[str]) -> dict:
    norm = ["        " + lines[0][8:]] + lines[1:]
    d = {"raw": "\n".join(lines), "name": "", "uses": "", "if": "", "id": "", "env": {}, "with": {}, "run": "", "keys": set()}
    i = 0
    while i < len(norm):
        m = re.match(r"^        ([\w.-]+):\s*(.*)$", norm[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        d["keys"].add(key)
        children = []
        j = i + 1
        while j < len(norm) and (not norm[j].strip() or len(norm[j]) - len(norm[j].lstrip()) > 8):
            children.append(norm[j])
            j += 1
        if key in ("env", "with"):
            d[key] = _map(children)
        elif key == "run":
            d["run"] = val + "\n" + "\n".join(children) if val not in BLOCK_VALUES else "\n".join(children)
        elif key in ("name", "uses", "if", "id"):
            d[key] = val.strip("'\"")
        i = j
    return d


def block_lines(s: dict, key: str) -> list[str]:
    """The value of `key` in a step: the lines of a block scalar (`key: |`), or the one-line value."""
    raw = s["raw"].split("\n")
    for i, line in enumerate(raw):
        m = re.match(rf"^(\s+)(?:- )?{re.escape(key)}:\s*(.*)$", line)
        if not m:
            continue
        value = m.group(2).strip()
        if value in BLOCK_VALUES:
            base, out = len(m.group(1)), []
            for nxt in raw[i + 1:]:
                if not nxt.strip():
                    continue
                if len(nxt) - len(nxt.lstrip()) <= base:
                    break
                out.append(nxt.strip())
            return out
        return [value.strip("'\"")] if value else []
    return []


def job_value(job: dict, key: str) -> str:
    """The one-line value of a job-level key (`needs`, `if`, `name`, `runs-on`); the text, whitespace-normalised."""
    for line in job["header"]:
        m = re.match(rf"^    {re.escape(key)}:\s*(.*)$", line)
        if m:
            return " ".join(m.group(1).split())
    return ""


def job_outputs(job: dict) -> dict[str, str]:
    out, inside = {}, False
    for line in job["header"]:
        if re.match(r"^    outputs:\s*$", line):
            inside = True
            continue
        if inside:
            m = re.match(r"^      ([\w-]+):\s*(.*)$", line)
            if not m:
                break
            out[m.group(1)] = m.group(2).strip()
    return out


def permissions(job: dict) -> dict[str, str]:
    """The `permissions:` map of a job header, as written."""
    out, base = {}, None
    for line in job["header"]:
        m = re.match(r"^(\s+)permissions:\s*(.*)$", line)
        if m and base is None:
            base = len(m.group(1))
            continue
        if base is not None:
            mm = re.match(r"^(\s+)([\w-]+):\s*(\S+)", line)
            if not mm or len(mm.group(1)) <= base:
                break
            out[mm.group(2)] = mm.group(3)
    return out


def secret_refs(s: dict) -> list[tuple[str, str, bool]]:
    """(where, name, boolean-only) for every secrets.X in the step."""
    found = []
    for where, blob in [("run", s["run"]), ("if", s["if"]), ("uses", s["uses"])] + \
            [("env", v) for v in s["env"].values()] + [("with", v) for v in s["with"].values()]:
        for m in SECRET_NAME.finditer(blob):
            found.append((where, m.group(1), bool(m.group(2))))
    return found


def blobs(s: dict) -> list[str]:
    return [s["run"], s["if"], s["uses"], s["name"], *s["env"].values(), *s["with"].values()]


def holds_token(s: dict) -> bool:
    """The step names the job token in any spelling, in `env:`, `with:`, `if:` or inline in `run:`."""
    return any(TOKEN_SPELLINGS.search(b) for b in blobs(s)) or any(k in s["env"] for k in TOKEN_ENV)


def holds_passphrase(s: dict) -> bool:
    return any(nm == "GPG_PASSPHRASE" and not boolean for _, nm, boolean in secret_refs(s)) or "MAVEN_GPG_PASSPHRASE" in s["env"]


def holds_private_key(s: dict) -> bool:
    return any(nm == "GPG_PRIVATE_KEY" and not boolean for _, nm, boolean in secret_refs(s))


def short(s: dict) -> str:
    """How a step is named in a finding and in the tables: its name, or the action it uses."""
    return s["name"] or s["uses"].split("@")[0].split("/")[-1]


def kind(s: dict) -> str:
    """`checkout` for a checkout step, `Set up JDK` for the setup-java step, the name otherwise."""
    if s["uses"].startswith("actions/checkout@"):
        return "checkout"
    if s["uses"].startswith("actions/setup-java@"):
        return "Set up JDK"
    return s["name"] or s["uses"]


def interpolations(s: dict) -> dict[tuple[str, str], list[str]]:
    """Every `${{ }}` of a step by (kind, place); `place` is name, run, if, uses, env:KEY or with:KEY."""
    found: dict[tuple[str, str], list[str]] = {}

    def add(place, blob):
        for m in EXPRESSION.finditer(blob):
            found.setdefault((kind(s), place), []).append(" ".join(m.group(1).split()))
    add("name", s["name"])
    add("run", s["run"])
    add("if", s["if"])
    add("uses", s["uses"])
    for k, v in s["env"].items():
        add(f"env:{k}", v)
    for k, v in s["with"].items():
        add(f"with:{k}", v)
    return found


def region(text: str, job: str) -> tuple[int, int]:
    """(start, end) of the text of one job, from its header line to the next job's."""
    start = text.index(f"\n  {job}:\n") + 1
    nxt = re.search(r"^  [\w-]+:\s*$", text[start + 1:], re.M)
    return start, (start + 1 + nxt.start() if nxt else len(text))


# --- the invariants ----------------------------------------------------------------------------------------------------
def violations(text: str) -> set[str]:
    wf = parse(text)
    jobs = wf["jobs"]
    out: set[str] = set()
    for need in ("build", "publish", "upload", "attest"):
        if need not in jobs:
            out.add(f"job-missing:{need}")
    if out:
        return out
    if set(jobs) != {"build", "publish", "upload", "attest"}:
        out.add("jobs-unexpected")
    for check in (_words_and_defaults, _graph, _permissions, _credentials, _upload_isolation, _upload_order,
                  _publish_order, _manifest_travel, _attest, _checkouts_and_digests, _gate_staging, _conditions, _pins):
        check(text, wf, jobs, out)
    return out


def _words_and_defaults(text, wf, jobs, out):
    # the file knows two targets, and no other repository, token or bundle
    for word in FORBIDDEN_WORDS:
        if word.lower() in text.lower():
            out.add(f"forbidden-word:{word.lower()}")
    target = [ln for ln in wf["lines"] if re.match(r"^      target:", ln)]
    if len(target) == 1 and not all(t in target[0] for t in TARGETS):
        out.add("target-values")
    compared = set(re.findall(r"inputs\.target\s*[!=]=\s*'([^']*)'", "\n".join(wf["lines"])))
    if compared - set(TARGETS):
        out.add("target-values")
    up = [ln for ln in wf["lines"] if re.match(r"^      upload:", ln)]
    tg = [ln for ln in wf["lines"] if re.match(r"^      target:", ln)]
    if len(up) != 1 or not re.search(r"type:\s*boolean\s*,\s*default:\s*false\b", up[0]):
        out.add("upload-default")
    if len(tg) != 1 or not re.search(r"""default:\s*["']none["']""", tg[0]):
        out.add("target-default")
    # a dry run is decided by what resolve_release.py says, from the two inputs and nothing else
    if not re.search(r"^\s+publish:\s*\$\{\{\s*steps\.rel\.outputs\.publish\s*\}\}\s*$", "\n".join(jobs["build"]["header"]), re.M):
        out.add("publish-output-not-resolved")
    resolve = [s for s in jobs["build"]["steps"] if "resolve_release.py" in s["run"]]
    if len(resolve) != 1 or '--target "$IN_TARGET"' not in resolve[0]["run"] or '--upload "$IN_UPLOAD"' not in resolve[0]["run"] \
            or resolve[0]["env"].get("IN_TARGET") != "${{ inputs.target }}" or resolve[0]["env"].get("IN_UPLOAD") != "${{ inputs.upload }}" \
            or resolve[0]["id"] != "rel":
        out.add("publish-not-resolved-from-inputs")


def _graph(text, wf, jobs, out):
    if job_value(jobs["build"], "needs") or job_value(jobs["build"], "if"):
        out.add("job-graph:build")
    if job_value(jobs["publish"], "needs") != "build":
        out.add("job-graph:publish")
    if job_value(jobs["upload"], "needs") != "[build, publish]":
        out.add("job-graph:upload")
    if job_value(jobs["attest"], "needs") != "[publish, upload]":
        out.add("job-graph:attest")
    if job_value(jobs["publish"], "if") != "${{ needs.build.outputs.publish == 'true' }}":
        out.add("publish-not-conditional")
    if job_value(jobs["upload"], "if") != "${{ needs.build.outputs.publish == 'true' && needs.publish.result == 'success' }}":
        out.add("upload-not-conditional")
    if job_value(jobs["attest"], "if") != "${{ needs.upload.result == 'success' }}":
        out.add("attest-not-conditional")


def _permissions(text, wf, jobs, out):
    want = {"build": {"contents": "read"}, "publish": {"contents": "read"},
            "upload": {"contents": "read", "packages": "write"},
            "attest": {"contents": "read", "id-token": "write", "attestations": "write"}}
    for name, j in jobs.items():
        if name not in want:
            continue
        got = permissions(j)
        if got != want[name]:
            out.add(f"permissions:{name}")
        head = "\n".join(j["header"])
        if re.search(r"packages:\s*write", head) and name != "upload":
            out.add(f"packages-write-outside-upload:{name}")
        if re.search(r"id-token:\s*write", head) and name != "attest":
            out.add(f"id-token-outside-attest:{name}")
        if re.search(r"attestations:\s*write", head) and name != "attest":
            out.add(f"attestations-outside-attest:{name}")
        if re.search(r"write-all|permissions:[ \t]*\S", head):
            out.add(f"permissions:{name}")
    top = "\n".join(wf["lines"][: next(i for i, ln in enumerate(wf["lines"]) if ln.startswith("jobs:"))])
    if re.search(r":\s*write\b|write-all", top):
        out.add("top-level-write-permission")


def _credentials(text, wf, jobs, out):
    # the job token: one step of upload, the resolve step of build (read-only), no other step anywhere
    holders = {n: [short(s) for s in j["steps"] if holds_token(s)] for n, j in jobs.items()}
    if holders["build"] != [RESOLVE_STEP]:
        out.add("token-holders:build")
    if holders["publish"]:
        out.add("token-holders:publish")
    if holders["attest"]:
        out.add("token-holders:attest")
    if holders["upload"] != [UPLOAD_STEP]:
        out.add("token-holders:upload")
    # the token is the context in `env:` and nowhere else: not inline in `run:`, not in `with:`, `if:` or `uses:`
    for n, want in (("build", {"GH_TOKEN": "${{ github.token }}"}), ("upload", {"GITHUB_TOKEN": "${{ github.token }}"})):
        for s in jobs[n]["steps"]:
            if not holds_token(s):
                continue
            carried = {k: v for k, v in s["env"].items() if k in TOKEN_ENV or TOKEN_SPELLINGS.search(v)}
            if carried != want or any(TOKEN_SPELLINGS.search(b) for b in (s["run"], s["if"], s["uses"], s["name"], *s["with"].values())):
                out.add(f"token-form:{n}")
    last = jobs["upload"]["steps"][-1]
    if short(last) != UPLOAD_STEP:
        out.add("upload-token-step-not-last")
    for s in jobs["upload"]["steps"][:-1]:
        if holds_token(s):
            out.add("token-before-last-step")
    # the signing secrets are in publish alone: the key in the import step, the passphrase in the build step
    for n in ("build", "upload", "attest"):
        if any(SECRET.search(s["raw"]) for s in jobs[n]["steps"]) or SECRET.search("\n".join(jobs[n]["header"])):
            out.add(f"secrets-outside-publish:{n}")
    pub = jobs["publish"]["steps"]
    if not SECRET_NAME.search("\n".join(jobs["publish"]["lines"])):
        out.add("publish-reads-no-secret")
    if [short(s) for s in pub if holds_private_key(s)] != [IMPORT_STEP]:
        out.add("private-key-holders")
    if [short(s) for s in pub if holds_passphrase(s)] != [BUILD_STEP]:
        out.add("passphrase-holders")
    for s in pub:
        for where, nm, boolean in secret_refs(s):
            allowed = boolean or (short(s) == IMPORT_STEP and where == "env" and nm == "GPG_PRIVATE_KEY") or \
                (short(s) == BUILD_STEP and where == "env" and nm == "GPG_PASSPHRASE")
            if not allowed:
                out.add("secret-value-outside-allowed-step")
    for n, j in jobs.items():
        for s in j["steps"]:
            if holds_token(s) and (holds_passphrase(s) or holds_private_key(s)):
                out.add("step-holds-token-and-secret")
    imports = [s for s in pub if "gpg --batch --import" in s["run"]]
    if len(imports) != 1:
        out.add("import-step-not-unique")
    for s in imports:
        if re.search(r"\b(mvn|python3?|curl|wget|bash|sh)\b(?! -c)", s["run"].replace("pipefail", "")):
            out.add("import-step-runs-more")
    if [s for s in pub if re.search(r":deploy-file\b|maven-deploy-plugin", s["run"])]:
        out.add("deploy-in-publish")


def _checkouts(job):
    return [s for s in job["steps"] if s["uses"].startswith("actions/checkout@")]


DIGEST_CHECK = re.compile(r'\[ "\$\(cd "\$S".*?exit 1; \}', re.S)
SETTINGS_HEAD = 'cat > "$RUNNER_TEMP/release-settings.xml" <<\'XML\''
UPLOAD_LINES = ("set -euo pipefail", 'cd "$RUNNER_TEMP/gated-download"', "for pom in *.pom; do", 'base="${pom%.pom}"', "done")
INSTALL_STEP = "Install the gate scripts outside the workspace"
COMPARE_STEP = "Compare the downloaded files with the manifest"


def logical_lines(run: str) -> list[str]:
    """The commands of a shell block, one per logical line (a continuation joined), blank lines dropped."""
    return [" ".join(ln.split()) for ln in run.replace("\\\n", " ").splitlines() if ln.strip()]


def _step_commands(name, s, out):
    """Each run block of `upload` and `attest` holds the commands it is meant to hold and no others."""
    run = s["run"]
    k = kind(s)
    if k == COMPARE_STEP:
        rest = DIGEST_CHECK.sub("", run).replace(VERIFY_CALL, "")
        if logical_lines(rest) != ["set -euo pipefail", 'S="$RUNNER_TEMP/caps-release-scripts"']:
            out.add(f"commands:{name}:compare")
    elif k == "Write the Maven settings":
        lines = logical_lines(run)
        if not lines or lines[0] != SETTINGS_HEAD or lines[-1] != "XML" or any(ln.startswith("cat ") for ln in lines[1:]):
            out.add(f"commands:{name}:settings")
    elif k == UPLOAD_STEP:
        lines = logical_lines(run)
        mvn = [ln for ln in lines if ln.startswith("mvn ")]
        rest = [ln for ln in lines if not ln.startswith("mvn ")]
        if rest != list(UPLOAD_LINES) or len(mvn) != 1 or lines.index(mvn[0]) != 4 or not mvn[0].startswith("mvn -B -ntp org.apache.maven.plugins:maven-deploy-plugin:"):
            out.add(f"commands:{name}:upload")
    elif k != INSTALL_STEP:
        out.add(f"commands:{name}:unexpected-step")
    if k != UPLOAD_STEP and "gated-download" in DIGEST_CHECK.sub("", run).replace(VERIFY_CALL, ""):
        out.add(f"download-dir-misused:{name}")
    if k == UPLOAD_STEP and "gated-download" in run.replace(f"cd {DOWNLOAD_SHELL}\n", "", 1):
        out.add(f"download-dir-misused:{name}")
    if EXECUTORS.search(" ".join(logical_lines(run)).replace("set -euo pipefail", "")) and k in (UPLOAD_STEP, "Write the Maven settings"):
        out.add(f"download-dir-misused:{name}")


def _upload_isolation(text, wf, jobs, out):
    installs = {" ".join(s["run"].split()) for n in jobs for s in jobs[n]["steps"] if s["name"] == INSTALL_STEP}
    if len(installs) != 1:
        out.add("scripts-install-differs")
    for name in ("upload", "attest"):
        j = jobs[name]
        steps = j["steps"]
        # the only checkout is this repository's scripts at the workflow's commit
        co = _checkouts(j)
        if len(co) != 1 or co[0]["with"].get("repository") != SCRIPTS_REPOSITORY or \
                set(co[0]["with"]) != {"repository", "ref", "path", "persist-credentials"}:
            out.add(f"caller-checkout:{name}")
        if any(not s["uses"].startswith(ALLOWED_USES[name]) for s in steps if s["uses"]):
            out.add(f"uses-allowlist:{name}")
        if re.search(r"actions/cache|\bcache\s*:|restore-keys|cache-dependency", "\n".join(s["raw"] for s in steps)):
            out.add(f"cache:{name}")
        dl = [s for s in steps if s["uses"].startswith("actions/download-artifact@")]
        if len(dl) != 1 or dl[0]["with"].get("path") != DOWNLOAD or set(dl[0]["with"]) != {"name", "path"} or \
                dl[0]["with"].get("name") != "${{ needs.publish.outputs.artifact }}":
            out.add(f"download:{name}")
        # nothing moves state between jobs but outputs and artifacts, so no step touches the files that do it within a job
        for s in steps:
            if re.search(r"GITHUB_ENV|GITHUB_PATH|GITHUB_STATE", s["run"]) or \
                    (re.search(r"GITHUB_OUTPUT", s["run"]) and kind(s) != INSTALL_STEP):
                out.add(f"env-file:{name}")
            # no condition and no continue-on-error: a step that follows a failed one never runs
            if s["if"] or "if" in s["keys"] or OUTCOME_CONDITION.search(s["raw"]):
                out.add(f"step-condition:{name}")
            if "continue-on-error" in s["keys"] or "continue-on-error" in s["raw"]:
                out.add(f"continue-on-error:{name}")
            if "working-directory" in s["keys"] or "shell" in s["keys"]:
                out.add(f"step-environment:{name}")
            if s["run"]:
                _step_commands(name, s, out)
        # interpolation: only these constants and these outputs, only in these places, never inside shell text
        seen: dict[tuple[str, str], str] = {}
        for s in steps:
            for place, exprs in interpolations(s).items():
                if place[1] == "run":
                    out.add(f"run-interpolation:{name}")
                if any(e.startswith("inputs.") and e != INTERPOLATIONS[name].get(place) for e in exprs):
                    out.add(f"input-reaches-job:{name}")
                seen[place] = exprs[0] if len(set(exprs)) == 1 else "|".join(exprs)
        if seen != INTERPOLATIONS[name]:
            out.add(f"interpolation-inventory:{name}")
    # the work the job does is the deploy plugin's, from the download directory, to one repository, with the settings it wrote
    ups = [s for s in jobs["upload"]["steps"] if s["name"] == UPLOAD_STEP]
    if len(ups) != 1:
        out.add("upload-step-not-unique")
        return
    u = ups[0]
    run = u["run"]
    if u["env"] != {"GITHUB_TOKEN": "${{ github.token }}"}:
        out.add("token-form:upload")
    if len(DEPLOY_GOAL.findall(run)) != 1:
        out.add("upload-goal")
    joined = run.replace("\\\n", " ")
    toks = toks_of(next((ln for ln in joined.splitlines() if re.search(r"\bmvn\b", ln)), ""))
    flags = {t for t in toks[1:] if t.startswith("-") and not t.startswith("-D")}
    props = {t[2:].split("=", 1)[0] for t in toks if t.startswith("-D")}
    if flags - MVN_FLAGS:
        out.add("upload-mvn-flags")
    if props != MVN_PROPERTIES:
        out.add("upload-mvn-properties")
    if '--settings "$RUNNER_TEMP/release-settings.xml"' not in joined:
        out.add("upload-settings")
    # the files it names are the downloaded ones by name, never by path
    for t in toks:
        if t.startswith(("-DpomFile=", "-Dfile=", "-Dsources=", "-Djavadoc=", "-Dfiles=")) and "/" in t:
            out.add("upload-mvn-properties")
    cds = re.findall(r"^\s*cd\s+(.+?)\s*$", run, re.M)
    if cds != [DOWNLOAD_SHELL] or run.find("cd ") > run.find("mvn"):
        out.add("upload-directory")
    urls = re.findall(r"-Durl=\"?([^\s\"]+)\"?", run)
    allurls = re.findall(r"[a-z][a-z0-9+.-]*://[^\s\"']+", run)
    if urls != [UPLOAD_URL] or set(allurls) - {UPLOAD_URL} or "-DaltDeploymentRepository" in run:
        out.add("upload-url")
    settings = [s for s in jobs["upload"]["steps"] if "release-settings.xml" in s["run"] and ":deploy-file" not in s["run"]]
    if "-DrepositoryId=github" not in run or len(settings) != 1 or "<id>github</id>" not in settings[0]["run"]:
        out.add("upload-server-id")
    for s in settings:
        # the settings hold placeholders, never a value, and the here-document is quoted so the shell expands none of them
        if "<<'XML'" not in s["run"] or s["env"] or s["with"]:
            out.add("settings-placeholders")
        if holds_token({**s, "run": s["run"].replace("${env.GITHUB_TOKEN}", "").replace("${env.GITHUB_ACTOR}", "")}):
            out.add("settings-placeholders")
        if "${env.GITHUB_TOKEN}" not in s["run"] or "${env.GITHUB_ACTOR}" not in s["run"]:
            out.add("settings-placeholders")
    if "-P" in toks or "--activate-profiles" in run:
        out.add("upload-with-profile")


def toks_of(run: str) -> list[str]:
    try:
        return shlex.split(run.replace("\\\n", " "))
    except ValueError:
        return []


def _index(steps, pred):
    hits = [i for i, s in enumerate(steps) if pred(s)]
    return hits[0] if len(hits) == 1 else None


def _upload_order(text, wf, jobs, out):
    steps = jobs["upload"]["steps"]
    wanted = [
        ("fetch", lambda s: s["uses"].startswith("actions/checkout@")),
        ("digest", lambda s: s["id"] == "scripts"),
        ("jdk", lambda s: s["uses"].startswith("actions/setup-java@")),
        ("download", lambda s: s["uses"].startswith("actions/download-artifact@")),
        ("compare", lambda s: "staged_manifest.py" in s["run"]),
        ("settings", lambda s: "release-settings.xml" in s["run"] and ":deploy-file" not in s["run"]),
        ("upload", lambda s: ":deploy-file" in s["run"]),
    ]
    pos = {}
    for label, pred in wanted:
        pos[label] = _index(steps, pred)
        if pos[label] is None:
            out.add(f"upload-step-not-unique:{label}")
    labels = [lb for lb, _ in wanted]
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            if pos[a] is not None and pos[b] is not None and pos[a] > pos[b]:
                out.add(f"upload-order:{a}-after-{b}")
    if len(steps) != len(wanted):
        out.add("upload-steps-unexpected")
    # nothing runs the build tool before the manifest check, and the digest of the scripts is compared before the script runs
    if pos["compare"] is not None:
        for s in steps[:pos["compare"]]:
            if re.search(r"\bmvn\b", s["run"]):
                out.add("mvn-before-manifest-check:upload")
        run = steps[pos["compare"]]["run"]
        cmp_ = DIGEST_COMPARE.search(run)
        if not cmp_ or cmp_.start() > run.find("staged_manifest.py") or "steps.scripts.outputs.digest" not in steps[pos["compare"]]["env"].get("SCRIPTS_DIGEST", ""):
            out.add("digest-not-reverified:upload")
        if logical_lines(run)[-1] != VERIFY_CALL or run.count("staged_manifest.py") != 1:
            out.add("manifest-check:upload")
    if pos["upload"] is not None and pos["upload"] != len(steps) - 1:
        out.add("upload-order:upload-not-last")


def _publish_order(text, wf, jobs, out):
    steps = jobs["publish"]["steps"]
    imp = _index(steps, lambda s: "gpg --batch --import" in s["run"])
    sign = _index(steps, lambda s: bool(re.search(r"\bmvn\b.*-P release\b.*\bverify\b", s["run"])) and "-DskipTests" in s["run"])
    rem = _index(steps, lambda s: "remove_signing_key.py" in s["run"])
    gate = _index(steps, lambda s: "check_release_readiness.py" in s["run"])
    art = _index(steps, lambda s: s["uses"].startswith("actions/upload-artifact@"))
    for label, i in (("import", imp), ("sign", sign), ("remove", rem), ("gate", gate), ("artifact", art)):
        if i is None:
            out.add(f"publish-step-not-unique:{label}")
    if None in (imp, sign, rem, gate, art):
        return
    if not imp < sign:
        out.add("publish-order:sign-before-import")
    if not sign < rem:
        out.add("removal-before-signing")
    elif rem != sign + 1:
        out.add("removal-not-directly-after-signing")
    if not rem < gate:
        out.add("removal-after-gate")
    if not gate < art:
        out.add("publish-order:artifact-before-gate")
    if not re.fullmatch(r"(\$\{\{\s*)?always\(\)(\s*\}\})?", steps[rem]["if"].strip()):
        out.add("removal-not-always")
    # the gate step stages and makes the manifest, in that order, and is the one step that names both
    g = steps[gate]
    run = g["run"]
    if g["id"] != "gate" or not STAGE_FLAG.search(run) or run.count("staged_manifest.py") != 1:
        out.add("gate-manifest-step")
    else:
        create = re.search(r'staged_manifest\.py" create --dir "\$RUNNER_TEMP/gated-files"\s*\\?\s*--output "\$GITHUB_OUTPUT"\s*$', run.strip())
        if not create or create.start() < run.find("check_release_readiness.py"):
            out.add("gate-manifest-step")
    # the artifact is exactly the staged directory, and only after a gate that passed
    a = steps[art]
    if block_lines(a, "path") != [GATED] or "target" in a["raw"].replace("target:", ""):
        out.add("publish-artifact-path")
    if a["with"].get("if-no-files-found", "").strip() != "error":
        out.add("publish-artifact-empty-allowed")
    if a["if"] or OUTCOME_CONDITION.search(a["raw"]):
        out.add("publish-artifact-not-on-success")
    # the staging directory is the gate's to create: nothing else in the job names it but the manifest step and the artifact
    for s in steps:
        if s is not g and s is not a and ("gated-files" in s["run"] or any("gated-files" in v for v in s["env"].values())):
            out.add("gated-files-written-elsewhere:publish")


def _manifest_travel(text, wf, jobs, out):
    pub = jobs["publish"]
    outs = job_outputs(pub)
    # the manifest leaves `publish` as a job output of the gate step, and the artifact is named after it
    if outs.get("manifest") != "${{ steps.gate.outputs.manifest }}" or set(outs) != {"manifest", "artifact"}:
        out.add("manifest-output")
    if outs.get("artifact") != ARTIFACT:
        out.add("artifact-output")
    art = [s for s in pub["steps"] if s["uses"].startswith("actions/upload-artifact@")]
    if len(art) != 1 or art[0]["with"].get("name") != outs.get("artifact"):
        out.add("artifact-name-mismatch")
    if "github.run_attempt" not in outs.get("artifact", "") or "manifest-id" not in outs.get("artifact", ""):
        out.add("artifact-name-parts")
    if len([s for s in pub["steps"] if s["id"] == "gate"]) != 1:
        out.add("gate-manifest-step")
    bld = [s for s in jobs["build"]["steps"] if s["uses"].startswith("actions/upload-artifact@")]
    if len(bld) != 1 or not bld[0]["with"].get("name", "").startswith("build-gate-") or bld[0]["with"].get("name") == outs.get("artifact"):
        out.add("build-artifact-name")
    for name in ("upload", "attest"):
        steps = jobs[name]["steps"]
        cmp_ = [s for s in steps if "staged_manifest.py" in s["run"]]
        if len(cmp_) != 1 or cmp_[0]["env"].get("MANIFEST") != "${{ needs.publish.outputs.manifest }}":
            out.add(f"manifest-env:{name}")
        # the output is read at one place, into the environment of the step that compares, and nowhere else
        if sum(s["raw"].count("outputs.manifest") for s in steps) != 1:
            out.add(f"manifest-expression-elsewhere:{name}")
        # no file is read as a manifest: the word occurs in a run block only in the verify call
        for s in steps:
            if re.search(r"manifest", s["run"].replace(VERIFY_CALL, ""), re.I):
                out.add(f"manifest-read-from-file:{name}")


def _attest(text, wf, jobs, out):
    steps = jobs["attest"]["steps"]
    if any(s["run"] and kind(s) not in ("Install the gate scripts outside the workspace", "Compare the downloaded files with the manifest")
           for s in steps) or any(re.search(r"\bmvn\b", s["run"]) for s in steps):
        out.add("attest-runs-code")
    dl = _index(steps, lambda s: s["uses"].startswith("actions/download-artifact@"))
    at = _index(steps, lambda s: s["uses"].startswith("actions/attest-build-provenance@"))
    cmp_ = _index(steps, lambda s: "staged_manifest.py" in s["run"])
    if None in (dl, at, cmp_):
        out.add("attest-steps-unexpected")
        return
    if len(steps) != 5:
        out.add("attest-steps-unexpected")
    if not dl < cmp_ < at:
        out.add("attest-before-manifest-check")
    subjects = block_lines(steps[at], "subject-path")
    if subjects != [f"{DOWNLOAD}/*.jar", f"{DOWNLOAD}/*.pom", f"{DOWNLOAD}/*.asc"]:
        out.add("attest-subjects")
    run = steps[cmp_]["run"]
    cmp_digest = DIGEST_COMPARE.search(run)
    if logical_lines(run)[-1] != VERIFY_CALL or not cmp_digest or cmp_digest.start() > run.find("staged_manifest.py") or \
            "steps.scripts.outputs.digest" not in steps[cmp_]["env"].get("SCRIPTS_DIGEST", ""):
        out.add("digest-not-reverified:attest")


def _checkouts_and_digests(text, wf, jobs, out):
    # the scripts come from the commit of this workflow, in every job
    for jname, j in jobs.items():
        own = [s for s in _checkouts(j) if s["with"].get("repository") == SCRIPTS_REPOSITORY]
        if len(own) != 1:
            out.add(f"scripts-checkout-missing:{jname}")
        for s in _checkouts(j):
            if s["with"].get("persist-credentials") != "false":
                out.add(f"scripts-checkout-credentials:{jname}")
            if s["with"].get("repository") and s["with"].get("ref") != SCRIPTS_REF:
                out.add(f"scripts-checkout-ref:{jname}")
            if not s["with"].get("repository") and ("ref" in s["with"]):
                out.add(f"scripts-checkout-ref:{jname}")
    for jname in ("build", "publish"):
        if len(_checkouts(jobs[jname])) != 2:
            out.add(f"caller-checkout:{jname}")
    # a script that runs after project code has run is verified against the digest taken before it
    for jname, j in jobs.items():
        seen_mvn = False
        for s in j["steps"]:
            run = s["run"]
            call = SCRIPT_CALL.search(run)
            if call and ("caps-release-scripts" in run or '"$S/' in run):
                mvn_before = [m.start() for m in re.finditer(r"\bmvn\b", run) if m.start() < call.start()]
                if seen_mvn or mvn_before or jname in ("upload", "attest"):
                    cmp_ = DIGEST_COMPARE.search(run)
                    if not cmp_ or cmp_.start() > call.start() or (mvn_before and cmp_.start() < max(mvn_before)):
                        out.add(f"digest-not-reverified:{jname}")
                    if "SCRIPTS_DIGEST" not in s["env"] or "steps.scripts.outputs.digest" not in s["env"].get("SCRIPTS_DIGEST", ""):
                        out.add(f"digest-not-passed:{jname}")
            if re.search(r"\bmvn\b", run):
                seen_mvn = True


def _gate_staging(text, wf, jobs, out):
    # what is kept is the set the readiness gate staged, and nothing under target/
    for jname in ("build", "publish"):
        steps_ = jobs[jname]["steps"]
        gates = [s for s in steps_ if "check_release_readiness.py" in s["run"]]
        if len(gates) != 1:
            out.add(f"gate-step-not-unique:{jname}")
        for g in gates:
            if not STAGE_FLAG.search(g["run"]):
                out.add(f"gate-not-staging:{jname}")
        ups = [s for s in steps_ if s["uses"].startswith("actions/upload-artifact@")]
        if len(ups) != 1:
            out.add(f"upload-missing:{jname}")
        for u in ups:
            if OUTCOME_CONDITION.search(u["if"]):
                out.add(f"upload-not-on-success:{jname}")
            if gates and steps_.index(u) < steps_.index(gates[0]):
                out.add(f"upload-before-gate:{jname}")
            if any("target" in p for p in block_lines(u, "path")):
                out.add(f"upload-from-target:{jname}")
            if block_lines(u, "path") != [GATED]:
                out.add(f"upload-path-not-gated:{jname}")
            if u["with"].get("if-no-files-found", "").strip() != "error":
                out.add(f"upload-empty-allowed:{jname}")
    for jname in ("upload", "attest"):
        if any("gated-files" in blob for s in jobs[jname]["steps"] for blob in blobs(s)):
            out.add(f"gated-files-written-elsewhere:{jname}")


def _conditions(text, wf, jobs, out):
    # a step of build or publish runs on success, but for the one that removes the key
    for jname in ("build", "publish"):
        for s in jobs[jname]["steps"]:
            if "continue-on-error" in s["keys"]:
                out.add(f"continue-on-error:{jname}")
            if s["if"] and not (jname == "publish" and "remove_signing_key.py" in s["run"]):
                out.add(f"step-condition:{jname}")


def _pins(text, wf, jobs, out):
    for j in jobs.values():
        for s in j["steps"]:
            if s["uses"] and not SHA_PIN.match(s["uses"]):
                out.add("uses-not-pinned")
