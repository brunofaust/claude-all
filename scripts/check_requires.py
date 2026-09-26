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

Exit codes: 0 = every entry resolves · 1 = a dangling/malformed entry · 2 = zero discovery
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

# Glob patterns used to discover manifest files — kept as constants so the
# zero-discovery message can name them explicitly.
MANIFEST_GLOBS = (
    "src/claude_all/**/claude-all.json",
    "src/claude_all/**/*.claude-all.json",
)


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
    """Return all manifest files matching the discovery globs, sorted."""
    return sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    )


def find_violations(known: set[str], manifests: list[Path]) -> list[str]:
    """Return one finding per dangling/malformed ``requires`` entry.

    Args:
        known: Every resolvable resource key.
        manifests: Manifest files to validate (pre-discovered by caller).

    Returns:
        Stable ``path: message`` findings (empty when the graph is clean).
    """
    findings: list[str] = []
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
    return findings


def count_requires_entries(manifests: list[Path]) -> int:
    """Count valid string requires entries across all manifests."""
    total = 0
    for manifest in manifests:
        try:
            config = json.loads(manifest.read_text(encoding="utf-8"))
            requires = config.get("requires", [])
            if isinstance(requires, list):
                total += sum(1 for d in requires if isinstance(d, str))
        except (json.JSONDecodeError, OSError):
            pass
    return total


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any, 2 on zero discovery."""
    known = load_resource_keys()
    manifests = find_manifests()

    # Zero-discovery hard failure: the glob patterns matched nothing.
    if not manifests:
        patterns = " and ".join(f"'{g}'" for g in MANIFEST_GLOBS)
        print(
            f"check_requires: FAIL — zero manifest files matched by glob pattern(s) {patterns}",
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

    # Success: print a single greppable summary line.
    requires_count = count_requires_entries(manifests)
    print(
        f"check_requires: inspected {len(manifests)} manifest file(s) with {requires_count} requires entry(ies)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
