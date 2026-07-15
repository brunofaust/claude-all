#!/usr/bin/env python3
"""Checker: enforce the Pydantic data-contract rules — no untyped dict carries a contract.

WHY
---
A ``dict`` carrying a contract lets a missing, blank, or renamed key slip through
silently. ``TypedDict`` does NOT fix this: it is a *static* annotation that
validates nothing at runtime, so ``cast(plan_row_dtype, dict(row))`` is a no-op
that only pretends to type — mypy stays green while the payload lies. Pydantic
validates at construction, at the boundary, at the point of failure.

The bug class is NOT the ``.get(k, default)`` spelling — that is a symptom. It is
a **default on a field that is required**. Once a payload has a real model, the
required-vs-optional decision is forced and the masking default becomes
removable. So these rules push payloads into models, then pin the contract:

  no-typeddict      TypedDict validates nothing at runtime — use a BaseModel.
  no-cast           `cast()` asserts a type instead of proving one.
  extra-forbid      Every model forbids unknown fields. No exceptions: a schema
                    change must be followed by a code change, and a query names
                    its columns (`SELECT a, b`), so no unmodelled key can arrive.
  masking-default   Optional ⇒ `T | None = None`. Required ⇒ no default. Any
                    other default (`""`, `0`, `[]`, `"task"`) is one more
                    spelling of "absent" and hides a missing key.
  opaque-annotation `Any` — and any dict/Mapping whose VALUE is `Any` — is the
                    untyped dict one level down. The *container* is fine when its
                    value type is concrete: `Mapping[str, str]` and
                    `dict[VectorKey, SearchResult]` (runtime keys, typed values)
                    both stay legal.
  splat             `f(**model.model_dump())` unpacks the model back into an
                    untyped dict and skips per-field checking at the one site
                    that pins the contract. Logging is the only exemption
                    (`log.bind(**ctx)` — arbitrary context by design).
  select-star       `SELECT *` re-introduces an unmodelled shape the code never
                    declared, which is exactly what `extra-forbid` assumes away.
  secret-repr       A credential/PII field without `repr=False` leaks the value
                    into any log line that reprs the model.

CONTRACT
--------
Prints one ``path: [rule] symbol — message`` finding per violation to stdout,
keyed by rule + enclosing symbol + field name and NEVER by line number, so an
unrelated edit does not churn the baseline. Composes with ``baseline_gate.py``.
Exits 0 when it ran (regardless of finding count); non-zero only on bad args.

USAGE
-----
    python checkers/pydantic_contract.py src/
    python checkers/pydantic_contract.py --select no-cast,extra-forbid src/
    baseline_gate.py --baseline pydantic_baseline.txt -- \\
        python checkers/pydantic_contract.py src/

PARSER NOTE
-----------
Uses the running interpreter's ``ast``; a file that will not parse is skipped
(fail-open) rather than crashing the gate — a sibling syntax gate owns those.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

__all__ = ["RULES", "Finding", "check_tree", "find_violations", "main"]

RULES: tuple[str, ...] = (
    "no-typeddict",
    "no-cast",
    "extra-forbid",
    "masking-default",
    "opaque-annotation",
    "splat",
    "select-star",
    "secret-repr",
)

#: Base classes that make a class a validated model.
MODEL_BASES = frozenset({"BaseModel", "BaseSettings"})

#: Mapping-ish containers that are opaque when bare or when their value is `Any`.
MAPPING_NAMES = frozenset({"dict", "Dict", "Mapping", "MutableMapping", "DefaultDict"})

#: Receivers whose `**kwargs` splat is arbitrary context by design.
LOG_RECEIVERS = frozenset({"log", "logger", "_log", "LOG", "LOGGER", "structlog"})

#: Field-name fragments that denote a credential or PII value.
SECRET_HINTS = ("password", "secret", "token", "api_key", "apikey", "credential", "private_key")

#: Rules that can legitimately occur MANY times inside one symbol. Their keys get a
#: per-symbol ordinal, so a second occurrence is a NEW finding instead of collapsing
#: into the first one's baseline entry (which would let a regression pass the gate).
#: Every other rule is at most once per symbol/field and needs no discriminator.
REPEATABLE = frozenset({"no-cast", "splat", "select-star"})

SELECT_STAR = re.compile(r"\bselect\s+\*", re.IGNORECASE)


class Finding(str):
    """A finding key. Subclasses ``str`` so callers can just print it."""

    __slots__ = ()


def _name_of(node: ast.expr | None, *, root: bool = False) -> str:
    """Resolve a bare name out of *node*.

    Args:
        node: The expression to name, or ``None``.
        root: When True, walk to the LEFTMOST name of an attribute chain
            (``log.bind`` -> ``log``) — used to identify a call's receiver.
            When False (default), take the TRAILING name (``typing.Any`` ->
            ``Any``) — used to identify an annotation or callee.

    Returns:
        The resolved name, or ``""`` when *node* carries none.
    """
    if root:
        while isinstance(node, ast.Attribute):
            node = node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_any(node: ast.expr | None) -> bool:
    """Return whether *node* is the ``Any`` annotation.

    Args:
        node: The annotation AST node, or ``None``.
    """
    return _name_of(node) == "Any"


def opaque_reason(node: ast.expr | None) -> str:
    """Return why *node* is an opaque annotation, or ``""`` when it is concrete.

    Opaque means the annotation carries no usable type at its value position:
    bare ``Any``, a bare mapping container, or a mapping whose VALUE type is
    ``Any``. A mapping with a concrete value type is NOT opaque — the container
    was never the problem.

    Args:
        node: The annotation AST node, or ``None`` when unannotated.

    Returns:
        A short reason string, or ``""`` when the annotation is acceptable.
    """
    if node is None:
        return ""
    if _is_any(node):
        return "Any"
    if isinstance(node, ast.Name | ast.Attribute) and _name_of(node) in MAPPING_NAMES:
        return f"bare {_name_of(node)}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return opaque_reason(node.left) or opaque_reason(node.right)
    if isinstance(node, ast.Subscript):
        base = _name_of(node.value)
        if base not in MAPPING_NAMES:
            return ""
        elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if elts and _is_any(elts[-1]):  # value position is the LAST arg
            return f"{base}[..., Any]"
    return ""


def _field_call_default(node: ast.expr) -> tuple[bool, str]:
    """Inspect a ``Field(...)`` call for a default.

    Args:
        node: The assigned value of a model field.

    Returns:
        ``(has_default, description)`` — ``has_default`` is False for a bare
        ``Field(alias=...)`` (still a required field) and for
        ``Field(default=None)`` (an explicitly optional field).
    """
    for kw in node.keywords if isinstance(node, ast.Call) else []:
        if kw.arg == "default_factory":
            return True, "Field(default_factory=...)"
        if kw.arg == "default" and not (
            isinstance(kw.value, ast.Constant) and kw.value.value is None
        ):
            return True, "Field(default=...)"
    if isinstance(node, ast.Call) and node.args:  # Field(<positional default>)
        return True, "Field(<positional default>)"
    return False, ""


def _has_repr_false(node: ast.expr | None) -> bool:
    """Return whether the assigned value is a ``Field(..., repr=False)`` call.

    Args:
        node: The assigned value of a model field, or ``None``.
    """
    if not isinstance(node, ast.Call):
        return False
    return any(
        kw.arg == "repr" and isinstance(kw.value, ast.Constant) and kw.value.value is False
        for kw in node.keywords
    )


def _config_forbids_extra(body: list[ast.stmt]) -> bool:
    """Return whether the class body pins ``extra="forbid"``.

    Recognises ``model_config = {...}``, ``model_config = ConfigDict(...)`` and
    the legacy ``class Config: extra = "forbid"`` form.

    Args:
        body: The statements of a class body.
    """
    for stmt in body:
        if (
            isinstance(stmt, ast.ClassDef)
            and stmt.name == "Config"
            and _config_forbids_extra(stmt.body)
        ):
            return True  # legacy `class Config: extra = "forbid"` nested form
        targets = (
            stmt.targets
            if isinstance(stmt, ast.Assign)
            else [stmt.target]
            if isinstance(stmt, ast.AnnAssign)
            else []
        )
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        value = stmt.value if isinstance(stmt, ast.Assign | ast.AnnAssign) else None
        if names == {"extra"} and isinstance(value, ast.Constant) and value.value == "forbid":
            return True  # legacy `class Config: extra = "forbid"`
        if "model_config" not in names or value is None:
            continue
        if isinstance(value, ast.Dict):
            pairs = zip(value.keys, value.values, strict=False)
            if any(
                isinstance(k, ast.Constant)
                and k.value == "extra"
                and isinstance(v, ast.Constant)
                and v.value == "forbid"
                for k, v in pairs
            ):
                return True
        if isinstance(value, ast.Call) and any(
            kw.arg == "extra" and isinstance(kw.value, ast.Constant) and kw.value.value == "forbid"
            for kw in value.keywords
        ):
            return True
    return False


def _is_model(node: ast.ClassDef) -> bool:
    """Return whether *node* subclasses a validated pydantic model base.

    Args:
        node: The class definition.
    """
    return any(_name_of(b) in MODEL_BASES for b in node.bases)


def _is_typeddict(node: ast.ClassDef) -> bool:
    """Return whether *node* subclasses ``TypedDict``.

    Args:
        node: The class definition.
    """
    return any(_name_of(b) == "TypedDict" for b in node.bases)


class _Visitor(ast.NodeVisitor):
    """Walks a module collecting contract violations with stable, line-free keys."""

    def __init__(self, path: str, select: frozenset[str]) -> None:
        self.path = path
        self.select = select
        self.findings: list[Finding] = []
        self._stack: list[str] = []
        self._ordinals: dict[tuple[str, str], int] = {}

    def _add(self, rule: str, symbol: str, message: str) -> None:
        """Record a finding under a stable, line-independent key.

        Args:
            rule: The rule name; ignored when not in ``--select``.
            symbol: The enclosing qualname (plus field/param where relevant).
            message: The human-facing explanation.
        """
        if rule not in self.select:
            return
        if rule in REPEATABLE:
            slot = (rule, symbol)
            ordinal = self._ordinals.get(slot, 0)
            self._ordinals[slot] = ordinal + 1
            symbol = f"{symbol}#{ordinal}"
        self.findings.append(Finding(f"{self.path}: [{rule}] {symbol} — {message}"))

    def _qual(self, extra: str = "") -> str:
        """Return the dotted name of the enclosing def/class stack.

        Args:
            extra: An optional trailing component to append.
        """
        parts = [*self._stack, extra] if extra else self._stack
        return ".".join(parts) or "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Check a class for TypedDict use and, when it is a model, its field contract.

        Args:
            node: The class definition.
        """
        self._stack.append(node.name)
        if _is_typeddict(node):
            self._add(
                "no-typeddict",
                self._qual(),
                "TypedDict validates nothing at runtime — use a pydantic BaseModel",
            )
        if _is_model(node):
            if not _config_forbids_extra(node.body):
                self._add(
                    "extra-forbid",
                    self._qual(),
                    'model must set model_config = {"extra": "forbid"} — an unknown key is a '
                    "renamed/typo'd field, not something to ignore",
                )
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    self._check_field(stmt.target.id, stmt)
        self.generic_visit(node)
        self._stack.pop()

    def _check_field(self, name: str, stmt: ast.AnnAssign) -> None:
        """Check one model field for an opaque type, a masking default, or a bare secret.

        Args:
            name: The field name.
            stmt: The annotated assignment declaring the field.
        """
        if name == "model_config":
            return
        symbol = f"{self._qual()}.{name}"

        if reason := opaque_reason(stmt.annotation):
            self._add(
                "opaque-annotation",
                symbol,
                f"model field is opaque ({reason}) — that is the untyped dict one level "
                "down; use a concrete value type or Sequence[Model]",
            )

        optional = isinstance(stmt.annotation, ast.BinOp) and any(
            isinstance(n, ast.Constant) and n.value is None
            for n in ast.walk(stmt.annotation)
            if isinstance(n, ast.Constant)
        )
        if stmt.value is not None:
            defaults_to_none = isinstance(stmt.value, ast.Constant) and stmt.value.value is None
            has_field_default, desc = _field_call_default(stmt.value)
            if not defaults_to_none and (has_field_default or not isinstance(stmt.value, ast.Call)):
                what = desc or ast.unparse(stmt.value)
                hint = (
                    "optional ⇒ `| None = None`"
                    if not optional
                    else "this field is already optional — default to None, not a value"
                )
                self._add(
                    "masking-default",
                    symbol,
                    f"default {what} masks an absent key — required ⇒ no default, {hint}",
                )

        if any(h in name.lower() for h in SECRET_HINTS) and not _has_repr_false(stmt.value):
            self._add(
                "secret-repr",
                symbol,
                "credential/PII field must use Field(repr=False) — a model repr in a log "
                "line is a token leak; verify with repr(Model(...))",
            )

    def _visit_fn(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Check a function signature for opaque parameter and return annotations.

        Args:
            fn: The function or coroutine definition.
        """
        self._stack.append(fn.name)
        args = fn.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if reason := opaque_reason(arg.annotation):
                self._add(
                    "opaque-annotation",
                    f"{self._qual()}({arg.arg})",
                    f"parameter is opaque ({reason}) — pass a model or a concrete type",
                )
        if reason := opaque_reason(fn.returns):
            self._add(
                "opaque-annotation",
                self._qual(),
                f"return is opaque ({reason}) — return a model, not an untyped mapping",
            )
        self.generic_visit(fn)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check a ``def`` signature for opaque annotations.

        Args:
            node: The function definition.
        """
        self._visit_fn(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check an ``async def`` signature for opaque annotations.

        Args:
            node: The coroutine definition.
        """
        self._visit_fn(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Check a call for ``cast()`` and for non-logging ``**`` splatting.

        Args:
            node: The call expression.
        """
        if _name_of(node.func) == "cast":
            self._add(
                "no-cast",
                self._qual(),
                "cast() asserts a type instead of proving one — cast(dtype, dict(row)) is a "
                "no-op; parse with Model.model_validate(...) instead",
            )
        if any(kw.arg is None for kw in node.keywords):
            receiver = _name_of(node.func, root=True)
            is_log = receiver in LOG_RECEIVERS or _name_of(node.func) == "bind"
            if not is_log:
                self._add(
                    "splat",
                    f"{self._qual()} -> {ast.unparse(node.func)}",
                    "** splatting unpacks a model back into an untyped dict and skips "
                    "per-field checking — name the fields (logging is the only exemption)",
                )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Check a string literal for ``SELECT *``.

        Args:
            node: The constant expression.
        """
        if isinstance(node.value, str) and SELECT_STAR.search(node.value):
            self._add(
                "select-star",
                self._qual(),
                "SELECT * yields an unmodelled shape — name the columns so the row's shape "
                'is one the code declared (this is what extra="forbid" relies on)',
            )


def check_tree(tree: ast.AST, path: str, select: frozenset[str]) -> list[Finding]:
    """Collect every violation in an already-parsed module.

    Args:
        tree: The parsed module.
        path: Path string used to key findings.
        select: The rule names to report.

    Returns:
        One finding per violation, in source order.
    """
    visitor = _Visitor(path, select)
    visitor.visit(tree)
    return visitor.findings


def find_violations(path: Path, select: frozenset[str]) -> list[Finding]:
    """Parse *path* and return its findings (fail-open on unparsable files).

    Args:
        path: The Python file to scan.
        select: The rule names to report.

    Returns:
        One finding per violation, in source order.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return []
    return check_tree(tree, path.as_posix(), select)


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
        0 when the check ran — findings go to stdout for ``baseline_gate.py``.
    """
    parser = argparse.ArgumentParser(
        description="Enforce the Pydantic data-contract rules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("roots", nargs="+", type=Path, help="files or dirs to scan")
    parser.add_argument(
        "--select",
        default=",".join(RULES),
        help=f"comma-separated rules to enforce (default: all). Available: {', '.join(RULES)}",
    )
    args = parser.parse_args(argv)

    select = frozenset(r.strip() for r in args.select.split(",") if r.strip())
    if unknown := select - set(RULES):
        parser.error(f"unknown rule(s): {', '.join(sorted(unknown))}")

    for file in iter_py_files(args.roots):
        for finding in find_violations(file, select):
            print(finding)
    return 0


if __name__ == "__main__":
    sys.exit(main())
