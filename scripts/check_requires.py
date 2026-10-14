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

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
INSTRUCTIONS_DIR = SRC / "claude_all" / "instructions"
CODE_SPAN = re.compile(r"`([^`\s]+)`")


def load_resource_keys() -> set[str]:
    """Return every installable resource key (``kind/name``) via the installer."""
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key

    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: set[str]) -> list[str]:
    findings: list[str] = []
    for manifest in sorted((SRC / "claude_all").rglob("claude-all.json")) + sorted(
        (SRC / "claude_all").rglob("*.claude-all.json")
    ):
        rel = manifest.relative_to(SRC)
        display_path = f"src/{rel}"
        try:
            config = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(f"{display_path}: not valid JSON — {exc}")
            continue
        requires = config.get("requires", [])
        if not isinstance(requires, list):
            findings.append(f"{display_path}: `requires` must be a list of 'kind/name' strings")
            continue
        for dep in requires:
            if not isinstance(dep, str):
                findings.append(f"{display_path}: non-string dependency {dep!r}")
            elif dep not in known:
                findings.append(
                    f"{display_path}: requires '{dep}' — no such resource (renamed/deleted? "
                    "a built-in like /code-review does not belong in requires)"
                )
    return findings


def find_undeclared_instruction_refs(
    known: set[str], instructions_dir: Path = INSTRUCTIONS_DIR
) -> list[str]:
    keys_by_name: dict[str, set[str]] = {}
    for key in known:
        keys_by_name.setdefault(key.split("/", 1)[1], set()).add(key)
    findings: list[str] = []
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
            if candidates and not candidates & declared:
                findings.append(
                    f"{rel}: names `{token}` but its claude-all.json does not require "
                    + " or ".join(sorted(candidates))
                )
    return findings


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any."""
    known = load_resource_keys()
    manifest_files = list(
        sorted((SRC / "claude_all").rglob("claude-all.json"))
        + sorted((SRC / "claude_all").rglob("*.claude-all.json"))
    )
    snippet_files = sorted(INSTRUCTIONS_DIR.glob("*/claude_md.md"))
    total_inspected = len(manifest_files) + len(snippet_files)
    if total_inspected == 0:
        patterns = [
            "src/claude_all/**/claude-all.json",
            "src/claude_all/**/*.claude-all.json",
            "src/claude_all/instructions/*/claude_md.md",
        ]
        print(
            f"No files discovered for inspection via patterns: {', '.join(patterns)}",
            file=sys.stderr,
        )
        return 2
    findings = find_violations(known) + find_undeclared_instruction_refs(known)
    # Print inspection count to stderr, consistent with other checkers
    print(
        f"inspected={len(manifest_files)} manifests, {len(snippet_files)} snippets",
        file=sys.stderr,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
