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

Exit codes: 0 = every entry resolves · 1 = a dangling/malformed entry or zero discovery.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


def load_resource_keys() -> set[str]:
    """Return every installable resource key (``kind/name``) via the installer.

    Returns:
        The set the installer's ``discover([])`` would yield, keyed exactly as a
        ``requires`` entry must be written.
    """
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key

    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: set[str]) -> tuple[list[str], int]:
    """Return one finding per dangling/malformed ``requires`` entry.

    Args:
        known: Every resolvable resource key.

    Returns:
        Tuple of (findings list, manifest count examined).
    """
    findings: list[str] = []
    manifests = sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    )
    for manifest in manifests:
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
    return findings, len(manifests)


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any."""
    known = load_resource_keys()

    findings, manifest_count = find_violations(known)

    # Zero-discovery check: fail loudly if we found no manifests to validate
    if manifest_count == 0:
        print(
            "0 manifests matched the discovery pattern "
            "src/claude_all/**/*.claude-all.json — dependency check would validate nothing",
            file=sys.stderr,
        )
        return 1

    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} dangling/invalid requires entry(ies) — a dependency "
            "manifest points at a resource the installer cannot discover.",
            file=sys.stderr,
        )
        return 1

    # Success: report how many units we actually inspected
    print(f"inspected {manifest_count} manifests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
