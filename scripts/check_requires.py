from __future__ import annotations
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

    def load_resource_keys() -> list[Path]:
        """Load all resource keys from claude-all.json manifests."""
        # Implementation of load_resource_keys not shown in provided snippets
        pass

    def find_violations(known: list[Path]) -> list[str]:
        """Find invalid requires entries in all claude-all.json files."""
        # Implementation of find_violations not shown in provided snippets
        pass

    if not findings and inspected > 0:
        print(f" ✔ {inspected} claude-all.json files inspected, all requires valid.", file=sys.stderr)
    return findings
    print(f" ✔ {inspected} claude-all.json files inspected, all requires valid.", file=sys.stderr)
return findings

def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any."""
    findings = find_violations(load_resource_keys())
    for finding in findings:
        print(finding)
    return len(findings)
