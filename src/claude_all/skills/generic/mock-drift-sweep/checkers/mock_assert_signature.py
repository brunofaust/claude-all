#!/usr/bin/env python3
"""Checker: a call-assertion's arguments must fit the patched target's real signature.

WHY
---
``mock.assert_called_with(a, b, c)`` / ``assert_awaited_with`` /
``assert_called_once_with`` / ``assert_any_call`` compare the recorded call
against whatever arguments you assert — they do NOT check those arguments
against the REAL function's signature, because by the time the assertion
runs the real function has already been replaced by the mock. So when a
signature changes (a parameter renamed, removed, or a positional arg
dropped) and nobody updates the assertion, the test keeps passing: it is only
checking that the code under test called the mock with args X, never that X
is a call the real function could have accepted.

WHAT IT FLAGS
-------------
A ``mock.assert_called_with(...)``-family call whose mock variable is bound
(in the SAME function, via one of exactly two forms — see BINDING below) to a
``patch``/``patch.object`` target that resolves to a real function/method
definition in the scanned source tree, where the asserted call:

- passes MORE positional arguments than the signature accepts, or
- passes a keyword argument that is not one of the signature's parameter
  names.

BINDING — narrow on purpose
----------------------------
Only two forms tie a mock variable to a specific resolved target:

    with patch("dotted.target") as m: ...      m.assert_called_with(...)
    m = patch("dotted.target").start(); ...    m.assert_called_with(...)

The ``@patch("dotted.target")`` DECORATOR form is deliberately NOT handled —
bottom-up decorator-to-parameter ordering plus pytest fixture argument offsets
make binding the right decorator to the right assertion error-prone, and a
wrong binding here would produce a false positive. If a bound variable is
reassigned anywhere else in the function, or bound more than once, tracking
for that variable is DROPPED (silent) rather than risk a stale binding.

RESOLUTION IS CONSERVATIVE — SILENCE OVER A FALSE POSITIVE
------------------------------------------------------------
Stays silent when:

- the mock variable cannot be tied to exactly one resolved patch target
  (decorator form, ``with patch(...):`` with no ``as``, reassignment,
  multiple bindings of the same name);
- the target does not resolve to a ``def``/``async def`` in the tree (same
  ``Module.name`` / ``Module.Class.method`` resolution as the sibling
  checkers — nothing deeper, nothing inherited: a class with any base other
  than bare ``object`` is skipped because the method could be inherited);
- the target's signature carries ``*args`` or ``**kwargs`` — any positional
  or keyword count is potentially valid;
- the target carries any decorator other than ``staticmethod``,
  ``classmethod``, or ``overload`` — an unknown decorator (e.g. a custom
  ``@retry`` wrapper) can change the accepted call shape;
- the asserted call itself contains a starred positional (``*args_var``) or a
  double-starred keyword (``**kwargs_var``) spread — the real arg count/names
  aren't visible in the AST.

A false negative (a missed arity/keyword drift) is acceptable; a false
positive is not.

Because resolution needs the *source*, pass BOTH source and tests:

    python checkers/mock_assert_signature.py tests src/myapp

CONTRACT
--------
Prints one ``path:line: [assert-signature] target — message`` finding per
violation. This rule is REGRESSION-ONLY (see the module-level baseline
support below) — it is expected to find real drift on a codebase with a large
mocked-call surface, so it ships with a baseline file and only fails on NEW
findings (a stale baseline entry — one that no longer reproduces — also
fails, so the count only ratchets down):

    python checkers/mock_assert_signature.py tests src/myapp --baseline
    python checkers/mock_assert_signature.py tests src/myapp --check
"""

import ast
import sys
from pathlib import Path

from mock_drift_common import (
    find_def,
    import_map,
    is_patch_call,
    is_patch_object_call,
    is_test_file,
    resolve_call_target,
    run_regression_gate_cli,
    trailing_name,
)

__all__ = ["Finding", "find_violations", "main"]

BASELINE_FILE = Path(__file__).parent / "mock_assert_signature_baseline.json"

#: The assertion methods this rule inspects — every ``mock`` call-shape
#: assertion that compares against a recorded call's positional/keyword args.
ASSERT_METHODS = frozenset(
    {
        "assert_called_with",
        "assert_awaited_with",
        "assert_called_once_with",
        "assert_awaited_once_with",
        "assert_any_call",
    }
)

#: Decorators that do NOT change a callable's accepted argument shape from
#: the caller's perspective. Any other decorator is unknown territory — skip.
TRANSPARENT_DECORATORS = frozenset({"staticmethod", "classmethod", "overload"})


class Finding(str):
    """A finding line. Subclasses ``str`` so callers can just print it."""

    __slots__ = ()


