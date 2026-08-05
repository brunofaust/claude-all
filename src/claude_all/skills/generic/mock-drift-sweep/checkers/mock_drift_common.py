#!/usr/bin/env python3
"""Shared AST helpers for the mock-drift checker family.

WHY A SHARED MODULE
--------------------
``check_async_mock_target.py`` and the four mock-drift-sweep checkers
(``check_patch_target_exists.py``, ``check_orphan_test_file.py``,
``check_mock_assert_signature.py``, ``check_unspecced_model_mock.py``) all need
the same low-level plumbing: turning a ``patch("dotted.path")`` /
``patch.object(Obj, "name")`` call site into a dotted target string, indexing
every parsed module in the tree by every dotted-suffix it could be imported
as, and walking a test module's ``from X import Y`` map. Extracting this once
avoids a jscpd clone across five checker files and keeps the CONSERVATIVE
RESOLUTION policy (silence over a false positive — see each checker's own
docstring) implemented in exactly one place.

Each checker keeps its OWN semantic resolution on top of this (e.g. "is the
target an async def", "does the name exist at all", "what is its parameter
list") — those differ per rule and do not belong here.
"""

import argparse
import ast
import json
import sys
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "build_module_index",
    "collect_patch_call_findings",
    "find_def",
    "import_map",
    "is_patch_call",
    "is_patch_object_call",
    "is_test_file",
    "is_truthy",
    "iter_py_files",
    "keyword",
    "load_baseline_keys",
    "make_patch_finding_checker",
    "module_suffixes",
    "new_positional_arg",
    "parse_trees",
    "patch_object_target",
    "report_unparsable",
    "resolve_call_target",
    "run_regression_gate_cli",
    "string_value",
    "trailing_name",
]


def trailing_name(node: ast.expr | None) -> str:
    """Return the TRAILING name of *node*.

    ``mock.AsyncMock`` -> ``AsyncMock``, ``AsyncMock(...)`` -> ``AsyncMock``,
    a bare ``Name`` -> its id.

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


def is_patch_call(call: ast.Call) -> bool:
    """True when *call* is ``patch(...)`` / ``mock.patch(...)`` (NOT ``patch.object``)."""
    func = call.func
    return isinstance(func, ast.Name | ast.Attribute) and trailing_name(func) == "patch"


def is_patch_object_call(call: ast.Call) -> bool:
    """True when *call* is ``patch.object(...)`` / ``mock.patch.object(...)``."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "object"
        and trailing_name(func.value) == "patch"
    )


def string_value(node: ast.expr | None) -> str | None:
    """Return the ``str`` constant *node* holds, or ``None`` when it is not a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    """Return the value expression of keyword *name* on *call*, or ``None``."""
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def is_truthy(node: ast.expr | None) -> bool:
    """True when *node* is a literal that is not falsy — used for ``autospec=``."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    return node is not None  # a non-literal autospec (variable) is treated as set


def module_suffixes(path: Path) -> list[str]:
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
        for suffix in module_suffixes(path):
            owners.setdefault(suffix, set()).add(path)
    return {suffix: trees[next(iter(paths))] for suffix, paths in owners.items() if len(paths) == 1}


def import_map(module: ast.Module) -> dict[str, str]:
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


def find_def(body: list[ast.stmt], name: str) -> ast.stmt | None:
    """Return the top-level def/class named *name* in *body*, or ``None``.

    Deliberately does NOT descend into ``If``/``Try``/``With`` bodies — a
    definition guarded that way is left unresolved (conservative: silence
    over a false positive) rather than risk crediting a conditional
    definition that isn't actually the one that runs.

    Args:
        body: A statement list (a module's or a class's ``body``).
        name: The def/class name to find.
    """
    for node in body:
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == name
        ):
            return node
    return None


def is_test_file(path: Path) -> bool:
    """True when *path* is a test module (name or a ``tests`` path segment)."""
    return path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts


