#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource.

Also checks that resources named by an instruction snippet are in its `requires`.
Targets are resolved via the installer's own `discover()`, never re-derived here.
Exit 0 = all resolve, 1 = dangling/malformed entry, 2 = discovery matched zero
files at one of its discovery points (nothing was examined, so nothing is passed).
On success one summary line (`requires-check: inspected ...`) is printed to stdout.
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


MANIFEST_PATTERNS = ("claude-all.json", "*.claude-all.json")
SNIPPET_PATTERN = "*/claude_md.md"


def manifest_paths() -> list[Path]:
    """Return every requires-manifest under ``src/claude_all`` (sorted per pattern)."""
    paths: list[Path] = []
    for pattern in MANIFEST_PATTERNS:
        paths.extend(sorted((SRC / "claude_all").rglob(pattern)))
    return paths


def snippet_paths(instructions_dir: Path) -> list[Path]:
    """Return every instruction snippet directly under ``instructions_dir``."""
    return sorted(instructions_dir.glob(SNIPPET_PATTERN))


def find_violations(known: set[str]) -> list[str]:
    findings: list[str] = []
    for manifest in manifest_paths():
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
    for snippet in snippet_paths(instructions_dir):
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


def count_requires(manifests: list[Path]) -> int:
    """Count the ``requires`` entries across manifests that parse to a list."""
    total = 0
    for manifest in manifests:
        try:
            requires = json.loads(manifest.read_text(encoding="utf-8")).get("requires", [])
        except (json.JSONDecodeError, OSError, AttributeError):
            continue
        if isinstance(requires, list):
            total += len(requires)
    return total


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any.

    Exits 2 (nothing examined) when a discovery point matches zero files.
    """
    manifests = manifest_paths()
    snippets = snippet_paths(INSTRUCTIONS_DIR)
    empty = []
    if not manifests:
        patterns = " / ".join(MANIFEST_PATTERNS)
        empty.append(f"CANNOT CHECK: pattern {patterns} under src/claude_all matched no files")
    if not snippets:
        empty.append(
            f"CANNOT CHECK: pattern {SNIPPET_PATTERN} under instructions/ matched no files"
        )
    known = load_resource_keys()
    if not known:
        empty.append("CANNOT CHECK: installer discover([]) matched no resources")
    if empty:
        for message in empty:
            print(f"{message} — fix the discovery paths", file=sys.stderr)
        return 2

    findings = find_violations(known) + find_undeclared_instruction_refs(known, INSTRUCTIONS_DIR)
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
    requires = count_requires(manifests)
    inspected = len(manifests) + len(snippets) + requires
    print(
        f"requires-check: inspected {inspected} unit(s) — "
        f"manifests={len(manifests)} snippets={len(snippets)} requires={requires} "
        f"resources={len(known)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
