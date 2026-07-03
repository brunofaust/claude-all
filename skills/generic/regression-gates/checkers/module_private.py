#!/usr/bin/env python3
"""Checker: ban module-level private names (`_foo` defined at module scope) in Python.

WHY
---
A leading-underscore name at module scope reads as "private", so dead-code
detectors (vulture) and "unused export" tooling skip it — a `_helper` that
nothing calls is invisible to them and rots forever. Worse, the underscore is a
*convention*, not an export mechanism: other modules can still import `_helper`.
Use the language's real export control instead — keep module-level names public
and list the public surface in ``__all__`` (which IS the export contract). Make
truly-local helpers nested functions, or move them behind a class.

Dunders (``__all__``, ``__version__``, …) are allowed — they are the export
mechanism, not private leakage.

CONTRACT
--------
Prints one ``path: message`` finding per offending top-level def/class/assign to
stdout — keyed by the kind + name, NOT by line number, so it composes with
``baseline_gate.py``'s stable-key contract. Exits 0 on success.

PARSER NOTE
-----------
Uses the running interpreter's ``ast``. New syntax only parses on a new enough
interpreter (e.g. PEP 758 ``except A, B:`` needs 3.14+); on older interpreters
such a file fails to parse and is skipped (fail-open) rather than crashing the
gate — pin the hook interpreter if you need those files checked.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

__all__ = ["find_violations", "main"]


def is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def top_level_names(node: ast.stmt) -> list[tuple[str, str]]:
    """Yield ``(name, kind)`` for a module-level definition/assignment node."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return [(node.name, "function")]
    if isinstance(node, ast.ClassDef):
        return [(node.name, "class")]
    out: list[tuple[str, str]] = []
    if isinstance(node, ast.Assign):
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                out.append((tgt.id, "name"))
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        out.append((node.target.id, "name"))
    return out


def find_violations(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return []  # fail open — a sibling syntax gate owns unparsable files
    findings: list[str] = []
    for node in tree.body:  # module scope only
        for name, kind in top_level_names(node):
            if is_private(name):
                findings.append(
                    f"{path}: module-level private {kind} {name!r} — keep it public "
                    "and list the surface in __all__, or nest it / move it behind a class"
                )
    return findings


def iter_py_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(root.rglob("*.py"))
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ban module-level private names in Python.")
    parser.add_argument("roots", nargs="+", type=Path, help="files or dirs to scan")
    args = parser.parse_args(argv)
    for file in iter_py_files(args.roots):
        for finding in find_violations(file):
            print(finding)
    return 0


if __name__ == "__main__":
    sys.exit(main())
