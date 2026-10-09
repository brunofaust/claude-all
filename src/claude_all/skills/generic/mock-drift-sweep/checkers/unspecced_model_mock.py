#!/usr/bin/env python3
"""Checker: an unspecced mock double must not stand in for a Pydantic model class. WHY --- When
every model sets ``extra="forbid"``, a REAL model construction already fails loudly on a
renamed/typo'd field — Pydantic drift is largely self-detecting.
"""

import ast
import sys
from pathlib import Path

from mock_drift_common import (
    collect_patch_call_findings,
    find_def,
    is_truthy,
    keyword,
    make_patch_finding_checker,
    new_positional_arg,
    run_regression_gate_cli,
    trailing_name,
)

__all__ = ["Finding", "find_violations", "main", "resolve_is_model_class"]

BASELINE_FILE = Path(__file__).parent / "unspecced_model_mock_baseline.json"

#: Mock-family constructors that are never awaited/validated on their own —
#: standing in for a model with no ``spec`` accepts any attribute silently.
MOCK_FAMILY_NAMES = frozenset(
    {"MagicMock", "Mock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock"}
)


class Finding(str):
    """A finding line."""

    __slots__ = ()


def is_pydantic_model_class(cls: ast.ClassDef) -> bool:
    """True when *cls* has ``BaseModel`` as a DIRECT base (literal name match).

    Args:
        cls: The class definition to check.
    """
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "BaseModel":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
            return True
    return False


def resolve_is_model_class(dotted: str, index: dict[str, ast.Module]) -> bool | None:
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module = index.get(".".join(parts[:split]))
        if module is None:
            continue
        remainder = parts[split:]
        if len(remainder) != 1:
            return None  # only a direct Module.ClassName reference is in scope
        node = find_def(module.body, remainder[0])
        if isinstance(node, ast.ClassDef):
            return is_pydantic_model_class(node)
        return False
    return None


def call_supplies_spec(call: ast.Call, *, new_positional: ast.expr | None) -> bool | None:
    if is_truthy(keyword(call, "autospec")):
        return True

    new_callable = keyword(call, "new_callable")
    new = keyword(call, "new") or new_positional

    for value in (new_callable, new):
        if value is None:
            continue
        name = trailing_name(value)
        if name == "create_autospec":
            return True
        if name in MOCK_FAMILY_NAMES:
            # True (suppress) when the double itself carries spec=/spec_set=;
            # False (the finding) for an unspecced instantiation, or a bare
            # class reference (e.g. `new_callable=MagicMock`).
            return isinstance(value, ast.Call) and (
                is_truthy(keyword(value, "spec")) or is_truthy(keyword(value, "spec_set"))
            )

    if new_callable is None and new is None:
        return False  # patch's default double is an unspecced MagicMock
    return None  # a custom, unclassifiable factory: do not flag


def is_unspecced_model_finding(
    target: str, index: dict[str, ast.Module], call: ast.Call
) -> bool | None:
    if resolve_is_model_class(target, index) is not True:
        return None
    return call_supplies_spec(call, new_positional=new_positional_arg(call)) is False


check_patch = make_patch_finding_checker(is_unspecced_model_finding)


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    findings = [
        Finding(
            f"{path.as_posix()}:{lineno}: [unspecced-model-mock] {target} — a Pydantic model class "
            "patched with an unspecced mock; use spec=/autospec=True/create_autospec()"
        )
        for path, lineno, target in collect_patch_call_findings(trees, index, check_patch)
    ]
    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — delegates to the shared regression-gate harness. Args: argv: Optional
    argument vector (defaults to ``sys.argv``).
    """
    return run_regression_gate_cli(
        argv,
        description="Flag an unspecced mock standing in for a patched Pydantic model class.",
        baseline_file=BASELINE_FILE,
        find_violations=find_violations,
    )


if __name__ == "__main__":
    sys.exit(main())
