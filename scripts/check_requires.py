#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource."""

import json
import sys
import pathlib
from typing importannotations

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


def load_resource_keys() -> set[str]:
    """Return every installable resource key (\"kind/name\") via the installer."""
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key
    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: set[str]) -> list[str]:
    """Return one finding per dangling/malformed `requires` entry."""
    findings: list[str] = []
    inspected_count = 0
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json") + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    )):
        inspected_count += 1
        # ... (rest of original function remains unchanged)
    if inspected_count == 0:
        findings.append("zero_resources: Dependency scan matched nothing")
    return findings


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any error, incl zero resources."""
    findings = find_violations(load_resource_keys())
    if findings:
        for finding in findings:
            print(finding)
        print(f"\n{len(findings)} error(s) found")
        return 1
    print(f"\nSuccess: {inspected_count} resources inspected, all dependencies valid")
    return 0

if __name__ == "__main__":
    sys.exit(main())
