#!/usr/bin/env python3
"""Checker: enforce per-symbol docstring and comment SIZE budgets.

WHY
---
Docstrings and comments rot faster than code: a paragraph explaining a
three-line function is read once and then drifts. This gate caps their size
relative to the code they describe. Documentation stays OPTIONAL — a missing
docstring or comment is never a finding; only an oversized one is.

LIMITS
------
Per symbol kind (``module``, ``class``, ``method``, ``function``)::

    docstring limit = min(docstring_max_chars, floor(docstring_code_ratio * code_chars))
                      (no ratio key -> just docstring_max_chars)
    comment limit   = max(comments_max_chars, floor(comments_code_ratio * code_chars))

Counts are raw source characters, whitespace included. Each comment belongs to
its innermost enclosing symbol (span includes decorators and trailing,
deeper-indented comments). ``code_chars`` is the symbol span minus all docs:
nested code counts toward the parent, nested docs do not.

CONFIG
------
``[tool.docstring-budget]`` in ``--config`` (default ``./pyproject.toml``)::

    [tool.docstring-budget]
    function.docstring_max_chars = 150
    function.docstring_code_ratio = 1.0
    function.comments_max_chars = 150
    function.comments_code_ratio = 0.5
    module.docstring_max_chars = 500

Keys given override the built-in defaults key by key; a missing table or file
means all defaults. Unknown keys or wrong types are an error.

CONTRACT
--------
Exit 0 clean, 1 findings, 2 errors. Zero selected files, an invalid config or
an unparsable file is an ERROR (exit 2), never a pass. The last line always
carries ``scanned=N`` so a green run shows its denominator.

USAGE
-----
    python checkers/docstring_budget.py src/myapp tests
    python checkers/docstring_budget.py --config pyproject.toml --limit 0 src/myapp/core.py
"""

from __future__ import annotations

import argparse
import ast
import io
import math
import re
import sys
import tokenize
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, NamedTuple

__all__ = [
    "DEFAULT_BUDGETS",
    "KINDS",
    "Budget",
    "Finding",
    "Report",
    "Symbol",
    "analyze_source",
    "load_budgets",
    "main",
    "select_files",
]

type Kind = Literal["module", "class", "method", "function"]
type Span = tuple[int, int]

KINDS: tuple[Kind, ...] = ("module", "class", "method", "function")
BUDGET_KEYS: frozenset[str] = frozenset(
    {"docstring_max_chars", "docstring_code_ratio", "comments_max_chars", "comments_code_ratio"}
)
COUNTERS: tuple[str, ...] = (
    "files",
    "symbols",
    "source_chars",
    "code_chars",
    "docstring_chars",
    "comment_chars",
    "docstring_excess_chars",
    "comment_excess_chars",
    "violations",
)


class Budget(NamedTuple):
    """Size limits for one symbol kind."""

    docstring_max_chars: int
    docstring_code_ratio: float | None
    comments_max_chars: int
    comments_code_ratio: float


DEFAULT_BUDGETS: dict[Kind, Budget] = {
    "module": Budget(500, None, 150, 0.5),
    "class": Budget(150, 1.0, 150, 0.5),
    "method": Budget(150, 1.0, 150, 0.5),
    "function": Budget(150, 1.0, 150, 0.5),
}


class Symbol(NamedTuple):
    """A documentable symbol and its source offsets."""

    name: str
    kind: Kind
    line: int
    start: int
    end: int
    ownership: Span
    depth: int
    docstring: Span | None


class Finding(NamedTuple):
    """One budget overrun."""

    path: str
    line: int
    symbol: str
    kind: Kind
    category: Literal["docstring", "comments"]
    actual: int
    limit: int


class Report:
    """Scan counters, findings and errors."""

    __slots__ = ("errors", "findings", "summary")

    def __init__(self) -> None:
        self.summary: dict[str, int] = dict.fromkeys(COUNTERS, 0)
        self.findings: list[Finding] = []
        self.errors: list[str] = []


