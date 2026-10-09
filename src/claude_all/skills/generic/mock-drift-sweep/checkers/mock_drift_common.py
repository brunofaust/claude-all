#!/usr/bin/env python3
"""Shared AST helpers for the mock-drift checker family."""

import argparse
import ast
import json
import sys
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "build_module_index",
    "collect_patch_call_findings",
    "find_def",
    "import_map",
    "is_patch_call",
    "is_patch_object_call",
    "is_test_file",
    "is_truthy",
    "iter_py_files",
    "keyword",
    "load_baseline_keys",
    "make_patch_finding_checker",
    "module_suffixes",
    "new_positional_arg",
    "parse_trees",
    "patch_object_target",
    "report_unparsable",
    "resolve_call_target",
    "run_regression_gate_cli",
    "string_value",
    "trailing_name",
]


def trailing_name(node: ast.expr | None) -> str:
    """Return the TRAILING name of *node*."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def is_patch_call(call: ast.Call) -> bool:
    """True when *call* is ``patch(...)`` / ``mock.patch(...)`` (NOT ``patch.object``)."""
    func = call.func
    return isinstance(func, ast.Name | ast.Attribute) and trailing_name(func) == "patch"


def is_patch_object_call(call: ast.Call) -> bool:
    """True when *call* is ``patch.object(...)`` / ``mock.patch.object(...)``."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "object"
        and trailing_name(func.value) == "patch"
    )


def string_value(node: ast.expr | None) -> str | None:
    """Return the ``str`` constant *node* holds, or ``None`` when it is not a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    """Return the value expression of keyword *name* on *call*, or ``None``."""
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def is_truthy(node: ast.expr | None) -> bool:
    """True when *node* is a literal that is not falsy — used for ``autospec=``."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    return node is not None  # a non-literal autospec (variable) is treated as set


def module_suffixes(path: Path) -> list[str]:
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts))] if parts else []


def build_module_index(trees: dict[Path, ast.Module]) -> dict[str, ast.Module]:
    owners: dict[str, set[Path]] = {}
    for path in trees:
        for suffix in module_suffixes(path):
            owners.setdefault(suffix, set()).add(path)
    return {suffix: trees[next(iter(paths))] for suffix, paths in owners.items() if len(paths) == 1}


def import_map(module: ast.Module) -> dict[str, str]:
    """Map a locally-bound name to the module it was imported FROM."""
    bound: dict[str, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def find_def(body: list[ast.stmt], name: str) -> ast.stmt | None:
    """Return the top-level def/class named *name* in *body*, or ``None``."""
    for node in body:
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == name
        ):
            return node
    return None


def is_test_file(path: Path) -> bool:
    """True when *path* is a test module (name or a ``tests`` path segment)."""
    return path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts


def patch_object_target(call: ast.Call, imports: dict[str, str]) -> str | None:
    if len(call.args) < 2:
        return None
    attr = string_value(call.args[1])
    if attr is None:
        return None
    obj = call.args[0]
    if isinstance(obj, ast.Name) and obj.id in imports:
        return f"{imports[obj.id]}.{attr}"
    return None


def iter_py_files(roots: list[Path]) -> list[Path]:
    """Yield every ``*.py`` under *roots* (files or dirs).

    Args:
        roots: Files or directories to scan.
    """
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def parse_trees(roots: list[Path]) -> tuple[dict[Path, ast.Module], list[str]]:
    """Parse every ``.py`` file under *roots*."""
    trees: dict[Path, ast.Module] = {}
    unparsable: list[str] = []
    for file in iter_py_files(roots):
        try:
            trees[file] = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            unparsable.append(f"{file}: {exc}")
    return trees, unparsable


def report_unparsable(unparsable: list[str]) -> None:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(
        f"\nERROR: {len(unparsable)} file(s) could not be parsed by the running "
        f"interpreter (python {version}). A file this checker could not read is a "
        "file it did NOT check. If the syntax is valid on the project's Python, this "
        "hook's interpreter is too old: pin `language_version` on THIS hook.",
        file=sys.stderr,
    )
    for item in unparsable:
        print(f"  {item}", file=sys.stderr)


def load_baseline_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def resolve_call_target(call: ast.Call, imports: dict[str, str]) -> str | None:
    if is_patch_call(call):
        return string_value(call.args[0]) if call.args else string_value(keyword(call, "target"))
    if is_patch_object_call(call):
        return patch_object_target(call, imports)
    return None


def new_positional_arg(call: ast.Call) -> ast.expr | None:
    """Return the positional ``new`` argument of a ``patch``/``patch.object`` call, if any."""
    if is_patch_call(call) and len(call.args) > 1:
        return call.args[1]
    if is_patch_object_call(call) and len(call.args) > 2:
        return call.args[2]
    return None


def make_patch_finding_checker(
    is_finding: Callable[[str, dict[str, ast.Module], ast.Call], bool | None],
) -> Callable[[ast.Call, dict[str, ast.Module], dict[str, str]], str | None]:

    def check_patch(
        call: ast.Call, index: dict[str, ast.Module], imports: dict[str, str]
    ) -> str | None:
        target = resolve_call_target(call, imports)
        if target is not None and is_finding(target, index, call) is True:
            return target
        return None

    return check_patch


def collect_patch_call_findings(
    trees: dict[Path, ast.Module],
    index: dict[str, ast.Module],
    check_patch: Callable[[ast.Call, dict[str, ast.Module], dict[str, str]], str | None],
) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for path, tree in trees.items():
        if not is_test_file(path):
            continue
        imports = import_map(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                result = check_patch(node, index, imports)
                if result is not None:
                    hits.append((path, node.lineno, result))
    return hits


def run_regression_gate_cli(
    argv: list[str] | None,
    *,
    description: str,
    baseline_file: Path,
    find_violations: Callable[[dict[Path, ast.Module], dict[str, ast.Module]], list[str]],
) -> int:
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "roots", nargs="+", type=Path, help="files or dirs — pass BOTH source and tests"
    )
    parser.add_argument(
        "--baseline", action="store_true", help="write the current findings as the baseline"
    )
    parser.add_argument(
        "--check", action="store_true", help="gate: fail on findings not in the baseline"
    )
    args = parser.parse_args(argv)

    trees, unparsable = parse_trees(args.roots)
    if unparsable:
        report_unparsable(unparsable)
        return 2

    index = build_module_index(trees)
    findings = find_violations(trees, index)

    if args.baseline:
        baseline_file.write_text(
            json.dumps(sorted(set(findings)), indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote {len(findings)} findings to {baseline_file}")
        return 0

    if not args.check:
        for finding in findings:
            print(finding)
        print(f"\nTotal: {len(findings)}")
        return 0

    baseline = load_baseline_keys(baseline_file)
    current = set(findings)
    new = [f for f in findings if f not in baseline]
    resolved = baseline - current

    for finding in new:
        print(f"NEW {finding}")
    for stale in sorted(resolved):
        print(f"STALE baseline entry (ratchet down — remove it): {stale}")

    if new or resolved:
        print(
            f"\nFAIL: {len(new)} new finding(s), {len(resolved)} stale baseline entry(ies).",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {len(current)} finding(s), all baselined; none new.")
    return 0
