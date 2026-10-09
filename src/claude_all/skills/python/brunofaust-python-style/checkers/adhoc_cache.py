#!/usr/bin/env python3
"""Checker: no ad-hoc caches (`functools.lru_cache` / `functools.cache`, cache libraries).

An ad-hoc cache is process-global state: it outlives the request, so a warm worker
serves one tenant's cached value to another, and pytest-xdist results depend on test
order. Route caching through the project's single sanctioned cache owner (exclude it
with --allow-path). `functools.cached_property` is per-instance and allowed.
Rules: references/enforcement.md.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import sys
from collections.abc import Mapping
from typing import NamedTuple

from py_files import iter_py_files

__all__ = [
    "BANNED_ATTRS",
    "BANNED_MODULES",
    "Finding",
    "banned_decorator_kind",
    "import_map",
    "iter_py_files",
    "main",
    "scan_tree",
]

#: `cached_property` is deliberately absent: it can never match.
BANNED_ATTRS: Mapping[str, str] = {"lru_cache": "lru-cache-decorator", "cache": "cache-decorator"}

BANNED_MODULES: frozenset[str] = frozenset({"cachetools", "diskcache", "aiocache", "beaker"})


class Finding(NamedTuple):
    """One ad-hoc cache at a file location."""

    path: str
    line: int
    kind: str
    symbol: str

    def render(self) -> str:
        """Return the `path:line: message` output line."""
        return (
            f"{self.path}:{self.line}: [{self.kind}] `{self.symbol}` is an ad-hoc process-global "
            "cache. Use the project's sanctioned cache owner, or compute a pure import-time "
            "value once as a module constant."
        )


def import_map(module: ast.Module) -> dict[str, str]:
    """Map each `from X import Y [as Z]` name bound in module to `X.Y`."""
    bound: dict[str, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def banned_decorator_kind(decorator: ast.expr, imports: Mapping[str, str]) -> str | None:
    """Resolve decorator through imports to a banned finding kind, or None."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "functools"
    ):
        return BANNED_ATTRS.get(target.attr)
    if isinstance(target, ast.Name):
        resolved = imports.get(target.id, "")
        if resolved.startswith("functools."):
            return BANNED_ATTRS.get(resolved.removeprefix("functools."))
    return None


def scan_tree(path: str, tree: ast.Module) -> list[Finding]:
    """Return every ad-hoc cache decorator or cache-library import in tree at path."""
    imports = import_map(tree)
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for deco in node.decorator_list:
                if kind := banned_decorator_kind(deco, imports):
                    findings.append(Finding(path, deco.lineno, kind, node.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.partition(".")[0] in BANNED_MODULES:
                    findings.append(Finding(path, node.lineno, "cache-library-import", alias.name))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and (node.module or "").partition(".")[0] in BANNED_MODULES
        ):
            module = node.module or ""
            findings.append(Finding(path, node.lineno, "cache-library-import", module))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flag ad-hoc caches in Python code.")
    parser.add_argument("paths", nargs="*", help="files or directories to scan")
    parser.add_argument(
        "--allow-path",
        action="append",
        default=[],
        help="fnmatch glob of a sanctioned cache-owner file to skip (repeatable)",
    )
    parser.add_argument("--exit-zero", action="store_true", help="print findings, exit 0")
    args = parser.parse_args(argv)

    files = [
        f
        for f in iter_py_files(args.paths)
        if not any(fnmatch.fnmatchcase(f.as_posix(), g) for g in args.allow_path)
    ]
    if not files:
        print("adhoc_cache: zero *.py files to scan — misconfigured paths", file=sys.stderr)
        return 2
    findings: list[Finding] = []
    try:
        for file in files:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=file.as_posix())
            findings.extend(scan_tree(file.as_posix(), tree))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        print(f"adhoc_cache: cannot scan: {exc}", file=sys.stderr)
        return 2
    for finding in sorted(findings):
        print(finding.render())
    print(f"scanned={len(files)}", file=sys.stderr)
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