def patch_object_target(call: ast.Call, imports: dict[str, str]) -> str | None:
    """Build a dotted target for ``patch.object(Obj, "attr")``.

    Only handles the case where *Obj* is a simple imported name — otherwise
    returns ``None`` (silent).

    Args:
        call: The ``patch.object`` call.
        imports: ``from X import Y`` map of the enclosing test file.
    """
    if len(call.args) < 2:
        return None
    attr = string_value(call.args[1])
    if attr is None:
        return None
    obj = call.args[0]
    if isinstance(obj, ast.Name) and obj.id in imports:
        return f"{imports[obj.id]}.{attr}"
    return None


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


def parse_trees(roots: list[Path]) -> tuple[dict[Path, ast.Module], list[str]]:
    """Parse every ``.py`` file under *roots*.

    Shared by every checker's CLI entry point — resolution needs BOTH source
    and tests parsed into the same tree dict.

    Args:
        roots: Files or directories to scan.

    Returns:
        ``(trees, unparsable)`` — parsed modules keyed by path, and a list of
        ``"path: error"`` strings for files the running interpreter couldn't parse.
    """
    trees: dict[Path, ast.Module] = {}
    unparsable: list[str] = []
    for file in iter_py_files(roots):
        try:
            trees[file] = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            unparsable.append(f"{file}: {exc}")
    return trees, unparsable


def report_unparsable(unparsable: list[str]) -> None:
    """Print the standard "file(s) could not be parsed" error block to stderr.

    A file this checker family could not read is a file it did NOT check —
    every checker treats that as a tool error (exit 2), never a silent skip.

    Args:
        unparsable: The ``"path: error"`` strings from :func:`parse_trees`.
    """
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


def load_baseline_keys(path: Path) -> set[str]:
    """Load a JSON regression-baseline file's finding keys, or an empty set when absent.

    Args:
        path: The baseline JSON file (a list of finding-key strings).
    """
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def resolve_call_target(call: ast.Call, imports: dict[str, str]) -> str | None:
    """Return the dotted string a ``patch``/``patch.object`` call targets.

    Args:
        call: A ``patch``/``patch.object`` call.
        imports: The test file's ``from X import Y`` map for ``patch.object`` objects.
    """
    if is_patch_call(call):
        return string_value(call.args[0]) if call.args else string_value(keyword(call, "target"))
    if is_patch_object_call(call):
        return patch_object_target(call, imports)
    return None


def new_positional_arg(call: ast.Call) -> ast.expr | None:
    """Return the positional ``new`` argument of a ``patch``/``patch.object`` call, if any.

    ``patch(target, new)`` puts ``new`` at ``args[1]``; ``patch.object(obj, "attr", new)``
    puts it at ``args[2]`` (one slot later, for the extra ``attr`` argument).

    Args:
        call: A ``patch``/``patch.object`` call.
    """
    if is_patch_call(call) and len(call.args) > 1:
        return call.args[1]
    if is_patch_object_call(call) and len(call.args) > 2:
        return call.args[2]
    return None


def make_patch_finding_checker(
    is_finding: Callable[[str, dict[str, ast.Module], ast.Call], bool | None],
) -> Callable[[ast.Call, dict[str, ast.Module], dict[str, str]], str | None]:
    """Build a ``check_patch(call, index, imports) -> str | None`` from one predicate.

    Every patch-call-shaped checker (rule 1's missing-target check, the
    async-mock and unspecced-model-mock double checks) follows the identical
    skeleton: resolve the call's dotted target, then ask ONE question of it —
    "is this a finding?" — and return the target when it is. Extracting the
    skeleton here leaves each rule's *own* logic (what makes a target
    interesting, what makes a double wrong) as the only thing that differs.

    Args:
        is_finding: ``(target, index, call) -> bool | None`` — the rule's own
            classifier. Receives the ORIGINAL call too (not just the target),
            since a double-shaped rule needs to inspect the supplied ``new``/
            ``new_callable`` argument, not just the resolved target string.

    Returns:
        A ``check_patch`` function suitable for
        :func:`collect_patch_call_findings`.
    """

    def check_patch(
        call: ast.Call, index: dict[str, ast.Module], imports: dict[str, str]
    ) -> str | None:
        """Return the target string when *call* is a finding, else ``None``.

        Args:
            call: A ``patch``/``patch.object`` call.
            index: Module index for dotted-target resolution.
            imports: The test file's ``from X import Y`` map for
                ``patch.object`` objects.
        """
        target = resolve_call_target(call, imports)
        if target is not None and is_finding(target, index, call) is True:
            return target
        return None

    return check_patch


