#!/usr/bin/env python3
"""Checker: single migration head + revision-id sanity for linked-revision frameworks. WHY ---
Frameworks like Alembic link migrations by ``revision`` / ``down_revision``. When two branches
each add a migration, the chain forks into TWO heads; the next ``upgrade head`` is ambiguous
and a fresh database may apply only one branch. A single-head invariant catches this at commit
time.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
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
    if isinstance(node, ast.Constant):
        return (node.value if isinstance(node.value, str) else None,)
    if isinstance(node, ast.Tuple | ast.List):
        out: list[str | None] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant):
                out.append(elt.value if isinstance(elt.value, str) else None)
        return tuple(out)
    return (None,)


def module_assignments(tree: ast.Module) -> Iterator[tuple[str, ast.expr]]:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    yield tgt.id, node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            yield node.target.id, node.value


def parse_file(path: Path) -> Revision | None:
    """Extract ``revision`` / ``down_revision`` from a migration file (no import).

    Args:
        path: Path to the migration file.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return None  # fail open
    revision: str | None = None
    down: tuple[str | None, ...] = ()
    for name, value in module_assignments(tree):
        if name == "revision" and isinstance(value, ast.Constant):
            revision = value.value if isinstance(value.value, str) else None
        elif name == "down_revision":
            down = literal(value)
    if revision is None and not down:
        return None  # not a migration file
    return Revision(path, revision, down)


def analyse(revisions: list[Revision], label: str = "migrations") -> list[str]:
    findings: list[str] = []
    ids = {r.revision for r in revisions if r.revision}
    referenced: set[str] = set()
    # Two migrations claiming the SAME revision id: the set above collapses them,
    # so head/dangling analysis silently treats them as one node. Track first-seen
    # owners separately to surface the collision.
    owner: dict[str, Path] = {}
    for rev in sorted(revisions, key=lambda r: r.path.name):
        if rev.revision:
            if rev.revision in owner:
                findings.append(
                    f"{rev.path.name}: duplicate revision id {rev.revision!r} "
                    f"(also defined in {owner[rev.revision].name})"
                )
            else:
                owner[rev.revision] = rev.path
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
            f"{label}: {len(heads)} heads {heads} — expected 1 "
            "(branches diverged; create a merge migration)"
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Single-migration-head + revision-id checker.")
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="migration trees to scan — each DIRECTORY is analysed as an INDEPENDENT "
        "graph (one dir per Alembic environment; never split one tree across dirs); "
        "loose FILE arguments are combined into ONE graph",
    )
    args = parser.parse_args(argv)
    # Each dir = one independent graph (merging environments fakes extra heads),
    # but loose file args belong to ONE tree — analysing each file alone would
    # report a guaranteed-false dangling down_revision per file and could never
    # see a multi-head divergence spread across the files.
    groups: list[tuple[str, list[Path]]] = []
    loose_files = [r for r in args.roots if r.is_file() and r.suffix == ".py"]
    if loose_files:
        groups.append((", ".join(str(f) for f in loose_files), loose_files))
    for root in args.roots:
        if root.is_dir():
            files = [p for p in root.rglob("*.py") if not p.name.startswith("__")]
            groups.append((str(root), files))
    parsed: list[tuple[str, list[Revision]]] = []
    for label, files in groups:
        revisions = [rev for rev in (parse_file(f) for f in files) if rev is not None]
        parsed.append((label, revisions))
    files = [rev.path for _, revisions in parsed for rev in revisions]
    print(f"scanned={len(files)}", file=sys.stderr)
    if not files:
        print("ERROR: scanned 0 files — refusing a vacuous pass", file=sys.stderr)
        return 2
    for label, revisions in parsed:
        for finding in analyse(revisions, label=label):
            print(finding)
    return 0


if __name__ == "__main__":
    sys.exit(main())
