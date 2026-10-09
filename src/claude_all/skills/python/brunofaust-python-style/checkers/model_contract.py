#!/usr/bin/env python3
"""Checker: enforce the Pydantic MODEL rules — the model IS the contract.
Rules: references/enforcement.md."""

# NOTE: on the skill's 3.12 baseline (no PEP 649 lazy annotations — that is
# 3.14-only), `from __future__ import annotations` is the recommended way to keep
# forward references and TYPE_CHECKING-only imports free at runtime.
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple

__all__ = ["RULES", "Finding", "Options", "check_tree", "find_violations", "main"]

RULES: tuple[str, ...] = (
    "json-parse-then-validate",
    "barrel-init",
    "pydantic-config",
    "verbatim-strip",
    "no-alias",
    "no-dataclass",
    "private-access",
)

#: Rules that can legitimately occur MANY times inside one symbol. Their keys get a
#: per-symbol ordinal, so a second occurrence is a NEW finding instead of collapsing
#: into the first one's baseline entry (which would let a regression pass the gate).
REPEATABLE = frozenset({"json-parse-then-validate", "barrel-init", "no-alias", "private-access"})

#: Default bases that make a class one of OUR models. Override with ``--model-base``.
#: See the MODEL_BASES ROTS warning in the module docstring — this names symbols.
DEFAULT_MODEL_BASES = frozenset({"BaseModel", "RootModel"})

#: pydantic-settings' ``BaseSettings`` is a DIFFERENT base with its own config
#: contract (env-var sources, ``SettingsConfigDict``); the shared config does not
#: apply to it. Never flag it as a model missing the shared config.
SETTINGS_BASES = frozenset({"BaseSettings"})

#: Default shared-config symbol a ``model_config`` must start from. Override with
#: ``--config-symbol`` (the name is project-specific).
DEFAULT_CONFIG_SYMBOL = "PYDANTIC_CONFIG"

#: Field-name pattern for "this field carries VERBATIM content". A HEURISTIC, and
#: deliberately broad: a false positive costs one explicit
#: ``str_strip_whitespace=False`` opt-in; a false negative silently corrupts
#: customer data. Override with ``--verbatim-pattern``.
DEFAULT_VERBATIM_PATTERN = (
    r"chunk_text|content|body|text|output|source|diff|snippet|preview|html|patch|raw"
)

#: Annotations that carry a string and so reach pydantic's whitespace stripping.
STR_ANNOTATIONS = frozenset({"str"})

#: Pydantic alias surfaces. All banned: the model is constructed field-by-field.
ALIAS_KWARGS = frozenset({"alias", "serialization_alias", "validation_alias"})
ALIAS_NAMES = frozenset({"AliasChoices", "AliasPath"})

#: Receivers that denote the object itself — NOT cross-object private access.
SELF_RECEIVERS = frozenset({"self", "cls"})

#: Third-party members whose leading underscore is the NAMEDTUPLE CONVENTION, not
#: "private" (``row._mapping`` is SQLAlchemy's published API). Extend with
#: ``--allow-private-attr``. The bar is DOCUMENTED-PUBLIC-DESPITE-UNDERSCORE.
DEFAULT_PRIVATE_ATTR_ALLOW = frozenset({"_mapping"})

#: The parse functions whose RESULT must never reach ``model_validate``. Matched on
#: the bare callee name, so ``orjson.loads(x)``, ``json.loads(x)`` and a bare
#: ``loads(x)`` all count. A non-JSON ``loads`` (``pickle.loads``) matching here is
#: a false positive costing one baseline entry — the right side to err on for a
#: rule whose false NEGATIVE silently skipped customer billing.
JSON_LOADS_NAMES = frozenset({"loads"})

#: The pydantic entry point taking ALREADY-PARSED objects. Its JSON-mode sibling
#: ``model_validate_json`` (which takes raw bytes/str, and is the FIX) is
#: deliberately absent — it is what this rule steers callers TO.
MODEL_VALIDATE_ATTR = "model_validate"


class Finding(str):
    """A finding key."""

    __slots__ = ()


