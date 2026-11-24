#!/usr/bin/env python3
"""Mechanical diff of two ThomsonLint design exports (baseline -> revised).

Each side is a directory holding one schematic export (*-thomson-export-sch.json,
"mode": "schematic"), optionally one board export (*-thomson-export-brd.json,
"mode": "board") and optionally one stackup export (*-thomson-export-stack.json,
"mode": "stackup"), as written by the Fusion Electronics ULPs, tools/fusion_export.py
or the KiCad exporter. Board and stackup are each diffed only when both sides
have one (one side only is an error).
The diff is deterministic: no judgement, just what changed. An AI reviewer then
reviews DIFF.json together with both designs.

Usage:
    python tools/thomson-diff.py <baseline-dir> <revised-dir> [-o DIFF.json]

Only uses the Python standard library.

Comparison rules:
- Records are matched by identity, not position: components by "ref", nets
  and board signals by "name"; any other list of objects that all carry a
  unique "name" (e.g. a component's pads) by that name.
- Other lists are compared as multisets (order is not meaningful in the
  exports): what is only in the baseline is "removed", only in the revised
  "added".
- Numbers are equal within 1e-6.
- "export_date" is ignored, and "project.name" (an absolute path that the
  ULP points into a temp directory) is compared by its file name only.
- Nets that disappear and appear under a new name with exactly the same pins
  are reported as "renamed" instead of removed + added.
"""

import argparse
import json
import os
import sys

DIFF_VERSION = "1.0"
KEYED_LISTS = {"components": "ref", "nets": "name", "signals": "name"}
IGNORED_KEYS = {"thomsonlint_version", "export_date", "mode"}
FLOAT_TOLERANCE = 1e-6


# ── loading ────────────────────────────────────────────────

