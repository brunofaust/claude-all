#!/usr/bin/env python3
"""Checker: an `INSERT INTO t VALUES (...)` with no column list is an error.

A positional insert silently misplaces values once the physical column order drifts
from the order the code assumes, and breaks on any column-count change. Scans string
and f-string literals in Python files; docstrings are skipped.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

__all__ = ["check_file", "collect_files", "docstring_ids", "flatten", "main"]

EXPR_PLACEHOLDER = "\x01"
MAX_SKIP_TOKENS = 4
# Skip up to MAX_SKIP_TOKENS unresolved tokens (e.g. an f-string `{cols}` slot) after the
# table, bounded so the match never walks into a later statement's VALUES.
INSERT_INTO_RE = re.compile(
    r"INSERT\s+INTO\s+(?P<table>[^\s(]+)"
    r"(?:\s+(?!SELECT\b|DEFAULT\s+VALUES\b|VALUES\b)[^\s(]+)"
    rf"{{0,{MAX_SKIP_TOKENS}}}"
    r"\s*(?P<next>\(|SELECT\b|DEFAULT\s+VALUES\b|VALUES\b)?",
    re.IGNORECASE,
)
SKIP_DIRS = frozenset({".venv", "venv", "__pycache__", "node_modules", ".git"})


def flatten(node: ast.Constant | ast.JoinedStr) -> str:
    """Render a string or f-string node as text, interpolations as one placeholder."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    return "".join(
        part.value
        if isinstance(part, ast.Constant) and isinstance(part.value, str)
        else EXPR_PLACEHOLDER
        for part in node.values
    )


def docstring_ids(tree: ast.AST) -> set[int]:
    """Return ids of bare-expression strings in tree and of f-string parts."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            ids.add(id(node.value))
        elif isinstance(node, ast.JoinedStr):
            ids.update(id(part) for part in node.values)
    return ids


def check_file(path: Path) -> list[str]:
    """Return one finding per column-less INSERT in path."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = docstring_ids(tree)
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant | ast.JoinedStr) or id(node) in skip:
            continue
        text = flatten(node)
        for match in INSERT_INTO_RE.finditer(text):
            if (match.group("next") or "").upper().startswith("VALUES"):
                line = node.lineno + text.count("\n", 0, match.start())
                findings.append(
                    f"{path.as_posix()}:{line}: column-less insert into "
                    f"`{match.group('table')}` — name the target columns, e.g. "
                    "`(col1, col2) VALUES (...)`"
                )
    return findings


def collect_files(roots: list[Path]) -> list[Path]:
    """Return every .py file under roots; raise FileNotFoundError on a missing root."""
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            files.add(root)
        elif root.is_dir():
            files.update(p for p in root.rglob("*.py") if not SKIP_DIRS.intersection(p.parts))
        else:
            raise FileNotFoundError(f"no such file or directory: {root}")
    return sorted(p for p in files if p.suffix == ".py")


def main(argv: list[str] | None = None) -> int:
    """Scan argv roots (files or dirs) for column-less INSERT statements."""
    parser = argparse.ArgumentParser(description="Require a column list on INSERT INTO.")
    parser.add_argument("roots", nargs="+", type=Path, help="Python files or dirs")
    parser.add_argument("--exit-zero", action="store_true", help="report but exit 0")
    args = parser.parse_args(argv)
    try:
        files = collect_files(args.roots)
        findings = [line for path in files for line in check_file(path)]
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        print(f"insert-column-list: cannot check — {exc}", file=sys.stderr)
        return 2
    print(f"scanned={len(files)}", file=sys.stderr)
    if not files:
        print("insert-column-list: no .py files found — checked nothing", file=sys.stderr)
        return 2
    for line in findings:
        print(line)
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
