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
from pathlib import Path

print("DEBUG: top of script", file=sys.stderr, flush=True)

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
INSTRUCTIONS_DIR = SRC / "claude_all" / "instructions"
CODE_SPAN = re.compile(r"`([^`\s]+)`")

print("DEBUG: after global definitions", file=sys.stderr, flush=True)


def load_resource_keys() -> set[str]:
    """Return every installable resource key (``kind/name``) via the installer."""
    print("DEBUG: in load_resource_keys", file=sys.stdout, flush=True)
    sys.path.insert(0, str(SRC))
    print("DEBUG: after sys.path insert", file=sys.stdout, flush=True)
    from claude_all.cli import discover, state_key

    print("DEBUG: import succeeded", file=sys.stdout, flush=True)
    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: set[str]) -> tuple[list[str], int]:
    """Return (findings, count) where count is the number of dependencies inspected."""
    findings: list[str] = []
    count = 0
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    ):
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
            count += 1
            if not isinstance(dep, str):
                findings.append(f"{rel}: non-string dependency {dep!r}")
            elif dep not in known:
                findings.append(
                    f"{rel}: requires '{dep}' — no such resource (renamed/deleted? "
                    "a built-in like /code-review does not belong in requires)"
                )
    return findings, count


def find_undeclared_instruction_refs(
    known: set[str], instructions_dir: Path = INSTRUCTIONS_DIR
) -> tuple[list[str], int]:
    """Return (findings, count) where count is the number of instruction tokens inspected."""
    keys_by_name: dict[str, set[str]] = {}
    for key in known:
        keys_by_name.setdefault(key.split("/", 1)[1], set()).add(key)
    findings: list[str] = []
    count = 0
    for snippet in sorted(instructions_dir.glob("*/claude_md.md")):
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
            if candidates:
                count += 1
                if not candidates & declared:
                    findings.append(
                        f"{rel}: names `{token}` but its claude-all.json does not require "
                        + " or ".join(sorted(candidates))
                    )
    return findings, count


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any."""
    # Debug: print sys.path and check for claude_all
    print(f"DEBUG: sys.path = {sys.path}", file=sys.stderr)
    print(f"DEBUG: REPO_ROOT = {REPO_ROOT}", file=sys.stderr)
    print(f"DEBUG: SRC = {SRC}", file=sys.stderr)
    print(f"DEBUG: SRC exists = {SRC.exists()}", file=sys.stderr)
    claude_all_dir = SRC / "claude_all"
    print(f"DEBUG: claude_all_dir = {claude_all_dir}", file=sys.stderr)
    print(f"DEBUG: claude_all_dir exists = {claude_all_dir.exists()}", file=sys.stderr)
    if claude_all_dir.exists():
        print(f"DEBUG: claude_all_dir contents = {list(claude_all_dir.iterdir())}", file=sys.stderr)
    known = load_resource_keys()
    violation_findings, violation_count = find_violations(known)
    instruction_findings, instruction_count = find_undeclared_instruction_refs(known)
    findings = violation_findings + instruction_findings
    total_count = violation_count + instruction_count

    if total_count == 0:
        print(
            "Error: dependency scan matched zero files — no resources discovered.",
            file=sys.stderr,
        )
        return 1

    if findings:
        for finding in findings:
            print(finding)
        print(
            f"\n{len(findings)} requires finding(s) — a dependency manifest points at a "
            "resource the installer cannot discover, or an instruction names one it "
            "does not require.",
            file=sys.stderr,
        )
        return 1

    print(f"Inspected {total_count} units")
    return 0


if __name__ == "__main__":
    sys.exit(main())
