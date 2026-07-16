#!/usr/bin/env python3
"""Checker: enforce the Pydantic MODEL rules — the model IS the contract.

WHY
---
A Pydantic model built on the project's SHARED config object is the contract
between every layer of an app: strict typing, ``extra="forbid"``, whitespace
policy, all decided ONCE. A model that opts out of that config — or is not a
model at all (a bare dataclass), or is fed pre-parsed JSON, or reaches into
another object's ``_private`` — is a hole in the contract, and the failure mode
is almost always SILENT: a validated-looking value that was never validated.

Each rule below has a production incident behind it. None of them is style.

  json-parse-then-validate  🔴 THE HEADLINE. ``Model.model_validate(orjson.loads(raw))``
                    instead of ``Model.model_validate_json(raw)``. Pydantic's
                    strict mode is CONTEXT-AWARE: given RAW JSON it knows a
                    ``UUID``/``datetime``/enum can only ARRIVE as a string (JSON
                    can't express those natively) and converts it. Pre-parsing
                    with ``orjson.loads`` throws that context away — pydantic now
                    sees an ordinary ``dict[str, str]`` and ``strict=True``
                    correctly REJECTS it. A caller that fails open
                    (``except ValidationError: return None``) then reads as "no
                    enforcement": a real system had every populated response
                    silently rejected and billing skipped for months, hidden
                    because the test fixture's list was empty so no row was ever
                    validated. The fix is ``Model.model_validate_json(raw)``.
  barrel-init       An ``__init__.py`` that does anything beyond a module
                    docstring (any import / assignment / def). Importing a barrel
                    makes every consumer load the WHOLE package (measured
                    324ms/12 submodules -> 0.3ms once emptied). Ruff's RUF067
                    does NOT cover this — it PERMITS "docstrings and re-exports",
                    which is exactly what is banned. Only a bare docstring (and an
                    empty ``__all__`` anti-barrel marker) is allowed.
  pydantic-config   A model whose ``model_config`` does not START FROM the shared
                    config object. A bare ``ConfigDict(...)`` silently drops
                    ``extra="forbid"`` / ``strict=True`` / ``validate_assignment=True``.
                    The sanctioned shapes are ``<CONFIG>`` and
                    ``<CONFIG> | ConfigDict(...)`` — the shared config's name is
                    project-specific, so it is the ``--config-symbol`` option.
  verbatim-strip    A model field whose NAME matches a verbatim-content pattern
                    (``content``, ``body``, ``diff``, ``snippet``, ``raw`` ...) on a
                    model that does NOT declare ``str_strip_whitespace=False``. The
                    shared config sets ``str_strip_whitespace=True`` (right for
                    names/emails), which SILENTLY strips leading indentation from
                    code/content — it corrupted every code chunk entering a RAG
                    index. A verbatim field needs
                    ``<CONFIG> | ConfigDict(str_strip_whitespace=False)``.
  no-alias          A pydantic ``Field(alias=...)`` / ``AliasChoices`` /
                    ``populate_by_name`` usage. Aliases are banned: dig the wire
                    key out explicitly and construct field-by-field (a
                    ``from_raw_claims()``-style classmethod is the reference), so a
                    renamed vendor key fails LOUD at the parse site instead of
                    arriving as a default.
  no-dataclass      A ``@dataclass`` (or ``@dataclasses.dataclass``). A dataclass
                    validates nothing — prefer a Pydantic model. Survivors are
                    ALLOWLISTED with ``--allow-dataclass`` for a proven structural
                    reason (holds a live non-serializable object / DI container /
                    TYPE_CHECKING-only import / target of ``dataclasses.replace()``).
  private-access    A ``_name`` reached ACROSS objects (``store._conn``,
                    ``connector._client``). The leading underscore IS the contract
                    ("may change without notice"), so an external caller depending
                    on it has no contract. ONLY cross-object access is a violation:
                    ``self._x`` / ``cls._x`` / ``super()._x`` / ``OwnClass._x`` (from
                    inside ``OwnClass``) are the object touching its own internals
                    and are ALLOWED; a dunder (``obj.__aenter__``) is a language
                    protocol, never private access.

NOT owned here: ``no-typeddict``. The sibling ``pydantic_contract.py`` already owns
it (plus ``extra-forbid``, ``no-cast``, ``masking-default``, ``opaque-annotation``,
``dict-return``, ``splat``, ``select-star``, ``secret-repr``). Run both checkers —
this one is the model/parse/barrel/private half, that one is the field-shape half.

⚠️ MODEL_BASES ROTS SILENTLY — a KNOWN LIMITATION. ``--model-base`` names SYMBOLS
(``BaseModel``, ``RootModel``), so it rots when a base is RENAMED, and it rots in
the WORST direction: an unrecognised base makes a class INVISIBLE to every
model-shaped rule here, so 0 findings reads as CLEAN instead of as "the checker
saw no model at all". This has bitten real gates twice (a returns-checker saw
ZERO models in a 285-model codebase). Keep ``--model-base`` in lockstep with the
project's actual bases, and pin it with a test that resolves each name against
the real modules — a rename must fail a test, not blind the gate.

CONTRACT
--------
Prints one ``path: [rule] symbol — message`` finding per violation to stdout and
**exits 1 when there is any finding**, so wiring it straight into prek/pre-commit
surfaces the findings and fails the commit — no baseline artifact required.

Keys are rule + enclosing symbol (+ field name where relevant) and NEVER a line
number, so an unrelated edit does not churn a baseline; the repeatable rules
(``json-parse-then-validate``, ``barrel-init``, ``no-alias``, ``private-access``)
carry a per-symbol ordinal so a second occurrence is a distinct finding rather
than a duplicate key.

The checker owns NO state: it writes no baseline, no JSON, no cache. If you want
the regression-only ratchet, compose it with ``regression-gates/baseline_gate.py``
and pass ``--exit-zero`` — that harness reads a non-zero exit as "the checker
crashed" and fails closed, so the flag is required there and nowhere else.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/model_contract.py src/
    python checkers/model_contract.py --select json-parse-then-validate,no-alias src/
    python checkers/model_contract.py --config-symbol MY_CONFIG \\
        --model-base BaseModel --model-base RootModel \\
        --allow-dataclass core/di.py=Container src/

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline model_baseline.txt -- \\
        python checkers/model_contract.py --exit-zero src/

PARSER NOTE — pin this hook's interpreter
-----------------------------------------
This checker parses with the ``ast`` of the interpreter it RUNS ON, so an
interpreter older than the project's silently fails to parse new syntax (PEP 695
``type X = int``, ``async def run[**P, T]``, PEP 758 ``except A, B:``). Any
Python-AST-based gate shares this: unpinned, bandit's env resolved to 3.12 and
logged "syntax error while parsing AST" for 25 files, SKIPPED them, and **still
exited success** — a security gate silently not scanning.

So this checker does NOT fail open. An unparsable file exits **2** (a tool error,
distinct from 1 = findings) even under ``--exit-zero``, because a file it could
not read is a file it did not check.

Pin ``language_version`` on THIS hook — a repo-level ``default_language_version``
does NOT reach a hook's isolated env. Gates with their own non-Python parser
(ruff, jscpd, tree-sitter-based tools) are immune and need no pin.
"""

