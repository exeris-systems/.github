"""Run the first steps of the `upload` job of caps-release.yml as the runner would: the `run:` blocks are parsed out of the
workflow and executed by bash, so the commands under test are the workflow's own and not copies of them.

The steps that are actions (checkout, setup-java, download-artifact) are replaced by what they leave behind: the scripts of this
repository in `.caps-release-src/`, and the artifact's files in `$RUNNER_TEMP/gated-download`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import textwrap

import caps_release_helpers as h
import workflow_invariants as w

INSTALL = "Install the gate scripts outside the workspace"
COMPARE = "Compare the downloaded files with the manifest"
SETTINGS = "Write the Maven settings"
UPLOAD = "Upload the gated files"


def step_of(job: str, name: str) -> dict:
    with open(h.WORKFLOW, encoding="utf-8") as fh:
        steps = [s for s in w.parse(fh.read())["jobs"][job]["steps"] if s["name"] == name]
    assert len(steps) == 1, f"job {job} must hold exactly one step named {name!r}"
    return steps[0]


def step_run(job: str, name: str) -> str:
    return textwrap.dedent(step_of(job, name)["run"]).strip("\n") + "\n"


def bash(script: str, env: dict, cwd: str | None = None, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script], env=env, cwd=cwd, capture_output=True,
                          text=True, timeout=timeout)


def runner_env(runner_temp: str, **extra) -> dict:
    env = {"PATH": "/usr/bin:/bin" + (":" + os.environ["PATH"] if "PATH" in os.environ else ""), "HOME": os.path.expanduser("~"),
           "LC_ALL": "C.UTF-8", "RUNNER_TEMP": runner_temp, "GITHUB_REPOSITORY": "owner/repository", "GITHUB_ACTOR": "actor"}
    if "JAVA_HOME" in os.environ:
        env["JAVA_HOME"] = os.environ["JAVA_HOME"]
    env.update(extra)
    return env


def install_scripts(case: h.Case, job: str, runner_temp: str) -> str:
    """Run the job's install step against a workspace that holds this repository's scripts; return the digest it publishes."""
    workspace = os.path.join(case.tmp, "workspace")
    src = os.path.join(workspace, ".caps-release-src", "scripts")
    os.makedirs(src, exist_ok=True)
    shutil.copytree(h.SCRIPT_DIR_OVERRIDE or h.SCRIPT_DIR, os.path.join(src, "caps_release"), ignore=shutil.ignore_patterns("__pycache__"),
                    dirs_exist_ok=True)
    output, summary = os.path.join(case.tmp, "install-output"), os.path.join(case.tmp, "install-summary")
    for f in (output, summary):
        open(f, "w").close()
    done = bash(step_run(job, INSTALL), runner_env(runner_temp, GITHUB_OUTPUT=output, GITHUB_STEP_SUMMARY=summary, SCRIPTS_COMMIT="0" * 40),
                cwd=workspace)
    case.assertEqual(done.returncode, 0, done.stderr)
    with open(output, encoding="utf-8") as fh:
        line = fh.read().strip()
    case.assertRegex(line, r"^digest=[0-9a-f]{64}$")
    return line.split("=", 1)[1]


def compare(job: str, runner_temp: str, digest: str, manifest: str | None) -> subprocess.CompletedProcess:
    """Run the job's comparison step; MANIFEST is unset when `manifest` is None, as an output that was never produced would leave it."""
    extra = {"SCRIPTS_DIGEST": digest}
    if manifest is not None:
        extra["MANIFEST"] = manifest
    return bash(step_run(job, COMPARE), runner_env(runner_temp, **extra))
