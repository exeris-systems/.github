#!/usr/bin/env python3
"""Resolve the release version and refuse a ref that cannot release.

Decides, from values it is given and nothing else: whether the inputs are well formed, which
version is released, whether an upload is allowed from this ref, and (on a tag) whether the tagged
commit is on the default branch. It reads no environment variable of GitHub's and writes only the
file named by --output.

Every value is validated as a whole string. Any code point of Unicode category Cc (the C0 controls
U+0000-U+001F, DEL and the C1 controls U+0080-U+009F), Cf (format, which includes the bidirectional
controls and the zero-width characters), Zl and Zp (the line and paragraph separators, U+2028 and
U+2029) or Cn (unassigned), and any byte that is not valid UTF-8, refuses the value before a pattern
is tried, in EVERY input, so a value cannot pass on one valid line and carry a second `key=value`
into the output file or hide behind a character that renders as nothing. NUL cannot reach this script through its arguments: argv is a C string and
ends at the first NUL, so the operating system hands over the part before it, and that part is
what is validated. A value that holds NUL inside this process (a test calling `main` with a Python
string) is refused like any other control character. Bash cannot hold NUL in a variable either, so
a validator written in bash could not see one at all.

Usage:
  resolve_release.py --target T --upload U --version V --generated-path P
      --ref-type {tag,branch} --ref-name N --ref R --default-branch B
      [--repository OWNER/NAME --sha SHA] [--compare-status S] [--output FILE]
      [--java-distribution D] [--java-version J]

  --target          none | github-packages (any other value is refused)
  --upload          true | false
  --version         MAJOR.MINOR.PATCH, each number written as 0 or without a leading zero and of at
                    most 9 digits (semantic versioning forbids a leading zero; 9 digits fit every
                    version type Maven and Java use); required off a tag, ignored on a tag unless it
                    differs
  --generated-path  repository-relative path; non-empty, not absolute, no `..` segment (`..` between
                    `/` or a backslash; `a..b` is a file name), no glob character (`*`, `?`, `[`,
                    `]`) and no leading `:` (pathspec magic)
  --java-distribution  temurin | graalvm: what the organisation's workflows install (any other value is
                    refused). Given, it is validated and written to --output as `java-distribution=<D>`;
                    a later job reads it from there and never from the caller's input, so the JDK
                    that runs on a runner holding a credential is the validated one. Not given, it is
                    neither validated nor written.
  --java-version    NN, NN.x, NN.N or NN.N.N: a major version of one or two digits without a leading zero,
                    optionally `.x`, or followed by one or two numbers of at most three digits
                    (`25`, `21.x`, `25.0.2`). Handled like --java-distribution, written as
                    `java-version=<J>`.
  --ref-type        `tag` for a tag ref; anything else is a branch ref
  --ref-name        the tag name when --ref-type is tag
  --ref             the full ref, `refs/heads/<default-branch>` allows an upload off a tag
  --compare-status  the answer of the default-branch comparison for the tagged commit. When absent
                    on a tag, `compare_status` asks the API through `gh` (needs --repository,
                    --sha and GH_TOKEN in the environment). Tests replace `compare_status` or
                    pass this flag.

A version, given or tagged, is ASCII: any other character refuses it (Maven's case-insensitive SNAPSHOT
test folds characters a Python `lower()` does not). The `gh` call is bounded by a timeout; its expiry
refuses.

Exit status: 0 resolved; 1 refused (reason on stderr as `::error::`); 2 usage error.
Output: stdout carries one human line `resolved: ...`. With --output, `version=<v>` and
`publish=<true|false>` (and `java-distribution` and `java-version` when given) are appended to that
file, one per line, and only on success.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata

GH_TIMEOUT = 120
NUMBER = r"(?:0|[1-9][0-9]{0,8})"
SEMVER = re.compile(rf"{NUMBER}\.{NUMBER}\.{NUMBER}")
TAG = re.compile(rf"v{NUMBER}\.{NUMBER}\.{NUMBER}")
PATH_SEPARATORS = re.compile(r"[/\\]")
ON_DEFAULT = ("identical", "behind")
JAVA_DISTRIBUTIONS = ("temurin", "graalvm")
JAVA_VERSION = re.compile(r"[1-9][0-9]?(?:\.x|(?:\.(?:0|[1-9][0-9]{0,2})){1,2})?")


class Refused(Exception):
    """A value or a combination that must not release."""


def control_character(value: str) -> str | None:
    """Describe the first character that may not appear in any input, or None."""
    for ch in value:
        o = ord(ch)
        if 0xD800 <= o <= 0xDFFF:           # an argument byte that is not UTF-8 decodes to one of these
            return "an undecodable byte"
        category = unicodedata.category(ch)
        if category == "Cc":
            return f"a control character (U+{o:04X})"
        if category in ("Cf", "Zl", "Zp", "Cn"):
            return f"a non-printing or unassigned character (U+{o:04X})"
    return None


def whole(label: str, value: str) -> str:
    found = control_character(value)
    if found:
        raise Refused(f"{label} holds {found}. It is one line of printable text.")
    return value


def compare_status(repository: str, sha: str, default_branch: str) -> str:
    """Ask GitHub how the commit relates to the default branch. The one place this script uses the network."""
    out = subprocess.run(
        ["gh", "api", f"repos/{repository}/compare/{default_branch}...{sha}", "--jq", ".status"],
        check=True, capture_output=True, text=True, timeout=GH_TIMEOUT)
    return out.stdout.strip()


def resolve(a: argparse.Namespace, compare=compare_status) -> tuple[str, bool]:
    for label in ("target", "upload", "version", "generated_path", "ref_type", "ref_name", "ref",
                  "default_branch", "repository", "sha", "compare_status", "output"):
        whole(label.replace("_", "-"), getattr(a, label) or "")
    for label in ("java_distribution", "java_version"):
        whole(label.replace("_", "-"), getattr(a, label) or "")

    if a.target not in ("none", "github-packages"):
        raise Refused(f"target must be 'none' or 'github-packages', got '{a.target}'.")
    if a.upload not in ("true", "false"):
        raise Refused(f"upload must be 'true' or 'false', got '{a.upload}'.")
    if a.java_distribution is not None and a.java_distribution not in JAVA_DISTRIBUTIONS:
        raise Refused(f"java-distribution must be one of {', '.join(JAVA_DISTRIBUTIONS)}, got '{a.java_distribution}'.")
    if a.java_version is not None and not JAVA_VERSION.fullmatch(a.java_version):
        raise Refused(f"java-version must be NN, NN.x or NN.N.N (for example 25, 21.x or 25.0.2), got '{a.java_version}'.")
    g = a.generated_path
    if (not g or g.startswith("/") or g.startswith(":") or any(c in g for c in "*?[]")
            or ".." in PATH_SEPARATORS.split(g)):
        raise Refused(f"generated-path must be a non-empty path inside the repository, without a `..` segment, "
                      f"a glob character or a leading `:`, got '{g}'.")

    on_tag = a.ref_type == "tag"
    if on_tag:
        tag = a.ref_name
        if not TAG.fullmatch(tag):
            raise Refused("the tag is not a release tag (expected vMAJOR.MINOR.PATCH). Nothing released.")
        version = tag[1:]
        if not a.version.isascii():
            raise Refused("the version holds a non-ASCII character; a release version is ASCII only.")
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
            except Exception as exc:
                raise Refused(f"the comparison with {a.default_branch} failed ({' '.join(str(exc).split())}); "
                              "nothing released.")
        whole("compare status", status)
        if status not in ON_DEFAULT:
            raise Refused(f"tag {tag} points at a commit that is NOT on {a.default_branch} (compare: {status}). "
                          f"Delete the tag, cut it from {a.default_branch}, tag again. Nothing was uploaded.")
        print(f"tag {tag} points at a commit on {a.default_branch} ({status})")
    else:
        version = a.version
        if not version.isascii():
            raise Refused("the version holds a non-ASCII character; a release version is ASCII only.")
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
    try:
        return run(argv, compare)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::the release resolution failed unexpectedly ({type(exc).__name__}: "
              f"{' '.join(str(exc).split())}).", file=sys.stderr)
        return 1


def run(argv: list[str] | None, compare) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("target", "upload", "version", "generated-path", "ref-type", "ref-name", "ref",
                 "default-branch", "repository", "sha", "compare-status", "output"):
        p.add_argument(f"--{flag}", default="")
    for flag in ("java-distribution", "java-version"):
        p.add_argument(f"--{flag}", default=None)
    a = p.parse_args(argv)
    try:
        version, publish = resolve(a, compare)
    except Refused as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if a.output:
        with open(a.output, "a", encoding="utf-8") as fh:
            fh.write(f"version={version}\npublish={'true' if publish else 'false'}\n")
            for key, value in (("java-distribution", a.java_distribution), ("java-version", a.java_version)):
                if value is not None:
                    fh.write(f"{key}={value}\n")
    print(f"resolved: version={version} target={a.target} publish={'true' if publish else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
