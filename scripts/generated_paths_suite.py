#!/usr/bin/env python3
"""Cases for `generated_paths.py` — which changed files are a renderer's copies, and of what.

Each case commits files to a throwaway repository and asks the scanner about them at `HEAD`, the
way the review's step does. The rule that the workflow runs the scanner and the prompt names its
list is `review_inputs_check.py`'s, and its cases are in `review_inputs_check_suite.py`.

Usage: generated_paths_suite.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generated_paths as gp  # noqa: E402

FAILED: list[str] = []


def case(title):
    def wrap(fn):
        try:
            fn()
            print(f"ok    {title}")
        except Exception as exc:                            # every class is reported, none hidden
            FAILED.append(title)
            print(f"::error title=generated_paths_suite::{title}: {type(exc).__name__}: {exc}")
        return fn
    return wrap


def repo_with(files: dict[str, str]) -> str:
    """A throwaway repository with `files` committed at HEAD."""
    tmp = tempfile.mkdtemp()
    run = lambda *cmd: subprocess.run(cmd, cwd=tmp, check=True, capture_output=True)
    run("git", "init", "-q")
    for path, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(tmp, path)) or tmp, exist_ok=True)
        with open(os.path.join(tmp, path), "w", encoding="utf-8") as fh:
            fh.write(text)
    run("git", "add", "-A")
    run("git", "-c", "user.email=s@x", "-c", "user.name=s", "commit", "-q", "-m", "c")
    return tmp


def generated_in(tmp: str, paths: list[str]) -> dict[str, str]:
    here = os.getcwd()
    try:
        os.chdir(tmp)
        return dict(gp.generated(paths, "HEAD"))
    finally:
        os.chdir(here)
        shutil.rmtree(tmp, ignore_errors=True)


@case("a copy's header is read in every comment form a renderer writes, frontmatter above it")
def _():
    tmp = repo_with({
        "hooks/dispatch.py": "#!/usr/bin/env python3\n# DO NOT EDIT. Generated from bundle/hooks/"
                             "bin/dispatch.py by agents_render.py\n",
        ".claude/agents/router.md": "---\nname: router\ndescription: x\n---\n\n<!-- DO NOT "
                                    "EDIT. Generated from .agents/agents/router/AGENT.md by "
                                    "agents_render.py -->\n",
        "gen/a.ts": "// DO NOT EDIT. Generated from model/a.json by codegen\n",
    })
    assert generated_in(tmp, ["hooks/dispatch.py", ".claude/agents/router.md", "gen/a.ts"]) == {
        "hooks/dispatch.py": "bundle/hooks/bin/dispatch.py",
        ".claude/agents/router.md": ".agents/agents/router/AGENT.md",
        "gen/a.ts": "model/a.json"}


@case("prose that quotes the marker is authored, and so is a marker far below the header")
def _():
    deep = "\n".join(["x = 1"] * gp.HEAD_LINES) + "\n# DO NOT EDIT. Generated from src by y\n"
    tmp = repo_with({
        "README.md": "Adapters say DO NOT EDIT. Generated from their source, and are rendered.\n",
        "deep.py": deep,
        "plain.py": "print('hello')\n",
    })
    assert generated_in(tmp, ["README.md", "deep.py", "plain.py"]) == {}


@case("a copy is read at the pull request's commit, not the working tree; a deletion is skipped")
def _():
    tmp = repo_with({"a.py": "# DO NOT EDIT. Generated from src/a.py by r\n"})
    # The working tree put back to base content, as a restoration step does.
    with open(os.path.join(tmp, "a.py"), "w", encoding="utf-8") as fh:
        fh.write("print('base')\n")
    assert generated_in(tmp, ["a.py", "gone.py"]) == {"a.py": "src/a.py"}


@case("the command line writes one `<path>` TAB `<source>` line per copy")
def _():
    tmp = repo_with({"a.py": "# DO NOT EDIT. Generated from src/a.py by r\n", "b.py": "x = 1\n"})
    try:
        with open(os.path.join(tmp, "pr.json"), "w", encoding="utf-8") as fh:
            fh.write('{"files": [{"path": "a.py"}, {"path": "b.py"}]}')
        subprocess.run([sys.executable, os.path.join(HERE, "generated_paths.py"), "--pr", "pr.json",
                        "--out", "list.txt"], cwd=tmp, check=True, capture_output=True)
        with open(os.path.join(tmp, "list.txt"), encoding="utf-8") as fh:
            assert fh.read() == "a.py\tsrc/a.py\n"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    total = sum(1 for line in open(__file__, encoding="utf-8") if line.startswith("@case("))
    print(f"generated_paths_suite: ran {total} cases, {len(FAILED)} failures")
    sys.exit(1 if FAILED else 0)
