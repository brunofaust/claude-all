#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource.

A per-resource dependency manifest (`claude-all.json`, key `requires`) is only
safe if its targets exist — a `requires` pointing at a renamed/deleted resource
would make the installer silently skip a dependency (treat it as "external") and
ship a broken closure. This is the drift guard: it fails when a `requires` entry
names no resource the installer can discover, and when a manifest is malformed.

It resolves targets by importing the installer's own `discover()` /`state_key`,
so "what counts as a resource" is defined in exactly one place (the installer),
never re-derived here.

Discovery is fail-loud: a glob that matches nothing fails OPEN — the scan
inspects zero manifests, exits 0, and the gate reports green while guarding
nothing. So a run where discovery comes up empty exits non-zero naming the
pattern that matched nothing, and every clean run prints how many manifests it
actually inspected.

Exit codes: 0 = every entry resolves · 1 = a dangling/malformed entry ·
2 = discovery matched nothing (a gate that inspected zero units never passes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
MANIFEST_PATTERNS = ("claude-all.json", "*.claude-all.json")


def load_resource_keys() -> set[str]:
    """Return every installable resource key (``kind/name``) via the installer.

    Returns:
        The set the installer's ``discover([])`` would yield, keyed exactly as a
        ``requires`` entry must be written.
    """
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key

    return {state_key(it.kind, it.name) for it in discover([])}


def find_manifests() -> list[Path]:
    """Return every dependency manifest under ``src/claude_all`` — the unit this
    gate inspects.

    Two shapes exist: a bare ``claude-all.json`` beside a folder resource, and a
    ``<name>.claude-all.json`` sibling of a flat resource (the same convention
    as the ``hook.*``/``.claude_md.md`` companions).
    """
    base = SRC / "claude_all"
    return [p for pattern in MANIFEST_PATTERNS for p in sorted(base.rglob(pattern))]


def find_violations(known: set[str], manifests: list[Path] | None = None) -> list[str]:
    """Return one finding per dangling/malformed ``requires`` entry.

    Args:
        known: Every resolvable resource key.
        manifests: Manifests to inspect; defaults to :func:`find_manifests`.

    Returns:
        Stable ``path: message`` findings (empty when the graph is clean).
    """
    findings: list[str] = []
    for manifest in find_manifests() if manifests is None else manifests:
        rel = manifest.relative_to(REPO_ROOT)
        try:
            config = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(f"{rel}: not valid JSON — {exc}")
            continue
        requires = config.get("requires", [])
        if not isinstance(requires, list):
            findings.append(f"{rel}: `requires` must be a list of 'kind/name' strings")
            continue
        for dep in requires:
            if not isinstance(dep, str):
                findings.append(f"{rel}: non-string dependency {dep!r}")
            elif dep not in known:
                findings.append(
                    f"{rel}: requires '{dep}' — no such resource (renamed/deleted? "
                    "a built-in like /code-review does not belong in requires)"
                )
    return findings


def main() -> int:
    """CLI entry point — findings on stdout; non-zero on findings or empty discovery."""
    manifests = find_manifests()
    if not manifests:
        patterns = " and ".join(f"`{p}`" for p in MANIFEST_PATTERNS)
        print(
            f"check_requires: 0 manifests matched {patterns} under "
            f"{(SRC / 'claude_all').relative_to(REPO_ROOT)} — a renamed/moved "
            "directory would do exactly this; a gate that inspected nothing never passes.",
            file=sys.stderr,
        )
        return 2
    known = load_resource_keys()
    if not known:
        print(
            "check_requires: installer discover([]) returned 0 resources — resource "
            "discovery is broken (renamed/moved tree?), so no `requires` entry can "
            "be validated.",
            file=sys.stderr,
        )
        return 2
    findings = find_violations(known, manifests)
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} dangling/invalid requires entry(ies) — a dependency "
            "manifest points at a resource the installer cannot discover.",
            file=sys.stderr,
        )
        return 1
    print(
        f"check_requires: {len(manifests)} manifest(s) inspected — "
        "every `requires` entry resolves."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