def check_number(value: object, key: str, *, integer: bool) -> int | float:
    """Return *value* (config *key*) if a nonnegative number; *integer* requires an int."""
    allowed: tuple[type, ...] = (int,) if integer else (int, float)
    if isinstance(value, bool) or not isinstance(value, allowed):
        raise ValueError(f"{key} must be {'an integer' if integer else 'a number'}, got {value!r}")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{key} must be finite and >= 0, got {value!r}")
    return value


def load_budgets(path: Path) -> dict[Kind, Budget]:
    """Read ``[tool.docstring-budget]`` from the TOML file at *path* over the defaults."""
    budgets = dict(DEFAULT_BUDGETS)
    if not path.is_file():
        return budgets
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    table = data.get("tool", {}).get("docstring-budget")
    if table is None:
        return budgets
    if not isinstance(table, dict):
        raise ValueError("[tool.docstring-budget] must be a table")
    for kind, values in table.items():
        if kind not in KINDS:
            raise ValueError(
                f"unknown kind {kind!r} in [tool.docstring-budget]; expected {', '.join(KINDS)}"
            )
        if not isinstance(values, dict):
            raise ValueError(f"{kind} must be a table of budget keys")
        if unknown := set(values) - BUDGET_KEYS:
            raise ValueError(f"unknown key(s) {', '.join(sorted(unknown))} under {kind}")
        fields = budgets[kind]._asdict()
        for key, value in values.items():
            fields[key] = check_number(value, f"{kind}.{key}", integer=key.endswith("_max_chars"))
        budgets[kind] = Budget(**fields)
    return budgets


def source_lines(source: str) -> tuple[list[str], list[int]]:
    """Split *source* into lines plus each line's start offset."""
    lines = [match.group() for match in re.finditer(r"[^\r\n]*(?:\r\n|\r|\n|$)", source)]
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    return lines, starts


def ast_offset(lines: Sequence[str], starts: Sequence[int], line: int, column: int) -> int:
    """Map an AST *line* + UTF-8 byte *column* to a char offset using *lines* and *starts*."""
    return starts[line - 1] + len(lines[line - 1].encode("utf-8")[:column].decode("utf-8"))


def node_span(node: ast.expr | ast.stmt, lines: Sequence[str], starts: Sequence[int]) -> Span:
    """Return a *node*'s (start, end) char offsets given *lines* and *starts*."""
    if node.end_lineno is None or node.end_col_offset is None:
        raise ValueError("AST node has no end position")
    return (
        ast_offset(lines, starts, node.lineno, node.col_offset),
        ast_offset(lines, starts, node.end_lineno, node.end_col_offset),
    )


def ownership_span(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    lines: Sequence[str],
    starts: Sequence[int],
) -> Span:
    """Return the span a *node* owns, decorators included (*lines*, *starts*: see node_span)."""
    first = min((decorator.lineno for decorator in node.decorator_list), default=node.lineno) - 1
    if node.decorator_list:
        while first > 0 and not lines[first].lstrip(" \t").startswith("@"):
            first -= 1
    if node.end_lineno is None:
        raise ValueError("AST symbol has no end position")
    last = node.end_lineno
    header = lines[node.lineno - 1]
    indentation = len(header[: len(header) - len(header.lstrip(" \t"))].expandtabs(8))
    while last < len(lines):
        text = lines[last].lstrip(" \t")
        indent = len(lines[last][: len(lines[last]) - len(text)].expandtabs(8))
        if text.strip() and (not text.startswith("#") or indent <= indentation):
            break
        last += 1
    start = starts[first] + len(lines[first]) - len(lines[first].lstrip(" \t"))
    return start, starts[last - 1] + len(lines[last - 1])


