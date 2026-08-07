# Exit codes: 0 = success (at least one resource inspected), 1 = no resources inspected (failure)

import json
import sys
from pathlib import Path
from typing import Set

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


def load_resource_keys() -> Set[str]:
    """Return every installable resource key (``kind/name``) via the installer."
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key

    """When `discover` is called with an empty list, it returns all resources."
    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: Set[str]) -> list[str]:
    """Return one finding per dangling/malformed ``requires`` entry."
    findings: list[str] = []
    inspected_count = 0

    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json") + (SRC / "claude_all").rglob("*.claude-all.json")):
        rel = manifest.relative_to(REPO_ROOT)
        inspected_count += 1

        try:
            with manifest.open("r", encoding="utf-8") as f:
                config = json.load(f)
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

    # Add summary line on success
    if not findings:
        print(f"Scanned {inspected_count} files, all requires entries valid")

    return findings


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any violation
    or zero files inspected."
    known = load_resource_keys()
    findings = find_violations(known)

    # Count how many files we should have inspected
    total_files = 0
    for pattern in ["claude-all.json", "*.claude-all.json"]:
        for manifest in (SRC / "claude_all").rglob(pattern):
            total_files += 1

    # If zero files were inspected, report failure
    if total_files == 0:
        print("No claude-all.json files found — nothing to inspect")
        return 1

    for finding in findings:
        print(finding)

    if findings:
        print(
            f"\n{len(findings)} dangling/invalid requires entry(ies) — a dependency "
            "manifest points at a resource the installer cannot discover.",
            file=sys.stderr,
        )
        return 1

    # All checks passed, but zero files were scanned (empty repo)
    if total_files == 0:
        print("No claude-all.json files found — nothing to inspect")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
