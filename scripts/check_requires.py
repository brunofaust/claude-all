#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource. A per-resource dependency manifest (`claude-all.json`, key `requires`) is only safe if its targets exist — a `requires` pointing at a renamed/deleted resource would make the installer silently skip a dependency (treat it as "external") and ship a broken closure. This is the drift guard: it fails when a `requires` entry names no resource the installer can discover, and when a manifest is malformed. It resolves targets by importing the installer's own `discover()` /`state_key`, so "what counts as a resource" is defined in exactly one place (the installer), never re-derived here. Exit codes: 0 = every entry resolves · 1 = a dangling/malformed entry. """
from __future__ import annotations
import json
import sys
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


def load_resource_keys() -> set[str]:
    """Return every installable resource key (\"kind/name\") via the installer.\n\n    Returns: The set the installer's ``discover([])`` would yield, keyed exactly as a\n    ``requires`` entry must be written. """
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key
    
    keys = {state_key(it.kind, it.name) for it in discover([])}
    
    # New: Print success message with inspected count
    if keys:
        print(f"Inspected {len(keys)} resources")
    
    return keys


def find_violations(known: set[str]) -> list[str]:
    """Return one finding per dangling/malformed ``requires`` entry."""
    findings: list[str] = []
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")):
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
                    f"{rel}: requires '{dep}' — no such resource (renamed/deleted? \n" +
                    f"    a built-in like /code-review does not belong in requires)" 
                )
    # Remove the second rglob (now redundant)
    return findings


def main() -> int:
    """CLI entry point -- print findings to stdout, exit 1 on any."""
    known = load_resource_keys()
    
    # New: Handle zero-discovery case
    if not known:
        print("No resources discovered. Check discovery logic.", file=sys.stderr)
        return 1
    
    findings = find_violations(known)
    for finding in findings:
        print(finding)
    
    if findings:
        print(
            f"\n{len(findings)} dangling/invalid requires entry(ies) -- a dependency \n" +
            f"    manifest points at a resource the installer cannot discover."
        , file=sys.stderr
        )
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())