#!/usr/bin/env python3
"""The release-readiness gate: what a release would send is complete and signed.

Inspects the root `target/` of a single-module build (the same files the run artifact keeps and the
attestation covers). Every coordinate, one per main jar (a `*.jar` that is not `-sources`,
`-javadoc` or `-tests`), needs:

  * a sources jar, a javadoc jar and a pom beside it, none missing;
  * an `index.html` in the javadoc jar;
  * a detached `.asc` for the main jar, the sources jar, the javadoc jar and the pom, each a good
    signature under the keyring `gpg` is pointed at (GNUPGHOME in the environment);
  * a version that is not a -SNAPSHOT.

With --expect-bundle true, `<target-dir>/central-publishing/central-bundle.zip` must exist and every
file in it must sit in a <group>/<artifact>/<version>/ directory that holds
<artifact>-<version>.pom and be named <artifact>-<version>.* or <artifact>-<version>-*. Central
refuses the whole deployment for one stray file.

All findings are reported before the gate fails; no main jar is fatal at once.

Usage: check_release_readiness.py --target-dir DIR [--expect-bundle {true,false}] [--uploaded] [--gpg PATH]

  --expect-bundle  default false
  --uploaded       the run has already uploaded: the final refusal also says to drop the deployment
  --gpg            the gpg executable (default `gpg`)

Exit status: 0 ready; 1 any finding; 2 usage error.
Output: `coordinate: <name> - main, sources, javadoc, pom, signatures` per coordinate without a finding,
`central bundle: N file(s), M outside a coordinate`, `release-readiness: ok`; findings on stderr as
`::error::`.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile


def stray_entries(names: list[str]) -> list[str]:
    entries = [n for n in names if not n.endswith("/")]
    stray = []
    for name in entries:
        directory, _, filename = name.rpartition("/")
        parts = directory.split("/")
        stem = f"{parts[-2]}-{parts[-1]}" if len(parts) >= 3 else None
        if (stem is None or f"{directory}/{stem}.pom" not in entries
                or not filename.startswith((stem + ".", stem + "-"))):
            stray.append(name)
    return stray


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target-dir", required=True)
    p.add_argument("--expect-bundle", choices=["true", "false"], default="false")
    p.add_argument("--uploaded", action="store_true")
    p.add_argument("--gpg", default="gpg")
    a = p.parse_args(argv)

    findings: list[str] = []

    def err(msg: str) -> None:
        findings.append(msg)
        print(f"::error::{msg}", file=sys.stderr)

    try:
        names = sorted(os.listdir(a.target_dir))
    except OSError as exc:
        print(f"::error::{a.target_dir} cannot be read ({exc}).", file=sys.stderr)
        return 1
    t = a.target_dir
    mains = [n for n in names if n.endswith(".jar") and os.path.isfile(os.path.join(t, n))
             and not n.endswith(("-sources.jar", "-javadoc.jar", "-tests.jar"))]
    if not mains:
        print("::error::the build produced no main jar", file=sys.stderr)
        return 1

    def good_signature(asc: str, f: str) -> bool:
        try:
            return subprocess.run([a.gpg, "--verify", asc, f], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
        except OSError:
            return False

    for main_jar in mains:
        before = len(findings)
        base = main_jar[:-len(".jar")]
        if base.endswith("-SNAPSHOT"):
            err(f"{base} is a SNAPSHOT; a release is final")
        files = [main_jar, f"{base}-sources.jar", f"{base}-javadoc.jar", f"{base}.pom"]
        for want in files[1:]:
            if not os.path.isfile(os.path.join(t, want)):
                err(f"{base} is missing {want} - Central rejects a coordinate without it")
        javadoc = os.path.join(t, f"{base}-javadoc.jar")
        if os.path.isfile(javadoc):
            try:
                if "index.html" not in zipfile.ZipFile(javadoc).namelist():
                    err(f"{base}-javadoc.jar holds no index.html")
            except zipfile.BadZipFile:
                err(f"{base}-javadoc.jar is not a zip file")
        for f in files:
            path = os.path.join(t, f)
            if not os.path.isfile(path):
                continue
            if not os.path.isfile(path + ".asc"):
                err(f"{f} has no detached signature")
            elif not good_signature(path + ".asc", path):
                err(f"{f}.asc is not a good signature")
        if len(findings) == before:
            print(f"coordinate: {base} - main, sources, javadoc, pom, signatures")

    if a.expect_bundle == "true":
        bundle = os.path.join(t, "central-publishing", "central-bundle.zip")
        if not os.path.isfile(bundle):
            err(f"{bundle} is missing; the release profile builds it at deploy")
        else:
            try:
                listed = zipfile.ZipFile(bundle).namelist()
            except zipfile.BadZipFile:
                err(f"{bundle} is not a zip file")
            else:
                stray = stray_entries(listed)
                for name in sorted(stray):
                    err(f"central bundle: {name} is not a file of a published coordinate")
                print(f"central bundle: {len([n for n in listed if not n.endswith('/')])} file(s), "
                      f"{len(stray)} outside a coordinate")

    if findings:
        tail = "; if a deployment was uploaded, DROP it in the portal." if a.uploaded else ""
        print(f"::error::release-readiness failed{tail}", file=sys.stderr)
        return 1
    print("release-readiness: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