def collect_patch_call_findings(
    trees: dict[Path, ast.Module],
    index: dict[str, ast.Module],
    check_patch: Callable[[ast.Call, dict[str, ast.Module], dict[str, str]], str | None],
) -> list[tuple[Path, int, str]]:
    """Walk every patch call in every test file, applying *check_patch* to each.

    Shared by the checker family shaped as "one ``patch``/``patch.object`` call
    site either is or isn't a finding, independent of any other call in the
    file" (``check_async_mock_target.py``, ``check_patch_target_exists.py``,
    ``check_unspecced_model_mock.py``). ``check_mock_assert_signature.py``
    does NOT fit this shape — it needs per-function binding state across
    several statements, not a flat per-call check.

    Args:
        trees: Parsed modules keyed by path (source + tests).
        index: Module index built from the same trees.
        check_patch: Per-call-site classifier returning a message string when
            *node* is a finding, else ``None``.

    Returns:
        ``(path, lineno, message)`` for every finding, across every test file.
    """
    hits: list[tuple[Path, int, str]] = []
    for path, tree in trees.items():
        if not is_test_file(path):
            continue
        imports = import_map(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                result = check_patch(node, index, imports)
                if result is not None:
                    hits.append((path, node.lineno, result))
    return hits


def run_regression_gate_cli(
    argv: list[str] | None,
    *,
    description: str,
    baseline_file: Path,
    find_violations: Callable[[dict[Path, ast.Module], dict[str, ast.Module]], list[str]],
) -> int:
    """Shared ``--baseline``/``--check`` CLI harness for a regression-only AST gate.

    Both ``check_mock_assert_signature.py`` and ``check_unspecced_model_mock.py``
    are expected to find real drift in a large patch surface, so each ships a
    JSON baseline: a NEW finding fails, and a STALE baseline entry (one that no
    longer reproduces) also fails, so the count only ever ratchets down. This
    is that CLI shape, extracted once — each caller supplies only its own
    description text, baseline path, and ``find_violations``.

    Args:
        argv: CLI argv (``None`` defaults to ``sys.argv``).
        description: argparse description text for this specific rule.
        baseline_file: Path to this rule's JSON baseline file.
        find_violations: The rule's own ``(trees, index) -> list[str]``.

    Returns:
        0 ran clean (or ``--baseline``/no-flag mode) · 1 gate failure (new or
        stale findings under ``--check``) · 2 an unparsable file.
    """
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "roots", nargs="+", type=Path, help="files or dirs — pass BOTH source and tests"
    )
    parser.add_argument(
        "--baseline", action="store_true", help="write the current findings as the baseline"
    )
    parser.add_argument(
        "--check", action="store_true", help="gate: fail on findings not in the baseline"
    )
    args = parser.parse_args(argv)

    trees, unparsable = parse_trees(args.roots)
    if unparsable:
        report_unparsable(unparsable)
        return 2

    index = build_module_index(trees)
    findings = find_violations(trees, index)

    if args.baseline:
        baseline_file.write_text(
            json.dumps(sorted(set(findings)), indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote {len(findings)} findings to {baseline_file}")
        return 0

    if not args.check:
        for finding in findings:
            print(finding)
        print(f"\nTotal: {len(findings)}")
        return 0

    baseline = load_baseline_keys(baseline_file)
    current = set(findings)
    new = [f for f in findings if f not in baseline]
    resolved = baseline - current

    for finding in new:
        print(f"NEW {finding}")
    for stale in sorted(resolved):
        print(f"STALE baseline entry (ratchet down — remove it): {stale}")

    if new or resolved:
        print(
            f"\nFAIL: {len(new)} new finding(s), {len(resolved)} stale baseline entry(ies).",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {len(current)} finding(s), all baselined; none new.")
    return 0
