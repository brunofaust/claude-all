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


def get_resource_key_from_manifest(path: Path) -> str | None:
    """Extract resource key from a manifest file path, or return None if not possible."""
    try:
        # Try to get the relative path from SRC / "claude_all"
        rel = path.relative_to(SRC / "claude_all")
        # We expect the manifest to be named claude-all.json and be in a directory that is kind/name
        if rel.name == "claude-all.json" and len(rel.parts) == 3:
            # rel.parts[0] = kind, rel.parts[1] = name, rel.parts[2] = claude-all.json
            return f"{rel.parts[0]}/{rel.parts[1]}"
    except ValueError:
        # path is not relative to SRC/claude_all
        pass
    return None


def get_resource_key_from_snippet(path: Path) -> str | None:
    """Extract resource key from a snippet file path, or return None if not possible."""
    try:
        rel = path.relative_to(INSTRUCTIONS_DIR)
        # We expect the snippet to be in a directory named after the resource name,
        # and the file to be claude_md.md
        if rel.name == "claude_md.md" and len(rel.parts) == 2:
            # rel.parts[0] = name, rel.parts[1] = claude_md.md
            return f"instructions/{rel.parts[0]}"
    except ValueError:
        pass
    return None


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
    # Discover files to inspect
    manifest_files = list((SRC / "claude_all").rglob("claude-all.json")) + list(
        (SRC / "claude_all").rglob("*.claude-all.json")
    )
    snippet_files = list(INSTRUCTIONS_DIR.glob("*/claude_md.md"))

    keys_inspected = set()
    for manifest in manifest_files:
        key = get_resource_key_from_manifest(manifest)
        if key is not None:
            keys_inspected.add(key)
    for snippet in snippet_files:
        key = get_resource_key_from_snippet(snippet)
        if key is not None:
            keys_inspected.add(key)

    if not keys_inspected:
        print(
            "Error: no resources discovered for inspection. Checked for manifest files in "
            "'src/claude_all/**/claude-all.json' and 'src/claude_all/**/*.claude-all.json' "
            "and instruction snippets in 'src/claude_all/instructions/*/claude_md.md'.",
            file=sys.stderr,
        )
        return 1

    keys_inspected = set()
    for manifest in manifest_files:
        key = get_resource_key_from_manifest(manifest)
        if key is not None:
            keys_inspected.add(key)
    for snippet in snippet_files:
        key = get_resource_key_from_snippet(snippet)
        if key is not None:
            keys_inspected.add(key)

    findings = find_violations(known) + find_undeclared_instruction_refs(known)
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
    print(f"Inspected {len(keys_inspected)} units")
    return 0


if __name__ == "__main__":
    sys.exit(main())