def resolve_def_node(
    dotted: str, index: dict[str, ast.Module]
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool] | None:
    """Resolve a dotted patch target to its real ``def``/``async def`` node.

    Args:
        dotted: The patch target, e.g. ``"pkg.mod.func"`` or ``"pkg.mod.Cls.method"``.
        index: Dotted-suffix -> module, from :func:`mock_drift_common.build_module_index`.

    Returns:
        ``(def_node, is_method)`` when confidently resolved to a plain
        function/method definition (a class with only trivial bases), else
        ``None`` — unresolvable, a class-with-inheritance, or deeper than
        ``Module.Class.method``.
    """
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module = index.get(".".join(parts[:split]))
        if module is None:
            continue
        remainder = parts[split:]
        if len(remainder) == 1:
            node = find_def(module.body, remainder[0])
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                return node, False
            return None
        if len(remainder) == 2:
            cls = find_def(module.body, remainder[0])
            if not isinstance(cls, ast.ClassDef):
                return None
            if cls.bases and not all(
                isinstance(b, ast.Name) and b.id == "object" for b in cls.bases
            ):
                return None  # a method could be inherited from an unseen base
            method = find_def(cls.body, remainder[1])
            if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
                return method, True
            return None
        return None
    return None


def signature_shape(
    func_def: ast.FunctionDef | ast.AsyncFunctionDef, *, is_method: bool
) -> tuple[int, set[str]] | None:
    """Return ``(max_positional, valid_keyword_names)``, or ``None`` to skip this target.

    Args:
        func_def: The resolved def/async-def node.
        is_method: Whether *func_def* is a method (drop the leading
            ``self``/``cls`` from the positional count unless it is a
            ``@staticmethod``).

    Returns:
        ``None`` when the signature has ``*args``/``**kwargs`` or an
        untrusted decorator — the caller must skip (silent).
    """
    args = func_def.args
    if args.vararg is not None or args.kwarg is not None:
        return None

    decorator_names = {trailing_name(dec) for dec in func_def.decorator_list}
    if decorator_names - TRANSPARENT_DECORATORS:
        return None

    positional = [*args.posonlyargs, *args.args]
    if is_method and "staticmethod" not in decorator_names and positional:
        positional = positional[1:]  # drop self/cls

    max_positional = len(positional)
    valid_keywords = {a.arg for a in args.args} | {a.arg for a in args.kwonlyargs}
    return max_positional, valid_keywords


def call_shape(call: ast.Call) -> tuple[int, list[str]] | None:
    """Return ``(positional_count, keyword_names)`` for an assertion call, or ``None`` to skip.

    Args:
        call: The ``assert_*_with``/``assert_any_call`` call.

    Returns:
        ``None`` when the call spreads a starred positional or a
        double-starred keyword — the real shape isn't visible in the AST.
    """
    if any(isinstance(a, ast.Starred) for a in call.args):
        return None
    if any(kw.arg is None for kw in call.keywords):
        return None
    return len(call.args), [kw.arg for kw in call.keywords if kw.arg is not None]


def check_assertion(call: ast.Call, target: str, index: dict[str, ast.Module]) -> str | None:
    """Return a finding message when *call*'s args don't fit *target*'s real signature.

    Args:
        call: The ``assert_*_with``/``assert_any_call`` call.
        target: The dotted patch target the mock variable is bound to.
        index: Module index for target resolution.
    """
    resolved = resolve_def_node(target, index)
    if resolved is None:
        return None
    func_def, is_method = resolved
    shape = signature_shape(func_def, is_method=is_method)
    if shape is None:
        return None
    max_positional, valid_keywords = shape

    asserted = call_shape(call)
    if asserted is None:
        return None
    positional_count, keyword_names = asserted

    if positional_count > max_positional:
        return (
            f"{target} — asserted {positional_count} positional arg(s) but the real signature "
            f"accepts at most {max_positional}"
        )
    for name in keyword_names:
        if name not in valid_keywords:
            return f"{target} — asserted keyword {name!r} is not a parameter of the real signature"
    return None


def bound_target(call: ast.Call, imports: dict[str, str]) -> str | None:
    """Return the dotted target when *call* is a resolvable ``patch``/``patch.object`` call.

    Args:
        call: A ``patch``/``patch.object`` call.
        imports: The test file's ``from X import Y`` map for ``patch.object`` objects.
    """
    return resolve_call_target(call, imports)


class BindingTracker:
    """Tracks ``mock variable name -> resolved patch target`` for one function body.

    A name bound more than once, or reassigned to anything else, DROPS
    tracking for that name rather than risk a stale binding (conservative —
    see the module docstring's BINDING section).
    """

    __slots__ = ("bindings", "dropped")

    def __init__(self) -> None:
        """Start with no bindings and no dropped names."""
        self.bindings: dict[str, str] = {}
        self.dropped: set[str] = set()

    def drop(self, name: str) -> None:
        """Stop trusting *name* — a reassignment or a second binding occurred.

        Args:
            name: The mock variable name to stop tracking.
        """
        self.dropped.add(name)
        self.bindings.pop(name, None)

    def bind(self, name: str, target: str | None) -> None:
        """Bind *name* to *target*, or drop it if already bound/dropped.

        Args:
            name: The mock variable name.
            target: The resolved dotted patch target, or ``None`` when the
                patch call itself didn't resolve (nothing to bind).
        """
        if name in self.bindings or name in self.dropped:
            self.drop(name)
            return
        if target is not None:
            self.bindings[name] = target


