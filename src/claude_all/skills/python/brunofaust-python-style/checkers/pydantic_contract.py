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
  opaque-annotation `Any`/`object` at ANY nesting depth — `Sequence[Any]`,
                    `list[dict[str, Any]]` — is the untyped dict one level down.
                    The *container* is fine when subscripted with concrete types:
                    `Mapping[str, str]` and `dict[VectorKey, SearchResult]`
                    (runtime keys, typed values) both stay legal.
  dict-return       A function returning a raw dict — including a CONCRETE
                    `dict[str, str]`, and including an unannotated
                    `return {...}` — leaks a payload across a boundary. Stricter
                    than `opaque-annotation`, and return-position only.
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
Prints one ``path: [rule] symbol — message`` finding per violation to stdout and
**exits 1 when there is any finding**, so wiring it straight into prek/pre-commit
surfaces the findings and fails the commit — no baseline artifact required.

Keys are rule + enclosing symbol + field name and NEVER a line number, so an
unrelated edit does not churn a baseline; the repeatable rules carry a per-symbol
ordinal so a second occurrence is a distinct finding rather than a duplicate key.

The checker owns NO state: it writes no baseline, no JSON, no cache. If you want
the regression-only ratchet, compose it with ``regression-gates/baseline_gate.py``
and pass ``--exit-zero`` — that harness reads a non-zero exit as "the checker
crashed" and fails closed, so the flag is required there and nowhere else.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/pydantic_contract.py src/
    python checkers/pydantic_contract.py --select no-cast,extra-forbid src/

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline pydantic_baseline.txt -- \\
        python checkers/pydantic_contract.py --exit-zero src/

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
    "dict-return",
    "splat",
    "select-star",
    "secret-repr",
)

#: Base classes that make a class a validated model.
MODEL_BASES = frozenset({"BaseModel", "BaseSettings", "RootModel"})

#: Mapping-ish containers. Opaque when BARE (unsubscripted); legal when subscripted
#: with concrete types — `Mapping[str, str]` and `dict[VectorKey, SearchResult]` are
#: fine. The container was never the problem; the opaque VALUE is.
MAPPING_NAMES = frozenset({"dict", "Dict", "Mapping", "MutableMapping", "DefaultDict"})

#: Annotations that erase the shape wherever they appear, at any nesting depth.
OPAQUE_NAMES = frozenset({"Any", "object"})

#: Receivers whose `**kwargs` splat is arbitrary context by design.
LOG_RECEIVERS = frozenset({"log", "logger", "_log", "LOG", "LOGGER", "structlog", "tlog"})

#: Logging method names — `.bind(**ctx)` / `.info(**ctx)` bind arbitrary context by
#: design, so an explicit-params rule there would be noise.
LOG_ATTRS = frozenset(
    {
        "bind",
        "bind_contextvars",
        "bound_contextvars",
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "exception",
    }
)

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


def opaque_reason(node: ast.expr | None) -> str:
    """Return why *node* is an opaque annotation, or ``""`` when it is concrete.

    Opaque means the annotation carries no usable type: ``Any``/``object`` at ANY
    nesting depth, or a BARE mapping container. Recursion through every subscript
    argument is load-bearing — ``Sequence[Any]``, ``list[dict[str, Any]]`` and
    ``Mapping[str, Any] | None`` are each the untyped dict one level down, and a
    value-position-only check silently passes all three.

    A container subscripted with concrete types is NOT opaque: ``Mapping[str, str]``
    and ``dict[VectorKey, SearchResult]`` (runtime keys, typed values) stay legal.
    The container was never the problem.

    Args:
        node: The annotation AST node, or ``None`` when unannotated.

    Returns:
        A short reason string, or ``""`` when the annotation is acceptable.
    """
    if node is None:
        return ""
    if isinstance(node, ast.Name | ast.Attribute):
        name = _name_of(node)
        if name in OPAQUE_NAMES:
            return name
        return f"bare {name}" if name in MAPPING_NAMES else ""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return opaque_reason(node.left) or opaque_reason(node.right)
    if isinstance(node, ast.Subscript):
        elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        for elt in elts:
            if reason := opaque_reason(elt):
                return f"{_name_of(node.value)}[… {reason} …]"
    return ""


def _is_dict_return(node: ast.expr | None) -> bool:
    """Return whether *node* annotates a raw dict return.

    A ``dict[...] | None`` union counts — the dict arm still leaks an unmodelled
    payload. Unlike :func:`opaque_reason` this fires on a CONCRETE dict too
    (``dict[str, str]``): a payload crossing a function boundary should be a
    model, whatever its value type.

    Args:
        node: The return-annotation AST node, or ``None``.
    """
    if node is None:
        return False
    if isinstance(node, ast.Name | ast.Attribute):
        return _name_of(node) in MAPPING_NAMES
    if isinstance(node, ast.Subscript):
        return _is_dict_return(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_dict_return(node.left) or _is_dict_return(node.right)
    return False


def _returns_dict_literal(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether *fn* returns a dict literal with no return annotation.

    An unannotated ``return {...}`` leaks exactly the same unmodelled payload as
    an annotated one, while dodging every annotation-based check.

    Args:
        fn: The function or coroutine definition.
    """
    if fn.returns is not None:
        return False
    return any(isinstance(n, ast.Return) and isinstance(n.value, ast.Dict) for n in ast.walk(fn))


def _is_log_call(func: ast.expr) -> bool:
    """Return whether *func* is a logging target whose ``**`` splat is by design.

    Args:
        func: The callee expression of a call.
    """
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in LOG_ATTRS:
        return True
    return _name_of(func, root=True) in LOG_RECEIVERS


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
        # dict-return is the stricter, more specific rule for the return position;
        # check it first so a `-> dict[str, Any]` reports ONCE, not twice.
        if _is_dict_return(fn.returns):
            self._add(
                "dict-return",
                self._qual(),
                "returns a raw dict — a payload crossing a function boundary should be a "
                "model, so its fields are named, typed, required-vs-optional, and "
                "validated at construction",
            )
        elif _returns_dict_literal(fn):
            self._add(
                "dict-return",
                self._qual(),
                "returns a dict literal with no return annotation — model it; an "
                "unannotated dict dodges every annotation-based check",
            )
        elif reason := opaque_reason(fn.returns):
            self._add(
                "opaque-annotation",
                self._qual(),
                f"return is opaque ({reason}) — return a model, not an untyped shape",
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
        if any(kw.arg is None for kw in node.keywords) and not _is_log_call(node.func):
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
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="print findings but always exit 0 — ONLY for composing behind "
        "baseline_gate.py, whose contract reads a non-zero exit as 'the checker "
        "itself crashed' and fails closed",
    )
    args = parser.parse_args(argv)

    select = frozenset(r.strip() for r in args.select.split(",") if r.strip())
    if unknown := select - set(RULES):
        parser.error(f"unknown rule(s): {', '.join(sorted(unknown))}")

    count = 0
    for file in iter_py_files(args.roots):
        for finding in find_violations(file, select):
            print(finding)
            count += 1

    if count and not args.exit_zero:
        print(
            f"\n{count} finding(s) — an untyped dict must not carry a contract.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
