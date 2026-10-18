#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource.

Also checks that resources named by an instruction snippet are in its `requires`.
Targets are resolved via the installer's own `discover()`, never re-derived here.
Exit 0 = all resolve, 1 = dangling/malformed entry, 2 = discovery matched nothing
(zero resource keys, zero manifests or zero instruction snippets — the gate cannot
check anything, so it refuses to pass). A success run prints one `scanned=N` line
on stderr with the number of manifests and instruction snippets inspected.
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


MANIFEST_GLOBS = ("claude-all.json", "*.claude-all.json")
SNIPPET_GLOB = "*/claude_md.md"


def manifest_paths() -> list[Path]:
    """Return every manifest under ``SRC/claude_all`` matched by ``MANIFEST_GLOBS``."""
    return [
        path for pattern in MANIFEST_GLOBS for path in sorted((SRC / "claude_all").rglob(pattern))
    ]


def snippet_paths(instructions_dir: Path) -> list[Path]:
    """Return every instruction snippet matched by ``SNIPPET_GLOB``."""
    return sorted(instructions_dir.glob(SNIPPET_GLOB))


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


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any, exit 2 on zero discovery."""
    known = load_resource_keys()
    if not known:
        print(
            "CANNOT CHECK: discover([]) returned no resource keys — nothing to resolve "
            "`requires` against. Fix discover() in src/claude_all/cli.py.",
            file=sys.stderr,
        )
        return 2
    manifests = manifest_paths()
    if not manifests:
        print(
            "CANNOT CHECK: no manifest matched "
            f"{' or '.join(MANIFEST_GLOBS)} under {(SRC / 'claude_all').as_posix()} — "
            "fix the globs or restore the manifests.",
            file=sys.stderr,
        )
        return 2
    snippets = snippet_paths(INSTRUCTIONS_DIR)
    if not snippets:
        print(
            f"CANNOT CHECK: no instruction snippet matched {SNIPPET_GLOB} under "
            f"{INSTRUCTIONS_DIR.as_posix()} — fix the glob or restore the snippets.",
            file=sys.stderr,
        )
        return 2
    print(
        f"scanned={len(manifests) + len(snippets)} requires unit(s) "
        f"(manifests={len(manifests)}, instruction snippets={len(snippets)})",
        file=sys.stderr,
    )
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
