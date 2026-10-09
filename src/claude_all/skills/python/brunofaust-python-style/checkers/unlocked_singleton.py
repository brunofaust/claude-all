#!/usr/bin/env python3
"""Checker: a lazy module-global singleton must be built under a lock.

`global X; if X is None: X = build()` with no lock lets every concurrent first caller
pass the check and build its own X; the losers are orphaned with whatever they hold
(16 racing threads built 16 pools). Build it inside a lock-named `with` block and
re-check the global under that lock. Rules: references/enforcement.md.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from typing import NamedTuple

from py_files import iter_py_files

__all__ = [
    "DEFAULT_LOCK_HINTS",
    "Finding",
    "findings_in_function",
    "is_none_comparison",
    "iter_py_files",
    "main",
]

#: Matched by NAME in the `with` expression: `self._lock` cannot be typed statically.
DEFAULT_LOCK_HINTS: tuple[str, ...] = ("lock", "mutex", "semaphore", "guard")

type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class Finding(NamedTuple):
    """One unlocked lazy-singleton assignment."""

    path: str
    line: int
    function: str
    name: str

    def render(self) -> str:
        """Return the `path:line: message` output line."""
        return (
            f"{self.path}:{self.line}: {self.function}() assigns module global '{self.name}' "
            "behind an unsynchronised emptiness check — concurrent callers each build one "
            "and the losers leak their resources. Build it inside a lock and re-check."
        )


def locked_ids(function: FunctionNode, hints: tuple[str, ...]) -> set[int]:
    """Return ids of nodes in function inside a `with` whose expression matches hints."""
    locked: set[int] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.With | ast.AsyncWith) and any(
            hint in ast.unparse(item.context_expr).lower() for item in node.items for hint in hints
        ):
            locked.update(id(sub) for sub in ast.walk(node))
    return locked


def is_none_comparison(node: ast.AST) -> bool:
    """Return whether node is an `is` / `is not` comparison against None."""
    return isinstance(node, ast.Compare) and any(
        isinstance(op, ast.Is | ast.IsNot)
        and isinstance(other, ast.Constant)
        and other.value is None
        for op, other in zip(node.ops, node.comparators, strict=True)
    )


def emptiness_tested_names(test: ast.expr) -> set[str]:
    """Return the names the if-test checks for being unset."""
    tested: set[str] = set()
    for node in ast.walk(test):
        if isinstance(node, ast.Compare) and is_none_comparison(node):
            tested |= {n.id for n in ast.walk(node.left) if isinstance(n, ast.Name)}
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            tested |= {n.id for n in ast.walk(node.operand) if isinstance(n, ast.Name)}
    return tested


def findings_in_function(
    path: str, function: FunctionNode, hints: tuple[str, ...]
) -> Iterator[Finding]:
    """Yield each unlocked check-then-set of a global in function at path, given lock hints."""
    declared = {
        n for node in ast.walk(function) if isinstance(node, ast.Global) for n in node.names
    }
    if not declared:
        return
    locked = locked_ids(function, hints)
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        candidates = emptiness_tested_names(node.test) & declared
        for stmt in ast.walk(node) if candidates else ():
            if not isinstance(stmt, ast.Assign) or id(stmt) in locked:
                continue
            targets = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
            for assigned in sorted(targets & candidates):
                yield Finding(path, stmt.lineno, function.name, assigned)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flag lazy module-global singletons built unlocked."
    )
    parser.add_argument("paths", nargs="*", help="files or directories to scan")
    parser.add_argument(
        "--lock-hint",
        action="append",
        default=[],
        help="extra lowercase substring marking a `with` expression as a lock (repeatable)",
    )
    parser.add_argument("--exit-zero", action="store_true", help="print findings, exit 0")
    args = parser.parse_args(argv)

    files = list(iter_py_files(args.paths))
    if not files:
        print("unlocked_singleton: zero *.py files to scan — misconfigured paths", file=sys.stderr)
        return 2
    hints = DEFAULT_LOCK_HINTS + tuple(h.lower() for h in args.lock_hint)
    findings: set[Finding] = set()
    try:
        for file in files:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=file.as_posix())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    findings.update(findings_in_function(file.as_posix(), node, hints))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        print(f"unlocked_singleton: cannot scan: {exc}", file=sys.stderr)
        return 2
    for finding in sorted(findings):
        print(finding.render())
    print(f"scanned={len(files)}", file=sys.stderr)
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
