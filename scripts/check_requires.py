#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource.

Also checks that resources named by an instruction snippet are in its `requires`.
Targets are resolved via the installer's own `discover()`, never re-derived here.
Exit 0 = all resolve, 1 = dangling/malformed entry, 2 = zero input.
"""

from __future__ import annotations

import json
import re
import sys
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


def find_violations(known: set[str]) -> tuple[list[str], int]:
    findings: list[str] = []
    manifest_count = 0
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    ):
        manifest_count += 1
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
    return findings, manifest_count


def find_undeclared_instruction_refs(
    known: set[str], instructions_dir: Path | None = None
) -> tuple[list[str], int]:
    if instructions_dir is None:
        instructions_dir = INSTRUCTIONS_DIR
    keys_by_name: dict[str, set[str]] = {}
    for key in known:
        keys_by_name.setdefault(key.split("/", 1)[1], set()).add(key)
    findings: list[str] = []
    snippet_count = 0
    for snippet in sorted(instructions_dir.glob("*/claude_md.md")):
        snippet_count += 1
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
    return findings, snippet_count


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any, 2 on zero input."""
    known = load_resource_keys()
    violations, manifest_count = find_violations(known)
    undeclared, snippet_count = find_undeclared_instruction_refs(known)
    findings = violations + undeclared
    total_units = manifest_count + snippet_count

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

    if total_units == 0:
        print(
            "No files discovered for inspection. Manifest patterns "
            "'**/claude-all.json' and '**/*.claude-all.json' under src/claude_all "
            "matched 0 files, and instruction snippet pattern '*/claude_md.md' "
            "under src/claude_all/instructions matched 0 files.",
            file=sys.stderr,
        )
        return 2

    # Calculate summary counts: manifests not under instructions, and snippets.
    manifest_count_summary = 0
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    ):
        try:
            # Skip manifests under instructions directory
            if str(manifest).startswith(str(INSTRUCTIONS_DIR) + "/"):
                continue
        except ValueError:
            # Manifest is not under INSTRUCTIONS_DIR (e.g., if INSTRUCTIONS_DIR is not a parent)
            pass
        manifest_count_summary += 1

    print(
        f"Inspected {manifest_count_summary} manifest file(s) and "
        f"{snippet_count} instruction snippet(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
