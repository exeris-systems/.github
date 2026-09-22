#!/usr/bin/env python3
"""The components a review run's identity is derived from, exported as digests — ADR-087 §C.14,
ADR-086 §C.14a.

The produce job runs the model and holds no write scope, so nothing downstream can look inside it
afterwards: the prompt it rendered, the routine it ran, the agent file the runner read and the
allow-list it ran under exist only while that job does. This reads them where they are and writes
out their DIGESTS. It decides nothing, fetches nothing, and touches neither the network nor the
clock — every value it writes is a function of a file it was handed or of an argument it was given.

NO TEXT LEAVES THE JOB. Everything written is a hash, a commit SHA, a version or a timestamp, and
each is a single line by construction. The prompt carries the pull request's body and its file
list, and the execution log carries the review's own reasoning; the public inbox is closed to that
material in any form. A digest of it is a comparison key rather than a copy, and a step that
exported one line of the text would have to be read as exporting all of it.

A COMPONENT THAT CANNOT BE READ COSTS THE DERIVED HASH, NEVER A CONVENIENT ONE. The rule the
contract is written to is no row rather than a plausible value, so a prompt or a routine this
cannot read leaves `system-prompt-sha256` empty and a consumer sees a component it did not get,
which is distinguishable from a component that was read. Two absences are STATES rather than
failures and are recorded as such: a repository with no agent file contributes the empty component,
which is one newline and the same value every time, and a launch with no allow-list is recorded
inside `tool-surface` as `null` rather than as a missing field.

WHY TWO DERIVATIONS ARE COPIED RATHER THAN IMPORTED. `system_prompt_sha256` and `tool_surface`
below are the producer's own definitions, carried here byte for byte with their docstrings. This
workflow runs in every repository that calls it, and a job that had to check a second repository
out to name its own inputs would fail for a reason that has nothing to do with the review it was
asked for. What a copy costs is drift, and the comparison that catches drift is already required:
a reconstructed hash and a live exported one are checked component by component, and two
canonicalisations that have parted company disagree there.

Usage: review_surface.py --prompt FILE --routine FILE [component paths] [--print]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

# The ten values the produce job exports, in the order they are written. The list is here rather
# than spelled out at each write so that the step, the job outputs and the publishing inputs can be
# read against one enumeration instead of against three.
EXPORTED = (
    "prompt-sha256",
    "routine-sha256",
    "routine-sha",
    "agents-md-sha256",
    "system-prompt-sha256",
    "tool-surface",
    "bundle-version",
    "checkout-sha",
    "head-sha",
    "review-started-at",
)


# --------------------------------------------------------------------------------------------
# Reading what the job holds
# --------------------------------------------------------------------------------------------


def read_text(path: str | None) -> str | None:
    """A component's text, or None where there is no file to read or its bytes are not UTF-8.

    A path that names nothing and a path that names something unreadable are one answer, because
    the hash cannot be computed either way. What the caller does with that answer differs by
    component, and it differs where the contract says it does rather than here.
    """
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def read_json(path: str | None) -> tuple[object | None, bool]:
    """A settings file's parsed content, and whether reading it succeeded.

    The two answers are separate because an absent settings file and an unparseable one are not the
    same state. A checkout that declares no permissions and one whose settings file this cannot
    read permit different things, and only the first is a state the canonicalisation has a value
    for.
    """
    text = read_text(path)
    if text is None:
        return None, not path or not os.path.exists(path)
    try:
        return json.loads(text), True
    except ValueError:
        return None, False


def component(text: str) -> str:
    """One component of the system-prompt hash, terminated the way the hash concatenates it.

    This is the per-component half of the normalisation `system_prompt_sha256` performs over all
    three at once, and the two agreeing is what makes the exported component digests checkable
    against the exported composite: a reader with the three texts can compute both and a reader
    with neither text can still tell which component of two runs differed.
    """
    return (text[:-1] if text.endswith("\n") else text) + "\n"


def component_sha256(text: str) -> str:
    """The digest of one normalised component."""
    return hashlib.sha256(component(text).encode("utf-8")).hexdigest()


def allow_tokens(value: str | None) -> list[str] | None:
    """The tools the client was launched with, or None where the launch passed no allow-list.

    The workflow hands over the value of `--allowedTools` rather than the whole launch line, so the
    only thing left to do with it is the split, which is at bracket depth zero: a token may carry a
    comma inside its own parentheses and a naive split would report one permission as two —
    `Bash(git log --format=a,b:*)` is one rule, and two halves of it are two rules the run never
    had.

    None and `[]` are different states and stay different: no allow-list is a run under the client's
    own defaults, and an empty one is a run permitted nothing. `tool_surface` records which.
    """
    if value is None:
        return None
    out, depth, current = [], 0, ""
    for character in value:
        if character in "([":
            depth += 1
        elif character in ")]":
            depth = max(0, depth - 1)
        if character == "," and depth == 0:
            out.append(current)
            current = ""
        else:
            current += character
    out.append(current)
    return [part.strip() for part in out if part.strip()]


def bundle_version(manifest: str | None, vendor_dir: list[str] | None) -> str | None:
    """`repository_state.bundle_version` — the pinned `exeris-agents` version in the checkout.

    The manifest's pin is the answer where there is one: it is the version the repository DECLARES
    it is on. A vendored tree with no manifest still names its version in the directory it was
    unpacked into, and that is the second answer, not a preferred one — a directory name is what the
    tree was called, while a pin is what the repository committed to. Neither present is no answer:
    the bundle carries the rules the run was subject to, so a value invented here would say what the
    run was subject to on no evidence.
    """
    if manifest:
        block = re.search(r"^\s*-\s*bundle:\s*exeris-agents\s*$(.*?)(?=^\s*-\s|\Z)",
                          manifest, re.M | re.S)
        if block:
            pin = re.search(r"^\s*version:\s*\"?([0-9]+\.[0-9]+\.[0-9]+)\"?\s*$",
                            block.group(1), re.M)
            if pin:
                return pin.group(1)
    for name in sorted(vendor_dir or []):
        found = re.fullmatch(r"exeris-agents-([0-9]+\.[0-9]+\.[0-9]+)", name)
        if found:
            return found.group(1)
    return None


# --------------------------------------------------------------------------------------------
# The two derivations the producer owns, carried here verbatim
# --------------------------------------------------------------------------------------------


def tool_surface(allow: list[str] | None, perms: dict | None) -> str:
    """`execution.tool_surface` — canonicalisation v1, documented here because it is the producer's.

    The contract leaves the canonicalisation to the producer and requires the producer to state it,
    so that the hash compares only across producers that canonicalise alike. Version 1 is SHA-256
    over this text, UTF-8:

        json.dumps({"v": 1, "allow": A, "checkout_permissions": P},
                   sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"

    `A` is the allow-list the client was launched with — stripped, deduplicated and sorted — or
    `null` where the launch passed none. `P` is the permission rules the checkout declares, as the
    client's own settings spell them, or `null` where it declares none.

    Three properties it is built for. An absent allow-list and an absent permission rule set are
    RECORDED STATES inside the text — `null`, written — never an absent field: a run under no
    allow-list is a run whose powers are known, and no digest would have meant "unrestricted". The
    allow-list is sorted because the surface is what the run was permitted and not the order
    somebody typed it, so two spellings of one surface hash alike. And the client's own tool
    manifest is outside the hash entirely: it says what the client offers, which is not what this
    run was permitted.

    One distinction it deliberately does not make. A checkout with no settings file and a checkout
    whose settings declare no permission rules are both `null` here, because the run was permitted
    the same things under either, and this hash is over what the run was permitted rather than over
    what the repository happens to contain.

    `"v": 1` is inside the hashed text so that a change to this canonicalisation is legible in the
    hash's own input and not only in the fence that must accompany it.
    """
    tokens = None if allow is None else sorted(set(part for part in allow if part))
    rules = perms.get("permissions") if isinstance(perms, dict) else None
    payload = {"v": 1, "allow": tokens, "checkout_permissions": rules}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def system_prompt_sha256(prompt: str, routine: str, agents_md: str) -> str:
    """`agent.system_prompt_sha256` — the instructions the repository controlled, in §C.14's order.

    Three components, each with one trailing newline stripped and exactly one appended, concatenated
    as prompt, routine, agent file. The normalisation is what makes the hash a function of the text
    rather than of how a host happened to terminate it, and the order is fixed because a hash over a
    set would be the same hash for two different arrangements of the same instructions.

    An empty third component is the documented state of a repository with no `AGENTS.md`: it
    contributes exactly one newline, the same value every time, so two such repositories agree and
    neither is confused with a repository whose agent file is an empty file.
    """
    parts = [(part[:-1] if part.endswith("\n") else part) + "\n"
             for part in (prompt, routine, agents_md)]
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------
# The export
# --------------------------------------------------------------------------------------------


def surface(args: argparse.Namespace) -> tuple[dict[str, str], list[str]]:
    """The ten values, and what could not be read.

    A value that could not be derived is the empty string, which is also what a consumer sees for a
    producer that never ran this step. That is deliberate: the two cases mean the same thing to a
    reader — this component was not exported — and a consumer that had to tell them apart would be
    acting on the difference between a producer with no step and a producer with an unreadable file.
    """
    out = dict.fromkeys(EXPORTED, "")
    unread: list[str] = []

    prompt = read_text(args.prompt)
    routine = read_text(args.routine)
    agents_md = read_text(args.agents_md)

    if prompt is None:
        unread.append(f"the rendered prompt ({args.prompt or 'not named'})")
    else:
        out["prompt-sha256"] = component_sha256(prompt)
    if routine is None:
        unread.append(f"the review routine ({args.routine or 'not named'})")
    else:
        out["routine-sha256"] = component_sha256(routine)
    # An absent agent file is the documented empty component and is hashed as one. Only a file that
    # exists and cannot be decoded is unread, and that one costs the composite like any other.
    if agents_md is None and args.agents_md and os.path.exists(args.agents_md):
        unread.append(f"the agent file ({args.agents_md})")
    else:
        out["agents-md-sha256"] = component_sha256(agents_md or "")

    if prompt is not None and routine is not None and out["agents-md-sha256"]:
        out["system-prompt-sha256"] = system_prompt_sha256(prompt, routine, agents_md or "")

    perms, readable = read_json(args.settings)
    if not readable:
        unread.append(f"the checkout's permission rules ({args.settings})")
    else:
        out["tool-surface"] = tool_surface(allow_tokens(args.allowed_tools),
                                           perms if isinstance(perms, dict) else None)

    vendor = None
    if args.vendor_dir and os.path.isdir(args.vendor_dir):
        vendor = sorted(os.listdir(args.vendor_dir))
    out["bundle-version"] = bundle_version(read_text(args.manifest), vendor) or ""

    out["routine-sha"] = args.routine_sha or ""
    out["checkout-sha"] = args.checkout_sha or ""
    out["head-sha"] = args.head_sha or ""
    out["review-started-at"] = args.review_started_at or ""
    return out, unread


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompt", default="", help="the rendered prompt the runner was handed")
    ap.add_argument("--routine", default="", help="the review routine the runner was pointed at")
    ap.add_argument("--routine-sha", default="", help="the commit the routine was read at")
    ap.add_argument("--agents-md", default="",
                    help="the reviewed checkout's agent file, if it has one")
    # Absent and empty are different launches, so the option's absence is not the empty string.
    ap.add_argument("--allowed-tools", default=None,
                    help="the value of --allowedTools; omit the option where the launch passed none")
    ap.add_argument("--settings", default="", help="the checkout's client settings, if it has any")
    ap.add_argument("--manifest", default="", help="the checkout's bundle manifest, if it has one")
    ap.add_argument("--vendor-dir", default="", help="the checkout's vendored bundle directory")
    ap.add_argument("--checkout-sha", default="", help="the commit the reviewed tree was read at")
    ap.add_argument("--head-sha", default="", help="the pull request's head commit")
    ap.add_argument("--review-started-at", default="",
                    help="when the reviewing step began, RFC 3339 UTC")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="write the pairs to stdout as well, for a run outside a workflow")
    args = ap.parse_args(argv)

    values, unread = surface(args)
    for said in unread:
        print(f"::notice title=review_surface::{said} could not be read, so the hashes over it are "
              f"not exported — a consumer sees a component it did not get rather than a value "
              f"nobody measured")
    lines = [f"{key}={values[key]}" for key in EXPORTED]
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    if args.show or not destination:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
