#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource.

Also checks that resources named by an instruction snippet are in its `requires`.
Targets are resolved via the installer's own `discover()`, never re-derived here.
Exit 0 = all resolve, 1 = dangling/malformed entry.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
INSTRUCTIONS_DIR = SRC / "claude_all" / "instructions"
CODE_SPAN = re.compile(r"`([^`\s]+)`")


def load_resource_keys() -> set[str]:
    """Return every installable resource key (``kind/name``) via the installer."""
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key

    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: set[str], manifests: Iterable[Path] | None = None) -> list[str]:
    if manifests is None:
        manifests = sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
            (SRC / "claude_all").rglob("*.claude-all.json")
        )
    findings: list[str] = []
    for manifest in sorted(manifests):
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
    return findings


def find_undeclared_instruction_refs(
    known: set[str], snippets: Iterable[Path] | None = None
) -> list[str]:
    if snippets is None:
        snippets = (INSTRUCTIONS_DIR).glob("*/claude_md.md")
    elif isinstance(snippets, Path):
        snippets = snippets.glob("*/claude_md.md") if snippets.is_dir() else [snippets]
    keys_by_name: dict[str, set[str]] = {}
    for key in known:
        keys_by_name.setdefault(key.split("/", 1)[1], set()).add(key)
    findings: list[str] = []
    for snippet in sorted(snippets):
        manifest = snippet.parent / "claude-all.json"
        declared: set[str] = set()
        if manifest.exists():
            try:
                declared = set(json.loads(manifest.read_text(encoding="utf-8")).get("requires", []))
            except (json.JSONDecodeError, OSError, TypeError):
                declared = set()
        own = f"instructions/{snippet.parent.name}"
        rel = snippet.relative_to(INSTRUCTIONS_DIR.parent)
        for token in sorted(set(CODE_SPAN.findall(snippet.read_text(encoding="utf-8")))):
            candidates = keys_by_name.get(token, set()) - {own}
            if candidates and not candidates & declared:
                findings.append(
                    f"{rel}: names `{token}` but its claude-all.json does not require "
                    + " or ".join(sorted(candidates))
                )
    return findings


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any."""
    known = load_resource_keys()

    # Discover files for the requires check
    manifest_pattern1 = (SRC / "claude_all").rglob("claude-all.json")
    manifest_pattern2 = (SRC / "claude_all").rglob("*.claude-all.json")
    manifest_files = set(manifest_pattern1) | set(manifest_pattern2)

    # Discover files for the instruction-ref check
    instruction_files = set((INSTRUCTIONS_DIR).glob("*/claude_md.md"))

    # Check for zero-discovery
    errors = []
    if not manifest_files:
        errors.append(
            "requires check: no claude-all.json files found "
            "(patterns: '**/claude-all.json' and '**/*.claude-all.json')"
        )
    if not instruction_files:
        errors.append(
            "instruction-ref check: no instruction snippet files found (pattern: '*/claude_md.md')"
        )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    # Run the checks
    findings = find_violations(known, manifest_files) + find_undeclared_instruction_refs(
        known, instruction_files
    )
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} requires finding(s) — a dependency manifest points at a "
            "resource the installer cannot discover, or an instruction names one it "
            "does not require.",
            file=sys.stderr,
        )
        return 1

    # Success: print summary
    total_units = len(manifest_files) + len(instruction_files)
    print(f"Inspected {total_units} units")
    return 0


if __name__ == "__main__":
    sys.exit(main())
