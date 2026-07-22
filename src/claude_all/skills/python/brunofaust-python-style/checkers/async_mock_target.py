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
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

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


def _trailing_name(node: ast.expr | None) -> str:
    """Return the TRAILING name of *node* — ``mock.AsyncMock`` -> ``AsyncMock``,
    ``AsyncMock(...)`` -> ``AsyncMock``, a bare ``Name`` -> its id.

    Args:
        node: The expression to name, or ``None``.

    Returns:
        The trailing name, or ``""`` when *node* carries none.
    """
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_patch_call(call: ast.Call) -> bool:
    """True when *call* is ``patch(...)`` / ``mock.patch(...)`` (NOT ``patch.object``)."""
    func = call.func
    return isinstance(func, ast.Name | ast.Attribute) and _trailing_name(func) == "patch"


def _is_patch_object_call(call: ast.Call) -> bool:
    """True when *call* is ``patch.object(...)`` / ``mock.patch.object(...)``."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "object"
        and _trailing_name(func.value) == "patch"
    )


def _string_value(node: ast.expr | None) -> str | None:
    """Return the ``str`` constant *node* holds, or ``None`` when it is not a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    """Return the value expression of keyword *name* on *call*, or ``None``."""
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_truthy(node: ast.expr | None) -> bool:
    """True when *node* is a literal that is not falsy — used for ``autospec=``."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    return node is not None  # a non-literal autospec (variable) is treated as set


def _call_supplies_async_double(call: ast.Call, *, new_positional: ast.expr | None) -> bool | None:
    """Decide whether *call* already supplies an acceptable double for an async target.

    Returns:
        ``True``  — an async-aware signal is present (``autospec=True``,
                    ``new_callable=AsyncMock``, ``new=AsyncMock(...)``): SUPPRESS.
        ``False`` — the double is a KNOWN sync mock (default ``MagicMock``, or an
                    explicit ``MagicMock``/``Mock``): this is the finding.
        ``None``  — ``new``/``new_callable`` names something the checker cannot
                    classify (a custom factory): stay silent, conservative.

    Args:
        call: The ``patch``/``patch.object`` call.
        new_positional: The positional ``new`` argument, if the call form has one.
    """
    if _is_truthy(_keyword(call, "autospec")):
        return True

    new_callable = _keyword(call, "new_callable")
    new = _keyword(call, "new") or new_positional

    for value in (new_callable, new):
        if value is not None and _trailing_name(value) == ASYNC_MOCK_NAME:
            return True
    for value in (new_callable, new):
        if value is not None and _trailing_name(value) in SYNC_MOCK_NAMES:
            return False

    if new_callable is None and new is None:
        return False  # patch's default double is a MagicMock — not awaitable
    return None  # a custom, unclassifiable factory: do not flag


def _module_suffixes(path: Path) -> list[str]:
    """Every dotted-module suffix a file could be imported as.

    ``src/pkg/sub/mod.py`` -> ``["mod", "sub.mod", "pkg.sub.mod", "src.pkg.sub.mod"]``;
    an ``__init__.py`` names its PACKAGE (the filename is dropped).

    Args:
        path: The ``.py`` file.
    """
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts))] if parts else []


def build_module_index(trees: dict[Path, ast.Module]) -> dict[str, ast.Module]:
    """Map each UNAMBIGUOUS dotted-module suffix to its parsed module.

    A suffix shared by two files is dropped — an ambiguous target must resolve to
    UNKNOWN (silent), never to the wrong file.

    Args:
        trees: Parsed modules keyed by path.
    """
    owners: dict[str, set[Path]] = {}
    for path in trees:
        for suffix in _module_suffixes(path):
            owners.setdefault(suffix, set()).add(path)
    return {suffix: trees[next(iter(paths))] for suffix, paths in owners.items() if len(paths) == 1}


def _find_def(body: list[ast.stmt], name: str) -> ast.stmt | None:
    """Return the top-level def/class named *name* in *body*, or ``None``."""
    for node in body:
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == name
        ):
            return node
    return None


def _lookup_in_module(module: ast.Module, remainder: list[str]) -> bool | None:
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
        node = _find_def(module.body, remainder[0])
        if isinstance(node, ast.AsyncFunctionDef):
            return True
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            return False
        return None
    if len(remainder) == 2:
        cls = _find_def(module.body, remainder[0])
        if not isinstance(cls, ast.ClassDef):
            return None
        method = _find_def(cls.body, remainder[1])
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
            return _lookup_in_module(module, parts[split:])
    return None


def _import_map(module: ast.Module) -> dict[str, str]:
    """Map a locally-bound name to the module it was imported FROM.

    Only ``from pkg.mod import Name [as local]`` is tracked — that is what a
    ``patch.object(Name, ...)`` object argument needs to resolve.

    Args:
        module: The parsed test module.
    """
    bound: dict[str, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def _is_test_file(path: Path) -> bool:
    """True when *path* is a test module (name or a ``tests`` path segment)."""
    return path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts


def _check_patch(
    call: ast.Call, index: dict[str, ast.Module], imports: dict[str, str]
) -> str | None:
    """Return the target string when *call* patches an async def with a sync double.

    Args:
        call: A ``patch``/``patch.object`` call.
        index: Module index for dotted-target resolution.
        imports: The test file's ``from X import Y`` map for ``patch.object`` objects.

    Returns:
        The resolved dotted target when it is a finding, else ``None``.
    """
    if _is_patch_call(call):
        target = (
            _string_value(call.args[0]) if call.args else _string_value(_keyword(call, "target"))
        )
        new_positional = call.args[1] if len(call.args) > 1 else None
    elif _is_patch_object_call(call):
        target = _patch_object_target(call, imports)
        new_positional = call.args[2] if len(call.args) > 2 else None
    else:
        return None

    if target is None or resolve_target(target, index) is not True:
        return None
    if _call_supplies_async_double(call, new_positional=new_positional) is False:
        return target
    return None


def _patch_object_target(call: ast.Call, imports: dict[str, str]) -> str | None:
    """Build a dotted target for ``patch.object(Obj, "attr")`` when *Obj* is a
    simple imported name — otherwise ``None`` (silent).

    Args:
        call: The ``patch.object`` call.
        imports: ``from X import Y`` map of the enclosing test file.
    """
    if len(call.args) < 2:
        return None
    attr = _string_value(call.args[1])
    if attr is None:
        return None
    obj = call.args[0]
    if isinstance(obj, ast.Name) and obj.id in imports:
        return f"{imports[obj.id]}.{attr}"
    return None


def check_tree(tree: ast.Module, path: str, index: dict[str, ast.Module]) -> list[Finding]:
    """Return findings for one parsed test module.

    Args:
        tree: The parsed module.
        path: Its display path.
        index: Module index for target resolution.
    """
    imports = _import_map(tree)
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _check_patch(node, index, imports)
        if target is not None:
            message = (
                f"{path}:{node.lineno}: [async-mock] {target} — async def patched with a "
                "sync mock; use AsyncMock, autospec=True, or new_callable=AsyncMock"
            )
            findings.append(Finding(message))
    return findings


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    """Return every finding across the parsed test modules.

    Args:
        trees: Parsed modules keyed by path (source + tests).
        index: Module index built from the same trees.
    """
    findings: list[Finding] = []
    for path, tree in trees.items():
        if _is_test_file(path):
            findings.extend(check_tree(tree, path.as_posix(), index))
    return findings


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

    trees: dict[Path, ast.Module] = {}
    unparsable: list[str] = []
    for file in iter_py_files(args.roots):
        try:
            trees[file] = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            unparsable.append(f"{file}: {exc}")

    if unparsable:
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
        return 2

    index = build_module_index(trees)
    findings = find_violations(trees, index)
    for finding in findings:
        print(finding)

    if findings and not args.exit_zero:
        print(
            f"\n{len(findings)} finding(s) — a MagicMock on an async target is a green "
            "test over a broken await.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
