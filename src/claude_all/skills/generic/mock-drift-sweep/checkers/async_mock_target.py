#!/usr/bin/env python3
"""Checker: a mock standing in for an ``async def`` must be async-aware.

WHY
---
A plain ``MagicMock``/``Mock`` is never awaited and never fails, so a test that
patches an ``async def`` with one *passes whether or not the code under test
actually awaits it* — it validates nothing about the seam it exists to protect.
A real system shipped a sync ``def`` factory into an ``async with`` because every
fixture used a bare ``MagicMock`` for it: the tests were green and the broken
async context manager reached production, where the first real ``async with``
blew up.

The rule: patching an ``async def`` target requires an async-aware double —
``AsyncMock``, ``autospec=True`` (autospec infers async from the real object), or
``new_callable=AsyncMock``. A bare ``MagicMock`` on an async target is a false
green.

WHAT IT FLAGS
-------------
A ``patch("dotted.path")`` / ``patch.object(Obj, "name")`` call **in a test file**
whose target — resolved to a definition *inside the scanned source tree* — is an
``async def``, and whose call supplies none of the async-aware signals above (and
so falls back to the ``MagicMock`` default, or explicitly names a sync ``Mock``).

RESOLUTION IS CONSERVATIVE — SILENCE OVER A FALSE POSITIVE
---------------------------------------------------------
The finding fires ONLY when the target can be resolved with confidence to an
``async def`` defined in the tree. Anything the checker cannot pin — a target
whose module is not in the scanned roots, an imported-then-re-exported name, an
ambiguous module suffix (two files share it), a ``patch.object`` whose object
expression is not a simple imported class, a dotted chain deeper than
``Module.Class.method`` — resolves to UNKNOWN and is **left silent**. A false
negative (a missed async target) is acceptable; a false positive is not.

Because resolution needs the *source*, pass BOTH the source and the tests so the
dotted targets resolve:

    python checkers/async_mock_target.py src tests

Passing only ``tests`` leaves every target unresolvable — and therefore silent.

CONTRACT
--------
Prints one ``path:line: [async-mock] target — message`` finding per violation to
stdout and **exits 1 when there is any finding**, so wiring it straight into
prek/pre-commit surfaces the findings and fails the commit. Compose it behind
``regression-gates/baseline_gate.py`` with ``--exit-zero`` for the regression-only
ratchet (that harness reads a non-zero exit as "the checker crashed" and fails
closed, so the flag is required there and nowhere else).

PARSER NOTE — pin this hook's interpreter
-----------------------------------------
This checker parses with the ``ast`` of the interpreter it RUNS ON, so an
interpreter older than the project's silently fails to parse new syntax. Like the
sibling checkers it does NOT fail open: an unparsable file exits **2** (a tool
error, distinct from 1 = findings) even under ``--exit-zero``, because a file it
could not read is a file it did not check. Pin ``language_version`` on THIS hook —
a repo-level ``default_language_version`` does NOT reach a hook's isolated env.
"""

# NOTE: this import looks like it violates the very standard the skill enforces —
# the skill's baseline is 3.14, where PEP 649 makes annotations lazy. It stays
# because this is TOOLING that lives in the claude-all repo, which is deliberately
# `requires-python = ">=3.11"` so the installer runs anywhere. Delete it only if
# claude-all's own floor moves to 3.14.

import argparse
import ast
import sys
from pathlib import Path

from mock_drift_common import (
    build_module_index,
    collect_patch_call_findings,
    find_def,
    is_truthy,
    keyword,
    make_patch_finding_checker,
    new_positional_arg,
    parse_trees,
    report_unparsable,
    trailing_name,
)

__all__ = ["Finding", "build_module_index", "find_violations", "main", "resolve_target"]

#: The `mock` factory names that are NOT awaitable — using one for an async target
#: is the bug. `AsyncMock` is the correct double and is deliberately absent here.
SYNC_MOCK_NAMES = frozenset(
    {"MagicMock", "Mock", "NonCallableMock", "NonCallableMagicMock", "PropertyMock"}
)

#: The one async-aware double name that suppresses the finding when passed as
#: `new=` / `new_callable=`.
ASYNC_MOCK_NAME = "AsyncMock"


class Finding(str):
    """A finding line. Subclasses ``str`` so callers can just print it."""

    __slots__ = ()


