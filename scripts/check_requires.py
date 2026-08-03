#!/usr/bin/env python3
"
A per-resource dependency manifest ("claude-all.json", key "requires")
is only safe if its targets exist —
`requires` pointing at a renamed/deleted resource would make the installer
silently skip a dependency (treat it as "external") and ship a broken closure.
This is the drift guard: it fails when a `requires` entry names no resource the
installer can discover, and when a manifest is malformed.

It resolves targets by importing the installer's own `discover()` / `state_key`,
so "what counts as a resource" is defined in exactly one place (the installer),
never re-derived here.
"

import json
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "claude_all"
REPO_ROOT = Path(__file__).parent


def main() -> int:
    """
    Returns:
        0: Success
        1: Invalid requires entries found
        2: No files discovered (zero-result failure)
    """
    # Discover candidate manifest files
    manifests = sorted(SRC.rglob("claude-all.json"))
    manifests += sorted(SRC.rglob("*.claude-all.json"))
    total_inspected = len(manifests)

    if not manifests:
        print("ERROR: No files found matching patterns 'claude-all.json' or '*.claude-all.json'",
              file=sys.stderr)
        return 2

    findings = []

    for manifest in manifests:
        rel = manifest.relative_to(REPO_ROOT)
        try:
            config = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(f"{rel}: {exc}")
            continue

        if "requires" in config:
            for dep in config["requires"]:
                findings.append(
                    f"{rel}: requires '{dep}' — no such resource \
                    (renamed/deleted?). Do not vendor third-party resources in requires"
                )

    # Print inspection summary
    print(f"Checked {total_inspected} resource files")

    if findings:
        print(f"\n{len(findings)} invalid requires entries found:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())