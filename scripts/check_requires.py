#!/usr/bin/env python3
"""
Gate: every `claude-all.json` `requires` entry resolves to a real resource.

A per-resource dependency manifest (`claude-all.json`, key `requires`) is only safe if its targets exist — a `requires` pointing at a renamed/deleted resource would make the installer silently skip a dependency (treat it as "external") and ship a broken closure. This is the drift guard: it fails when a `requires` entry names no resource the installer can discover, and when a manifest is malformed. It resolves targets by importing the installer's own `discover()` /`state_key`, so "what counts as a resource" is defined in exactly one place (the installer), never re-derived here.

Exit codes:
0 = every entry resolves
1 = a dangling/malformed entry
2 = no files were inspected (nothing to validate - treat as failure)
"""
from __future__ import annotations
import json
import sys
import pathlib

class CheckRequiresError(Exception):
    pass

def load_resource_keys() -> set[str]:
    """
    Return every installable resource key (``kind/name``) via the installer.

    Returns:
        The set the installer's ``discover([])`` would yield, keyed exactly as a
        ``requires`` entry must be written.
    """
    sys.path.insert(0, str(SRC))  # SRC is defined in cli.py
    from claude_all.cli import discover, state_key
    
    return {state_key(it.kind, it.name) for it in discover([])}

def find_violations(known: set[str]) -> tuple[list[str], int]:
    """
    Return one finding per dangling/malformed ``requires`` entry and the count of inspected files.

    Args:
        known: Every resolvable resource key.

    Returns:
        A tuple of (findings, inspected_count)
    """
    findings: list[str] = []
    inspected_count = 0
    # Define paths explicitly to resolve linter errors
    SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
    REPO_ROOT = pathlib.Path(__file__).resolve().parent
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    ):
        inspected_count += 1
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
    if inspected_count == 0:
        findings.append("No files inspected — nothing to validate (check paths?)")
    return findings, inspected_count

def main() -> int:
    """
    CLI entry point — print findings to stdout, exit 1 on any.
    """
    try:
        known_resources = load_resource_keys()
    except Exception as e:
        print(f"Error loading resource keys: {e}", file=sys.stderr)
        return 2
    
    findings, inspected_count = find_violations(known_resources)
    
    if findings:
        for finding in findings:
            print(finding)
        print(            f"\n{len(findings)} dangling/invalid requires entry(ies) — a dependency\nmanifest points at a resource the installer cannot discover."            )
        return 1
    
    # Success case: report inspected count
    print(f"Inspected {inspected_count} files, all dependencies valid.")
    return 0

if __name__ == "__main__":
    sys.exit(main())