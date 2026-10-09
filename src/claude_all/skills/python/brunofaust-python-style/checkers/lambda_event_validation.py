#!/usr/bin/env python3
"""Checker: every Lambda handler validates its raw ``event`` through a Pydantic model.
Rules: references/enforcement.md."""

# NOTE: on the skill's 3.12 baseline (no PEP 649 lazy annotations — that is
# 3.14-only), `from __future__ import annotations` is the recommended way to keep
# forward references and TYPE_CHECKING-only imports free at runtime.
from __future__ import annotations

import argparse
import ast
import sys
from fnmatch import fnmatch
from pathlib import Path

__all__ = ["RULES", "Finding", "check_tree", "find_violations", "iter_handler_files", "main"]

RULES: tuple[str, ...] = (
    "missing-validation",
    "stale-allowlist",
)

#: Names AWS Lambda is configured to invoke. A module binding one of these — by
#: `def`, `async def`, or a module-level assignment (`handler = Mangum(app)`) — is a
#: Lambda boundary and owes the event a model.
ENTRY_POINTS = frozenset({"handler", "lambda_handler"})

#: Base classes that make a locally declared class a validated model, so that
#: CONSTRUCTING one (shape 2) counts as validation at the boundary.
MODEL_BASES = frozenset({"BaseModel", "RootModel"})

#: The method name of shape 1. Matched as an attribute call so `MyEvent.model_validate`
#: and `_MODEL.model_validate` both count.
VALIDATE_METHOD = "model_validate"

DEFAULT_HANDLER_GLOB = "**/handler.py"


class Finding(str):
    """A finding key."""

    __slots__ = ()


