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


def find_violations(known: set[str], manifest_files: Iterable[Path] | None = None) -> list[str]:
    findings: list[str] = []
    if manifest_files is None:
        seen = set()
        manifest_files = []
        for pattern in ("claude-all.json", "*.claude-all.json"):
            for manifest in (SRC / "claude_all").rglob(pattern):
                if manifest not in seen:
                    seen.add(manifest)
                    manifest_files.append(manifest)
        manifest_files.sort(key=lambda p: str(p))
    for manifest in manifest_files:
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
    known: set[str],
    instruction_files: Iterable[Path] | None = None,
    instructions_dir: Path = INSTRUCTIONS_DIR,
) -> list[str]:
    findings: list[str] = []
    if instruction_files is None:
        instruction_files = instructions_dir.glob("*/claude_md.md")
    keys_by_name: dict[str, set[str]] = {}
    for key in known:
        keys_by_name.setdefault(key.split("/", 1)[1], set()).add(key)
    for snippet in sorted(instruction_files, key=lambda p: str(p)):
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
    """CLI entry point — print findings to stdout, exit 1 on any."""
    # Discover manifest files and instruction snippet files
    manifest_base = SRC / "claude_all"
    manifest_files: set[Path] = set()
    for pattern in ("claude-all.json", "*.claude-all.json"):
        manifest_files.update(manifest_base.rglob(pattern))

    instruction_base = INSTRUCTIONS_DIR
    instruction_files: set[Path] = set()
    instruction_files.update(instruction_base.glob("*/claude_md.md"))

    total_inspected = len(manifest_files) + len(instruction_files)
    if total_inspected == 0:
        patterns_str = [
            str(manifest_base / "**" / "claude-all.json"),
            str(manifest_base / "**" / "*.claude-all.json"),
            str(instruction_base / "*/claude_md.md"),
        ]
        print(
            f"ERROR: No files matched the patterns: {', '.join(map(repr, patterns_str))}",
            file=sys.stderr,
        )
        return 1

    known = load_resource_keys()
    findings = find_violations(known, manifest_files) + find_undeclared_instruction_refs(
        known, instruction_files, INSTRUCTIONS_DIR
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
    print(f"Inspected {total_inspected} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
