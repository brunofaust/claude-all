#!/usr/bin/env python3
"""Checker: SQL states what it means and fails loudly when reality disagrees.

Targeted ON CONFLICT, IF [NOT] EXISTS, DROP ... CASCADE and a swallowed IntegrityError
each need an allowlist entry with a written reason. A bare ON CONFLICT (no target) is
banned outright: on sequence-supplied ids a bare ON CONFLICT DO NOTHING could never
fire — it inserted duplicates while looking idempotent.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from pathlib import Path
from typing import NamedTuple

__all__ = ["CONSTRUCTS", "Allowance", "Finding", "judge", "load_allowlist", "main", "scan"]

BANNED = "on-conflict-bare"
CONSTRUCTS: frozenset[str] = frozenset(
    {
        BANNED,
        "on-conflict-target",
        "ddl-if-not-exists",
        "ddl-if-exists",
        "drop-cascade",
        "suppressed-integrity-error",
    }
)
# Only strings that START with a SQL verb are SQL, so prose and regexes are not flagged.
SQL_START = re.compile(
    r"^\s*\(*\s*(WITH|SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|COMMENT"
    r"|GRANT|REVOKE|SET|DO)\b",
    re.IGNORECASE,
)
ON_CONFLICT = re.compile(r"\bON\s+CONFLICT\b(?P<target>\s*(?:\(|ON\s+CONSTRAINT\b))?", re.I)
IF_NOT_EXISTS = re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.IGNORECASE)
IF_EXISTS = re.compile(r"\bIF\s+EXISTS\b", re.IGNORECASE)
DROP_VERB = re.compile(
    r"\bDROP\s+(?:TABLE|VIEW|MATERIALIZED\s+VIEW|INDEX|SCHEMA|TYPE|SEQUENCE|COLUMN|CONSTRAINT"
    r"|FUNCTION|PROCEDURE|TRIGGER|DATABASE|EXTENSION|POLICY|ROLE|PUBLICATION|SUBSCRIPTION)\b",
    re.IGNORECASE,
)
CASCADE = re.compile(r"\bCASCADE\b", re.IGNORECASE)
REFERENTIAL_CASCADE = re.compile(r"\bON\s+(?:DELETE|UPDATE)\s+CASCADE\b", re.IGNORECASE)
CONFLICT_METHODS = frozenset({"on_conflict_do_nothing", "on_conflict_do_update"})
CONFLICT_TARGET_KWARGS = frozenset({"index_elements", "constraint", "index_where"})
DDL_KWARGS = {"if_not_exists": "ddl-if-not-exists", "if_exists": "ddl-if-exists"}
SKIP_DIRS = frozenset({".venv", "venv", "__pycache__", "node_modules", ".git"})


class Allowance(NamedTuple):
    """One reviewed tolerant-SQL site from the allowlist."""

    site: str
    construct: str
    reason: str


class Finding(NamedTuple):
    """One tolerant construct found at `<path>::<function>`."""

    path: str
    line: int
    site: str
    construct: str
    detail: str


class ConfigError(Exception):
    """Unreadable input; exits 2."""


def load_allowlist(path: Path | None) -> list[Allowance]:
    """Read `[[allow]]` tables (site, construct, reason) from the TOML file at path."""
    if path is None:
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8")).get("allow", [])
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read allowlist ({exc})") from exc
    if not isinstance(raw, list):
        raise ConfigError(f"{path}: `allow` must be an array of tables")
    out: list[Allowance] = []
    for index, entry in enumerate(raw):
        where = f"{path} allow[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"site", "construct", "reason"}:
            raise ConfigError(f"{where}: needs exactly site, construct and reason")
        allowance = Allowance(entry["site"], entry["construct"], entry["reason"])
        if not all(isinstance(value, str) for value in allowance):
            raise ConfigError(f"{where}: site, construct and reason must be strings")
        if not allowance.reason.strip():
            raise ConfigError(f"{where}: empty reason — an allowance needs a written reason")
        if allowance.construct not in CONSTRUCTS:
            raise ConfigError(f"{where}: unknown construct {allowance.construct!r}")
        if allowance.construct == BANNED:
            raise ConfigError(f"{where}: {BANNED} is banned outright and cannot be allowed")
        if any(a[:2] == allowance[:2] for a in out):
            raise ConfigError(f"{where}: duplicate entry for {allowance.site}")
        out.append(allowance)
    return out


def trailing_name(node: ast.expr) -> str:
    """Return the last dotted component of node (`a.b.c` -> `c`), else ''."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def sql_constructs(sql: str) -> list[tuple[str, str]]:
    """Classify every tolerant construct in one SQL string sql."""
    found = [
        ("on-conflict-target", "ON CONFLICT names a target")
        if match.group("target")
        else (BANNED, "ON CONFLICT with no target")
        for match in ON_CONFLICT.finditer(sql)
    ]
    if IF_NOT_EXISTS.search(sql):
        found.append(("ddl-if-not-exists", "IF NOT EXISTS"))
    if IF_EXISTS.search(sql):
        found.append(("ddl-if-exists", "IF EXISTS"))
    for stmt in sql.split(";"):
        bare = REFERENTIAL_CASCADE.sub(" ", stmt)
        if DROP_VERB.search(bare) and CASCADE.search(bare):
            found.append(("drop-cascade", "DROP ... CASCADE"))
            break
    return found


