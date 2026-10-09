#!/usr/bin/env python3
"""Checker: enforce the ``__all__`` export contract — import only what a module exports.
Rules: references/enforcement.md."""

# NOTE: on the skill's 3.12 baseline (no PEP 649 lazy annotations — that is
# 3.14-only), `from __future__ import annotations` is the recommended way to keep
# forward references and TYPE_CHECKING-only imports free at runtime.
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

__all__ = [
    "RULES",
    "Finding",
    "check_tree",
    "declares_all",
    "discover_packages",
    "extract_all",
    "find_violations",
    "iter_py_files",
    "main",
    "module_to_path",
    "public_module_level_names",
    "resolve_relative",
]

RULES: tuple[str, ...] = (
    "missing-all",
    "not-in-all",
    "private-in-all",
)

#: Rules that can legitimately occur MANY times inside one symbol. Their keys get a
#: per-symbol ordinal, so a second occurrence is a NEW finding instead of collapsing
#: into the first one's baseline entry (which would let a regression pass the gate).
REPEATABLE = frozenset({"not-in-all"})

#: Directory names that never hold first-party source, so package auto-detection
#: must not mistake one for the project's top-level package.
NON_PACKAGE_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "build", "dist", "__pycache__", ".tox", ".mypy_cache"}
)


class Finding(str):
    """A finding key."""

    __slots__ = ()


def is_dunder(name: str) -> bool:
    """Return whether *name* is a dunder (``__version__``, ``__init__``, …)."""
    return name.startswith("__") and name.endswith("__")


def attribute_chain(node: ast.expr) -> str | None:
    parts: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _package_root_of(directory: Path) -> Path | None:
    """Walk up from *directory* to the TOPMOST directory that is still a package."""
    if not (directory / "__init__.py").exists():
        return None
    top = directory
    while (top.parent / "__init__.py").exists() and top.parent != top:
        top = top.parent
    return top


def _child_packages(directory: Path) -> dict[str, Path]:
    """Map each immediate child package of *directory* to *directory*."""
    found: dict[str, Path] = {}
    if not directory.is_dir():
        return found
    try:
        children = sorted(directory.iterdir())
    except OSError:
        return found
    for child in children:
        if child.name in NON_PACKAGE_DIRS or not child.is_dir():
            continue
        if (child / "__init__.py").exists():
            found[child.name] = directory
    return found


def discover_packages(roots: list[Path], package: str | None = None) -> dict[str, Path]:
    packages: dict[str, Path] = {}
    for root in roots:
        resolved = root.resolve()
        directory = resolved.parent if resolved.is_file() else resolved
        if top := _package_root_of(directory):
            packages[top.name] = top.parent
            continue
        packages.update(_child_packages(directory))
        packages.update(_child_packages(directory / "src"))
    if package is not None:
        packages = {name: root for name, root in packages.items() if name == package}
    return packages


def module_to_path(module_name: str, packages: dict[str, Path]) -> Path | None:
    if not module_name:
        return None
    import_root = packages.get(module_name.split(".")[0])
    if import_root is None:
        return None
    rel = import_root / Path(*module_name.split("."))
    pkg = rel / "__init__.py"
    if pkg.exists():
        return pkg
    mod = rel.with_suffix(".py")
    return mod if mod.exists() else None


def resolve_relative(relative_module: str, level: int, current_file: Path) -> Path | None:
    current_pkg = current_file.parent
    for _ in range(level - 1):
        current_pkg = current_pkg.parent
    target = current_pkg / Path(*relative_module.split(".")) if relative_module else current_pkg
    pkg = target / "__init__.py"
    if pkg.exists():
        return pkg
    mod = target.with_suffix(".py")
    return mod if mod.exists() else None


def resolve_import_module(
    node: ast.ImportFrom, current_file: Path, packages: dict[str, Path]
) -> Path | None:
    if node.level:
        target = resolve_relative(node.module or "", node.level, current_file)
        if target is None:
            return None
        inside = any(target.is_relative_to(root) for root in packages.values())
        return target if inside else None
    return module_to_path(node.module or "", packages)


def extract_all(path: Path, cache: dict[Path, frozenset[str] | None]) -> frozenset[str] | None:
    if path in cache:
        return cache[path]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: frozenset[str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List | ast.Tuple):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        names = frozenset(
            elt.value
            for elt in node.value.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        )
        break
    cache[path] = names
    return names


def declares_all(tree: ast.Module) -> bool:
    """Return whether *tree* declares ``__all__`` at module scope, in either form."""
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == "__all__"
        ):
            return True
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets
        ):
            return True
    return False


def public_module_level_names(tree: ast.Module) -> list[str]:
    return [
        stmt.name
        for stmt in tree.body
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and not stmt.name.startswith("_")
    ]


