#!/usr/bin/env python3
"""Checker: a test patch that does not revert on its own.

``patch(...).start()`` (inline or via a bound patcher) and ``mod.attr = MagicMock()`` on an
imported module leak into later tests when the matching ``stop()``/restore is skipped by an
exception. Only ``with patch(...)`` blocks and ``@patch`` decorators revert unconditionally.
Global fixture files (e.g. ``conftest.py``) can be exempted with ``--allow``.
"""

import argparse
import ast
import fnmatch
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from mock_drift_common import (
    import_map,
    is_patch_call,
    is_patch_object_call,
    iter_py_files,
    parse_trees,
    report_unparsable,
    resolve_call_target,
    trailing_name,
)

__all__ = [
    "MOCK_FAMILY_NAMES",
    "Finding",
    "dotted_name",
    "find_violations",
    "imported_roots",
    "is_allowed",
    "main",
    "patcher_bindings",
]

MOCK_FAMILY_NAMES = frozenset(
    {"MagicMock", "Mock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock"}
)
UNRESOLVED = "<unresolved patch target>"
MESSAGES = {
    "patch-start": "`.start()` on patch target `{detail}` — use `with patch(...):` or "
    "`@patch(...)`; both revert on exception, `.start()`/`.stop()` does not",
    "attr-assign": "direct Mock substitution of imported `{detail}` — use "
    "`with patch.object(...):` or `@patch.object(...)` so it reverts",
}


class Finding(NamedTuple):
    path: str
    line: int
    kind: str
    detail: str

    def render(self) -> str:
        message = MESSAGES[self.kind].format(detail=self.detail)
        return f"{self.path}:{self.line}: {self.kind}: {message}"


def dotted_name(node: ast.expr) -> str | None:
    """Render *node* as ``a.b.c`` when it is a plain Name/Attribute chain."""
    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(attrs)])


def as_patch(node: ast.expr | None) -> ast.Call | None:
    """Return *node* when it is a ``patch(...)`` / ``patch.object(...)`` call."""
    if isinstance(node, ast.Call) and (is_patch_call(node) or is_patch_object_call(node)):
        return node
    return None


def patcher_bindings(tree: ast.Module, imports: dict[str, str]) -> dict[str, str]:
    """Map names (incl. ``self.patcher``) bound to a patch in *tree*, via *imports*."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign) and (call := as_patch(node.value)):
            target = resolve_call_target(call, imports) or UNRESOLVED
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for name in filter(None, map(dotted_name, targets)):
                bound[name] = target
    return bound


def imported_roots(tree: ast.Module) -> frozenset[str]:
    """Every local name an ``import`` statement binds anywhere in *tree*."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return frozenset(names)


def start_target(call: ast.Call, imports: dict[str, str], bound: dict[str, str]) -> str | None:
    """Patch target that *call* starts, from inline *imports* or *bound* patchers."""
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "start"):
        return None
    if (inner := as_patch(func.value)) is not None:
        return resolve_call_target(inner, imports) or UNRESOLVED
    name = dotted_name(func.value)
    return bound.get(name) if name is not None else None


def mock_assignments(tree: ast.Module) -> Iterator[tuple[ast.expr, int]]:
    """Yield (target, line) for each ``x.y = <Mock-family>(...)`` in *tree*."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(node.value, ast.Call):
            if trailing_name(node.value.func) not in MOCK_FAMILY_NAMES:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute):
                    yield target, node.lineno


def find_violations(path: Path, tree: ast.Module) -> list[Finding]:
    """Return every unscoped-patch finding in the *tree* parsed from *path*."""
    imports = import_map(tree)
    bound = patcher_bindings(tree, imports)
    roots = imported_roots(tree)
    posix = path.as_posix()
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (target := start_target(node, imports, bound)):
            findings.append(Finding(posix, node.lineno, "patch-start", target))
    for target, line in mock_assignments(tree):
        name = dotted_name(target)
        if name is not None and name.split(".")[0] in roots:
            findings.append(Finding(posix, line, "attr-assign", name))
    return findings


def is_allowed(path: Path, patterns: list[str]) -> bool:
    """True when *path*'s name or posix path matches one of *patterns*."""
    return any(
        fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(path.as_posix(), pattern)
        for pattern in patterns
    )


def main(argv: list[str] | None = None) -> int:
    """Scan the test roots in *argv* and print unscoped patches."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path, help="test files or directories")
    parser.add_argument(
        "--allow", action="append", default=[], help="exempt file glob, e.g. conftest.py"
    )
    parser.add_argument("--exit-zero", action="store_true", help="report findings, exit 0")
    args = parser.parse_args(argv)

    files = [path for path in iter_py_files(args.roots) if not is_allowed(path, args.allow)]
    trees, unparsable = parse_trees(files)
    if unparsable:
        report_unparsable(unparsable)
        return 2
    print(f"scanned={len(trees)}", file=sys.stderr)
    if not trees:
        print("CANNOT CHECK: zero Python files scanned — fix the paths.", file=sys.stderr)
        return 2

    findings = sorted(f for path, tree in trees.items() for f in find_violations(path, tree))
    for finding in findings:
        print(finding.render())
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