class Options(NamedTuple):
    """Resolved run configuration — the project-specific knobs the visitor reads."""

    model_bases: frozenset[str]
    config_symbol: str
    verbatim_pattern: re.Pattern[str]
    verbatim_allow: tuple[tuple[str, str], ...]
    private_allow: tuple[tuple[str, str], ...]
    private_attr_allow: frozenset[str]
    config_owner: tuple[str, ...]


def _name_of(node: ast.expr | None, *, root: bool = False) -> str:
    if root:
        while isinstance(node, ast.Attribute):
            node = node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def base_names(node: ast.ClassDef) -> set[str]:
    """Return the bare names of every base class of *node*."""
    return {name for base in node.bases if (name := _name_of(base))}


def is_model_class(node: ast.ClassDef, model_bases: frozenset[str]) -> bool:
    names = base_names(node)
    return bool(names & model_bases) and not (names & SETTINGS_BASES)


def config_starts_from_shared(value: ast.expr, config_symbol: str) -> bool:
    if isinstance(value, ast.Name):
        return value.id == config_symbol
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
        return config_starts_from_shared(value.left, config_symbol)
    return False


def config_kwarg_is_false(value: ast.expr, name: str) -> bool:
    """True when a ``ConfigDict(...)`` anywhere in *value* passes ``name=False``."""
    for node in ast.walk(value):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                return True
    return False


