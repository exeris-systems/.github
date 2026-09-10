#!/usr/bin/env python3
"""`labels-from-verdict.json` against the two files it names — ADR-087 §B.7.

The map turns a verdict into labels, and it can be wrong in two directions that a reader cannot
see from the file: a left-hand side the routine may never emit, and a right-hand side no repository
has a label for. Neither shows up as an error when the publish step runs — a tag nothing produces
simply never fires, and a label that does not exist is created by the API with a default colour and
no description, outside the taxonomy `labels.yml` owns.

Both sides are files here — the composed schema's enums and `labels.yml` — which is why this is
checked rather than reviewed.

`decision` is the vendored base's enum and `tag` is the one the composing schema adds — on a
finding rather than on the verdict, so it is read through the same
`#/properties/findings/items` pointer the composition closes over. Both are reached the way a
validator reaches them: by following the relative `$ref` from disk.

Usage: label_map_check.py [--root .] [--map labels-from-verdict.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _common import Report

SCHEMA = os.path.join(".agents", "schemas", "verdict.schema.json")
LABELS = "labels.yml"
# Which verdict field each section of the map keys off, and where in a verdict that field sits:
# the array properties to descend through, `()` being the root object. `tag` is a FINDING's field,
# so the enum bounding it lives inside `findings` — looked for at the root it is simply not there,
# and the check would then call the map unbounded rather than wrong. A section not named here is a
# mapping nothing applies, and the check says so rather than passing over it.
SECTIONS = {
    "decision": ((), "decision"),
    "tag": (("findings",), "tag"),
    "remove-on": ((), "decision"),
}


def spelled(at: tuple[str, ...], field: str) -> str:
    """The field as a reader locates it in a verdict, so a finding names one place and not two."""
    return f"`{field}`" if not at else f"`{field}` on a `{'/'.join(at)}` entry"


def pointed_at(doc, pointer: str):
    """The node a JSON pointer names, or None — `#/properties/findings/items` and nothing fancier."""
    node = doc
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def enums(path: str, at: tuple[str, ...] = ()) -> dict[str, set[str]]:
    """Every property enum this schema imposes on one object, following `$ref`s into the base.

    `at` names that object as the array properties to descend through: `()` is the verdict itself
    and `("findings",)` is one of its findings. Descending is what makes a nested enum findable at
    all — the schema constrains a finding's `tag` under `properties/findings/items`, several
    `allOf` branches and one `$ref` pointer away from the root.

    `allOf` is a conjunction, so a property constrained in more than one branch allows the
    intersection — which is what narrowing means and what a validator will enforce.
    """
    return _enums(json.load(open(path, encoding="utf-8")), path, at, set())


def _enums(node, path: str, at: tuple[str, ...], seen: set) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not isinstance(node, dict):
        return out

    def merge(other: dict[str, set[str]]):
        for key, values in other.items():
            out[key] = out[key] & values if key in out else set(values)

    properties = node.get("properties") or {}
    if at:
        items = (properties.get(at[0]) or {}).get("items")
        if isinstance(items, dict):
            merge(_enums(items, path, at[1:], seen))
    else:
        merge({name: set(spec["enum"]) for name, spec in properties.items()
               if isinstance(spec, dict) and isinstance(spec.get("enum"), list)})

    ref = node.get("$ref")
    if isinstance(ref, str) and not ref.startswith(("http://", "https://")):
        # The pointer is followed as well as the file. A composition closes a nested object by
        # `$ref`-ing `<base>#/properties/<name>/items`, and reading the file and ignoring the
        # pointer lands on the base's ROOT — which is a different object with different enums.
        file_part, _, pointer = ref.partition("#")
        target = (os.path.normpath(os.path.join(os.path.dirname(path), file_part))
                  if file_part else path)
        key = (os.path.realpath(target), pointer)
        if key not in seen and os.path.exists(target):
            seen.add(key)
            document = json.load(open(target, encoding="utf-8"))
            landed = pointed_at(document, pointer) if pointer.startswith("/") else document
            merge(_enums(landed, target, at, seen))

    for branch in node.get("allOf") or []:
        merge(_enums(branch, path, at, seen))
    return out


def main() -> int:
    import yaml

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--map", default="labels-from-verdict.json")
    a = ap.parse_args()
    rep = Report("label_map_check")
    rel = a.map

    map_path = os.path.join(a.root, a.map)
    schema_path = os.path.join(a.root, SCHEMA)
    labels_path = os.path.join(a.root, LABELS)
    for path, what in ((map_path, a.map), (schema_path, SCHEMA), (labels_path, LABELS)):
        if not os.path.exists(path):
            rep.error(what, "does not exist, and the map is checkable only because all three do",
                      rule="label-map")
    if rep.errors:
        sys.exit(rep.emit())

    rep.checked += 1
    try:
        mapping = json.load(open(map_path, encoding="utf-8"))
    except Exception as exc:
        rep.error(rel, f"not valid JSON ({type(exc).__name__}: {exc})", rule="label-map")
        sys.exit(rep.emit())

    allowed = {at: enums(schema_path, at) for at, _ in SECTIONS.values()}
    labels = {entry.get("name") for entry in (yaml.safe_load(open(labels_path, encoding="utf-8"))
                                              or []) if isinstance(entry, dict)}

    for section, values in mapping.items():
        if section.startswith("$"):
            continue
        named = SECTIONS.get(section)
        if named is None:
            rep.error(rel, f"section '{section}' keys off no verdict field — nothing applies it",
                      rule="label-map")
            continue
        at, field = named
        vocabulary = allowed[at].get(field)
        if vocabulary is None:
            rep.error(SCHEMA, f"{spelled(at, field)} has no enum, so section '{section}' of {rel} "
                              f"is checked against nothing", rule="label-map")
            continue
        for key, applied in (values or {}).items():
            if key.startswith("$"):
                continue
            if key not in vocabulary:
                rep.error(rel, f"'{section}.{key}' is not a value of {spelled(at, field)} in "
                               f"{SCHEMA} ({', '.join(sorted(vocabulary))}) — a verdict can never "
                               f"carry it, so the label it names is never applied", rule="label-map")
            for name in ([applied] if isinstance(applied, str) else applied or []):
                if name not in labels:
                    rep.error(rel, f"'{section}.{key}' applies label '{name}', which {LABELS} does "
                                   f"not define — the sync would leave it outside the taxonomy it "
                                   f"owns", rule="label-map")

    sys.exit(rep.emit())


if __name__ == "__main__":
    main()