def call_constructs(node: ast.Call) -> list[tuple[str, str]]:
    """Classify the tolerant constructs expressed by one call node."""
    name = trailing_name(node.func)
    found: list[tuple[str, str]] = []
    if name in CONFLICT_METHODS:
        kwargs = {kw.arg for kw in node.keywords}
        targeted = bool(node.args) or bool(kwargs & CONFLICT_TARGET_KWARGS)
        found.append(
            ("on-conflict-target", f"{name}(targeted)") if targeted else (BANNED, f"{name}()")
        )
    found.extend(
        (DDL_KWARGS[kw.arg], f"{name}({kw.arg}=True)")
        for kw in node.keywords
        if kw.arg in DDL_KWARGS and isinstance(kw.value, ast.Constant) and kw.value.value is True
    )
    if name == "suppress" and any(
        trailing_name(arg).endswith("IntegrityError") for arg in node.args
    ):
        found.append(("suppressed-integrity-error", "suppress(IntegrityError)"))
    return found


def handler_constructs(node: ast.ExceptHandler) -> list[tuple[str, str]]:
    """Classify an `except IntegrityError: pass` handler node."""
    if node.type is None:
        return []
    caught = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
    if not any(trailing_name(item).endswith("IntegrityError") for item in caught):
        return []
    swallows = all(
        isinstance(stmt, ast.Pass)
        or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        for stmt in node.body
    )
    return [("suppressed-integrity-error", "except IntegrityError: pass")] if swallows else []


def skipped_ids(tree: ast.Module) -> set[int]:
    """Return ids of docstrings in tree and of f-string parts (read via the f-string)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
        elif isinstance(node, ast.JoinedStr):
            ids.update(id(part) for part in node.values)
    return ids


def node_constructs(node: ast.AST, skip: set[int]) -> list[tuple[str, str]]:
    """Return the constructs of one AST node, ignoring string ids in skip."""
    if isinstance(node, ast.Call):
        return call_constructs(node)
    if isinstance(node, ast.ExceptHandler):
        return handler_constructs(node)
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
        text = node.value
    elif isinstance(node, ast.JoinedStr):
        text = "".join(
            p.value if isinstance(p, ast.Constant) and isinstance(p.value, str) else "?"
            for p in node.values
        )
    else:
        return []
    return sql_constructs(text) if SQL_START.match(text) else []


def scan_file(path: Path, rel: str) -> list[Finding]:
    """Return every tolerant construct in path, sited as `<rel>::<function>`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise ConfigError(f"{rel}: cannot parse ({exc})") from exc
    skip = skipped_ids(tree)
    spans = [
        (n.lineno, n.end_lineno or n.lineno, n.name)
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not (constructs := node_constructs(node, skip)):
            continue
        line = getattr(node, "lineno", 0)
        inside = [(end - start, name) for start, end, name in spans if start <= line <= end]
        site = f"{rel}::{min(inside)[1] if inside else '<module>'}"
        findings.extend(
            Finding(rel, line, site, construct, detail) for construct, detail in constructs
        )
    return findings


def scan(roots: list[Path]) -> tuple[list[Finding], set[str]]:
    """Scan .py files under roots; return findings and the scanned relative paths."""
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            files.add(root)
        elif root.is_dir():
            files.update(p for p in root.rglob("*.py") if not SKIP_DIRS.intersection(p.parts))
        else:
            raise ConfigError(f"no such file or directory: {root}")
    findings: list[Finding] = []
    scanned: set[str] = set()
    for path in sorted(p for p in files if p.suffix == ".py"):
        rel = path.as_posix()
        scanned.add(rel)
        findings.extend(scan_file(path, rel))
    return findings, scanned


def judge(findings: list[Finding], allow: list[Allowance], scanned: set[str]) -> list[str]:
    """Apply the rules to findings given allow entries and scanned paths."""
    allowed = {(a.site, a.construct) for a in allow}
    out: list[str] = []
    for f in sorted(findings):
        if f.construct == BANNED:
            out.append(
                f"{f.path}:{f.line}: banned `{BANNED}` ({f.detail}) at `{f.site}` — a conflict "
                "clause with no target is never verifiable; name a target (`ON CONFLICT (id)`) "
                "or guard with WHERE NOT EXISTS. Cannot be allowlisted."
            )
        elif (f.site, f.construct) not in allowed:
            out.append(
                f"{f.path}:{f.line}: unauthorized `{f.construct}` ({f.detail}) at `{f.site}` — "
                "make it assertive, or add to the allowlist: [[allow]] "
                f'site = "{f.site}" construct = "{f.construct}" reason = "..."'
            )
    live = {(f.site, f.construct) for f in findings}
    out.extend(
        f"{a.site.split('::', 1)[0]}:1: stale allow entry `{a.site}` / `{a.construct}` — "
        "no live site matches; delete or re-key it"
        for a in allow
        if a.site.split("::", 1)[0] in scanned and (a.site, a.construct) not in live
    )
    return out


def main(argv: list[str] | None = None) -> int:
    """Scan argv roots for tolerant SQL not covered by the allowlist."""
    parser = argparse.ArgumentParser(description="Ban silently tolerant SQL.")
    parser.add_argument("roots", nargs="+", type=Path, help="Python files or dirs")
    parser.add_argument("--allowlist", type=Path, help="TOML file of [[allow]] entries")
    parser.add_argument("--exit-zero", action="store_true", help="report but exit 0")
    args = parser.parse_args(argv)
    try:
        allow = load_allowlist(args.allowlist)
        findings, scanned = scan(args.roots)
    except ConfigError as exc:
        print(f"assertive-sql: cannot check — {exc}", file=sys.stderr)
        return 2
    print(f"scanned={len(scanned)}", file=sys.stderr)
    if not scanned:
        print("assertive-sql: no .py files found — checked nothing", file=sys.stderr)
        return 2
    violations = judge(findings, allow, scanned)
    for line in violations:
        print(line)
    return 1 if violations and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
