#!/usr/bin/env python3
"""Checker: a call-assertion's arguments must fit the patched target's real signature. WHY ---
``mock.assert_called_with(a, b, c)`` / ``assert_awaited_with`` / ``assert_called_once_with`` /
``assert_any_call`` compare the recorded call against whatever arguments you assert — they do
NOT check those arguments against the REAL function's signature, because by the time the
assertion runs the real function has already been replaced by the mock.
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
    """A finding line."""

    __slots__ = ()


def resolve_def_node(
    dotted: str, index: dict[str, ast.Module]
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool] | None:
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
    """Return ``(positional_count, keyword_names)`` for an assertion call, or ``None`` to skip."""
    if any(isinstance(a, ast.Starred) for a in call.args):
        return None
    if any(kw.arg is None for kw in call.keywords):
        return None
    return len(call.args), [kw.arg for kw in call.keywords if kw.arg is not None]


def check_assertion(call: ast.Call, target: str, index: dict[str, ast.Module]) -> str | None:
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
    return resolve_call_target(call, imports)


class BindingTracker:
    """Tracks ``mock variable name -> resolved patch target`` for one function body."""

    __slots__ = ("bindings", "dropped")

    def __init__(self) -> None:
        """Start with no bindings and no dropped names."""
        self.bindings: dict[str, str] = {}
        self.dropped: set[str] = set()

    def drop(self, name: str) -> None:
        self.dropped.add(name)
        self.bindings.pop(name, None)

    def bind(self, name: str, target: str | None) -> None:
        if name in self.bindings or name in self.dropped:
            self.drop(name)
            return
        if target is not None:
            self.bindings[name] = target


def handle_with_node(
    node: ast.With | ast.AsyncWith, tracker: BindingTracker, imports: dict[str, str]
) -> None:
    for item in node.items:
        call = item.context_expr
        if (
            isinstance(call, ast.Call)
            and (is_patch_call(call) or is_patch_object_call(call))
            and isinstance(item.optional_vars, ast.Name)
        ):
            tracker.bind(item.optional_vars.id, bound_target(call, imports))


def start_call_target(value: ast.expr) -> ast.Call | None:
    """Return the inner ``patch``/``patch.object`` call when *value* is ``patch(...).start()``."""
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
    imports = import_map(tree)
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            findings.extend(analyze_function(node, path, index, imports))
    return findings


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    findings: list[Finding] = []
    for path, tree in trees.items():
        if is_test_file(path):
            findings.extend(check_tree(tree, path.as_posix(), index))
    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — delegates to the shared regression-gate harness. Args: argv: Optional
    argument vector (defaults to ``sys.argv``).
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
