#!/usr/bin/env python3
"""Checker: a ``patch(...)`` target must actually exist somewhere. WHY ---
``unittest.mock.patch`` does not validate that the attribute it is about to replace exists —
it happily creates a brand-new attribute on whatever object it resolved and patches THAT.
"""

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

from mock_drift_common import (
    build_module_index,
    collect_patch_call_findings,
    make_patch_finding_checker,
    parse_trees,
    report_unparsable,
)

__all__ = ["Finding", "find_violations", "main", "patch_target_missing"]


class Finding(str):
    """A finding line."""

    __slots__ = ()


def walk_module_level(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    for node in body:
        yield node
        if isinstance(node, ast.If):
            yield from walk_module_level(node.body)
            yield from walk_module_level(node.orelse)
        elif isinstance(node, ast.Try):
            yield from walk_module_level(node.body)
            for handler in node.handlers:
                yield from walk_module_level(handler.body)
            yield from walk_module_level(node.orelse)
            yield from walk_module_level(node.finalbody)
        elif isinstance(node, ast.With | ast.AsyncWith):
            yield from walk_module_level(node.body)


def assignment_target_names(target: ast.expr) -> set[str]:
    """Return every simple name bound by an assignment target."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return assignment_target_names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        names: set[str] = set()
        for elt in target.elts:
            names.update(assignment_target_names(elt))
        return names
    return set()


def uses_globals_call(module: ast.Module) -> bool:
    """True when *module* calls the ``globals()`` builtin anywhere."""
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "globals"
        for node in ast.walk(module)
    )


def defined_names(module: ast.Module) -> set[str] | None:
    """Every name resolvable at module level, or ``None`` when the module can't be trusted."""
    if uses_globals_call(module):
        return None
    names: set[str] = set()
    for node in walk_module_level(module.body):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return None
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(assignment_target_names(target))
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            names.update(assignment_target_names(node.target))
    return names


def top_level_classes(module: ast.Module) -> dict[str, ast.ClassDef]:
    """Map every module-level (incl. nested in ``If``/``Try``/``With``) class by name.

    Args:
        module: The parsed module.
    """
    return {
        node.name: node for node in walk_module_level(module.body) if isinstance(node, ast.ClassDef)
    }


def class_member_names(cls: ast.ClassDef) -> set[str]:
    """Every name bound in *cls*'s own body (methods, nested classes, assignments).

    Args:
        cls: The class definition.
    """
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(assignment_target_names(target))
        elif isinstance(node, ast.AnnAssign):
            names.update(assignment_target_names(node.target))
    return names


def class_has_only_trivial_bases(cls: ast.ClassDef) -> bool:
    """True when *cls* has no base, or its only base is bare ``object``."""
    if not cls.bases:
        return True
    return all(isinstance(base, ast.Name) and base.id == "object" for base in cls.bases)


def patch_target_missing(dotted: str, index: dict[str, ast.Module]) -> bool | None:
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module = index.get(".".join(parts[:split]))
        if module is None:
            continue
        remainder = parts[split:]
        if len(remainder) not in (1, 2):
            return None  # deeper than Module.Class.method -- not resolved

        names = defined_names(module)
        if names is None:
            return None  # wildcard import / globals() call -- whole module unknown

        if len(remainder) == 1:
            return remainder[0] not in names

        # remainder length 2: Module.Class.method
        head, tail = remainder
        cls = top_level_classes(module).get(head)
        if cls is None:
            # Unbound head: confidently missing. Bound non-class (singleton): unknown.
            return True if head not in names else None
        if not class_has_only_trivial_bases(cls):
            return None  # member could be inherited from an unseen base
        return tail not in class_member_names(cls)
    return None  # module itself never resolved


def is_missing_finding(target: str, index: dict[str, ast.Module], call: ast.Call) -> bool | None:
    del call  # this rule has no "double" concept — signature kept uniform
    return patch_target_missing(target, index)


check_patch = make_patch_finding_checker(is_missing_finding)


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    return [
        Finding(
            f"{path.as_posix()}:{lineno}: [patch-target-missing] {target} — patch target does not "
            "exist anywhere in the scanned source tree (renamed/moved/deleted symbol?)"
        )
        for path, lineno, target in collect_patch_call_findings(trees, index, check_patch)
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Args: argv: Optional argument vector (defaults to ``sys.argv``)."""
    parser = argparse.ArgumentParser(
        description="Flag a patch() target absent from every scanned source file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="files or dirs — pass BOTH source and tests so dotted targets resolve",
    )
    args = parser.parse_args(argv)

    trees, unparsable = parse_trees(args.roots)
    if unparsable:
        report_unparsable(unparsable)
        return 2

    index = build_module_index(trees)
    findings = find_violations(trees, index)
    for finding in findings:
        print(finding)

    if findings:
        print(
            f"\n{len(findings)} finding(s) — a patch() target that does not exist silently "
            "creates the attribute instead of testing anything.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
