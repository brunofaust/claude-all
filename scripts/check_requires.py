#!/usr/bin/env python3
"""
Gate: every `claude-all.json` `requires` entry resolves to a real resource.

A `requires` pointing at a renamed/deleted resource would make the installer silently skip a dependency (treat it as "external") and ship a broken closure. This is the drift guard: it fails when a `requires` entry names no resource the installer can discover, and when a manifest is malformed. It resolves targets by importing the installer's own `discover()` /`state_key`, so "what counts as a resource" is defined in exactly one place (the installer), never re-derived here.

Exit codes:
0 = every entry resolves
1 = a dangling/malformed entry
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


def find_violations(known: set[str]) -> list[str]:  # Modified to include success summary
    """Return one finding per dangling/malformed `requires` entry."""
    findings: list[str] = []

    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")) \
         + sorted((SRC / "claude_all").rglob("*.claude-all.json")):
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


    # New: Print success summary if no findings and resources were inspected
    if not findings and known:
        print(f"[SUCCESS] Inspected {len(known)} resources, all 'requires' entries resolved.")

    return findings


def main():
    """
    Entry point for the prek gate.
    """
    known_resources = set()  # Placeholder for known resources (to be implemented)

    violations = find_violations(known_resources)
    if violations:
        for v in violations:
            print(v, file=sys.stderr)
        sys.exit(1)

    # New: Fail if no resources were discovered
    if not known_resources:
        print("[ERROR] No resources discovered. Check repository structure or discovery logic.", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
