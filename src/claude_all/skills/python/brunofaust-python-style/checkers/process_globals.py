#!/usr/bin/env python3
"""Checker: no process-global state in application code.

A warm Lambda container, a long-lived worker, or a pytest-xdist process reuses the
module, so anything bound at module or class scope survives into the next run: one
tenant's client leaks into another's invocation, and tests pass or fail depending on
order. Build collaborators inside the per-run entry point and inject them instead.
Rules: references/enforcement.md.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

from py_files import iter_py_files

__all__ = [
    "DATA_MODEL_BASES",
    "IMMUTABLE_ANNOTATIONS",
    "MUTABLE_CONSTRUCTORS",
    "PROCESS_STATE_CALLS",
    "Config",
    "Finding",
    "Visitor",
    "annotation_root",
    "callee_dotted",
    "import_map",
    "is_optional_annotation",
    "iter_py_files",
    "main",
    "scan",
]

IMMUTABLE_ANNOTATIONS: frozenset[str] = frozenset(
    {
        "Mapping",
        "Sequence",
        "Final",
        "frozenset",
        "AbstractSet",
        "Collection",
        "Iterable",
        "tuple",
    }
)

MUTABLE_CONSTRUCTORS: frozenset[str] = frozenset(
    {
        "dict",
        "list",
        "set",
        "collections.OrderedDict",
        "collections.defaultdict",
        "collections.deque",
        "OrderedDict",
        "defaultdict",
        "deque",
    }
)

#: Dotted callables whose result is process state when bound at module scope.
#: Extend with --resource-call; any `Async<Upper>...()` call also counts.
PROCESS_STATE_CALLS: frozenset[str] = frozenset(
    {
        "asyncio.Lock",
        "asyncio.Semaphore",
        "asyncio.BoundedSemaphore",
        "asyncio.Event",
        "asyncio.Queue",
        "threading.Lock",
        "threading.RLock",
        "threading.Semaphore",
        "threading.Event",
        "weakref.WeakSet",
        "weakref.WeakKeyDictionary",
        "weakref.WeakValueDictionary",
        "contextvars.ContextVar",
        "concurrent.futures.ThreadPoolExecutor",  # guard:allow (data literal, not a call)
        "sqlalchemy.ext.asyncio.create_async_engine",
        "sqlalchemy.ext.asyncio.async_sessionmaker",
        "sqlalchemy.create_engine",
        "httpx.AsyncClient",
        "httpx.Client",
        "aiohttp.ClientSession",
        "requests.Session",
        "jinja2.Environment",
        "boto3.client",
        "boto3.resource",
        "boto3.Session",
    }
)

#: Bases whose class-body assignments are FIELDS, not shared state.
DATA_MODEL_BASES: frozenset[str] = frozenset(
    {
        "BaseModel",
        "BaseSettings",
        "Enum",
        "StrEnum",
        "IntEnum",
        "Flag",
        "IntFlag",
        "Protocol",
        "NamedTuple",
        "TypedDict",
        "Base",
        "DeclarativeBase",
    }
)

DATA_MODEL_SUFFIXES: tuple[str, ...] = ("Model", "Settings", "Enum", "Schema", "Config")

type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class Config(NamedTuple):
    """Scan knobs: resource calls, first-party packages, and exempt symbol globs."""

    resource_calls: frozenset[str]
    packages: tuple[str, ...]
    exempt: tuple[str, ...]
    data_model_bases: frozenset[str]


class Finding(NamedTuple):
    """One process-global shape at a file location."""

    path: str
    line: int
    kind: str
    symbol: str

    def render(self) -> str:
        """Return the `path:line: message` output line."""
        return (
            f"{self.path}:{self.line}: [{self.kind}] `{self.symbol}` keeps state alive across "
            "runs. Build it inside the per-run entry point (e.g. `async def main()`) and "
            "inject it; nothing tenant-bound or resource-holding may live at module or "
            "class scope."
        )


def import_map(module: ast.Module) -> dict[str, str]:
    """Map each locally bound import name in module to its absolute dotted path."""
    bound: dict[str, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.partition(".")[0]
                bound[alias.asname or head] = alias.name if alias.asname else head
    return bound


def trailing_name(node: ast.expr | None) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def annotation_root(annotation: ast.expr | None) -> str | None:
    """Return the outermost name of annotation (`Mapping[str, int]` -> `Mapping`)."""
    node = annotation
    while isinstance(node, ast.Subscript):
        node = node.value
    return trailing_name(node) or None


def is_optional_annotation(annotation: ast.expr | None) -> bool:
    """Return whether annotation admits None (`T | None`, `Optional[T]`)."""
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and annotation.value is None:
        return True
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return is_optional_annotation(annotation.left) or is_optional_annotation(annotation.right)
    return annotation_root(annotation) == "Optional"


def callee_dotted(call: ast.Call, imports: Mapping[str, str]) -> str:
    """Resolve the call callee through imports (`Lock` -> `asyncio.Lock`)."""
    func = call.func
    if isinstance(func, ast.Name):
        return imports.get(func.id, func.id)
    text = ast.unparse(func)
    head, _, rest = text.partition(".")
    resolved = imports.get(head)
    return f"{resolved}.{rest}" if resolved and rest else text


def assignment_parts(stmt: ast.stmt) -> tuple[str, ast.expr | None, ast.expr | None] | None:
    if isinstance(stmt, ast.AnnAssign):
        target, annotation, value = stmt.target, stmt.annotation, stmt.value
    elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target, annotation, value = stmt.targets[0], None, stmt.value
    else:
        return None
    return (target.id, annotation, value) if isinstance(target, ast.Name) else None


def decorator_names(node: FunctionNode) -> set[str]:
    return {name for deco in node.decorator_list if (name := trailing_name(deco))}


def cls_name(function: FunctionNode) -> str | None:
    return function.args.args[0].arg if function.args.args else None


def cls_attribute_targets(function: FunctionNode) -> set[str]:
    """Return the `cls.<attr>` names function assigns (directly or by subscript)."""
    owner = cls_name(function)
    assigned: set[str] = set()
    for node in ast.walk(function):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            attr = target.value if isinstance(target, ast.Subscript) else target
            if (
                isinstance(attr, ast.Attribute)
                and isinstance(attr.value, ast.Name)
                and attr.value.id == owner
            ):
                assigned.add(attr.attr)
    return assigned


def reads_cls_attribute(function: FunctionNode) -> bool:
    owner = cls_name(function)
    return owner is not None and any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == owner
        for node in ast.walk(function)
    )


class Visitor(ast.NodeVisitor):
    """Collect every process-global shape in one module."""

    def __init__(self, path: str, imports: Mapping[str, str], config: Config) -> None:
        """Bind the path, its imports map and the scan config."""
        self.path = path
        self.imports = imports
        self.config = config
        self.stack: list[str] = []
        self.findings: list[Finding] = []

    def add(self, kind: str, symbol: str, line: int) -> None:
        """Record one finding of kind for symbol at line unless it is exempt."""
        key = f"{self.path}::{symbol}"
        globs = self.config.exempt
        if any(fnmatch.fnmatchcase(key, g) or fnmatch.fnmatchcase(symbol, g) for g in globs):
            return
        self.findings.append(Finding(self.path, line, kind, symbol))

    def value_kind(self, value: ast.expr | None, local_classes: frozenset[str]) -> str | None:
        """Classify an assigned value against local_classes, or None when harmless."""
        literals = ast.Dict | ast.List | ast.Set | ast.ListComp | ast.DictComp | ast.SetComp
        if isinstance(value, literals):
            return "module-mutable-literal"
        if not isinstance(value, ast.Call):
            return None
        dotted = callee_dotted(value, self.imports)
        simple = dotted.rsplit(".", 1)[-1]
        if dotted in MUTABLE_CONSTRUCTORS:
            return "module-mutable-literal"
        if dotted in self.config.resource_calls or (
            simple.startswith("Async") and simple[5:6].isupper()
        ):
            return "module-resource-instance"
        local = isinstance(value.func, ast.Name) and value.func.id in local_classes
        first_party = any(dotted.startswith(f"{pkg}.") for pkg in self.config.packages)
        if local or (first_party and simple[:1].isupper()):
            return "module-first-party-instance"
        return None

    def visit_Module(self, node: ast.Module) -> None:
        """Check each direct module-level assignment in node, then recurse."""
        local_classes = frozenset(s.name for s in node.body if isinstance(s, ast.ClassDef))
        for stmt in node.body:
            parts = assignment_parts(stmt)
            if parts is None or parts[0] == "__all__":
                continue
            name, annotation, value = parts
            root = annotation_root(annotation)
            if root == "Final":
                continue
            none = isinstance(value, ast.Constant) and value.value is None
            if none and is_optional_annotation(annotation):
                self.add("module-lazy-slot", name, stmt.lineno)
                continue
            kind = self.value_kind(value, local_classes)
            if kind == "module-mutable-literal" and root in IMMUTABLE_ANNOTATIONS:
                continue
            if kind is not None:
                self.add(kind, name, stmt.lineno)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        """Flag every name in a `global` statement node (the singleton write half)."""
        scope = ".".join(self.stack) or "<module>"
        for name in node.names:
            self.add("global-statement", f"{scope}::{name}", node.lineno)

    def is_data_model(self, node: ast.ClassDef) -> bool:
        """Return whether class node declares fields rather than shared state."""
        bases = {root for base in node.bases if (root := annotation_root(base))}
        return bool(bases & self.config.data_model_bases) or any(
            name.endswith(DATA_MODEL_SUFFIXES) for name in bases
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Check class node for mutable attributes and namespace shape."""
        qualname = ".".join([*self.stack, node.name])
        if not self.is_data_model(node):
            for stmt in node.body:
                parts = assignment_parts(stmt)
                if parts and self.value_kind(parts[2], frozenset()) == "module-mutable-literal":
                    self.add("class-mutable-attribute", f"{qualname}.{parts[0]}", stmt.lineno)
        methods = [s for s in node.body if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)]
        if (
            methods
            and not node.bases
            and not any(m.name in {"__init__", "__new__"} for m in methods)
            and all(decorator_names(m) & {"staticmethod", "classmethod"} for m in methods)
        ):
            self.add("namespace-class", qualname, node.lineno)
        self.visit_scope(node)

    def visit_scope(self, node: ast.ClassDef | FunctionNode) -> None:
        """Recurse into node with its name pushed on the scope stack."""
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def check_def(self, node: FunctionNode) -> None:
        """Flag class-object mutation from node as a classmethod or `__new__`."""
        qualname = ".".join([*self.stack, node.name])
        if node.name == "__new__":
            if cls_attribute_targets(node) or reads_cls_attribute(node):
                self.add("singleton-new", qualname, node.lineno)
        elif "classmethod" in decorator_names(node):
            for attr in sorted(cls_attribute_targets(node)):
                self.add("classmethod-mutates-class", f"{qualname}::{attr}", node.lineno)
        self.visit_scope(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check sync function node."""
        self.check_def(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function node."""
        self.check_def(node)


def scan(files: Iterable[Path], config: Config) -> list[Finding]:
    """Parse files and return every finding under config, sorted by location."""
    findings: list[Finding] = []
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=file.as_posix())
        visitor = Visitor(file.as_posix(), import_map(tree), config)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flag process-global state in Python code.")
    parser.add_argument("paths", nargs="*", help="files or directories to scan")
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="first-party package; a module-level `pkg.Class()` instance is flagged (repeatable)",
    )
    parser.add_argument(
        "--resource-call",
        action="append",
        default=[],
        help="extra dotted callable whose module-level result is process state (repeatable)",
    )
    parser.add_argument(
        "--data-model-base",
        action="append",
        default=[],
        help="extra base class whose class-body assignments are fields (repeatable)",
    )
    parser.add_argument(
        "--exempt",
        action="append",
        default=[],
        help="fnmatch glob over `symbol` or `path::symbol` to skip (repeatable)",
    )
    parser.add_argument("--exit-zero", action="store_true", help="print findings, exit 0")
    args = parser.parse_args(argv)

    files = list(iter_py_files(args.paths))
    if not files:
        print("process_globals: zero *.py files to scan — misconfigured paths", file=sys.stderr)
        return 2
    config = Config(
        resource_calls=PROCESS_STATE_CALLS | frozenset(args.resource_call),
        packages=tuple(args.package),
        exempt=tuple(args.exempt),
        data_model_bases=DATA_MODEL_BASES | frozenset(args.data_model_base),
    )
    try:
        findings = scan(files, config)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        print(f"process_globals: cannot scan: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.render())
    print(f"scanned={len(files)}", file=sys.stderr)
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
