#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource.

Also checks that resources named by an instruction snippet are in its `requires`.
Targets are resolved via the installer's own `discover()`, never re-derived here.
Exit 0 = all resolve, 1 = dangling/malformed entry.
# BDN-2 fix: ensures zero-discovery fails loudly
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Backward compatibility attribute for tests
SRC = None  # Will be set below

CODE_SPAN = re.compile(r"`([^`\s]+)`")


def get_repo_root() -> Path:
    """Get the repository root, allowing override for testing."""
    test_base = os.environ.get("CLAUDE_ALL_TEST_BASE")
    if test_base:
        return Path(test_base)
    return Path(__file__).resolve().parent.parent


def get_src_path() -> Path:
    """Get the src path."""
    return get_repo_root() / "src"


def get_instructions_dir() -> Path:
    """Get the instructions directory path."""
    return get_src_path() / "claude_all" / "instructions"


# Set backward compatibility attribute
SRC = get_src_path()


def load_resource_keys() -> set[str]:
    """Return every installable resource key (``kind/name``) via the installer."""
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key

    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: set[str], manifest_paths: list[Path]) -> list[str]:
    findings: list[str] = []
    repo_root = get_repo_root()
    for manifest in sorted(manifest_paths):
        rel = manifest.relative_to(repo_root)
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


def find_undeclared_instruction_refs(
    known: set[str], snippet_paths: list[Path], instructions_dir: Path
) -> list[str]:
    keys_by_name: dict[str, set[str]] = {}
    for key in known:
        keys_by_name.setdefault(key.split("/", 1)[1], set()).add(key)
    findings: list[str] = []
    for snippet in sorted(snippet_paths):
        manifest = snippet.parent / "claude-all.json"
        declared: set[str] = set()
        if manifest.exists():
            try:
                declared = set(json.loads(manifest.read_text(encoding="utf-8")).get("requires", []))
            except (json.JSONDecodeError, OSError, TypeError):
                declared = set()
        own = f"instructions/{snippet.parent.name}"
        rel = snippet.relative_to(instructions_dir.parent)
        for token in sorted(set(CODE_SPAN.findall(snippet.read_text(encoding="utf-8")))):
            candidates = keys_by_name.get(token, set()) - {own}
            if candidates and not candidates & declared:
                findings.append(
                    f"{rel}: names `{token}` but its claude-all.json does not require "
                    + " or ".join(sorted(candidates))
                )
    return findings


def main() -> int:
    """CLI entry point - print findings to stdout, exit 1 on any."""
    # Discover files relative to the repository root
    manifest_paths = list(
        sorted((get_src_path() / "claude_all").rglob("claude-all.json"))
        + sorted((get_src_path() / "claude_all").rglob("*.claude-all.json"))
    )
    snippet_paths = sorted(get_instructions_dir().glob("*/claude_md.md"))

    # Check for zero discovery
    if not manifest_paths and not snippet_paths:
        print(
            "error: no claude-all.json or *.claude-all.json manifests found in src/claude_all",
            file=sys.stderr,
        )
        print(
            "error: no */claude_md.md snippets found in src/claude_all/instructions",
            file=sys.stderr,
        )
        return 2

    # Calculate total units for summary
    total_units = len(manifest_paths) + len(snippet_paths)

    known = load_resource_keys()
    findings = find_violations(known, manifest_paths) + find_undeclared_instruction_refs(
        known, snippet_paths, get_instructions_dir()
    )
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} requires finding(s) - a dependency manifest points at a "
            "resource the installer cannot discover, or an instruction names one it "
            "does not require.",
            file=sys.stderr,
        )
        return 1

    # Success case - print scanned summary
    print(f"scanned={total_units}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
