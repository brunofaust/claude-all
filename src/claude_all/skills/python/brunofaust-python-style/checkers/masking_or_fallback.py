#!/usr/bin/env python3
"""Checker: `<identity> or <falsy literal>` (`org_id or 0`, `token or ""`) fakes an identity.

A zero org or an empty token is never a valid value; it is absence wearing a valid value's
clothes. `int(conn.get("org_id") or 0)` once built an UNAUTHENTICATED client that read as a
permissions bug for months. Only identity names (and identity keyword sinks) are judged:
`rowcount or 0` has a meaningful empty case and is out of scope."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator, Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "DEFAULT_IDENTITY",
    "DEFAULT_SINK_EXCLUSIONS",
    "DEFAULT_TRACING",
    "Finding",
    "Rules",
    "Visitor",
    "falsy_literal",
    "iter_py_files",
    "main",
    "matcher_health_error",
    "subject_name",
]

IDENTITY_WORDS: tuple[str, ...] = (
    "id",
    "ids",
    "key",
    "uuid",
    "arn",
    "org",
    "tenant",
    "account",
    "scope",
    "owner",
    "token",
    "secret",
    "branch",
)
#: Whole name or trailing `_`-segment: `org_id` / `project_key` hit, `valid` / `monkey` do not.
DEFAULT_IDENTITY: tuple[str, ...] = tuple(
    pattern for word in IDENTITY_WORDS for pattern in (word, f"*_{word}")
)
#: Identity-SHAPED handles that exist only to be logged; an empty one degrades a log line.
DEFAULT_TRACING: tuple[str, ...] = (
    "aws_request_id",
    "cache_key",
    "correlation_id",
    "event_id",
    "execution_id",
    "idempotency_key",
    "message_id",
    "request_id",
    "run_id",
    "session_id",
    "trace_id",
)
#: `key=` is the stdlib sort/group callable parameter, never a tenant key.
DEFAULT_SINK_EXCLUSIONS: tuple[str, ...] = ("key",)
SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".tox"}
)


class Finding(NamedTuple):
    """One identity `or`-fallback."""

    path: str
    line: int
    kind: str
    detail: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.kind} — `{self.detail}` fakes an identity when the "
            "value is missing. Delete the fallback and let it raise, or model the source so the "
            "field's declared optionality answers the question."
        )


class Rules(NamedTuple):
    """Configured name vocabularies."""

    identity: tuple[str, ...]
    tracing: frozenset[str]
    sink_exclusions: frozenset[str]

    def is_identity(self, name: str | None) -> bool:
        if name is None or name in self.tracing:
            return False
        return any(fnmatchcase(name, pattern) for pattern in self.identity)


def falsy_literal(node: ast.expr) -> str | None:
    # Empty containers are out of scope: `items or []` has a meaningful empty case.
    match node:
        case ast.Constant(value=bool() | None):
            return None
        case ast.Constant(value=""):
            return '""'
        case ast.Constant(value=int() | float() as number) if number == 0:
            return "0"
        case _:
            return None


def subject_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Await(value=inner):
            return subject_name(inner)
        case ast.BoolOp(values=[*_, last]):
            return subject_name(last)
        case ast.Subscript(slice=ast.Constant(value=str() as literal_key)):
            return literal_key
        case ast.Subscript(value=inner):
            return subject_name(inner)
        case ast.Attribute(attr=attr):
            return attr
        case ast.Call(
            func=ast.Attribute(attr="get" | "pop"), args=[ast.Constant(value=str() as key), *_]
        ):
            return key
        case ast.Call(func=ast.Attribute(attr=attr)):
            return attr
        case ast.Call(func=ast.Name(id=callee)):
            return callee
        case _:
            return None


class Visitor(ast.NodeVisitor):
    """Collect identity `or`-fallbacks and count every candidate classified."""

    def __init__(self, path: str, rules: Rules) -> None:
        self.path = path
        self.rules = rules
        self.candidates = 0
        self.findings: list[Finding] = []
        # A sink binds ONLY to the expression passed directly as the keyword value.
        self.sink_by_node: dict[int, str] = {}

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg is not None and node.arg not in self.rules.sink_exclusions:
            self.sink_by_node[id(node.value)] = node.arg
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if isinstance(node.op, ast.Or):
            self.classify(node)
        self.generic_visit(node)

    def classify(self, node: ast.BoolOp) -> None:
        fallback = falsy_literal(node.values[-1])  # `a or b or 0`: the literal is last
        if fallback is None:
            return
        self.candidates += 1
        text = ast.unparse(node)
        if self.rules.is_identity(subject_name(node.values[-2])):
            kind = "identity-or-zero" if fallback == "0" else "identity-or-empty"
            self.findings.append(Finding(self.path, node.lineno, kind, text))
            return
        sink = self.sink_by_node.get(id(node))
        if self.rules.is_identity(sink):
            self.findings.append(
                Finding(self.path, node.lineno, "identity-kwarg-or", f"{sink}={text}")
            )


def matcher_health_error(rules: Rules) -> str | None:
    tree = ast.parse('org_id or 0\ntoken or ""\n')
    visitor = Visitor("<sentinel>", Rules(DEFAULT_IDENTITY, frozenset(), rules.sink_exclusions))
    visitor.visit(tree)
    kinds = {finding.kind for finding in visitor.findings}
    if visitor.candidates != 2 or kinds != {"identity-or-zero", "identity-or-empty"}:
        return "the in-memory sentinel was not classified as expected"
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
        "--identity",
        action="append",
        metavar="GLOB",
        help="identity-name glob (repeatable; replaces the defaults)",
    )
    parser.add_argument(
        "--allow-name",
        action="append",
        metavar="NAME",
        help="tracing name exempt from the rule (repeatable; replaces the defaults)",
    )
    parser.add_argument(
        "--sink-exclude",
        action="append",
        metavar="NAME",
        help="keyword name that is never an identity sink (repeatable; replaces the defaults)",
    )
    parser.add_argument("--exit-zero", action="store_true", help="report but always exit 0")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rules = Rules(
        tuple(args.identity or DEFAULT_IDENTITY),
        frozenset(args.allow_name or DEFAULT_TRACING),
        frozenset(args.sink_exclude or DEFAULT_SINK_EXCLUSIONS),
    )
    if error := matcher_health_error(rules):
        print(f"CANNOT CHECK: {error}", file=sys.stderr)
        return 2
    files = list(iter_py_files(args.paths))
    candidates = 0
    findings: list[Finding] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            print(f"CANNOT CHECK: could not parse {path}: {exc}", file=sys.stderr)
            return 2
        visitor = Visitor(path.as_posix(), rules)
        visitor.visit(tree)
        candidates += visitor.candidates
        findings.extend(visitor.findings)
    print(f"scanned={len(files)} files candidates={candidates}", file=sys.stderr)
    if not files:
        print(f"CANNOT CHECK: zero Python files under {args.paths}", file=sys.stderr)
        return 2
    for finding in sorted(findings):
        print(finding.render())
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
