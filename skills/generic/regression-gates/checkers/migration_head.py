#!/usr/bin/env python3
"""Checker: single migration head + revision-id sanity for linked-revision frameworks.

WHY
---
Frameworks like Alembic link migrations by ``revision`` / ``down_revision``. When
two branches each add a migration, the chain forks into TWO heads; the next
``upgrade head`` is ambiguous and a fresh database may apply only one branch.
A single-head invariant catches this at commit time. It also flags over-length
revision ids (some backends truncate the ``alembic_version.version_num`` column —
classically 32 chars) and dangling ``down_revision`` pointers.

This is a PURE STATIC PARSE — it never imports the migration modules (importing
runs top-level code and may need the app/DB). It reads ``revision`` /
``down_revision`` assignments via ``ast``. Files it cannot parse are skipped
(fail-open) — a sibling migration-integrity gate owns those.

CONTRACT
--------
Prints one ``key: message`` finding per problem to stdout; exits 0 on success so
it composes with ``baseline_gate.py``.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

__all__ = ["Revision", "analyse", "main", "parse_file"]

MAX_REVISION_LEN = 32  # alembic_version.version_num default width


class Revision:
    """One migration's parsed revision metadata."""

    def __init__(self, path: Path, revision: str | None, down: tuple[str | None, ...]) -> None:
        self.path = path
        self.revision = revision
        self.down = down


def literal(node: ast.expr) -> tuple[str | None, ...]:
    """Flatten a down_revision RHS (str | None | tuple/list of those) to a tuple."""
    if isinstance(node, ast.Constant):
        return (node.value if isinstance(node.value, str) else None,)
    if isinstance(node, ast.Tuple | ast.List):
        out: list[str | None] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant):
                out.append(elt.value if isinstance(elt.value, str) else None)
        return tuple(out)
    return (None,)


def parse_file(path: Path) -> Revision | None:
    """Extract ``revision`` / ``down_revision`` from a migration file (no import)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return None  # fail open
    revision: str | None = None
    down: tuple[str | None, ...] = ()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Name):
                continue
            if tgt.id == "revision" and isinstance(node.value, ast.Constant):
                revision = node.value.value if isinstance(node.value.value, str) else None
            elif tgt.id == "down_revision":
                down = literal(node.value)
    if revision is None and not down:
        return None  # not a migration file
    return Revision(path, revision, down)


def analyse(revisions: list[Revision]) -> list[str]:
    """Return findings: multiple heads, dangling down-revisions, over-length ids."""
    findings: list[str] = []
    ids = {r.revision for r in revisions if r.revision}
    referenced: set[str] = set()
    for rev in revisions:
        if rev.revision and len(rev.revision) > MAX_REVISION_LEN:
            findings.append(
                f"{rev.path.name}: revision id {rev.revision!r} exceeds {MAX_REVISION_LEN} chars "
                "(may be truncated by alembic_version.version_num)"
            )
        for parent in rev.down:
            if parent is None:
                continue
            referenced.add(parent)
            if parent not in ids:
                findings.append(
                    f"{rev.path.name}: down_revision {parent!r} has no matching revision "
                    "(dangling — base migration missing or id typo)"
                )
    heads = sorted(ids - referenced)
    if len(heads) > 1:
        findings.append(
            f"migrations: {len(heads)} heads {heads} — expected 1 "
            "(branches diverged; create a merge migration)"
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Single-migration-head + revision-id checker.")
    parser.add_argument("roots", nargs="+", type=Path, help="migration dirs (or files) to scan")
    args = parser.parse_args(argv)
    files: list[Path] = []
    for root in args.roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(p for p in root.rglob("*.py") if not p.name.startswith("__"))
    revisions = [rev for rev in (parse_file(f) for f in files) if rev is not None]
    for finding in analyse(revisions):
        print(finding)
    return 0


if __name__ == "__main__":
    sys.exit(main())
