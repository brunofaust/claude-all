#!/usr/bin/env python3
"""Checker: a mock standing in for an ``async def`` must be async-aware. WHY --- A plain
``MagicMock``/``Mock`` is never awaited and never fails, so a test that patches an ``async
def`` with one *passes whether or not the code under test actually awaits it* — it validates
nothing about the seam it exists to protect.
"""

import argparse
import ast
import sys
from pathlib import Path

from mock_drift_common import (
    build_module_index,
    collect_patch_call_findings,
    find_def,
    is_truthy,
    keyword,
    make_patch_finding_checker,
    new_positional_arg,
    parse_trees,
    report_unparsable,
    trailing_name,
)

__all__ = ["Finding", "build_module_index", "find_violations", "main", "resolve_target"]

#: The `mock` factory names that are NOT awaitable — using one for an async target
#: is the bug. `AsyncMock` is the correct double and is deliberately absent here.
SYNC_MOCK_NAMES = frozenset(
    {"MagicMock", "Mock", "NonCallableMock", "NonCallableMagicMock", "PropertyMock"}
)

#: The one async-aware double name that suppresses the finding when passed as
#: `new=` / `new_callable=`.
ASYNC_MOCK_NAME = "AsyncMock"


class Finding(str):
    """A finding line."""

    __slots__ = ()


def call_supplies_async_double(call: ast.Call, *, new_positional: ast.expr | None) -> bool | None:
    if is_truthy(keyword(call, "autospec")):
        return True

    new_callable = keyword(call, "new_callable")
    new = keyword(call, "new") or new_positional

    for value in (new_callable, new):
        if value is not None and trailing_name(value) == ASYNC_MOCK_NAME:
            return True
    for value in (new_callable, new):
        if value is not None and trailing_name(value) in SYNC_MOCK_NAMES:
            return False

    if new_callable is None and new is None:
        return False  # patch's default double is a MagicMock — not awaitable
    return None  # a custom, unclassifiable factory: do not flag


def lookup_in_module(module: ast.Module, remainder: list[str]) -> bool | None:
    if len(remainder) == 1:
        node = find_def(module.body, remainder[0])
        if isinstance(node, ast.AsyncFunctionDef):
            return True
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            return False
        return None
    if len(remainder) == 2:
        cls = find_def(module.body, remainder[0])
        if not isinstance(cls, ast.ClassDef):
            return None
        method = find_def(cls.body, remainder[1])
        if isinstance(method, ast.AsyncFunctionDef):
            return True
        if isinstance(method, ast.FunctionDef):
            return False
    return None


def resolve_target(dotted: str, index: dict[str, ast.Module]) -> bool | None:
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module = index.get(".".join(parts[:split]))
        if module is not None:
            return lookup_in_module(module, parts[split:])
    return None


def is_async_finding(target: str, index: dict[str, ast.Module], call: ast.Call) -> bool | None:
    if resolve_target(target, index) is not True:
        return None
    return call_supplies_async_double(call, new_positional=new_positional_arg(call)) is False


check_patch = make_patch_finding_checker(is_async_finding)


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    return [
        Finding(
            f"{path.as_posix()}:{lineno}: [async-mock] {target} — async def patched with a "
            "sync mock; use AsyncMock, autospec=True, or new_callable=AsyncMock"
        )
        for path, lineno, target in collect_patch_call_findings(trees, index, check_patch)
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Args: argv: Optional argument vector (defaults to ``sys.argv``)."""
    parser = argparse.ArgumentParser(
        description="Flag a MagicMock standing in for an async def in a patch() target.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="files or dirs — pass BOTH source and tests so dotted targets resolve",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="print findings but always exit 0 — ONLY for composing behind "
        "baseline_gate.py, whose contract reads a non-zero exit as 'the checker crashed'",
    )
    args = parser.parse_args(argv)

    trees, unparsable = parse_trees(args.roots)
    if unparsable:
        report_unparsable(unparsable)
        return 2

    index = build_module_index(trees)
    findings = find_violations(trees, index)
    for finding in findings:
        print(finding)

    if findings and not args.exit_zero:
        print(
            f"\n{len(findings)} finding(s) — a MagicMock on an async target is a green test "
            "over a broken await.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
