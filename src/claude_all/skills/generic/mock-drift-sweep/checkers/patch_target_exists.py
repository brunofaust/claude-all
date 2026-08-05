#!/usr/bin/env python3
"""Checker: a ``patch(...)`` target must actually exist somewhere.

WHY
---
``unittest.mock.patch`` does not validate that the attribute it is about to
replace exists — it happily creates a brand-new attribute on whatever object
it resolved and patches THAT. So when a function is renamed, moved, or
deleted, every ``patch("old.dotted.path")`` string that named it keeps
"working": the test still collects, still runs, still passes — it is just no
longer testing anything, because the code under test never reads the name the
test replaced. ``pytest --collect-only`` cannot catch this (it never resolves
patch strings), so the drift is invisible until someone reads the diff by
hand or the real call site silently uses the un-mocked original.

WHAT IT FLAGS
-------------
A ``patch("dotted.path")`` / ``patch.object(Obj, "name")`` call in a test file
whose target module IS one of the scanned source files, but the trailing name
is absent from EVERY one of: a module-level ``def``/``async def``/``class``,
a module-level assignment (``NAME = ...``, tuple/list unpacking, annotated),
an ``import X`` / ``from Y import X [as N]`` binding, or (for the
``Module.Class.method`` form) the class's own body.

CRITICAL FALSE-POSITIVE TRAP — READ BEFORE CHANGING THIS FILE
---------------------------------------------------------------
``patch("myapp.api.deps.get_db")`` where ``get_db`` is IMPORTED INTO that
module rather than defined there is CORRECT and COMMON — you patch a name
*where it is used*, not where it is defined. "Not defined in this file" does
NOT mean "does not exist". The name-existence check below therefore treats an
import binding as existence, on equal footing with a def/class/assignment.

RESOLUTION IS CONSERVATIVE — SILENCE OVER A FALSE POSITIVE
------------------------------------------------------------
A finding fires ONLY when the checker is confident the name is absent. Stays
UNKNOWN (silent) for:

- a module using ``from y import *`` anywhere at module level (cannot know
  what names that binds) — the WHOLE module is treated as unknown;
- a module that calls ``globals()`` anywhere (could inject names dynamically)
  — the whole module is unknown;
- the ``Module.Class.method`` form when ``Class`` has any base other than
  bare ``object`` — the member could be INHERITED from a base this checker
  cannot see into, so the class's own body is not the full picture;
- a dotted chain deeper than ``Module.Class.method`` (e.g. patching an
  attribute on a module-level singleton) — not resolved, left silent;
- the usual whole-checker-family bails: an unresolvable/ambiguous module
  suffix, a ``patch.object`` whose object expression is not a simple imported
  name.

A false negative (a missed dead patch target) is acceptable; a false
positive is not — a noisy hook gets disabled and then protects nothing.

Because resolution needs the *source*, pass BOTH source and tests:

    python checkers/patch_target_exists.py tests src/myapp

CONTRACT
--------
Prints one ``path:line: [patch-target-missing] target — message`` finding per
violation and exits 1 when there is any finding (0 when none, 2 when a file
could not be parsed by the running interpreter — pin ``language_version`` on
this hook).
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
    """A finding line. Subclasses ``str`` so callers can just print it."""

    __slots__ = ()


def walk_module_level(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield module-level statements, descending into ``If``/``Try``/``With`` bodies.

    A name defined under ``if TYPE_CHECKING:`` or a ``try/except ImportError``
    fallback is still module-level and must count as "exists" — only
    ``def``/``class`` bodies are opaque (a name bound INSIDE a function is
    local, not module-level).

    Args:
        body: A statement list (starts as ``module.body``).
    """
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
    """Return every simple name bound by an assignment target.

    Handles a bare ``Name``, and ``Tuple``/``List``/``Starred`` unpacking
    (recursively) — ``a, (b, *c) = ...`` binds ``a``, ``b``, ``c``.

    Args:
        target: An assignment target expression.
    """
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
    """True when *module* calls the ``globals()`` builtin anywhere.

    A module that can inject attributes dynamically via ``globals()[...] = ...``
    cannot be trusted for a name-absence verdict.

    Args:
        module: The parsed module.
    """
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "globals"
        for node in ast.walk(module)
    )


def defined_names(module: ast.Module) -> set[str] | None:
    """Every name resolvable at module level, or ``None`` when the module can't be trusted.

    Counts ``def``/``async def``/``class``, plain and annotated assignments,
    and every ``import``/``from ... import`` binding as "exists" — an import
    binding is patched WHERE IT IS USED, which is correct, not drift.

    Args:
        module: The parsed module.

    Returns:
        The set of bound names, or ``None`` for a wildcard import or a
        ``globals()`` call anywhere in the module (whole-module UNKNOWN).
    """
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
    """True when *cls* has no base, or its only base is bare ``object``.

    Any other base means a member could be INHERITED — this checker cannot
    see into a base it hasn't resolved, so callers must treat that class as
    UNKNOWN for member-absence verdicts.

    Args:
        cls: The class definition.
    """
    if not cls.bases:
        return True
    return all(isinstance(base, ast.Name) and base.id == "object" for base in cls.bases)


def patch_target_missing(dotted: str, index: dict[str, ast.Module]) -> bool | None:
    """Decide whether *dotted* names something absent from the scanned tree.

    Args:
        dotted: The patch target, e.g. ``"pkg.mod.func"`` or ``"pkg.mod.Cls.method"``.
        index: Dotted-suffix -> module, from :func:`mock_drift_common.build_module_index`.

    Returns:
        ``True`` — confidently missing (the finding). ``False`` — the name
        resolves (or is presumed to). ``None`` — unresolvable/ambiguous: stay
        silent.
    """
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
            # `head` isn't a class we can see. If it isn't bound at all, the
            # whole chain is confidently missing at the first hop; if it IS
            # bound (e.g. a module-level singleton instance), the attribute
            # chain on it is out of scope -- unknown.
            return True if head not in names else None
        if not class_has_only_trivial_bases(cls):
            return None  # member could be inherited from an unseen base
        return tail not in class_member_names(cls)
    return None  # module itself never resolved


def is_missing_finding(target: str, index: dict[str, ast.Module], call: ast.Call) -> bool | None:
    """True when *target* is confidently missing from the scanned tree.

    Args:
        target: The resolved dotted patch target.
        index: Module index for dotted-target resolution.
        call: The original ``patch``/``patch.object`` call (unused — this
            rule needs only the resolved target, never the supplied double).
    """
    del call  # this rule has no "double" concept — signature kept uniform
    return patch_target_missing(target, index)


check_patch = make_patch_finding_checker(is_missing_finding)


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    """Return every finding across the parsed test modules.

    Args:
        trees: Parsed modules keyed by path (source + tests).
        index: Module index built from the same trees.
    """
    return [
        Finding(
            f"{path.as_posix()}:{lineno}: [patch-target-missing] {target} — patch target does not "
            "exist anywhere in the scanned source tree (renamed/moved/deleted symbol?)"
        )
        for path, lineno, target in collect_patch_call_findings(trees, index, check_patch)
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        0 ran clean · 1 findings · 2 an unparsable file (a tool error).
    """
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