def collect_symbols(source: str, tree: ast.Module) -> list[Symbol]:
    """Return every module, class, method and function in *source* and its *tree*."""
    lines, starts = source_lines(source)
    symbols: list[Symbol] = []
    pending: list[tuple[ast.AST, str, Kind, int]] = [(tree, "", "module", -1)]
    while pending:
        node, parent_name, parent_kind, depth = pending.pop()
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if isinstance(node, ast.Module):
                kind: Kind = "module"
                name, start, end, line = "<module>", 0, len(source), 1
                ownership = (start, end)
            else:
                kind = (
                    "class"
                    if isinstance(node, ast.ClassDef)
                    else "method"
                    if parent_kind == "class"
                    else "function"
                )
                name = f"{parent_name}.{node.name}" if parent_name else node.name
                start, end = node_span(node, lines, starts)
                line = node.lineno
                ownership = ownership_span(node, lines, starts)
            docstring = None
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    docstring = node_span(value, lines, starts)
            depth += 1
            symbols.append(Symbol(name, kind, line, start, end, ownership, depth, docstring))
            parent_name, parent_kind = ("" if kind == "module" else name), kind
        pending.extend(
            (child, parent_name, parent_kind, depth)
            for child in reversed(list(ast.iter_child_nodes(node)))
        )
    return symbols


def comment_spans(source: str) -> list[Span]:
    """Return the char span of every comment token in *source*."""
    _, starts = source_lines(source)
    with io.StringIO(source, newline=None) as stream:
        return [
            (starts[token.start[0] - 1] + token.start[1], starts[token.end[0] - 1] + token.end[1])
            for token in tokenize.generate_tokens(stream.readline)
            if token.type == tokenize.COMMENT
        ]


def covered_chars(start: int, end: int, spans: Sequence[Span]) -> int:
    """Count chars of [start, end) inside *spans*."""
    return sum(max(0, min(end, right) - max(start, left)) for left, right in spans)


def union_spans(spans: Sequence[Span]) -> list[Span]:
    """Merge overlapping or touching spans."""
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def record_symbol(
    symbol: Symbol,
    sizes: tuple[int, int, int],
    path: str,
    budgets: dict[Kind, Budget],
    report: Report,
) -> None:
    """Count one *symbol* (*sizes*, *path*) and record any *budgets* overrun in *report*."""
    code_chars, docstring_chars, comment_chars = sizes
    budget = budgets[symbol.kind]
    doc_limit = budget.docstring_max_chars
    if budget.docstring_code_ratio is not None:
        doc_limit = min(doc_limit, math.floor(budget.docstring_code_ratio * code_chars))
    comment_limit = max(
        budget.comments_max_chars, math.floor(budget.comments_code_ratio * code_chars)
    )
    report.summary["symbols"] += 1
    checks: tuple[tuple[Literal["docstring", "comments"], int, int], ...] = (
        ("docstring", docstring_chars, doc_limit),
        ("comments", comment_chars, comment_limit),
    )
    for category, actual, limit in checks:
        if actual > limit:
            report.findings.append(
                Finding(path, symbol.line, symbol.name, symbol.kind, category, actual, limit)
            )
            key = "docstring_excess_chars" if category == "docstring" else "comment_excess_chars"
            report.summary[key] += actual - limit
            report.summary["violations"] += 1


