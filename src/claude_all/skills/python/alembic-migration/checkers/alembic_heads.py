#!/usr/bin/env python3
"""Checker: enforce a single Alembic head and a bounded revision-id length.

WHY
---
Two migration-graph failure classes this check catches, both real and both
silent until someone runs `alembic upgrade head`:

- **Multiple heads.** Two migrations independently pick the same
  `down_revision` (typically two parallel PRs each branching off the same tip).
  `main` ends up with two heads, and `alembic upgrade head` errors until
  someone manually repoints one migration's `down_revision` onto the other.
  This check finds the fork before it merges, not after.
- **Oversized revision id.** Alembic's own `alembic_version.version_num`
  column is `VARCHAR(32)` by default. A generated or hand-picked revision id
  longer than that overflows on a FRESH database — existing databases with an
  already-written row never notice, so this bites exactly the deploy that
  can't afford it (e.g. a new environment, a disaster-recovery restore).

Pure AST parse of `alembic/versions/*.py` — no alembic import, no database
connection, fast enough to run on every commit.

CONTRACT
--------
Prints one violation per line to stderr; exits 0 clean, 1 on any violation —
wire it as a prek/pre-commit `entry` (`language = "system"`) or run standalone.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

__all__ = ["check_versions", "main", "revision_links"]

MAX_REVISION_ID_LENGTH = 32  # alembic_version.version_num is VARCHAR(32) by default
DEFAULT_VERSIONS_DIR = Path("alembic/versions")


def literal_str_values(node: ast.expr) -> list[str]:
    """Return the string literals bound by a `revision`/`down_revision` assignment.

    Args:
        node: The AST expression assigned to `revision` or `down_revision`.

    Returns:
        String constants found — one for a plain string, several for the tuple
        form Alembic uses on a merge revision, empty for `None`/a dynamic value.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Tuple):
        return [
            el.value
            for el in node.elts
            if isinstance(el, ast.Constant) and isinstance(el.value, str)
        ]
    return []


def revision_links(path: Path) -> tuple[str | None, list[str]]:
    """Extract `(revision, down_revisions)` from one migration file.

    Args:
        path: A migration file under the versions directory.

    Returns:
        The file's revision id (`None` if unparsable) and the list of
        down-revision ids it points at.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None, []
    revision: str | None = None
    down: list[str] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        for target in targets:
            if not isinstance(target, ast.Name) or value is None:
                continue
            if target.id == "revision":
                values = literal_str_values(value)
                revision = values[0] if values else None
            elif target.id == "down_revision":
                down.extend(literal_str_values(value))
    return revision, down


def check_versions(versions_dir: Path) -> list[str]:
    """Return violation messages for the migration graph under `versions_dir`.

    Args:
        versions_dir: Directory containing Alembic migration files.

    Returns:
        Human-readable violations: oversized revision ids, duplicate revision
        ids, dangling `down_revision` references, or more than one head.
    """
    revisions: dict[str, Path] = {}
    referenced: set[str] = set()
    violations: list[str] = []
    for path in sorted(versions_dir.glob("*.py")):
        revision, down = revision_links(path)
        if revision is None:
            continue
        if len(revision) > MAX_REVISION_ID_LENGTH:
            violations.append(
                f"{path}: revision id '{revision}' is {len(revision)} chars — "
                f"alembic_version.version_num is VARCHAR({MAX_REVISION_ID_LENGTH})"
            )
        if revision in revisions:
            violations.append(
                f"{path}: duplicate revision id '{revision}' (also in {revisions[revision]})"
            )
        revisions[revision] = path
        referenced.update(down)
    dangling = referenced - revisions.keys()
    for ref in sorted(dangling):
        violations.append(f"down_revision '{ref}' does not match any revision in {versions_dir}")
    heads = sorted(revisions.keys() - referenced)
    if len(heads) > 1:
        files = ", ".join(f"{head} ({revisions[head].name})" for head in heads)
        violations.append(
            f"{len(heads)} alembic heads found — repoint the newest down_revision so the chain "
            f"is linear: {files}"
        )
    return violations


def main(argv: list[str] | None = None) -> int:
    """Entry point: validate the alembic migration graph.

    Args:
        argv: Command-line arguments, or `None` to read `sys.argv`.

    Returns:
        0 if the migration graph is clean, 1 if any violation was found.
    """
    parser = argparse.ArgumentParser(
        description="Enforce a single alembic head + revision-id length."
    )
    parser.add_argument(
        "versions_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_VERSIONS_DIR,
        help=f"directory containing migration files (default: {DEFAULT_VERSIONS_DIR})",
    )
    args = parser.parse_args(argv)

    if not args.versions_dir.is_dir():
        print(f"{args.versions_dir} not found — run from the repo root", file=sys.stderr)
        return 1
    violations = check_versions(args.versions_dir)
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