class _Visitor(ast.NodeVisitor):
    """Walks a module collecting ``__all__``-contract violations with line-free keys."""

    def __init__(
        self,
        path: str,
        file: Path,
        select: frozenset[str],
        packages: dict[str, Path],
        cache: dict[Path, frozenset[str] | None],
    ) -> None:
        self.path = path
        self.file = file
        self.select = select
        self.packages = packages
        self.cache = cache
        self.findings: list[Finding] = []
        self._stack: list[str] = []
        self._ordinals: dict[tuple[str, str], int] = {}
        #: `{source-text dotted prefix: module name}` for every first-party
        #: `import myapp.core` / `import myapp.core as c`. An alias is just a
        #: one-part prefix, so `c.x` and `myapp.core.x` take the same code path.
        self._prefixes: dict[str, str] = {}

    def _add(self, rule: str, symbol: str, message: str) -> None:
        if rule not in self.select:
            return
        if rule in REPEATABLE:
            slot = (rule, symbol)
            ordinal = self._ordinals.get(slot, 0)
            self._ordinals[slot] = ordinal + 1
            symbol = f"{symbol}#{ordinal}"
        self.findings.append(Finding(f"{self.path}: [{rule}] {symbol} — {message}"))

    def _qual(self) -> str:
        """Return the dotted name of the enclosing def/class stack."""
        return ".".join(self._stack) or "<module>"

    def collect_imports(self, tree: ast.AST) -> None:
        """Pre-scan *tree* for first-party ``import x`` / ``import x as y`` prefixes."""
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import):
                continue
            for alias in node.names:
                if alias.name.split(".")[0] not in self.packages:
                    continue
                self._prefixes[alias.asname or alias.name] = alias.name

    def _exports_of(self, module_name: str) -> frozenset[str] | None:
        target = module_to_path(module_name, self.packages)
        return extract_all(target, self.cache) if target else None

    def _check_name(self, name: str, exports: frozenset[str], symbol: str, source: str) -> None:
        if is_dunder(name) or name in exports:
            return
        self._add(
            "not-in-all",
            symbol,
            f"{source} — `{name}` is not in that module's __all__, so it is not public; "
            "importing it couples you to an implementation detail that can move or vanish "
            "without notice. Export it (add it to __all__) or import a name that is exported",
        )

    def visit_Module(self, node: ast.Module) -> None:
        if not declares_all(node) and public_module_level_names(node):
            self._add(
                "missing-all",
                "<module>",
                "defines a public module-level def/class but declares no __all__, so it "
                "has no export contract — `not-in-all` cannot verify imports FROM it, and "
                "deleting __all__ becomes an escape hatch out of the whole gate. A module "
                "with public names and no __all__ also breaks mypy strict's "
                'no_implicit_reexport ("Module X does not explicitly export attribute Y"). '
                "Declare __all__ = [...] listing the public API",
            )
        self.generic_visit(node)

    def _push_pop(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._push_pop(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._push_pop(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._push_pop(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check an ``__all__ = [...]`` assignment for underscore-prefixed entries.

        Args:
            node: The assignment statement.
        """
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return
        if not isinstance(node.value, ast.List | ast.Tuple):
            return
        for elt in node.value.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                continue
            name = elt.value
            if not name.startswith("_") or is_dunder(name):
                continue
            self._add(
                "private-in-all",
                f"{self._qual()}[{name}]",
                f"`__all__` entry {name!r} starts with an underscore — that declares "
                "'public' and 'private' at once. __all__ IS how a module says private: "
                "omit the name. A leading underscore at module scope also blinds "
                "dead-code tools, so the name rots instead of being deleted",
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = [alias.name for alias in node.names if alias.name != "*"]
        if not names:
            return
        target = resolve_import_module(node, self.file, self.packages)
        if target is None:
            return
        exports = extract_all(target, self.cache)
        if exports is None:
            return
        module = "." * node.level + (node.module or "")
        for name in names:
            self._check_name(
                name,
                exports,
                f"{self._qual()}({module}.{name})",
                f"`from {module} import {name}`",
            )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        chain = attribute_chain(node)
        if chain is not None and "." in chain:
            prefix, _, name = chain.rpartition(".")
            if (module := self._prefixes.get(prefix)) and (
                exports := self._exports_of(module)
            ) is not None:
                self._check_name(name, exports, f"{self._qual()}({prefix}.{name})", f"`{chain}`")
        self.generic_visit(node)


def check_tree(
    tree: ast.AST,
    path: str,
    file: Path,
    select: frozenset[str],
    packages: dict[str, Path],
    cache: dict[Path, frozenset[str] | None],
) -> list[Finding]:
    visitor = _Visitor(path, file, select, packages, cache)
    visitor.collect_imports(tree)
    visitor.visit(tree)
    return visitor.findings


def find_violations(
    path: Path,
    select: frozenset[str],
    packages: dict[str, Path],
    cache: dict[Path, frozenset[str] | None],
) -> list[Finding]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return check_tree(tree, path.as_posix(), path.resolve(), select, packages, cache)


def iter_py_files(roots: list[Path]) -> list[Path]:
    """Yield every ``*.py`` under *roots* (files or dirs)."""
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enforce the __all__ export contract.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("roots", nargs="+", type=Path, help="files or dirs to scan")
    parser.add_argument(
        "--package",
        default=None,
        help="top-level first-party package name (default: auto-detect from the roots)",
    )
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

    packages = discover_packages(args.roots, args.package)
    # Fail CLOSED: with no first-party package resolved, `not-in-all` can never
    # fire and the gate would report a broken repo clean.
    if not packages and "not-in-all" in select:
        parser.error(
            "no first-party package found under the given roots — `not-in-all` would "
            "silently check nothing. Pass a package dir or a `src/` layout, or name it "
            "with --package"
        )

    count = 0
    unparsable: list[str] = []
    cache: dict[Path, frozenset[str] | None] = {}
    for file in iter_py_files(args.roots):
        try:
            findings = find_violations(file, select, packages, cache)
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
            f"\n{count} finding(s) — __all__ is the export contract; "
            "importing past it couples you to an implementation detail.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
