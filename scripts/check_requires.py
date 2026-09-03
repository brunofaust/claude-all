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

Exit codes: 0 = every entry resolves · 1 = a dangling/malformed entry, or a
zero-inspection run (the dependency scan matched no resources — a gate that
examined nothing must never report green).
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


def find_violations(known: set[str]) -> list[str]:
    """Return one finding per dangling/malformed ``requires`` entry.

    Args:
        known: Every resolvable resource key.

    Returns:
        Stable ``path: message`` findings (empty when the graph is clean).
    """
    findings: list[str] = []
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    ):
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


def run(known: set[str]) -> int:
    """Validate the manifest graph against *known*; return the process exit code.

    Fails hard when *known* is empty — discovery matched no resources, so the
    scan inspected nothing and must not exit 0 (a gate that examined nothing
    must never report green). On a clean run it prints one greppable summary
    line with the inspected resource count.

    Args:
        known: Every resolvable resource key, as ``load_resource_keys()`` yields.

    Returns:
        0 when every entry resolves and at least one resource was inspected,
        1 otherwise.
    """
    if not known:
        print(
            "ERROR: dependency scan matched ZERO resources — the installer's "
            "discover() found nothing under src/claude_all (renamed/moved "
            "directory?), so no resources were inspected. Refusing to exit 0 on "
            "an empty scan.",
            file=sys.stderr,
        )
        return 1
    findings = find_violations(known)
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} dangling/invalid requires entry(ies) — a dependency "
            "manifest points at a resource the installer cannot discover.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: inspected {len(known)} resource(s), no dangling requires.")
    return 0


def main() -> int:
    """CLI entry point — run the gate on the installer's discovered resources."""
    return run(load_resource_keys())


if __name__ == "__main__":
    sys.exit(main())
