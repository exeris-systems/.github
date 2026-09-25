#!/usr/bin/env python3
"""Cases for `review_plan.py` — which parts of the review a pull request's files call for.

The plan decides what the aggregate holds the runs to, so each case names a diff and the parts it
must and must not run. The last case compares the plan's parts with the routine's own `## Part`
headings: the two are one list kept in two places, and a part in one and not the other is a part
that runs with no rules or has rules that never run.

Usage: review_plan_suite.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import review_plan as rp  # noqa: E402

FAILED: list[str] = []


def case(title):
    def wrap(fn):
        try:
            fn()
            print(f"ok    {title}")
        except Exception as exc:                            # every class is reported, none hidden
            FAILED.append(title)
            print(f"::error title=review_plan_suite::{title}: {type(exc).__name__}: {exc}")
        return fn
    return wrap


def parts(files, routine=""):
    return rp.plan(files, routine)["parts"]


@case("a pull request that changes nothing the parts name still runs `pr`")
def _():
    got = rp.plan(["scripts/x.txt"], "")
    assert got["parts"] == ["pr"], got
    assert set(got["skipped"]) == {"docs", "records", "code-docs", "code", "repo"}, got


@case("every part is either run or skipped with a reason, never both and never neither")
def _():
    for files in ([], ["README.md"], ["docs/adr/ADR-001-x.md", "a.java"]):
        got = rp.plan(files, "rules.md")
        assert sorted(got["parts"] + list(got["skipped"])) == sorted(rp.PARTS), got
        assert all(len(r) > 10 for r in got["skipped"].values()), got


@case("a Markdown page runs `docs`, and so does `.cursorrules`")
def _():
    assert parts(["guides/how-to.md"]) == ["pr", "docs"]
    assert parts([".cursorrules"]) == ["pr", "docs"]
    assert parts(["./.cursorrules"]) == ["pr", "docs"]


@case("an ADR is a page and a record, so it runs both")
def _():
    assert parts(["docs/adr/ADR-087-x.md"]) == ["pr", "docs", "records"]
    assert parts(["adr-index.md"]) == ["pr", "docs", "records"]
    assert parts(["docs/adr/ADR-087.link.md"]) == ["pr", "docs", "records"]
    assert parts(["standards/claims-and-evidence.md"]) == ["pr", "docs", "records"]


@case("code, comments and goldens run `code-docs`")
def _():
    for f in ("core/src/main/java/A.java", "src/index.ts", "scripts/x.py",
              ".github/workflows/w.yml", "config.yaml", "tools/run.sh", "src/tools/list.ts"):
        assert parts([f]) == ["pr", "code-docs", "code"], f
    for f in ("packages/sdk/api/sdk.api.json", "src/app/generated/model.txt"):
        assert parts([f]) == ["pr", "code-docs"], f


@case("`code` reaches every language a build runs, which `code-docs` does not")
def _():
    for f in ("src/Main.kt", "web/app.tsx", "web/util.js", "web/esm.mjs"):
        assert parts([f]) == ["pr", "code"], f


@case("a build file is code by its name, at the root and in a module alike")
def _():
    for f in ("pom.xml", "core/pom.xml", "package.json", "packages/sdk/package.json",
              "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"):
        assert parts([f]) == ["pr", "code"], f
    # A name that only contains a build file's is not one.
    assert parts(["docs/pom.xml.txt", "my-package.json"]) == ["pr"]


@case("generated output is not `code`, whatever its suffix: its generator is the code under review")
def _():
    assert parts(["src/app/generated/model.ts"]) == ["pr", "code-docs"]
    assert parts(["target/generated/Model.java"]) == ["pr", "code-docs"]
    # A directory that merely contains the word is not generated output.
    assert "code" in parts(["src/regenerated/Model.java"])


@case("each scope clause holds on its own, with no other clause to lean on")
def _():
    # A stub outside any `adr/` or `standards/` directory is a record by its name alone.
    assert parts(["ADR-055.link.md"]) == ["pr", "docs", "records"]
    # A tool's description outside the code suffixes is a documented surface by its directory, at
    # the root of the repository and inside a package alike.
    assert parts(["src/tools/list.json"]) == ["pr", "code-docs"]
    assert parts(["packages/mcp/src/tools/list.json"]) == ["pr", "code-docs"]
    # And a directory that only ends in the name is not it.
    assert parts(["notsrc/tools/list.json"]) == ["pr"]


@case("a golden written in Markdown is a page and an API surface")
def _():
    assert parts(["api/sdk.api.md"]) == ["pr", "docs", "code-docs"]


@case("`repo` runs exactly when the repository passes an extension")
def _():
    assert "repo" in parts(["x.txt"], "repo-review-rules.md")
    assert "repo" not in parts(["x.txt"], "")
    assert "repo" not in parts(["x.txt"], "  ")


@case("a directory merely named like a scope is not one: `adrs/` and `standard/` are not records")
def _():
    assert "records" not in parts(["adrs/notes.txt", "standard/x.txt"])


@case("a vendored bundle counts for no part, and a part it would have run says why it did not")
def _():
    got = rp.plan([".agents/vendor/exeris-agents-2.1.0/evals/run.py",
                   ".agents/vendor/exeris-agents-2.1.0/BUNDLE.md"], "")
    assert got["parts"] == ["pr"], got
    for part in ("docs", "code-docs", "code"):
        assert "2 vendored file(s)" in got["skipped"][part], got["skipped"][part]
    # Beside a file of its own, the part runs for that file, and the reason is not needed.
    got = rp.plan([".agents/vendor/exeris-agents-2.1.0/evals/run.py", "scripts/x.py"], "")
    assert got["parts"] == ["pr", "code-docs", "code"], got
    # Only the vendor tree: `.agents/` itself, and a directory merely named `vendor`, are judged.
    assert rp.plan([".agents/manifest.yaml"], "")["parts"] == ["pr", "code-docs", "code"]
    assert rp.plan(["third_party/vendor/lib.py"], "")["parts"] == ["pr", "code-docs", "code"]
    # With nothing vendored, a skip reason carries no note about vendoring.
    assert "vendored" not in rp.plan(["x.txt"], "")["skipped"]["docs"]


@case("the command line writes the matrix and the reasons to GITHUB_OUTPUT")
def _():
    with tempfile.TemporaryDirectory() as tmp:
        files = os.path.join(tmp, "files.txt")
        out = os.path.join(tmp, "gh-output")
        plan_path = os.path.join(tmp, "plan.json")
        with open(files, "w", encoding="utf-8") as fh:
            fh.write("README.md\nsrc/a.ts\n")
        env = dict(os.environ, GITHUB_OUTPUT=out)
        subprocess.run([sys.executable, os.path.join(HERE, "review_plan.py"), "--files", files,
                        "--out", plan_path], check=True, env=env, capture_output=True)
        lines = dict(line.split("=", 1) for line in open(out, encoding="utf-8").read().splitlines())
        assert json.loads(lines["parts"]) == ["pr", "docs", "code-docs", "code"], lines
        assert set(json.loads(lines["skipped"])) == {"records", "repo"}, lines
        assert json.load(open(plan_path, encoding="utf-8"))["parts"] == ["pr", "docs", "code-docs",
                                                                         "code"]


@case("the plan's parts are the routine's `## Part` headings, and `repo` is its extension")
def _():
    with open(os.path.join(ROOT, "docs-guardrails-review.md"), encoding="utf-8") as fh:
        routine = fh.read()
    headed = re.findall(r"^## Part `([a-z-]+)`", routine, re.M)
    assert headed == [p for p in rp.PARTS if p != "repo"], headed
    assert "`repo`" in routine and "## Repository extension" in routine
    for part in headed:
        assert part == "pr" or part in rp.SCOPES, part


if __name__ == "__main__":
    total = sum(1 for line in open(__file__, encoding="utf-8") if line.startswith("@case("))
    print(f"review_plan_suite: ran {total} cases, {len(FAILED)} failures")
    sys.exit(1 if FAILED else 0)