def analyze_source(source: str, path: str, budgets: dict[Kind, Budget], report: Report) -> None:
    """Parse *source* from *path*; record counters and findings per *budgets* in *report*."""
    tree = ast.parse(source, filename=path)
    symbols = collect_symbols(source, tree)
    comments = comment_spans(source)
    docs = [symbol.docstring for symbol in symbols if symbol.docstring is not None]
    documentation = union_spans([*docs, *comments])
    owned = [0] * len(symbols)
    for start, end in comments:
        owner = max(
            (
                index
                for index, symbol in enumerate(symbols)
                if symbol.ownership[0] <= start and end <= symbol.ownership[1]
            ),
            key=lambda index: symbols[index].depth,
        )
        owned[owner] += end - start
    for index, symbol in enumerate(symbols):
        code_chars = (
            symbol.end - symbol.start - covered_chars(symbol.start, symbol.end, documentation)
        )
        docstring_chars = 0
        if symbol.docstring is not None:
            start, end = symbol.docstring
            docstring_chars = end - start - covered_chars(start, end, comments)
        record_symbol(symbol, (code_chars, docstring_chars, owned[index]), path, budgets, report)
    comment_chars = sum(end - start for start, end in comments)
    documentation_chars = sum(end - start for start, end in documentation)
    report.summary["files"] += 1
    report.summary["source_chars"] += len(source)
    report.summary["code_chars"] += len(source) - documentation_chars
    report.summary["docstring_chars"] += documentation_chars - comment_chars
    report.summary["comment_chars"] += comment_chars


def select_files(names: Sequence[str]) -> list[Path]:
    """Expand file and directory *names* into sorted ``*.py`` paths."""
    selected: set[Path] = set()
    for raw in names:
        path = Path(raw)
        if path.is_dir():
            selected.update(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
        elif path.is_file() and path.suffix == ".py":
            selected.add(path)
        else:
            raise ValueError(f"input path is missing or not a Python file/directory: {raw!r}")
    return sorted(selected)


def read_source(path: Path) -> str:
    """Read *path* using its declared source encoding."""
    raw = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding)


def print_report(report: Report, limit: int | None) -> None:
    """Print *report* issues up to *limit* (None = all), then totals."""
    for error in report.errors[:limit]:
        print(f"ERROR: {error}")
    remaining = None if limit is None else max(0, limit - len(report.errors))
    for f in report.findings[:remaining]:
        print(
            f"{f.path}:{f.line}: {f.kind} {f.symbol}: {f.category} "
            f"{f.actual} > {f.limit} (+{f.actual - f.limit})"
        )
    total = len(report.errors) + len(report.findings)
    omitted = 0 if limit is None else total - min(limit, total)
    if omitted:
        print(f"... {omitted} more issue(s); re-run with --limit 0 for the full list")
    s = report.summary
    print(
        f"Files: {s['files']}; scanned={s['files']}; symbols: {s['symbols']}; "
        f"source: {s['source_chars']}; code: {s['code_chars']}; "
        f"docstrings: {s['docstring_chars']}; comments: {s['comment_chars']}; "
        f"docstring excess: {s['docstring_excess_chars']}; "
        f"comment excess: {s['comment_excess_chars']}; "
        f"violations: {s['violations']}; errors: {len(report.errors)}"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point over *argv*; returns 0 clean, 1 findings, 2 errors."""
    parser = argparse.ArgumentParser(description="Enforce docstring and comment size budgets.")
    parser.add_argument(
        "--config", type=Path, default=Path("pyproject.toml"), help="pyproject.toml to read"
    )
    parser.add_argument(
        "--limit", type=int, default=20, help="maximum issues to print; 0 prints every one"
    )
    parser.add_argument("paths", nargs="*", help="Python files or directories to scan")
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    report = Report()
    try:
        budgets = load_budgets(args.config)
        files = select_files(args.paths)
    except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError) as exc:
        report.errors.append(f"configuration/discovery failed: {exc}")
        files = []
    else:
        if not files:
            report.errors.append("no Python files selected")
        for path in files:
            try:
                analyze_source(read_source(path), path.as_posix(), budgets, report)
            except (
                OSError,
                UnicodeError,
                SyntaxError,
                tokenize.TokenError,
                ValueError,
                OverflowError,
            ) as exc:
                report.errors.append(f"{path.as_posix()}: {exc}")
    print_report(report, None if args.limit == 0 else args.limit)
    return 2 if report.errors else 1 if report.findings else 0


if __name__ == "__main__":
    sys.exit(main())
