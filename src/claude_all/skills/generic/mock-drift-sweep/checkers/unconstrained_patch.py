#!/usr/bin/env python3
"""Checker: a resolvable ``patch()`` target patched with an unconstrained double.

A bare ``patch("myapp.mod.func")`` builds a MagicMock that accepts any call signature, so the
test keeps passing after the real signature changes. Large suites carry thousands of such
sites, most never type-checked. Callables need ``autospec=True``, constants a real ``new=``
and properties ``new_callable=PropertyMock``.
"""

import argparse
import ast
import sys
from pathlib import Path
from typing import NamedTuple

from mock_drift_common import (
    build_module_index,
    collect_patch_call_findings,
    find_def,
    iter_py_files,
    keyword,
    make_patch_finding_checker,
    parse_trees,
    report_unparsable,
    trailing_name,
)

__all__ = [
    "MOCK_FAMILY_NAMES",
    "Finding",
    "constant_new_is_unconstrained",
    "find_violations",
    "is_unconstrained_finding",
    "main",
    "resolve_target_kind",
]

MOCK_FAMILY_NAMES = frozenset(
    {"MagicMock", "Mock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock"}
)
MESSAGE = (
    "unconstrained-patch: `{target}` — callables need autospec=True, constants an explicit "
    "non-Mock new=, properties new_callable=PropertyMock"
)


class Finding(NamedTuple):
    path: str
    line: int
    target: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {MESSAGE.format(target=self.target)}"


def binds_name(statement: ast.stmt, name: str) -> bool:
    """True when *statement* assigns the module-level *name*."""
    if isinstance(statement, ast.Assign):
        return any(isinstance(t, ast.Name) and t.id == name for t in statement.targets)
    if isinstance(statement, ast.AnnAssign):
        return isinstance(statement.target, ast.Name) and statement.target.id == name
    return False


def kind_in_module(module: ast.Module, remainder: list[str]) -> str | None:
    """Classify the *remainder* attribute path inside *module*."""
    if len(remainder) == 1:
        node = find_def(module.body, remainder[0])
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return "function"
        if isinstance(node, ast.ClassDef):
            return "class"
        if any(binds_name(statement, remainder[0]) for statement in module.body):
            return "constant"
        return None
    if len(remainder) != 2:
        return None
    cls = find_def(module.body, remainder[0])
    # Inherited members are unknowable statically: only plain classes resolve.
    if not isinstance(cls, ast.ClassDef) or any(
        not (isinstance(base, ast.Name) and base.id == "object") for base in cls.bases
    ):
        return None
    method = find_def(cls.body, remainder[1])
    if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    if any(trailing_name(decorator) == "property" for decorator in method.decorator_list):
        return "property"
    return "method"


def resolve_target_kind(dotted: str, index: dict[str, ast.Module]) -> str | None:
    """Resolve *dotted* against *index* to function/class/constant/method/property."""
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module = index.get(".".join(parts[:split]))
        if module is not None:
            return kind_in_module(module, parts[split:])
    return None


def constant_new_is_unconstrained(new: ast.expr | None) -> bool:
    """True when *new* is absent, ``DEFAULT`` or a Mock-family double."""
    if new is None:
        return True
    name = trailing_name(new)
    return name == "DEFAULT" or name in MOCK_FAMILY_NAMES


def is_unconstrained_finding(
    target: str, index: dict[str, ast.Module], call: ast.Call
) -> bool | None:
    """True when *target* resolves via *index* and *call* leaves the double unconstrained."""
    kind = resolve_target_kind(target, index)
    if kind in {"function", "method", "class"}:
        autospec = keyword(call, "autospec")
        return not (isinstance(autospec, ast.Constant) and autospec.value is True)
    if kind == "constant":
        return constant_new_is_unconstrained(keyword(call, "new"))
    if kind == "property":
        return trailing_name(keyword(call, "new_callable")) != "PropertyMock"
    return None


def find_violations(tests: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    """Return every finding in the *tests* trees, resolved against *index*."""
    checker = make_patch_finding_checker(is_unconstrained_finding)
    hits = collect_patch_call_findings(tests, index, checker)
    return sorted(Finding(path.as_posix(), line, target) for path, line, target in hits)


def main(argv: list[str] | None = None) -> int:
    """Run the checker over test roots in *argv*; ``--src`` roots supply resolution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="+", type=Path, help="test files or directories")
    parser.add_argument(
        "--src", action="append", type=Path, required=True, help="first-party source root"
    )
    parser.add_argument("--exit-zero", action="store_true", help="report findings, exit 0")
    args = parser.parse_args(argv)

    test_trees, bad_tests = parse_trees(args.tests)
    src_trees, bad_src = parse_trees(args.src)
    if bad_tests or bad_src:
        report_unparsable(bad_tests + bad_src)
        return 2
    print(f"scanned={len(test_trees)}", file=sys.stderr)
    if not test_trees or not iter_py_files(args.src):
        print("CANNOT CHECK: zero test or source files — fix the paths.", file=sys.stderr)
        return 2

    index = build_module_index({**src_trees, **test_trees})
    findings = find_violations(test_trees, index)
    for finding in findings:
        print(finding.render())
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