def handle_with_node(
    node: ast.With | ast.AsyncWith, tracker: BindingTracker, imports: dict[str, str]
) -> None:
    """Bind ``with patch(...) as m:`` targets from one ``with``/``async with`` node.

    Args:
        node: The ``With``/``AsyncWith`` AST node.
        tracker: The enclosing function's binding tracker.
        imports: The test file's ``from X import Y`` map.
    """
    for item in node.items:
        call = item.context_expr
        if (
            isinstance(call, ast.Call)
            and (is_patch_call(call) or is_patch_object_call(call))
            and isinstance(item.optional_vars, ast.Name)
        ):
            tracker.bind(item.optional_vars.id, bound_target(call, imports))


def start_call_target(value: ast.expr) -> ast.Call | None:
    """Return the inner ``patch``/``patch.object`` call when *value* is ``patch(...).start()``.

    Args:
        value: The RHS expression of an assignment.
    """
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "start"
        and isinstance(value.func.value, ast.Call)
        and (is_patch_call(value.func.value) or is_patch_object_call(value.func.value))
    ):
        return value.func.value
    return None


def handle_assign_node(node: ast.Assign, tracker: BindingTracker, imports: dict[str, str]) -> None:
    """Bind ``m = patch(...).start()``, or drop tracking on any other reassignment.

    Args:
        node: The ``Assign`` AST node.
        tracker: The enclosing function's binding tracker.
        imports: The test file's ``from X import Y`` map.
    """
    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        start_target = start_call_target(node.value)
        if start_target is not None:
            tracker.bind(node.targets[0].id, bound_target(start_target, imports))
            return
    for target_expr in node.targets:
        if isinstance(target_expr, ast.Name) and target_expr.id in tracker.bindings:
            tracker.drop(target_expr.id)


def handle_assertion_node(
    node: ast.Call, tracker: BindingTracker, path: str, index: dict[str, ast.Module]
) -> Finding | None:
    """Return a finding when *node* is a bound assertion call whose args don't fit.

    Args:
        node: A ``Call`` AST node, checked for the assertion-method shape.
        tracker: The enclosing function's binding tracker.
        path: The enclosing file's display path.
        index: Module index for target resolution.
    """
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in ASSERT_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in tracker.bindings
    ):
        return None
    message = check_assertion(node, tracker.bindings[node.func.value.id], index)
    if message is None:
        return None
    return Finding(f"{path}:{node.lineno}: [assert-signature] {message}")


def analyze_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    path: str,
    index: dict[str, ast.Module],
    imports: dict[str, str],
) -> list[Finding]:
    """Return findings for one function/method body.

    Tracks ``with patch(...) as m:`` and ``m = patch(...).start()`` bindings
    in SOURCE ORDER; any reassignment or a second binding of the same name
    drops tracking for that name (conservative — see module docstring).

    Args:
        func: The function/method AST node to scan.
        path: Its enclosing file's display path.
        index: Module index for target resolution.
        imports: The enclosing test file's ``from X import Y`` map.
    """
    tracker = BindingTracker()
    findings: list[Finding] = []

    for node in ast.walk(func):
        if isinstance(node, ast.With | ast.AsyncWith):
            handle_with_node(node, tracker, imports)
        elif isinstance(node, ast.Assign):
            handle_assign_node(node, tracker, imports)
        elif isinstance(node, ast.Call):
            finding = handle_assertion_node(node, tracker, path, index)
            if finding is not None:
                findings.append(finding)

    return findings


def check_tree(tree: ast.Module, path: str, index: dict[str, ast.Module]) -> list[Finding]:
    """Return findings for every function/method in one parsed test module.

    Args:
        tree: The parsed module.
        path: Its display path.
        index: Module index for target resolution.
    """
    imports = import_map(tree)
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            findings.extend(analyze_function(node, path, index, imports))
    return findings


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    """Return every finding across the parsed test modules.

    Args:
        trees: Parsed modules keyed by path (source + tests).
        index: Module index built from the same trees.
    """
    findings: list[Finding] = []
    for path, tree in trees.items():
        if is_test_file(path):
            findings.extend(check_tree(tree, path.as_posix(), index))
    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — delegates to the shared regression-gate harness.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        0 ran clean · 1 gate failure (new/stale findings under ``--check``,
        or any finding without ``--check``/``--baseline``) · 2 an unparsable file.
    """
    return run_regression_gate_cli(
        argv,
        description="Flag an assert_*_with()/assert_any_call() whose args don't fit the real "
        "signature.",
        baseline_file=BASELINE_FILE,
        find_violations=find_violations,
    )


if __name__ == "__main__":
    sys.exit(main())
