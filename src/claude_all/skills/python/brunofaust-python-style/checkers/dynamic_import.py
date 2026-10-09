#!/usr/bin/env python3
"""Checker: a first-party module must be imported statically, not via `importlib`/`__import__`.

A module reached dynamically is typed `ModuleType`, whose `__getattr__` returns `Any`, so mypy
stops checking EVERY attribute access through that handle (123 unchecked accesses in one file),
and static checkers cannot resolve a patch target through it. Computed names, relative imports
and calls inside a `with` block (import-after-patch) are exempt."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import NamedTuple

__all__ = ["Finding", "Visitor", "iter_py_files", "main"]

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".tox"}
)


class Finding(NamedTuple):
    """One dynamic first-party import."""

    path: str
    line: int
    call: str
    module: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}: dynamic-import — `{self.call}({self.module!r})`. Import it "
            f"statically (`import {self.module} as <name>`): a dynamic handle is `ModuleType`, so "
            "mypy stops checking every attribute read through it."
        )


class Visitor(ast.NodeVisitor):
    """Collect literal first-party dynamic imports outside `with` blocks."""

    def __init__(self, path: str, packages: frozenset[str]) -> None:
        self.path = path
        self.packages = packages
        self.with_depth = 0
        self.findings: list[Finding] = []
        # Local names bound to `importlib.import_module` (`from importlib import import_module`).
        self.import_module_names: set[str] = set()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    self.import_module_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.with_depth += 1
        self.generic_visit(node)
        self.with_depth -= 1

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.with_depth += 1
        self.generic_visit(node)
        self.with_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        call = self.dynamic_call_name(node.func)
        if call is not None and self.with_depth == 0:
            module = self.first_party_literal(node)
            if module is not None:
                self.findings.append(Finding(self.path, node.lineno, call, module))
        self.generic_visit(node)

    def dynamic_call_name(self, func: ast.expr) -> str | None:
        match func:
            case ast.Attribute(value=ast.Name(id="importlib"), attr="import_module"):
                return "importlib.import_module"
            case ast.Name(id="__import__"):
                return "__import__"
            case ast.Name(id=name) if name in self.import_module_names:
                return name
            case _:
                return None

    def first_party_literal(self, node: ast.Call) -> str | None:
        # A computed name has no static equivalent; `package=` / `level=` mean relative.
        if not node.args or any(kw.arg in {"package", "level"} for kw in node.keywords):
            return None
        match node.args[0]:
            case ast.Constant(value=str() as module) if module.split(".")[0] in self.packages:
                return module
            case _:
                return None


def iter_py_files(paths: Sequence[str]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            for found in sorted(path.rglob("*.py")):
                if not SKIP_DIRS & set(found.parts):
                    yield found


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Python files or directories to scan")
    parser.add_argument(
        "--package",
        action="append",
        required=True,
        metavar="NAME",
        help="first-party top-level package name (repeatable)",
    )
    parser.add_argument("--exit-zero", action="store_true", help="report but always exit 0")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packages = frozenset(args.package)
    files = list(iter_py_files(args.paths))
    findings: list[Finding] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            print(f"CANNOT CHECK: could not parse {path}: {exc}", file=sys.stderr)
            return 2
        visitor = Visitor(path.as_posix(), packages)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    print(f"scanned={len(files)} files", file=sys.stderr)
    if not files:
        print(f"CANNOT CHECK: zero Python files under {args.paths}", file=sys.stderr)
        return 2
    for finding in sorted(findings):
        print(finding.render())
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
