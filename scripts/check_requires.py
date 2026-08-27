#!/usr/bin/env python3
"""Gate: every `claude-all.json` `requires` entry resolves to a real resource.

A per-resource dependency manifest (`claude-all.json`, key `requires`) is only
safe if its targets exist — a `requires` pointing at a renamed/deleted resource
would make the installer silently skip a dependency (treat it as "external") and
ship a broken closure. This is the drift guard: it fails when a `requires` entry
names no resource the installer can discover, and when a manifest is malformed.

It resolves targets by importing the installer's own `discover()` /`state_key`,
so "what counts as a resource" is defined in exactly one place (the installer),
never re-derived here.

Exit codes: 0 = everything resolves and was inspected · 1 = a dangling/malformed
entry, or the manifest scan matched zero files (a gate that examined nothing must
never pass).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


def load_resource_keys() -> set[str]:
    """Return every installable resource key (``kind/name``) via the installer.

    Returns:
        The set the installer's ``discover([])`` would yield, keyed exactly as a
        ``requires`` entry must be written.
    """
    sys.path.insert(0, str(SRC))
    from claude_all.cli import discover, state_key

    return {state_key(it.kind, it.name) for it in discover([])}


def find_violations(known: set[str], src_dir: Path | None = None) -> tuple[int, int, list[str]]:
    """Return one finding per dangling/malformed ``requires`` entry.

Discovery is by glob under the manifests root (``claude_all`` on the real
    repo, or ``src_dir`` when a test injects a synthetic tree). Fail-open
    protection: the caller must treat a zero-manifest result as a hard failure,
    never a pass.

    Args:
        known: Every resolvable resource key.
        src_dir: Directory to scan for manifests (defaults to the repo's
            ``src/claude_all``). Test hook.

    Returns:
        ``(manifest_count, requires_count, findings)`` — how many manifests were
        examined, how many ``requires`` entries were checked across them, and the
        stable ``path: message`` findings (empty when the graph is clean).
    """
    base = (src_dir or (SRC / "claude_all")).resolve()
    manifests = sorted(base.rglob("claude-all.json")) + sorted(base.rglob("*.claude-all.json"))
    findings: list[str] = []
    requires_count = 0
    for manifest in manifests:
        try:
            rel = manifest.relative_to(REPO_ROOT)
        except ValueError:
            # A synthetic manifest from a test tree is outside the repo — show
            # its absolute-ish path so a finding still points somewhere real.
            rel = manifest
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
            requires_count += 1
            if not isinstance(dep, str):
                findings.append(f"{rel}: non-string dependency {dep!r}")
            elif dep not in known:
                findings.append(
                    f"{rel}: requires '{dep}' — no such resource (renamed/deleted? "
                    "a built-in like /code-review does not belong in requires)"
                )
    return len(manifests), requires_count, findings


def main() -> int:
    """CLI entry point — print findings to stdout, exit 1 on any."""
    manifest_count, requires_count, findings = find_violations(load_resource_keys())

    # Hard fail on zero discovery: a pattern that silently matches nothing is a
    # broken gate that would otherwise report green without examining a thing.
    if manifest_count == 0:
        print(
            "no manifests matched 'claude-all.json' or '*.claude-all.json' under "
            f"{(SRC / 'claude_all')} — the dependency scan matched zero files; "
            "nothing was inspected, refusing to pass green",
            file=sys.stderr,
        )
        return 1

    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} dangling/invalid requires entry(ies) — a dependency "
            "manifest points at a resource the installer cannot discover.",
            file=sys.stderr,
        )
        return 1

    print(
        f"inspected: {manifest_count} manifest(s), "
        f"{requires_count} requires entr(ies) checked — OK"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