def _name_of(node: ast.expr | None) -> str:
    """Resolve the trailing bare name out of *node*."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def calls_named(tree: ast.AST, name: str) -> bool:
    """Return whether any call in *tree* invokes something named *name*."""
    return any(
        isinstance(node, ast.Call) and _name_of(node.func) == name for node in ast.walk(tree)
    )


def declared_model_names(tree: ast.AST) -> set[str]:
    """Return the names of pydantic models DECLARED in *tree*."""
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and any(_name_of(b) in MODEL_BASES for b in node.bases)
    }


def constructs_local_model(tree: ast.AST) -> bool:
    names = declared_model_names(tree)
    if not names:
        return False
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names
        for node in ast.walk(tree)
    )


def has_entry_point(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in ENTRY_POINTS:
            return True
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id in ENTRY_POINTS for t in targets):
            return True
    return False


def check_tree(
    tree: ast.AST,
    path: str,
    select: frozenset[str],
    allow: dict[str, str],
) -> list[Finding]:
    symbol = Path(path).parent.name or Path(path).stem
    findings: list[Finding] = []

    def add(rule: str, message: str) -> None:
        if rule in select:
            findings.append(Finding(f"{path}: [{rule}] {symbol} — {message}"))

    if symbol in allow:
        callable_name = allow[symbol]
        # A positively-verified exemption: never a bare `continue`. The allowlist entry
        # states WHY the boundary is safe, and that reason is re-proved on every run.
        if not calls_named(tree, callable_name):
            add(
                "stale-allowlist",
                f"allowlisted because it calls {callable_name}(...), but no "
                f"{callable_name}(...) call found — allowlist stale? Either restore the "
                "validation indirection, or drop the --allow entry so this module must "
                "parse its own event into a model",
            )
        return findings

    if not has_entry_point(tree):
        return findings

    if not (calls_named(tree, VALIDATE_METHOD) or constructs_local_model(tree)):
        add(
            "missing-validation",
            "Lambda entry point does not parse `event` into a Pydantic model — the event "
            "is the most untrusted dict in the process and must be validated at the "
            "boundary, before any logic, via `Model.model_validate(event)` (when the "
            "payload IS our shape) or `Model(field=event.get(...), ...)` (preferred for "
            'an AWS envelope: it keeps the model extra="forbid"). If it validates through '
            "an indirection, exempt it with --allow "
            f"{symbol}=<callable> so the reason stays verified",
        )
    return findings


def find_violations(
    path: Path,
    select: frozenset[str],
    allow: dict[str, str],
) -> list[Finding]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return check_tree(tree, path.as_posix(), select, allow)


def iter_handler_files(roots: list[Path], glob: str) -> list[Path]:
    """Return every handler module under *roots* matching *glob*."""
    basename = glob.rsplit("/", 1)[-1]
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            if fnmatch(root.name, basename):
                files.add(root)
        elif root.is_dir():
            files.update(p for p in root.glob(glob) if p.is_file())
    return sorted(files)


def parse_allow(entries: list[str] | None) -> dict[str, str]:
    allow: dict[str, str] = {}
    for entry in entries or []:
        name, sep, callable_name = entry.partition("=")
        if not sep or not name.strip() or not callable_name.strip():
            raise ValueError(f"--allow must be DIR=CALLABLE, got: {entry!r}")
        allow[name.strip()] = callable_name.strip()
    return allow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enforce Pydantic validation of the Lambda event at the boundary.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("roots", nargs="+", type=Path, help="files or dirs to scan")
    parser.add_argument(
        "--handler-glob",
        default=DEFAULT_HANDLER_GLOB,
        help=f"pattern identifying Lambda handler modules (default: {DEFAULT_HANDLER_GLOB})",
    )
    parser.add_argument(
        "--allow",
        action="append",
        metavar="DIR=CALLABLE",
        help="exempt handler dir DIR because its module calls CALLABLE(...) — the reason "
        "is re-verified every run, and a module that stops calling CALLABLE reports "
        "stale-allowlist instead of passing (repeatable)",
    )
    parser.add_argument(
        "--select",
        default=",".join(RULES),
        help=f"comma-separated rules to enforce (default: all). Available: {', '.join(RULES)}",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="print findings but always exit 0 — ONLY for composing behind "
        "baseline_gate.py, whose contract reads a non-zero exit as 'the checker "
        "itself crashed' and fails closed. An unparsable file still exits 2.",
    )
    args = parser.parse_args(argv)

    select = frozenset(r.strip() for r in args.select.split(",") if r.strip())
    if unknown := select - set(RULES):
        parser.error(f"unknown rule(s): {', '.join(sorted(unknown))}")
    try:
        allow = parse_allow(args.allow)
    except ValueError as exc:
        parser.error(str(exc))

    files = iter_handler_files(args.roots, args.handler_glob)
    print(f"scanned={len(files)}", file=sys.stderr)
    if not files:
        print("ERROR: scanned 0 files — refusing a vacuous pass", file=sys.stderr)
        return 2

    count = 0
    unparsable: list[str] = []
    for file in files:
        try:
            findings = find_violations(file, select, allow)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            unparsable.append(f"{file}: {exc}")
            continue
        for finding in findings:
            print(finding)
            count += 1

    # Fail CLOSED on an unparsable file, and do it even under --exit-zero: this is a
    # TOOL error, not a finding, and baseline_gate.py must see it as one.
    if unparsable:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(
            f"\nERROR: {len(unparsable)} file(s) could not be parsed by the running "
            f"interpreter (python {version}). A file this checker could not read is a "
            "file it did NOT check — skipping it silently would report a Lambda "
            "boundary clean.\n"
            "If the syntax is valid on the project's Python, this hook's interpreter is "
            "too old: pin `language_version` on THIS hook. A repo-level "
            "`default_language_version` does NOT reach a hook's isolated env.",
            file=sys.stderr,
        )
        for item in unparsable:
            print(f"  {item}", file=sys.stderr)
        return 2

    if count and not args.exit_zero:
        print(
            f"\n{count} finding(s) — a Lambda event must be a model before it is logic.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