def call_supplies_async_double(call: ast.Call, *, new_positional: ast.expr | None) -> bool | None:
    """Decide whether *call* already supplies an acceptable double for an async target.

    Args:
        call: The ``patch``/``patch.object`` call.
        new_positional: The positional ``new`` argument, if the call form has one.

    Returns:
        ``True``  — an async-aware signal is present (``autospec=True``,
                    ``new_callable=AsyncMock``, ``new=AsyncMock(...)``): SUPPRESS.
        ``False`` — the double is a KNOWN sync mock (default ``MagicMock``, or an
                    explicit ``MagicMock``/``Mock``): this is the finding.
        ``None``  — ``new``/``new_callable`` names something the checker cannot
                    classify (a custom factory): stay silent, conservative.
    """
    if is_truthy(keyword(call, "autospec")):
        return True

    new_callable = keyword(call, "new_callable")
    new = keyword(call, "new") or new_positional

    for value in (new_callable, new):
        if value is not None and trailing_name(value) == ASYNC_MOCK_NAME:
            return True
    for value in (new_callable, new):
        if value is not None and trailing_name(value) in SYNC_MOCK_NAMES:
            return False

    if new_callable is None and new is None:
        return False  # patch's default double is a MagicMock — not awaitable
    return None  # a custom, unclassifiable factory: do not flag


def lookup_in_module(module: ast.Module, remainder: list[str]) -> bool | None:
    """Resolve an attribute chain inside a module to an ``async def``.

    Args:
        module: The parsed target module.
        remainder: Attribute path after the module prefix — ``["func"]`` for a
            top-level def, ``["Class", "method"]`` for a method. Deeper chains are
            left UNKNOWN.

    Returns:
        ``True`` async def · ``False`` a def/class that is not async · ``None`` unresolved.
    """
    if len(remainder) == 1:
        node = find_def(module.body, remainder[0])
        if isinstance(node, ast.AsyncFunctionDef):
            return True
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            return False
        return None
    if len(remainder) == 2:
        cls = find_def(module.body, remainder[0])
        if not isinstance(cls, ast.ClassDef):
            return None
        method = find_def(cls.body, remainder[1])
        if isinstance(method, ast.AsyncFunctionDef):
            return True
        if isinstance(method, ast.FunctionDef):
            return False
    return None


def resolve_target(dotted: str, index: dict[str, ast.Module]) -> bool | None:
    """Resolve a dotted patch target to whether it names an ``async def``.

    Splits at the LONGEST module prefix present in *index* — the real module — and
    resolves the remainder as an attribute chain there.

    Args:
        dotted: The patch target, e.g. ``"pkg.mod.func"`` or ``"pkg.mod.Cls.method"``.
        index: Dotted-suffix -> module, from :func:`build_module_index`.

    Returns:
        ``True`` async · ``False`` a non-async def/class · ``None`` unresolvable (silent).
    """
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module = index.get(".".join(parts[:split]))
        if module is not None:
            return lookup_in_module(module, parts[split:])
    return None


def is_async_finding(target: str, index: dict[str, ast.Module], call: ast.Call) -> bool | None:
    """True when *target* is an ``async def`` patched with a sync (non-async-aware) double.

    Args:
        target: The resolved dotted patch target.
        index: Module index for dotted-target resolution.
        call: The original ``patch``/``patch.object`` call — inspected for
            the supplied ``new``/``new_callable`` double.
    """
    if resolve_target(target, index) is not True:
        return None
    return call_supplies_async_double(call, new_positional=new_positional_arg(call)) is False


check_patch = make_patch_finding_checker(is_async_finding)


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    """Return every finding across the parsed test modules.

    Args:
        trees: Parsed modules keyed by path (source + tests).
        index: Module index built from the same trees.
    """
    return [
        Finding(
            f"{path.as_posix()}:{lineno}: [async-mock] {target} — async def patched with a "
            "sync mock; use AsyncMock, autospec=True, or new_callable=AsyncMock"
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
        description="Flag a MagicMock standing in for an async def in a patch() target.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="files or dirs — pass BOTH source and tests so dotted targets resolve",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="print findings but always exit 0 — ONLY for composing behind "
        "baseline_gate.py, whose contract reads a non-zero exit as 'the checker crashed'",
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

    if findings and not args.exit_zero:
        print(
            f"\n{len(findings)} finding(s) — a MagicMock on an async target is a green test "
            "over a broken await.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
