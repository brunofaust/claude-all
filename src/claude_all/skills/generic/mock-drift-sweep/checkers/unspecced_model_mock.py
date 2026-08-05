#!/usr/bin/env python3
"""Checker: an unspecced mock double must not stand in for a Pydantic model class.

WHY
---
When every model sets ``extra="forbid"``, a REAL model construction already
fails loudly on a renamed/typo'd field — Pydantic drift is largely
self-detecting. The gap is exactly where a model class is replaced, via
``patch``, by an unspecced ``MagicMock``/``Mock``/``AsyncMock``: attribute
access on that double then INVENTS whatever field the test asks for, silently,
because a bare mock accepts any attribute. A field rename that would 422 a
real request sails straight through a test built on an unspecced stand-in for
the model that would have caught it.

WHAT IT FLAGS
-------------
A ``patch("dotted.path.Model")`` / ``patch.object(module, "Model")`` call
whose target resolves — in the scanned source tree — to a class directly
subclassing ``BaseModel`` (checked by LITERAL base name, ``BaseModel`` or
``pydantic.BaseModel`` — deliberately a literal-name match rather than a
resolved-inheritance check, since a project may have no single shared base
class to resolve against), where the supplied double is
``MagicMock``/``Mock``/``AsyncMock`` with none of: ``autospec=True``,
``spec=``, ``spec_set=``, or ``create_autospec(...)``.

RESOLUTION IS CONSERVATIVE — SILENCE OVER A FALSE POSITIVE
------------------------------------------------------------
Mirrors the sibling checkers' conservatism exactly:

- the patch target must resolve to a class defined directly in a scanned
  module — a ``Module.Class`` reference only (one level), not a method, not
  a deeper chain;
- the class must have ``BaseModel`` as a DIRECT base — a model-of-a-model
  (grandparent inheritance) is a false negative here, never a false positive;
- ``new``/``new_callable`` naming anything this checker cannot classify (a
  custom factory) stays silent;
- any ``spec=``/``spec_set=``/``autospec=True``/``create_autospec(...)``
  signal suppresses the finding, even when the spec argument is a variable
  this checker cannot evaluate (conservative in the SILENT direction).

A false negative (a missed unspecced model double) is acceptable; a false
positive is not.

Because resolution needs the *source*, pass BOTH source and tests:

    python checkers/unspecced_model_mock.py tests src/myapp

CONTRACT
--------
Prints one ``path:line: [unspecced-model-mock] target — message`` finding per
violation. This rule is REGRESSION-ONLY — a bare Pydantic-model double is the
NOISIEST rule in this family by design (any codebase with hundreds of
``BaseModel`` subclasses will find real hits immediately), so it ships with a
baseline and only fails on NEW findings (a stale baseline entry also fails,
ratcheting the count toward zero):

    python checkers/unspecced_model_mock.py tests src/myapp --baseline
    python checkers/unspecced_model_mock.py tests src/myapp --check
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
    """A finding line. Subclasses ``str`` so callers can just print it."""

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
    """Resolve a dotted patch target to whether it names a direct ``BaseModel`` subclass.

    Args:
        dotted: The patch target — must be a ``Module.ClassName`` reference.
        index: Dotted-suffix -> module, from :func:`mock_drift_common.build_module_index`.

    Returns:
        ``True`` it's a BaseModel subclass · ``False`` it resolves to something
        else · ``None`` unresolvable (module not found, or a chain deeper than
        ``Module.ClassName``).
    """
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
    """Decide whether *call* already supplies a spec/autospec signal for a model target.

    Args:
        call: The ``patch``/``patch.object`` call.
        new_positional: The positional ``new`` argument, if the call form has one.

    Returns:
        ``True``  — a spec-aware signal is present (``autospec=True``,
                    ``create_autospec(...)``, ``spec=``/``spec_set=`` on the
                    double itself): SUPPRESS.
        ``False`` — the double is a KNOWN unspecced mock (default, or an
                    explicit ``MagicMock``/``Mock``/``AsyncMock`` with no
                    ``spec``/``spec_set``): this is the finding.
        ``None``  — ``new``/``new_callable`` names something this checker
                    cannot classify (a custom factory): stay silent.
    """
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
    """True when *target* is a direct ``BaseModel`` subclass patched with an unspecced double.

    Args:
        target: The resolved dotted patch target.
        index: Module index for dotted-target resolution.
        call: The original ``patch``/``patch.object`` call — inspected for
            the supplied ``new``/``new_callable`` double.
    """
    if resolve_is_model_class(target, index) is not True:
        return None
    return call_supplies_spec(call, new_positional=new_positional_arg(call)) is False


check_patch = make_patch_finding_checker(is_unspecced_model_finding)


def find_violations(trees: dict[Path, ast.Module], index: dict[str, ast.Module]) -> list[Finding]:
    """Return every finding across the parsed test modules.

    Args:
        trees: Parsed modules keyed by path (source + tests).
        index: Module index built from the same trees.
    """
    findings = [
        Finding(
            f"{path.as_posix()}:{lineno}: [unspecced-model-mock] {target} — a Pydantic model class "
            "patched with an unspecced mock; use spec=/autospec=True/create_autospec()"
        )
        for path, lineno, target in collect_patch_call_findings(trees, index, check_patch)
    ]
    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — delegates to the shared regression-gate harness.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        0 ran clean · 1 gate failure (new/stale findings under ``--check``) ·
        2 an unparsable file.
    """
    return run_regression_gate_cli(
        argv,
        description="Flag an unspecced mock standing in for a patched Pydantic model class.",
        baseline_file=BASELINE_FILE,
        find_violations=find_violations,
    )


if __name__ == "__main__":
    sys.exit(main())
