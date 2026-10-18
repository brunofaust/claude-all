#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource.

Also checks that instruction snippets name only resources in their `requires`.
Targets come from the installer's own `discover()`. Exit 0 = all resolve, 1 = findings,
2 = discovery matched nothing (nothing checked). On success one summary line goes to
stderr: `check_requires: inspected N unit(s) (M manifest(s), K instruction snippet(s))`.
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


def discover_manifests() -> list[Path]:
    """Return every dependency manifest under ``src/claude_all``, across all patterns."""
    return [
        manifest
        for pattern in MANIFEST_PATTERNS
        for manifest in sorted((SRC / "claude_all").rglob(pattern))
    ]


def find_violations(known: set[str]) -> list[str]:
    findings: list[str] = []
    for manifest in discover_manifests():
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


def discover_instruction_snippets(instructions_dir: Path) -> list[Path]:
    """Return every instruction snippet (``*/claude_md.md``) under ``instructions_dir``."""
    return sorted(instructions_dir.glob("*/claude_md.md"))


def find_undeclared_instruction_refs(
    known: set[str], instructions_dir: Path = INSTRUCTIONS_DIR
) -> list[str]:
    keys_by_name: dict[str, set[str]] = {}
    for key in known:
        keys_by_name.setdefault(key.split("/", 1)[1], set()).add(key)
    findings: list[str] = []
    for snippet in discover_instruction_snippets(instructions_dir):
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
    """CLI entry point — findings to stdout (exit 1), zero discovery exits 2."""
    known = load_resource_keys()
    manifests = discover_manifests()
    snippets = discover_instruction_snippets(INSTRUCTIONS_DIR)

    unmatched: list[str] = []
    if not known:
        unmatched.append("discover([]) returned no installable resources")
    if not manifests:
        unmatched.extend(
            f"no manifests matched {pattern} under src/claude_all" for pattern in MANIFEST_PATTERNS
        )
    if not snippets:
        unmatched.append(
            "no instruction snippets matched */claude_md.md under src/claude_all/instructions"
        )
    if unmatched:
        for reason in unmatched:
            print(f"CANNOT CHECK: {reason}", file=sys.stderr)
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
    print(
        f"check_requires: inspected {len(manifests) + len(snippets)} unit(s) "
        f"({len(manifests)} manifest(s), {len(snippets)} instruction snippet(s))",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
