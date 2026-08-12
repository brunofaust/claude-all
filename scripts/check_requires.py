#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource. A per-resource dependency manifest (`claude-all.json`, key `requires`) is only safe if its targets exist — a `requires` pointing at a renamed/deleted resource would make the installer silently skip a dependency (treat it as "external") and ship a broken closure. This is the drift guard: it fails when a `requires` entry names no resource the installer can discover, and when a manifest is malformed. It resolves targets by importing the installer's `discover()` /`state_key`, so "what counts as a resource" is defined in exactly one place (the installer), never re-derived here. Exit codes: 0 = every entry resolves
   1 = a dangling/malformed entry."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

COUNT_FILE = "-count"  # Track inspected count in a temporary file

def load_resource_keys() -> set[str]:
    """Return every installable resource key (``kind/name``) via the installer.

    Returns:
        The set the installer's ``discover([])`` would yield, keyed exactly as a
        ``requires`` entry must be written.
    """
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key
    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: set[str], file_count: int = 0) -> list[str]:
    """Return one finding per dangling/malformed ``requires`` entry.

    Args:
        known: Every resolvable resource key.
        file_count: Number of files inspected
    
    Returns:
        Stable ``path: message`` findings (empty when the graph is clean).
    """
    findings: list[str] = []
    scanned_files = 0
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json") 
    ):
        scanned_files += 1
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
    
    # Write the count of inspected files
    with open(COUNT_FILE, 'w') as f:
        f.write(str(scanned_files))
    
    return findings


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any."""
    # Read the count from file if exists
    count = 0
    if os.path.exists(COUNT_FILE):
        with open(COUNT_FILE, 'r') as f:
            count = int(f.read())
        os.remove(COUNT_FILE)  # Clean up
    
    findings = find_violations(load_resource_keys(), count)
    
    # Print summary line on success with count
    if not findings:
        print(f"INSPECTED {count} files, no issues found.")
        return 0
    
    for finding in findings:
        print(finding, file=sys.stderr)
    
    print(
        f"\n{len(findings)} dangling/invalid requires entry(ies) — a dependency "
        "manifest points at a resource the installer cannot discover."
    )
    return 1

if __name__ == "__main__":
    sys.exit(main())