def str_annotation(node: ast.expr | None) -> bool:
    """True when *node* is (or contains) a string-carrying annotation."""
    if node is None:
        return False
    if isinstance(node, ast.Name | ast.Attribute):
        return _name_of(node) in STR_ANNOTATIONS
    if isinstance(node, ast.Constant):  # a stringised forward ref, e.g. "str | None"
        return isinstance(node.value, str) and node.value in STR_ANNOTATIONS
    if isinstance(node, ast.Subscript):
        return str_annotation(node.value) or str_annotation(node.slice)
    if isinstance(node, ast.Tuple):
        return any(str_annotation(elt) for elt in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return str_annotation(node.left) or str_annotation(node.right)
    return False


def allowlisted(path: str, name: str, allowlist: tuple[tuple[str, str], ...]) -> bool:
    """True when this exact (path suffix, name) pair is on *allowlist*."""
    return any(path.endswith(suffix) and name == allowed for suffix, allowed in allowlist)


def is_dataclass_decorator(node: ast.expr) -> bool:
    """True when *node* is a ``@dataclass`` / ``@dataclass(...)`` decorator."""
    target = node.func if isinstance(node, ast.Call) else node
    return _name_of(target) == "dataclass"


def is_dunder(name: str) -> bool:
    """True when *name* is a dunder (``__aenter__``, ``__init__``, ...)."""
    return name.startswith("__") and name.endswith("__")


def is_self_receiver(node: ast.expr) -> bool:
    """True when *node* is a receiver that denotes the object itself."""
    if isinstance(node, ast.Name):
        return node.id in SELF_RECEIVERS
    return isinstance(node, ast.Call) and _name_of(node.func) == "super"


def is_json_loads_call(node: ast.expr | None) -> bool:
    """True when *node* is a ``*.loads(...)`` / ``loads(...)`` call."""
    if not isinstance(node, ast.Call):
        return False
    return _name_of(node.func) in JSON_LOADS_NAMES


def loads_bound_names(node: ast.AST) -> set[str]:
    """Return the names *node*'s OWN scope binds from a ``*.loads(...)`` call."""
    names: set[str] = set()
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue  # its own scope — collected when the visitor descends into it
        if isinstance(child, ast.Assign) and is_json_loads_call(child.value):
            names.update(t.id for t in child.targets if isinstance(t, ast.Name))
        elif (
            isinstance(child, ast.AnnAssign | ast.NamedExpr)
            and is_json_loads_call(child.value)
            and isinstance(child.target, ast.Name)
        ):
            names.add(child.target.id)
        stack.extend(ast.iter_child_nodes(child))
    return names


def is_empty_all_assign(stmt: ast.stmt) -> bool:
    """True when *stmt* is an EMPTY ``__all__`` declaration."""
    if isinstance(stmt, ast.AnnAssign):
        target, value = stmt.target, stmt.value
    elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
        target, value = stmt.targets[0], stmt.value
    else:
        return False
    if not isinstance(target, ast.Name) or target.id != "__all__":
        return False
    return isinstance(value, ast.List) and not value.elts


class _Visitor(ast.NodeVisitor):
    """Walks a module collecting model-rule violations with stable, line-free keys."""

    def __init__(self, path: str, select: frozenset[str], opts: Options) -> None:
        self.path = path
        self.select = select
        self.opts = opts
        self.findings: list[Finding] = []
        self._stack: list[str] = []
        self._ordinals: dict[tuple[str, str], int] = {}
        # Stack of per-scope names bound from `*.loads(...)`; lookups see enclosing scopes.
        self._loads_scopes: list[set[str]] = []
        # Enclosing class names; `OwnClass._helper()` inside OwnClass is self-access.
        self._class_stack: list[str] = []

    def _add(self, rule: str, symbol: str, message: str) -> None:
        if rule not in self.select:
            return
        if rule in REPEATABLE:
            slot = (rule, symbol)
            ordinal = self._ordinals.get(slot, 0)
            self._ordinals[slot] = ordinal + 1
            symbol = f"{symbol}#{ordinal}"
        self.findings.append(Finding(f"{self.path}: [{rule}] {symbol} — {message}"))

    def _qual(self, extra: str = "") -> str:
        parts = [*self._stack, extra] if extra else self._stack
        return ".".join(parts) or "<module>"

    def visit_Module(self, node: ast.Module) -> None:
        """Seed the module ``loads`` scope, check for a barrel, then descend.

        Args:
            node: The module node being scanned.
        """
        self._loads_scopes.append(loads_bound_names(node))
        self._check_barrel_init(node)
        self.generic_visit(node)
        self._loads_scopes.pop()

    def _check_barrel_init(self, node: ast.Module) -> None:
        """Flag every module-level node in an ``__init__.py`` that is not the docstring."""
        if not self.path.endswith("__init__.py"):
            return
        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]  # the docstring — the ONLY sanctioned content
        for stmt in body:
            if is_empty_all_assign(stmt):
                continue
            self._add(
                "barrel-init",
                "<module>",
                f"`{type(stmt).__name__}` in __init__.py — a barrel makes every consumer "
                "load the whole package; keep it a docstring only and import from the module",
            )

    def _json_derived(self, node: ast.expr) -> bool:
        """True when *node*'s value came from a ``*.loads(...)`` call."""
        if is_json_loads_call(node):
            return True
        if isinstance(node, ast.Name):
            return any(node.id in scope for scope in self._loads_scopes)
        if isinstance(node, ast.Subscript):
            return self._json_derived(node.value)
        if isinstance(node, ast.Call):  # a wrapper called ON a parsed value
            args = [*node.args, *(kw.value for kw in node.keywords)]
            return any(self._json_derived(arg) for arg in args)
        return False

    def _record_json_parse_then_validate(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute) or node.func.attr != MODEL_VALIDATE_ATTR:
            return
        if not node.args or not self._json_derived(node.args[0]):
            return
        self._add(
            "json-parse-then-validate",
            self._qual(),
            "use `Model.model_validate_json(raw)` — pre-parsing with orjson.loads/json.loads "
            "discards JSON type context and strict then rejects valid UUID/datetime/enum",
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Apply every class-scoped rule (dataclass, pydantic-config, verbatim-strip).

        Args:
            node: The class definition.
        """
        self._stack.append(node.name)
        self._class_stack.append(node.name)
        qual = self._qual()

        for decorator in node.decorator_list:
            if is_dataclass_decorator(decorator):
                self._add(
                    "no-dataclass",
                    qual,
                    "@dataclass validates nothing — use a Pydantic model (live objects: "
                    "arbitrary_types_allowed=True)",
                )

        if is_model_class(node, self.opts.model_bases):
            config = self._model_config_value(node)
            self._check_pydantic_config(node, config)
            self._check_verbatim_strip(node, config)

        self.generic_visit(node)
        self._stack.pop()
        self._class_stack.pop()

    def _model_config_value(self, node: ast.ClassDef) -> ast.expr | None:
        """Return the ``model_config`` assigned value in *node*'s body, if any."""
        for stmt in node.body:
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == "model_config"
                and stmt.value is not None
            ):
                return stmt.value
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "model_config" for t in stmt.targets
            ):
                return stmt.value
        return None

    def _check_pydantic_config(self, node: ast.ClassDef, config: ast.expr | None) -> None:
        symbol = self.opts.config_symbol
        if any(self.path.endswith(suffix) for suffix in self.opts.config_owner):
            return  # the file that DEFINES the shared config cannot start from it
        if config is None:
            self._add(
                "pydantic-config",
                self._qual(),
                f"model sets no model_config — start it from `{symbol}`",
            )
        elif not config_starts_from_shared(config, symbol):
            self._add(
                "pydantic-config",
                self._qual(),
                f"model_config does not start from `{symbol}` — a bare ConfigDict(...) drops "
                f"extra=forbid/strict; use `{symbol}` or `{symbol} | ConfigDict(...)`",
            )

    def _check_verbatim_strip(self, node: ast.ClassDef, config: ast.expr | None) -> None:
        if config is not None and config_kwarg_is_false(config, "str_strip_whitespace"):
            return
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            field = stmt.target.id
            if field == "model_config" or not str_annotation(stmt.annotation):
                continue
            if not self.opts.verbatim_pattern.search(field):
                continue
            symbol = self._qual(field)
            if allowlisted(self.path, symbol, self.opts.verbatim_allow):
                continue
            self._add(
                "verbatim-strip",
                symbol,
                "verbatim content field under a stripping config — the shared config's "
                "str_strip_whitespace=True silently eats leading indentation; declare "
                "`| ConfigDict(str_strip_whitespace=False)`",
            )

    def _record_alias(self, node: ast.Call) -> None:
        callee = _name_of(node.func)
        for kw in node.keywords:
            if kw.arg in ALIAS_KWARGS and callee == "Field":
                detail = f"`Field({kw.arg}=...)` — aliases are banned; construct field-by-field"
            elif kw.arg == "populate_by_name" and callee == "ConfigDict":
                detail = "`ConfigDict(populate_by_name=...)` — aliases banned; build field-by-field"
            elif (
                kw.arg == "by_alias"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                detail = "`by_alias=True` — aliases are banned"
            else:
                continue
            self._add("no-alias", self._qual(), detail)

    def visit_Call(self, node: ast.Call) -> None:
        """Record alias and json-parse-then-validate findings on a call.

        Args:
            node: The call expression.
        """
        self._record_alias(node)
        self._record_json_parse_then_validate(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Flag a use of ``AliasChoices`` / ``AliasPath``.

        Args:
            node: The name expression.
        """
        if node.id in ALIAS_NAMES:
            self._add("no-alias", self._qual(), f"`{node.id}` — aliases are banned")
        self.generic_visit(node)

    def _is_own_class_receiver(self, node: ast.expr) -> bool:
        """True when *node* names a class we are lexically inside."""
        return isinstance(node, ast.Name) and node.id in self._class_stack

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        own = is_self_receiver(node.value) or self._is_own_class_receiver(node.value)
        allowed = attr in self.opts.private_attr_allow or allowlisted(
            self.path, attr, self.opts.private_allow
        )
        if attr.startswith("_") and not is_dunder(attr) and not own and not allowed:
            recv = _name_of(node.value, root=True) or "<expr>"
            self._add(
                "private-access",
                self._qual(),
                f"`{recv}.{attr}` reaches another object's private member — the leading "
                "underscore says 'may change without notice'; drop it or stop reaching in",
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped(node)

    def _visit_scoped(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._stack.append(node.name)
        self._loads_scopes.append(loads_bound_names(node))
        self.generic_visit(node)
        self._loads_scopes.pop()
        self._stack.pop()


def check_tree(tree: ast.AST, path: str, select: frozenset[str], opts: Options) -> list[Finding]:
    visitor = _Visitor(path, select, opts)
    visitor.visit(tree)
    return visitor.findings


def find_violations(path: Path, select: frozenset[str], opts: Options) -> list[Finding]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return check_tree(tree, path.as_posix(), select, opts)


def iter_py_files(roots: list[Path]) -> list[Path]:
    """Yield every ``*.py`` under *roots* (files or dirs)."""
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def parse_allow(
    entries: list[str] | None, parser: argparse.ArgumentParser, flag: str
) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for entry in entries or []:
        suffix, sep, name = entry.partition("=")
        if not sep or not suffix or not name:
            parser.error(f"{flag} expects PATHSUFFIX=Name, got: {entry!r}")
        out.append((suffix, name))
    return tuple(out)


def build_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Options:
    return Options(
        model_bases=frozenset(args.model_base) if args.model_base else DEFAULT_MODEL_BASES,
        config_symbol=args.config_symbol,
        verbatim_pattern=re.compile(args.verbatim_pattern),
        verbatim_allow=parse_allow(args.allow_verbatim, parser, "--allow-verbatim"),
        private_allow=parse_allow(args.allow_private, parser, "--allow-private"),
        private_attr_allow=(
            frozenset(args.allow_private_attr)
            if args.allow_private_attr
            else DEFAULT_PRIVATE_ATTR_ALLOW
        ),
        config_owner=tuple(args.config_owner or ()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enforce the Pydantic model-contract rules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("roots", nargs="+", type=Path, help="files or dirs to scan")
    parser.add_argument(
        "--select",
        default=",".join(RULES),
        help=f"comma-separated rules to enforce (default: all). Available: {', '.join(RULES)}",
    )
    parser.add_argument(
        "--model-base",
        action="append",
        metavar="NAME",
        help="model base, repeatable (default: BaseModel/RootModel). Names a symbol — "
        "rots silently on a base rename; see the docstring.",
    )
    parser.add_argument(
        "--config-symbol",
        default=DEFAULT_CONFIG_SYMBOL,
        metavar="NAME",
        help=f"the shared config a model_config must start from (default: {DEFAULT_CONFIG_SYMBOL})",
    )
    parser.add_argument(
        "--config-owner",
        action="append",
        metavar="PATHSUFFIX",
        help="path suffix of the file that DEFINES the shared config — exempt from pydantic-config "
        "(repeatable; it cannot start from what it declares)",
    )
    parser.add_argument(
        "--verbatim-pattern",
        default=DEFAULT_VERBATIM_PATTERN,
        metavar="REGEX",
        help="field-name pattern for verbatim-content fields (default: content/body/diff/...)",
    )
    parser.add_argument(
        "--allow-verbatim",
        action="append",
        metavar="PATHSUFFIX=Qual.field",
        help="exempt a verbatim-strip field at (path suffix, field qualname) — repeatable",
    )
    parser.add_argument(
        "--allow-private",
        action="append",
        metavar="PATHSUFFIX=_attr",
        help="exempt a private-access at (path suffix, attribute) — repeatable, one call site",
    )
    parser.add_argument(
        "--allow-private-attr",
        action="append",
        metavar="_attr",
        help=f"attribute whose underscore is namedtuple convention, not private (default: "
        f"{sorted(DEFAULT_PRIVATE_ATTR_ALLOW)}); repeatable, applies everywhere",
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
    opts = build_options(args, parser)

    count = 0
    unparsable: list[str] = []
    for file in iter_py_files(args.roots):
        try:
            findings = find_violations(file, select, opts)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            unparsable.append(f"{file}: {exc}")
            continue
        for finding in findings:
            print(finding)
            count += 1

    # Fail CLOSED on an unparsable file, and do it even under --exit-zero: this is
    # a TOOL error, not a finding, and baseline_gate.py must see it as one.
    if unparsable:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(
            f"\nERROR: {len(unparsable)} file(s) could not be parsed by the running "
            f"interpreter (python {version}). A file this checker could not read is a "
            "file it did NOT check — skipping it silently would report it clean.\n"
            "If the syntax is valid on the project's Python, this hook's interpreter is "
            "too old: pin `language_version` on THIS hook. A repo-level "
            "`default_language_version` does NOT reach a hook's isolated env.",
            file=sys.stderr,
        )
        for item in unparsable:
            print(f"  {item}", file=sys.stderr)
        return 2

    if count and not args.exit_zero:
        print(
            f"\n{count} finding(s) — the model IS the contract; a hole in it fails silently.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
