#!/usr/bin/env python3
"""Checker: e2e tests must drive real execution, not bypass it in-process.

Flags, under the e2e roots: a `patch`/`patch.object`/`monkeypatch.setattr` target or Mock
`spec=` that resolves to first-party code; env mutation (`setenv`, `os.environ[...] =`,
`patch.dict(os.environ)`) not sourced from a shared env view; and importing a production
entrypoint to call it in-process (skipping its container/queue boundary)."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import NamedTuple

__all__ = ["Config", "Finding", "Visitor", "collect_bindings", "iter_py_files", "main"]

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".tox"}
)
MOCK_FAMILY: frozenset[str] = frozenset({"Mock", "MagicMock", "AsyncMock", "create_autospec"})
MESSAGES: dict[str, str] = {
    "mock-first-party-patch": "patch target resolves to OUR OWN code; drive the real path",
    "mock-first-party-spec": "Mock spec resolves to OUR OWN code; drive the real class",
    "env-setenv": "monkeypatch.setenv manufactures config the deployed stack never sees",
    "env-environ-assign": "os.environ assignment manufactures config the stack never sees",
    "env-patch-dict": "patch.dict(os.environ) manufactures config the stack never sees",
    "prod-entrypoint-import": "production entrypoint called in-process skips its boundary",
}


class Config(NamedTuple):
    """Checker settings."""

    packages: frozenset[str]
    entrypoints: frozenset[tuple[str, str]]
    sdk_boundaries: frozenset[str]
    shared_env: frozenset[str]

    def first_party(self, target: str | None) -> bool:
        if target is None or target in self.sdk_boundaries:
            return False
        return target.split(".")[0] in self.packages


class Finding(NamedTuple):
    """One e2e bypass."""

    path: str
    line: int
    kind: str
    detail: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.kind} — `{self.detail}`: {MESSAGES[self.kind]}."


def dotted(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=inner, attr=attr):
            head = dotted(inner)
            return None if head is None else f"{head}.{attr}"
        case _:
            return None


def collect_bindings(tree: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    """Map local names in `tree` to dotted paths (imports + import_module) and string constants."""
    names: dict[str, str] = {}
    constants: dict[str, str] = {}
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=aliases):
                for alias in aliases:
                    local = alias.asname or alias.name.split(".")[0]
                    names[local] = alias.name if alias.asname else local
            case ast.ImportFrom(module=str() as module, level=0, names=aliases):
                for alias in aliases:
                    names[alias.asname or alias.name] = f"{module}.{alias.name}"
            case ast.Assign(targets=[ast.Name(id=local)], value=ast.Constant(value=str() as text)):
                constants[local] = text
            case ast.Assign(
                targets=[ast.Name(id=local)],
                value=ast.Call(func=func, args=[ast.Constant(value=str() as module), *_]),
            ) if (dotted(func) or "").endswith("import_module"):
                names[local] = module
    return names, constants


class Visitor(ast.NodeVisitor):
    """Collect e2e bypass findings in one module."""

    def __init__(self, path: str, config: Config, tree: ast.Module) -> None:
        self.path = path
        self.config = config
        self.names, self.constants = collect_bindings(tree)
        self.findings: list[Finding] = []

    def add(self, node: ast.expr | ast.stmt, kind: str, detail: str) -> None:
        self.findings.append(Finding(self.path, node.lineno, kind, detail))

    def resolve(self, node: ast.expr) -> str | None:
        path = dotted(node)
        if path is None:
            return None
        head, _, rest = path.partition(".")
        base = self.names.get(head)
        if base is None:
            return None
        return f"{base}.{rest}" if rest else base

    def string(self, node: ast.expr) -> str | None:
        match node:
            case ast.Constant(value=str() as text):
                return text
            case ast.Name(id=name):
                return self.constants.get(name)
            case _:
                return None

    def shared(self, node: ast.expr | None) -> bool:
        if node is None:
            return False
        return any(
            isinstance(sub, ast.Name) and sub.id in self.config.shared_env for sub in ast.walk(node)
        )

    def patch_target(self, node: ast.Call) -> str | None:
        func = dotted(node.func) or ""
        leaf = func.rsplit(".", 1)[-1]
        is_patch = leaf == "patch" or func.endswith("monkeypatch.setattr")
        is_object = func.endswith("patch.object") or func.endswith("monkeypatch.setattr")
        if not node.args:
            return None
        if is_patch and (literal := self.string(node.args[0])) is not None:
            return literal
        if is_object and len(node.args) > 1 and (attr := self.string(node.args[1])) is not None:
            owner = self.resolve(node.args[0])
            return None if owner is None else f"{owner}.{attr}"
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if node.module is not None and (node.module, alias.name) in self.config.entrypoints:
                self.add(node, "prod-entrypoint-import", f"{node.module}.{alias.name}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = dotted(node.func) or ""
        target = self.patch_target(node)
        spec = next((kw.value for kw in node.keywords if kw.arg in {"spec", "spec_set"}), None)
        if self.config.first_party(target) and target is not None:
            self.add(node, "mock-first-party-patch", target)
        elif func.rsplit(".", 1)[-1] in MOCK_FAMILY and spec is not None:
            resolved = self.resolve(spec)
            if self.config.first_party(resolved) and resolved is not None:
                self.add(node, "mock-first-party-spec", resolved)
        elif func.endswith(".setenv") and node.args:
            key = self.string(node.args[0])
            value = node.args[1] if len(node.args) > 1 else None
            if key is not None and not self.shared(value):
                self.add(node, "env-setenv", key)
        elif func.endswith("patch.dict") and node.args and dotted(node.args[0]) == "os.environ":
            sources = [*node.args[1:], *(kw.value for kw in node.keywords)]
            if not any(self.shared(source) for source in sources):
                self.add(node, "env-patch-dict", "os.environ")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Subscript) and dotted(target.value) == "os.environ":
                key = self.string(target.slice)
                if key is not None and not self.shared(node.value):
                    self.add(node, "env-environ-assign", key)
        self.generic_visit(node)


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
    parser.add_argument("--e2e-root", action="append", required=True, metavar="DIR")
    parser.add_argument("--package", action="append", required=True, metavar="NAME")
    parser.add_argument(
        "--entrypoint",
        action="append",
        default=[],
        metavar="MODULE:FUNC",
        help="production entrypoint never to import in e2e tests (repeatable)",
    )
    parser.add_argument(
        "--sdk-boundary",
        action="append",
        default=[],
        metavar="DOTTED",
        help="first-party target that is a thin third-party SDK wrapper (repeatable)",
    )
    parser.add_argument(
        "--shared-env",
        action="append",
        default=[],
        metavar="NAME",
        help="env view an env mutation may be sourced from (repeatable)",
    )
    parser.add_argument("--exit-zero", action="store_true", help="report but always exit 0")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    entrypoints: set[tuple[str, str]] = set()
    for raw in args.entrypoint:
        module, sep, func = raw.partition(":")
        if not (sep and module and func):
            print(f"CANNOT CHECK: --entrypoint must be MODULE:FUNC, got {raw!r}", file=sys.stderr)
            return 2
        entrypoints.add((module, func))
    config = Config(
        frozenset(args.package),
        frozenset(entrypoints),
        frozenset(args.sdk_boundary),
        frozenset(args.shared_env),
    )
    files = list(iter_py_files(args.e2e_root))
    findings: list[Finding] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            print(f"CANNOT CHECK: could not parse {path}: {exc}", file=sys.stderr)
            return 2
        visitor = Visitor(path.as_posix(), config, tree)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    print(f"scanned={len(files)} files", file=sys.stderr)
    if not files:
        print(f"CANNOT CHECK: zero Python files under {args.e2e_root}", file=sys.stderr)
        return 2
    for finding in sorted(findings):
        print(finding.render())
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
