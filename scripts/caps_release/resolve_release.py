#!/usr/bin/env python3
"""Resolve the release version and refuse a ref that cannot release.

Decides, from values it is given and nothing else: whether the inputs are well formed, which
version is released, whether an upload is allowed from this ref, and (on a tag) whether the tagged
commit is on the default branch. It reads no environment variable of GitHub's and writes only the
file named by --output.

Every value is validated as a whole string. Any C0 control character (U+0000-U+001F), DEL (U+007F),
any C1 control character (U+0080-U+009F) and any byte that is not valid UTF-8 refuses the value
before a pattern is tried, so a value cannot pass on one valid line and carry a second `key=value`
into the output file. NUL cannot reach this script through its arguments: argv is a C string and
ends at the first NUL, so the operating system hands over the part before it, and that part is
what is validated. A value that holds NUL inside this process (a test calling `main` with a Python
string) is refused like any other control character. Bash cannot hold NUL in a variable either, so
a validator written in bash could not see one at all.

Usage:
  resolve_release.py --target T --upload U --version V --generated-path P
      --ref-type {tag,branch} --ref-name N --ref R --default-branch B
      [--repository OWNER/NAME --sha SHA] [--compare-status S] [--output FILE]

  --target          none | central | github-packages
  --upload          true | false
  --version         MAJOR.MINOR.PATCH; required off a tag, ignored on a tag unless it differs
  --generated-path  repository-relative path; non-empty, not absolute, no `..`
  --ref-type        `tag` for a tag ref; anything else is a branch ref
  --ref-name        the tag name when --ref-type is tag
  --ref             the full ref, `refs/heads/<default-branch>` allows an upload off a tag
  --compare-status  the answer of the default-branch comparison for the tagged commit. When absent
                    on a tag, `compare_status` asks the API through `gh` (needs --repository,
                    --sha and GH_TOKEN in the environment). Tests replace `compare_status` or
                    pass this flag.

Exit status: 0 resolved; 1 refused (reason on stderr as `::error::`); 2 usage error.
Output: stdout carries one human line `resolved: ...`. With --output, `version=<v>` and
`publish=<true|false>` are appended to that file, one per line, and only on success.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
ON_DEFAULT = ("identical", "behind")


class Refused(Exception):
    """A value or a combination that must not release."""


def control_character(value: str) -> str | None:
    """Name the first character that may not appear in any input, or None."""
    for ch in value:
        o = ord(ch)
        if o < 0x20 or 0x7F <= o <= 0x9F:
            return f"U+{o:04X}"
        if 0xD800 <= o <= 0xDFFF:           # an argument byte that is not UTF-8 decodes to one of these
            return "an undecodable byte"
    return None


def whole(label: str, value: str) -> str:
    found = control_character(value)
    if found:
        raise Refused(f"{label} holds a control character ({found}). It is one line of printable text.")
    return value


def compare_status(repository: str, sha: str, default_branch: str) -> str:
    """Ask GitHub how the commit relates to the default branch. The one place this script uses the network."""
    out = subprocess.run(
        ["gh", "api", f"repos/{repository}/compare/{default_branch}...{sha}", "--jq", ".status"],
        check=True, capture_output=True, text=True)
    return out.stdout.strip()


def resolve(a: argparse.Namespace, compare=compare_status) -> tuple[str, bool]:
    for label in ("target", "upload", "version", "generated_path", "ref_type", "ref_name", "ref",
                  "default_branch", "repository", "sha", "compare_status"):
        whole(label.replace("_", "-"), getattr(a, label) or "")

    if a.target not in ("none", "central", "github-packages"):
        raise Refused(f"target must be 'none', 'central' or 'github-packages', got '{a.target}'.")
    if a.upload not in ("true", "false"):
        raise Refused(f"upload must be 'true' or 'false', got '{a.upload}'.")
    g = a.generated_path
    if not g or g.startswith("/") or ".." in g:
        raise Refused(f"generated-path must be a non-empty path inside the repository, got '{g}'.")

    on_tag = a.ref_type == "tag"
    if on_tag:
        tag = a.ref_name
        if not TAG.fullmatch(tag):
            raise Refused("the tag is not a release tag (expected vMAJOR.MINOR.PATCH). Nothing released.")
        version = tag[1:]
        if a.version and a.version != version:
            raise Refused(f"tag {tag} and version input '{a.version}' disagree. On a tag the version is the tag.")
        if not a.default_branch:
            raise Refused("the default branch is unknown; containment of the tagged commit cannot be checked.")
        status = a.compare_status
        if not status:
            if not (a.repository and a.sha):
                raise Refused("containment of the tagged commit cannot be checked without --repository and --sha.")
            try:
                status = compare(a.repository, a.sha, a.default_branch)
            except (subprocess.CalledProcessError, OSError) as exc:
                raise Refused(f"the comparison with {a.default_branch} failed ({exc}); nothing released.")
        whole("compare status", status)
        if status not in ON_DEFAULT:
            raise Refused(f"tag {tag} points at a commit that is NOT on {a.default_branch} (compare: {status}). "
                          f"Delete the tag, cut it from {a.default_branch}, tag again. Nothing was uploaded.")
        print(f"tag {tag} points at a commit on {a.default_branch} ({status})")
    else:
        version = a.version
        if not SEMVER.fullmatch(version):
            raise Refused(f"version '{version}' is not MAJOR.MINOR.PATCH. A dry run needs one, and never a -SNAPSHOT.")

    publish = False
    if a.upload == "true" and a.target == "none":
        print("::warning::upload was requested with target 'none': nothing is uploaded. Name a target to upload.")
    elif a.upload == "true":
        publish = True
        if not on_tag and (not a.default_branch or a.ref != f"refs/heads/{a.default_branch}"):
            raise Refused(f"An upload from a dispatch is allowed on {a.default_branch or '(unknown default branch)'} only; "
                          f"this ref is {a.ref}. Re-run without upload to exercise the release path from here.")
    return version, publish


def main(argv: list[str] | None = None, compare=compare_status) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("target", "upload", "version", "generated-path", "ref-type", "ref-name", "ref",
                 "default-branch", "repository", "sha", "compare-status", "output"):
        p.add_argument(f"--{flag}", default="")
    a = p.parse_args(argv)
    try:
        version, publish = resolve(a, compare)
    except Refused as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if a.output:
        with open(a.output, "a", encoding="utf-8") as fh:
            fh.write(f"version={version}\npublish={'true' if publish else 'false'}\n")
    print(f"resolved: version={version} target={a.target} publish={'true' if publish else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
