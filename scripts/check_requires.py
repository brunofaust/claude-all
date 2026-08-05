#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

def find_violations(known: set[str]) -> list[str]:
    """Return one finding per dangling/malformed `requires` entry.

    Args:
        known: Every resolvable resource key.

    Returns:
        Stable `path: message` findings (empty when the graph is clean).
    """
    """Return one finding per dangling/malformed `requires` entry.

    Args:
        known: Every resolvable resource key.

    Returns:
        Stable `path: message` findings (empty when the graph is clean).
    """
    def find_violations(known: set[str]) -> list[str]:
        findings: list[str] = []
        resource_count = 0  # New counter for resources inspected
        for manifest in sorted((SRC / "claude_all").rglob("claude-all.json"), key=lambda p: p.parts):
            resource_count += 1  # Increment counter for each resource
            rel = manifest.relative_to(REPO_ROOT)  # Get relative path for reporting
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
                        f"a built-in like /code-review does not belong in requires)"
                    )
        
        # New: Report if no resources were inspected
        if resource_count == 0:
            findings.insert(0, "No resources were inspected. Check discovery patterns in find_violations()")
            sys.exit(1)
        
        return findings
    if not isinstance(dep, str):
        findings.append(f"{rel}: non-string dependency {dep!r}")
    elif dep not in known:
        findings.append(
            f"{rel}: requires '{dep}' — no such resource (renamed/deleted?"
            f"a built-in like /code-review does not belong in requires)"
        )
    findings = []
    resource_count = 0  # New counter for resources inspected
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")):
        resource_count += 1  # Increment counter for each resource
        rel = manifest.relative_to(REPO_ROOT)  # Get relative path for reporting
        try:
            config = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(f"{rel}: not valid JSON — {exc}")
        
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
                    f"a built-in like /code-review does not belong in requires)"
                )
    
    if resource_count == 0:
        findings.insert(0, "No resources were inspected. Check discovery patterns in find_violations()")
        sys.exit(1)
    
    return findings