def load_export(path):
    """Parse an export. The Fusion ULP writes the host's ANSI code page (e.g.
    "µ" as byte 0xB5), not UTF-8, so fall back to cp1252, then latin-1."""
    with open(path, "rb") as fh:
        raw = fh.read()
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return json.loads(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: cannot decode")  # unreachable: latin-1 decodes anything


def find_exports(directory):
    """{"schematic": path or None, "board": path or None} for one side."""
    found = {"schematic": [], "board": [], "stackup": []}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not (os.path.isfile(path) and name.lower().endswith(".json")):
            continue
        try:
            mode = load_export(path).get("mode")
        except (ValueError, AttributeError):
            continue
        if mode in found:
            found[mode].append(path)
    for mode, paths in found.items():
        if len(paths) > 1:
            raise ValueError(f"{directory}: more than one {mode} export: {', '.join(paths)}")
    if not found["schematic"]:
        raise ValueError(f"{directory}: no schematic export (a JSON file with \"mode\": \"schematic\")")
    return {mode: (paths[0] if paths else None) for mode, paths in found.items()}


# ── comparison ─────────────────────────────────────────────

def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= FLOAT_TOLERANCE
    return a == b


def _identity_key(a, b):
    """The key two lists of objects can be matched by — present as a string
    and unique within each list — or None."""
    if not (a or b) or not all(isinstance(i, dict) for i in a + b):
        return None
    for key in ("ref", "name"):
        if all(_unique_strings([i.get(key) for i in items]) for items in (a, b)):
            return key
    return None


def _unique_strings(values):
    return all(isinstance(v, str) for v in values) and len(set(values)) == len(values)


def diff_values(a, b, path=""):
    """Changes between two JSON values, as a list of records:
    {"path", "from", "to"} for a changed value, {"path", "added", "removed"}
    for a list compared as a multiset, and {"path", "added", "removed",
    "changed"} for a list of identified objects (see diff_keyed)."""
    if isinstance(a, dict) and isinstance(b, dict):
        changes = []
        for key in sorted(set(a) | set(b)):
            sub = f"{path}.{key}" if path else key
            if key not in a:
                changes.append({"path": sub, "from": None, "to": b[key]})
            elif key not in b:
                changes.append({"path": sub, "from": a[key], "to": None})
            else:
                changes.extend(diff_values(a[key], b[key], sub))
        return changes
    if isinstance(a, list) and isinstance(b, list):
        key = _identity_key(a, b)
        if key is not None:
            keyed = diff_keyed(a, b, key)
            return [{"path": path, **keyed}] if any(keyed.values()) else []
        added, removed = _multiset_diff(a, b)
        return [{"path": path, "added": added, "removed": removed}] if (added or removed) else []
    if _equal(a, b):
        return []
    return [{"path": path, "from": a, "to": b}]


def _multiset_diff(a, b):
    remaining = {}
    for item in a:
        remaining.setdefault(_canonical(item), []).append(item)
    added = []
    for item in b:
        bucket = remaining.get(_canonical(item))
        if bucket:
            bucket.pop()
        else:
            added.append(item)
    removed = [item for bucket in remaining.values() for item in bucket]
    return added, removed


def diff_keyed(a, b, key):
    """Match two lists of objects by `key`: {"added": [objects],
    "removed": [objects], "changed": [{key: id, "changes": [...]}]}."""
    base = {item[key]: item for item in a}
    rev = {item[key]: item for item in b}
    changed = []
    for ident in sorted(set(base) & set(rev)):
        changes = diff_values(base[ident], rev[ident])
        if changes:
            changed.append({key: ident, "changes": changes})
    return {
        "added":   [rev[i] for i in sorted(set(rev) - set(base))],
        "removed": [base[i] for i in sorted(set(base) - set(rev))],
        "changed": changed,
    }


def _pin_set(net):
    return _canonical(sorted(_canonical(p) for p in net.get("pins") or []))


def detect_net_renames(nets_diff):
    """Move removed/added nets with identical, non-empty pin sets to
    "renamed": [{"from", "to", "changes"}]."""
    renamed = []
    by_pins = {}
    for net in nets_diff["removed"]:
        if net.get("pins"):
            by_pins.setdefault(_pin_set(net), []).append(net)
    still_added = []
    for net in nets_diff["added"]:
        candidates = by_pins.get(_pin_set(net)) if net.get("pins") else None
        if candidates:
            old = candidates.pop(0)
            changes = [c for c in diff_values(old, net) if c["path"] != "name"]
            renamed.append({"from": old["name"], "to": net["name"], "changes": changes})
        else:
            still_added.append(net)
    renamed_from = {r["from"] for r in renamed}
    nets_diff["added"] = still_added
    nets_diff["removed"] = [n for n in nets_diff["removed"] if n["name"] not in renamed_from]
    nets_diff["renamed"] = renamed
    return nets_diff


def _normalize(export):
    export = {k: v for k, v in export.items() if k not in IGNORED_KEYS}
    project = export.get("project")
    if isinstance(project, dict) and isinstance(project.get("name"), str):
        name = project["name"].replace("\\", "/").rsplit("/", 1)[-1]
        export["project"] = {**project, "name": name}
    return export


def diff_exports(base, rev):
    """Section-by-section diff of two exports of the same kind."""
    base, rev = _normalize(base), _normalize(rev)
    result = {}
    for key in sorted(set(base) | set(rev)):
        a, b = base.get(key), rev.get(key)
        if key in KEYED_LISTS and isinstance(a or [], list) and isinstance(b or [], list):
            section = diff_keyed(a or [], b or [], KEYED_LISTS[key])
            if key == "nets":
                section = detect_net_renames(section)
        else:
            section = diff_values(a, b)
        result[key] = section
    return result


def _summary(section_diff):
    summary = {}
    for key, section in section_diff.items():
        if isinstance(section, dict):
            summary[key] = {k: len(v) for k, v in section.items()}
        else:
            summary[key] = {"changes": len(section)}
    return summary


def build_diff(baseline_dir, revised_dir):
    base_files, rev_files = find_exports(baseline_dir), find_exports(revised_dir)
    for mode in ("board", "stackup"):
        if (base_files[mode] is None) != (rev_files[mode] is None):
            side = "baseline" if base_files[mode] else "revised"
            raise ValueError(f"only the {side} side has a {mode} export — a {mode} diff needs both or neither")

    diff = {
        "thomsonlint_diff_version": DIFF_VERSION,
        "baseline": base_files,
        "revised": rev_files,
        "schematic": diff_exports(load_export(base_files["schematic"]), load_export(rev_files["schematic"])),
        "board": None,
        "stackup": None,
    }
    for mode in ("board", "stackup"):
        if base_files[mode]:
            diff[mode] = diff_exports(load_export(base_files[mode]), load_export(rev_files[mode]))
    diff["summary"] = {
        mode: (_summary(diff[mode]) if diff[mode] is not None else None)
        for mode in ("schematic", "board", "stackup")
    }
    return diff


def main():
    parser = argparse.ArgumentParser(description="Mechanical diff of two ThomsonLint design exports.")
    parser.add_argument("baseline", help="directory with the baseline exports")
    parser.add_argument("revised", help="directory with the revised exports")
    parser.add_argument("-o", "--output", help="write the diff here instead of stdout")
    args = parser.parse_args()

    try:
        diff = build_diff(args.baseline, args.revised)
    except (OSError, ValueError) as exc:
        print(f"thomson-diff: {exc}", file=sys.stderr)
        sys.exit(1)

    text = json.dumps(diff, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