# NOTE: this import looks like it violates the very standard this file enforces —
# the skill's baseline is 3.14, where PEP 649 makes annotations lazy and the import
# is dead weight. It stays because this is TOOLING, not an example: it lives in the
# claude-all repo, which is deliberately `requires-python = ">=3.11"` so the
# installer runs anywhere. Delete it only if claude-all's own floor moves to 3.14.
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
    """A finding key. Subclasses ``str`` so callers can just print it."""

    __slots__ = ()


class Options(NamedTuple):
    """Resolved run configuration — the project-specific knobs the visitor reads.

    Every field is defaulted from a module constant and overridable on the CLI, so
    nothing project-specific is hardcoded in the visitor.
    """

    model_bases: frozenset[str]
    config_symbol: str
    verbatim_pattern: re.Pattern[str]
    dataclass_allow: tuple[tuple[str, str], ...]
    verbatim_allow: tuple[tuple[str, str], ...]
    private_allow: tuple[tuple[str, str], ...]
    private_attr_allow: frozenset[str]
    config_owner: tuple[str, ...]


def _name_of(node: ast.expr | None, *, root: bool = False) -> str:
    """Resolve a bare name out of *node*.

    Args:
        node: The expression to name, or ``None``.
        root: When True, walk to the LEFTMOST name of an attribute chain
            (``a.b.c`` -> ``a``) — used to identify a call's receiver. When False
            (default), take the TRAILING name (``pydantic.BaseModel`` ->
            ``BaseModel``) — used to identify a base, annotation, or callee.

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


def base_names(node: ast.ClassDef) -> set[str]:
    """Return the bare names of every base class of *node*.

    Reads the attribute for a dotted base so ``pydantic.BaseModel`` resolves to
    ``BaseModel``.

    Args:
        node: The class definition to inspect.

    Returns:
        The set of base names (empty for an object-only class).
    """
    return {name for base in node.bases if (name := _name_of(base))}


def is_model_class(node: ast.ClassDef, model_bases: frozenset[str]) -> bool:
    """True when *node* subclasses one of the configured model bases.

    A ``BaseSettings`` subclass is NOT a model for this gate — it is a different
    base with its own config contract.

    Args:
        node: The class definition to inspect.
        model_bases: The bases that mark a class as one of our models.

    Returns:
        True when a base is in *model_bases* and none is a settings base.
    """
    names = base_names(node)
    return bool(names & model_bases) and not (names & SETTINGS_BASES)


def config_starts_from_shared(value: ast.expr, config_symbol: str) -> bool:
    """True when a ``model_config`` value STARTS FROM the shared config symbol.

    Accepts exactly ``<CONFIG>`` and ``<CONFIG> | ConfigDict(...)``. The recursion
    walks the LEFT arm only, so ``ConfigDict(...) | <CONFIG>`` is rejected — there
    the shared config's keys would win over the model's own deliberate overrides,
    the opposite of what the author intended.

    Args:
        value: The assigned ``model_config`` expression.
        config_symbol: The sanctioned shared-config name.

    Returns:
        Whether the config is rooted at the shared symbol.
    """
    if isinstance(value, ast.Name):
        return value.id == config_symbol
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
        return config_starts_from_shared(value.left, config_symbol)
    return False


def config_kwarg_is_false(value: ast.expr, name: str) -> bool:
    """True when a ``ConfigDict(...)`` anywhere in *value* passes ``name=False``.

    Args:
        value: The assigned ``model_config`` expression.
        name: The config key to look for (e.g. ``"str_strip_whitespace"``).

    Returns:
        Whether *name* is explicitly set to ``False``.
    """
    for node in ast.walk(value):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                return True
    return False


def str_annotation(node: ast.expr | None) -> bool:
    """True when *node* is (or contains) a string-carrying annotation.

    Recurses through unions and subscripts so ``str | None`` and ``Sequence[str]``
    both count — each still reaches pydantic's whitespace stripping.

    Args:
        node: A field's annotation AST node, or ``None``.

    Returns:
        Whether the annotation carries a string.
    """
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
    """True when this exact (path suffix, name) pair is on *allowlist*.

    Keyed by (path suffix, name) so a rename or a move fails the gate rather than
    silently carrying the exemption to a different symbol. An entry that no longer
    matches any code is itself dead and worth pruning.

    Args:
        path: The POSIX path of the file being scanned.
        name: The dotted qualname / attribute the allowlist keys on.
        allowlist: The ``(suffix, name)`` pairs to check against.

    Returns:
        Whether the pair appears in *allowlist*.
    """
    return any(path.endswith(suffix) and name == allowed for suffix, allowed in allowlist)


def is_dataclass_decorator(node: ast.expr) -> bool:
    """True when *node* is a ``@dataclass`` / ``@dataclass(...)`` decorator.

    Args:
        node: A decorator AST node.

    Returns:
        Whether the decorator is ``dataclass`` (bare, called, or dotted).
    """
    target = node.func if isinstance(node, ast.Call) else node
    return _name_of(target) == "dataclass"


def is_dunder(name: str) -> bool:
    """True when *name* is a dunder (``__aenter__``, ``__init__``, ...).

    A dunder is a language PROTOCOL hook, not a private member: ``obj.__aenter__()``
    is how ``async with`` is spelled by hand, so it is never private access.

    Args:
        name: The attribute name.

    Returns:
        Whether *name* both starts and ends with a double underscore.
    """
    return name.startswith("__") and name.endswith("__")


def is_self_receiver(node: ast.expr) -> bool:
    """True when *node* is a receiver that denotes the object itself.

    ``self`` / ``cls`` are the object; ``super()`` is still the same instance, so
    ``super()._helper()`` is self-access spelled through the MRO.

    Args:
        node: The receiver expression of an attribute access.

    Returns:
        Whether the receiver is self-ish.
    """
    if isinstance(node, ast.Name):
        return node.id in SELF_RECEIVERS
    return isinstance(node, ast.Call) and _name_of(node.func) == "super"


def is_json_loads_call(node: ast.expr | None) -> bool:
    """True when *node* is a ``*.loads(...)`` / ``loads(...)`` call.

    Reads the bare callee name, so ``orjson.loads(x)``, ``json.loads(x)`` and a
    bare ``loads(x)`` all match.

    Args:
        node: The AST node to inspect.

    Returns:
        Whether *node* parses a JSON document into Python objects.
    """
    if not isinstance(node, ast.Call):
        return False
    return _name_of(node.func) in JSON_LOADS_NAMES


def loads_bound_names(node: ast.AST) -> set[str]:
    """Return the names *node*'s OWN scope binds from a ``*.loads(...)`` call.

    Covers the binding forms that reach real code — ``body = loads(raw)``,
    ``body: T = loads(raw)`` and the walrus ``(body := loads(raw))``. Descends into
    ``if`` / ``try`` / ``for`` bodies but STOPS at a nested ``def`` / ``lambda`` /
    ``class``, which own their scope — otherwise one function's local ``body`` would
    make a sibling's unrelated ``body`` parameter look JSON-derived. Closure
    visibility is handled by the caller stacking these sets, not by over-collecting.

    Args:
        node: The scope node (a module or a function) to collect bindings from.

    Returns:
        Every local name assigned the result of a ``loads`` call.
    """
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
    """True when *stmt* is an EMPTY ``__all__`` declaration.

    ``__all__ = []`` / ``__all__: list[str] = []`` is the explicit "this package
    exports NOTHING" marker — the OPPOSITE of a barrel — so it does not count as
    barrel content. A NON-empty ``__all__`` is NOT exempt: it names re-exports,
    which is the violation itself. Neither can hide a real barrel, because the
    ``import`` statements a barrel needs are flagged independently.

    Args:
        stmt: A module-level statement from an ``__init__.py``.

    Returns:
        Whether *stmt* declares ``__all__`` as an empty list.
    """
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
        # A STACK of per-scope name sets bound from `*.loads(...)`. Stacked rather
        # than merged so a lookup sees enclosing scopes (a closure legitimately
        # reads an outer `body`) without a sibling function's locals leaking in.
        self._loads_scopes: list[set[str]] = []
        # Enclosing CLASS names only. `OwnClass._helper()` written inside OwnClass
        # is self-access: naming the class is the ONLY way a @staticmethod can
        # reach a sibling private, so it must not be flagged.
        self._class_stack: list[str] = []

    def _add(self, rule: str, symbol: str, message: str) -> None:
        """Record a finding under a stable, line-independent key.

        Args:
            rule: The rule name; ignored when not in ``--select``.
            symbol: The enclosing qualname (plus field/attr where relevant).
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

        Returns:
            The dotted qualname, or ``"<module>"`` at module scope.
        """
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
        """Flag every module-level node in an ``__init__.py`` that is not the docstring.

        An ``__init__.py`` must be a DOCSTRING ONLY. The one carve-out is an empty
        ``__all__`` (the anti-barrel marker) — see :func:`is_empty_all_assign`.

        Args:
            node: The module node being scanned.
        """
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
        """True when *node*'s value came from a ``*.loads(...)`` call.

        Covers the three shapes that reach real code: a direct
        ``M.model_validate(loads(raw))``, a local ``body = loads(raw); ...(body)``,
        and a wrapper ``...(unwrap(body))`` around a parsed value. A ``Subscript`` of
        a JSON-derived name (``body["data"]``) counts too. Cross-FUNCTION dataflow is
        deliberately NOT covered (documented, not overlooked) — it needs
        whole-program analysis, and intra-function catches every shape this bug has
        actually taken.

        Args:
            node: The first argument of a ``model_validate`` call.

        Returns:
            Whether the argument is already-parsed JSON.
        """
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
        """Flag ``Model.model_validate(<already-parsed JSON>)``.

        NOT flagged: ``model_validate`` on a dict that did NOT come from a ``loads``
        (a DB ``dict(row)``, a hand-built dict) — that value was never a JSON
        document, so there is no JSON type context to preserve.

        Args:
            node: The call node to inspect.
        """
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
            if is_dataclass_decorator(decorator) and not allowlisted(
                self.path, qual, self.opts.dataclass_allow
            ):
                self._add(
                    "no-dataclass",
                    qual,
                    "@dataclass validates nothing — use a Pydantic model, or allowlist it "
                    "with --allow-dataclass for a proven structural reason",
                )

        if is_model_class(node, self.opts.model_bases):
            config = self._model_config_value(node)
            self._check_pydantic_config(node, config)
            self._check_verbatim_strip(node, config)

        self.generic_visit(node)
        self._stack.pop()
        self._class_stack.pop()

    def _model_config_value(self, node: ast.ClassDef) -> ast.expr | None:
        """Return the ``model_config`` assigned value in *node*'s body, if any.

        Args:
            node: The class definition to inspect.

        Returns:
            The assigned expression, or ``None`` when the class sets no config.
        """
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
        """Flag a model whose ``model_config`` does not start from the shared config.

        Args:
            node: The model class definition.
            config: The assigned ``model_config`` expression, or ``None``.
        """
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
        """Flag a content-ish str field that does not opt out of whitespace stripping.

        Args:
            node: The model class definition.
            config: The assigned ``model_config`` expression, or ``None``.
        """
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
        """Flag a pydantic alias surface on a call.

        An ``alias=`` kwarg is flagged ONLY on a ``Field(...)`` call: FastAPI's
        ``Header(alias=...)`` / ``Query(alias=...)`` name an HTTP header or query
        param, not a model field, and a plain ``alias=`` on a log call is ordinary
        context — neither is a pydantic alias.

        Args:
            node: The call node to inspect.
        """
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
        """True when *node* names a class we are lexically inside.

        ``OwnClass._helper(x)`` written inside ``OwnClass`` is the class reaching its
        OWN internals — and from a ``@staticmethod`` (no ``self``/``cls`` in scope)
        naming the class is the only way to reach a sibling private at all.

        Args:
            node: The receiver expression of an attribute access.

        Returns:
            Whether the receiver is an enclosing class's own name.
        """
        return isinstance(node, ast.Name) and node.id in self._class_stack

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Flag a ``_name`` reached across objects (read or write).

        Skips the legitimate shapes: a dunder protocol hook, a self-ish receiver
        (``self`` / ``cls`` / ``super()`` / the enclosing class's own name), an
        allowlisted namedtuple-convention member (``row._mapping``), and an
        allowlisted call site.

        Args:
            node: The attribute-access expression.
        """
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
        """Track a ``def`` as the enclosing symbol and ``loads`` scope.

        Args:
            node: The function definition.
        """
        self._visit_scoped(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track an ``async def`` as the enclosing symbol and ``loads`` scope.

        Args:
            node: The coroutine definition.
        """
        self._visit_scoped(node)

    def _visit_scoped(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Push the function's name and ``loads`` scope, descend, then pop both.

        Args:
            node: The function or coroutine definition.
        """
        self._stack.append(node.name)
        self._loads_scopes.append(loads_bound_names(node))
        self.generic_visit(node)
        self._loads_scopes.pop()
        self._stack.pop()


def check_tree(tree: ast.AST, path: str, select: frozenset[str], opts: Options) -> list[Finding]:
    """Collect every violation in an already-parsed module.

    Args:
        tree: The parsed module.
        path: Path string used to key findings.
        select: The rule names to report.
        opts: The resolved run configuration.

    Returns:
        One finding per violation, in source order.
    """
    visitor = _Visitor(path, select, opts)
    visitor.visit(tree)
    return visitor.findings


def find_violations(path: Path, select: frozenset[str], opts: Options) -> list[Finding]:
    """Parse *path* and return its findings.

    Args:
        path: The Python file to scan.
        select: The rule names to report.
        opts: The resolved run configuration.

    Returns:
        One finding per violation, in source order.

    Raises:
        SyntaxError: When the RUNNING interpreter cannot parse *path*. This is
            deliberately NOT swallowed — see the PARSER NOTE in the module
            docstring. A file the checker could not read is a file it did not
            check; returning ``[]`` would report it clean.
        ValueError: On a null byte or similar unreadable source.
        UnicodeDecodeError: When the file is not valid UTF-8.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return check_tree(tree, path.as_posix(), select, opts)


def iter_py_files(roots: list[Path]) -> list[Path]:
    """Yield every ``*.py`` under *roots* (files or dirs).

    Args:
        roots: Files or directories to scan.

    Returns:
        Every Python file found, directories walked in sorted order.
    """
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
    """Parse repeated ``PATHSUFFIX=Name`` allowlist entries into ``(suffix, name)`` pairs.

    Args:
        entries: The raw ``--allow-*`` values, or ``None`` when the flag was unused.
        parser: The argument parser, used to raise a clean error on a bad entry.
        flag: The flag name, for the error message.

    Returns:
        The parsed ``(suffix, name)`` pairs.
    """
    out: list[tuple[str, str]] = []
    for entry in entries or []:
        suffix, sep, name = entry.partition("=")
        if not sep or not suffix or not name:
            parser.error(f"{flag} expects PATHSUFFIX=Name, got: {entry!r}")
        out.append((suffix, name))
    return tuple(out)


def build_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Options:
    """Resolve CLI arguments into an :class:`Options`, defaulting every knob.

    Args:
        args: The parsed argument namespace.
        parser: The argument parser, used to raise clean errors.

    Returns:
        The resolved run configuration.
    """
    return Options(
        model_bases=frozenset(args.model_base) if args.model_base else DEFAULT_MODEL_BASES,
        config_symbol=args.config_symbol,
        verbatim_pattern=re.compile(args.verbatim_pattern),
        dataclass_allow=parse_allow(args.allow_dataclass, parser, "--allow-dataclass"),
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
    """CLI entry point.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        0 when the check ran clean, 1 on any finding, 2 on an unparsable file.
    """
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
        "--allow-dataclass",
        action="append",
        metavar="PATHSUFFIX=Class",
        help="exempt a @dataclass at (path suffix, class) — repeatable; proven reason",
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
