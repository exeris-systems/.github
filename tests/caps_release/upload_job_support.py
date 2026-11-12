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


STUB = '#!/usr/bin/python3\nimport json, sys\nwith open({record!r}, "a", encoding="utf-8") as fh:\n    fh.write(json.dumps(sys.argv[1:]) + "\\n")\n'
KNOWN_PROPERTIES = ("repositoryId", "url", "pomFile", "file", "sources", "javadoc", "files", "classifiers", "types")
SUFFIXES = (".jar", ".pom", "-sources.jar", "-javadoc.jar")


def upload_arguments(case: h.Case, bases) -> list[list[str]]:
    """The argument vector of every `mvn` call the workflow's own upload step makes for the coordinates BASES.

    The download directory holds the eight files of each base; the job's comparison step accepts it against the manifest `create` made of
    it, the settings step runs, and the upload step runs with a `mvn` that records its arguments and does nothing else.
    """
    import json

    from manifest_support import SCRIPT, make_coordinate, parse_github_output
    runner = case.path("runner")
    download = os.path.join(runner, "gated-download")
    os.makedirs(download)
    for base in bases:
        make_coordinate(download, base)
    output = case.path("github-output")
    made = h.run_main(SCRIPT, ["create", "--dir", download, "--output", output])
    case.assertEqual(made.rc, 0, made)
    with open(output, encoding="utf-8") as fh:
        manifest = parse_github_output(fh.read())["manifest"]
    digest = install_scripts(case, "upload", runner)
    compared = compare("upload", runner, digest, manifest)
    case.assertEqual(compared.returncode, 0, compared.stdout + compared.stderr)
    env = runner_env(runner, GITHUB_TOKEN="not-a-token")
    settings = bash(step_run("upload", SETTINGS), env)
    case.assertEqual(settings.returncode, 0, settings.stderr)
    record = case.path("argv-record")
    stub_dir = case.path("stub")
    os.makedirs(stub_dir)
    stub = os.path.join(stub_dir, "mvn")
    with open(stub, "w", encoding="utf-8") as fh:
        fh.write(STUB.format(record=record))
    os.chmod(stub, 0o755)
    env["PATH"] = stub_dir + ":" + env["PATH"]
    done = bash(step_run("upload", UPLOAD), env)
    case.assertEqual(done.returncode, 0, done.stdout + done.stderr)
    with open(record, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def assert_arguments_of(case: h.Case, argv: list[str], base: str, settings: str) -> None:
    """The call names exactly the files of BASE, in the four `-Dfiles` entries, and no element of it is an option the step did not write."""
    options = {"-B", "-ntp", "--settings"}
    values = {}
    for arg in argv:
        if arg.startswith("-D"):
            key, sep, value = arg[2:].partition("=")
            case.assertTrue(sep and key in KNOWN_PROPERTIES and key not in values, f"{arg!r} is not an option the step writes, once")
            values[key] = value
        elif arg.startswith("-"):
            case.assertIn(arg, options, f"{arg!r} is an option the step does not write")
        else:
            case.assertIn(arg, ("org.apache.maven.plugins:maven-deploy-plugin:3.1.4:deploy-file", settings), f"{arg!r} is an argument the step does not write")
    case.assertEqual(set(values), set(KNOWN_PROPERTIES))
    case.assertEqual(values["pomFile"], base + ".pom")
    case.assertEqual(values["file"], base + ".jar")
    case.assertEqual(values["sources"], base + "-sources.jar")
    case.assertEqual(values["javadoc"], base + "-javadoc.jar")
    case.assertEqual(values["files"].split(","), [base + s + ".asc" for s in SUFFIXES])
    case.assertEqual(len(values["files"].split(",")), 4)
    case.assertEqual(values["classifiers"].split(","), ["", "", "sources", "javadoc"])
    case.assertEqual(values["types"].split(","), ["jar.asc", "pom.asc", "jar.asc", "jar.asc"])
    case.assertEqual(argv.count("--settings"), 1)
    case.assertEqual(argv[argv.index("--settings") + 1], settings)
    for key in ("pomFile", "file", "sources", "javadoc"):
        case.assertFalse(values[key].startswith("-"), values[key])
    case.assertFalse(any(entry.startswith("-") for entry in values["files"].split(",")))
