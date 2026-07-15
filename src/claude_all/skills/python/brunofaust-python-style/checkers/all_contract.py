#!/usr/bin/env python3
"""Checker: enforce the ``__all__`` export contract — import only what a module exports.

WHY
---
``__all__`` is the real export contract. A module-level name that is not in
``__all__`` is **not public**, so importing it couples you to an implementation
detail that can move, be renamed, or vanish without notice — and without any
signal to the importer. The module never promised that name; the import invented
the promise.

This pairs with the sibling rule that **module-level names never start with an
underscore**. A leading ``_`` at module scope blinds dead-code tools — vulture
treats an underscore-prefixed module-level name as intentionally-unused and stops
reporting it, so ``_helper`` rots forever instead of being deleted. ``__all__``,
not a leading underscore, is how a module says "private": list the public names,
and everything else is private *by omission* while staying visible to tooling.

The two rules are the two halves of that contract:

  not-in-all      ``from x import y`` where ``y`` is not in ``x``'s ``__all__``.
                  Also fires on attribute access through an imported module
                  (``import myapp.core as c; c.y`` / ``myapp.core.y``) — reaching
                  in through a dot is the same coupling as reaching in through an
                  import, so checking only ``from``-imports would leave the door
                  open.
  private-in-all  ``__all__ = ["_helper"]``. Exporting an underscore name is a
                  contradiction: it declares "public" and "private" at once.
                  Drop the underscore (it is public — say so) or drop the entry.

Dunder names (``__version__``, ``__author__``, …) are always allowed: they are
protocol, not exports. Star imports are skipped — a separate rule bans them.

MODULES WITH NO ``__all__`` ARE SKIPPED
--------------------------------------
A module with no ``__all__`` has declared no contract, and Python's default is
that every module-level name is public. There is nothing to violate, so flagging
its importers would report the *importer* for the *imported* module's omission —
punishing the wrong file, and firing on every intra-repo import in a codebase
that has not adopted the convention yet, which makes the gate impossible to
adopt incrementally. "Every module must declare ``__all__``" is a real rule, but
it is a *different* rule about a *different* file; enforce it on its own.

CONTRACT
--------
Prints one ``path: [rule] symbol — message`` finding per violation to stdout and
**exits 1 when there is any finding**, so wiring it straight into prek/pre-commit
surfaces the findings and fails the commit — no baseline artifact required.

Keys are rule + enclosing symbol + the imported name, and NEVER a line number, so
an unrelated edit does not churn a baseline. ``not-in-all`` can legitimately fire
many times inside one symbol (a function touching ``c.a`` then ``c.b`` then
``c.a`` again), so its keys carry a per-symbol ordinal — a second occurrence is a
distinct finding rather than a duplicate key that collapses in a set-based
baseline and lets a regression through.

The checker owns NO state: it writes no baseline, no JSON, no cache file. If you
want the regression-only ratchet, compose it with
``regression-gates/baseline_gate.py`` and pass ``--exit-zero`` — that harness
reads a non-zero exit as "the checker crashed" and fails closed, so the flag is
required there and nowhere else.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/all_contract.py src/
    python checkers/all_contract.py --select private-in-all src/
    python checkers/all_contract.py --package myapp src/ tests/

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline all_baseline.txt -- \\
        python checkers/all_contract.py --exit-zero src/

The first-party packages are auto-detected from the roots (a ``src/`` layout, a
package dir passed directly, or a file inside one). ``--package`` narrows that
set when a repo ships several. Only first-party modules are resolved — a
third-party import has no in-repo file, so it is never checked.

PARSER NOTE — pin this hook's interpreter
-----------------------------------------
This checker parses with the ``ast`` of the interpreter it RUNS ON, so an
interpreter older than the project's silently fails to parse new syntax (PEP 695
``type X = int``, ``async def run[**P, T]``, PEP 758 ``except A, B:``). Any
Python-AST-based gate shares this: unpinned, bandit's env resolved to 3.12 and
logged "syntax error while parsing AST" for 25 files, SKIPPED them, and **still
exited success** — a security gate silently not scanning. Vulture's resolved to
3.11 and dropped 35 files from dead-code analysis the same way.

So this checker does NOT fail open. An unparsable file exits **2** (a tool error,
distinct from 1 = findings) even under ``--exit-zero``, because a file it could
not read is a file it did not check. That covers the *imported* module too: if
its ``__all__`` cannot be parsed, every import from it would silently pass.

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
import sys
from pathlib import Path

__all__ = [
    "RULES",
    "Finding",
    "check_tree",
    "discover_packages",
    "extract_all",
    "find_violations",
    "iter_py_files",
    "main",
    "module_to_path",
    "resolve_relative",
]

RULES: tuple[str, ...] = (
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
    """A finding key. Subclasses ``str`` so callers can just print it."""

    __slots__ = ()


def is_dunder(name: str) -> bool:
    """Return whether *name* is a dunder (``__version__``, ``__init__``, …).

    Dunders are protocol, not exports: they are never required to appear in
    ``__all__`` and are never rejected from it.

    Args:
        name: The identifier to classify.

    Returns:
        True when *name* both starts and ends with a double underscore.
    """
    return name.startswith("__") and name.endswith("__")


def attribute_chain(node: ast.expr) -> str | None:
    """Extract the full dotted name from nested ``Attribute``/``Name`` nodes.

    Args:
        node: An AST expression node, typically an ``ast.Attribute``.

    Returns:
        The dotted string (``"myapp.core.public_fn"``), or ``None`` when the
        chain bottoms out in something other than a bare name (a call, a
        subscript, a literal) and therefore names no module path.
    """
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
    """Walk up from *directory* to the TOPMOST directory that is still a package.

    Args:
        directory: A directory that may sit inside a package tree.

    Returns:
        The outermost directory in the unbroken chain of ``__init__.py``-bearing
        parents, or ``None`` when *directory* is not itself a package.
    """
    if not (directory / "__init__.py").exists():
        return None
    top = directory
    while (top.parent / "__init__.py").exists() and top.parent != top:
        top = top.parent
    return top


def _child_packages(directory: Path) -> dict[str, Path]:
    """Map each immediate child package of *directory* to *directory*.

    Args:
        directory: The directory to scan for package subdirectories.

    Returns:
        ``{package_name: containing_dir}`` for every child dir holding an
        ``__init__.py``; empty when *directory* is unreadable or holds none.
    """
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
    """Derive the first-party top-level packages from the scan *roots*.

    Handles the three shapes a root takes: a package dir passed directly
    (``src/myapp``), a file inside one (``src/myapp/core.py``), and a container
    of packages (``src/``, or a repo root with a ``src/`` layout).

    Args:
        roots: The files or directories the caller asked to scan.
        package: Optional top-level package name to narrow the detected set to,
            for a repo shipping several. ``None`` keeps all of them.

    Returns:
        ``{top_level_package_name: import_root}``, where ``import_root`` is the
        directory a fully-qualified module name resolves against (the ``src/``
        of a ``src/`` layout).
    """
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
    """Resolve an absolute module name to its first-party source file.

    Args:
        module_name: Fully-qualified dotted module name (``myapp.core.aws``).
        packages: The ``{package_name: import_root}`` map from
            :func:`discover_packages`.

    Returns:
        The module's ``.py`` path (its ``__init__.py`` when it is a package), or
        ``None`` when it belongs to no first-party package or is absent on disk
        (a third-party import, or a C extension).
    """
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
    """Resolve a relative import (``from ..core import x``) to a source file.

    Args:
        relative_module: The dotted suffix after the leading dots — empty for
            ``from . import name``.
        level: The number of leading dots (1 = current package, 2 = parent, …).
        current_file: Absolute path of the file containing the import.

    Returns:
        The target module's ``.py`` path, or ``None`` when it is absent on disk.
    """
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
    """Resolve an ``ImportFrom`` node to the first-party file it imports from.

    Args:
        node: The ``from X import Y`` node.
        current_file: Absolute path of the file containing the import, needed to
            anchor a relative import.
        packages: The ``{package_name: import_root}`` map.

    Returns:
        The imported module's path, or ``None`` when it is third-party, absent,
        or (for a relative import) outside every first-party package tree.
    """
    if node.level:
        target = resolve_relative(node.module or "", node.level, current_file)
        if target is None:
            return None
        inside = any(target.is_relative_to(root) for root in packages.values())
        return target if inside else None
    return module_to_path(node.module or "", packages)


def extract_all(path: Path, cache: dict[Path, frozenset[str] | None]) -> frozenset[str] | None:
    """Return the statically-declared ``__all__`` of the module at *path*.

    Args:
        path: The module file to read.
        cache: Cross-file memo of already-parsed modules, mutated in place — one
            module is typically imported by many files.

    Returns:
        The exported names, or ``None`` when the module declares no ``__all__``
        or declares one that is not a literal list/tuple of strings (a computed
        ``__all__`` is not statically knowable, so it is treated as absent).

    Raises:
        SyntaxError: When the RUNNING interpreter cannot parse *path*. NOT
            swallowed — see the PARSER NOTE in the module docstring: an
            unreadable ``__all__`` would silently green-light every import from
            this module.
        ValueError: On a null byte or similar unreadable source.
        UnicodeDecodeError: When the file is not valid UTF-8.
    """
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
        """Record a finding under a stable, line-independent key.

        Args:
            rule: The rule name; ignored when not in ``--select``.
            symbol: The enclosing qualname plus the offending imported name.
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

    def _qual(self) -> str:
        """Return the dotted name of the enclosing def/class stack.

        Returns:
            The dotted qualname, or ``"<module>"`` at module scope.
        """
        return ".".join(self._stack) or "<module>"

    def collect_imports(self, tree: ast.AST) -> None:
        """Pre-scan *tree* for first-party ``import x`` / ``import x as y`` prefixes.

        This runs BEFORE the visit pass because an import is not guaranteed to
        precede its uses in the AST walk — a module-scope ``import`` sits after a
        function that already dots into it.

        Args:
            tree: The parsed module.
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import):
                continue
            for alias in node.names:
                if alias.name.split(".")[0] not in self.packages:
                    continue
                self._prefixes[alias.asname or alias.name] = alias.name

    def _exports_of(self, module_name: str) -> frozenset[str] | None:
        """Return the ``__all__`` of a first-party module named at import time.

        Args:
            module_name: The fully-qualified dotted module name.

        Returns:
            Its exported names, or ``None`` when the module is not first-party,
            not on disk, or declares no static ``__all__``.
        """
        target = module_to_path(module_name, self.packages)
        return extract_all(target, self.cache) if target else None

    def _check_name(self, name: str, exports: frozenset[str], symbol: str, source: str) -> None:
        """Flag *name* when the module it came from does not export it.

        Args:
            name: The imported/accessed name.
            exports: The owning module's ``__all__``.
            symbol: The finding key's symbol component.
            source: Human-facing description of the offending expression.
        """
        if is_dunder(name) or name in exports:
            return
        self._add(
            "not-in-all",
            symbol,
            f"{source} — `{name}` is not in that module's __all__, so it is not public; "
            "importing it couples you to an implementation detail that can move or vanish "
            "without notice. Export it (add it to __all__) or import a name that is exported",
        )

    def _push_pop(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Visit a def/class body with its name pushed on the qualname stack.

        Args:
            node: The class, function, or coroutine definition.
        """
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track the enclosing class for finding keys.

        Args:
            node: The class definition.
        """
        self._push_pop(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track the enclosing function for finding keys.

        Args:
            node: The function definition.
        """
        self._push_pop(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track the enclosing coroutine for finding keys.

        Args:
            node: The coroutine definition.
        """
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
        """Check ``from X import Y`` against ``X``'s ``__all__``.

        Star imports are skipped (a separate rule bans them), as are imports from
        modules that are third-party or declare no ``__all__``.

        Args:
            node: The ``from X import Y`` node.
        """
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
        """Check ``c.y`` / ``myapp.core.y`` against the imported module's ``__all__``.

        Dotting into a module reaches past its export contract exactly the way a
        ``from``-import does, so both are the same rule. The chain must be the
        module prefix plus EXACTLY one component: a deeper chain is either a
        submodule (checked by its own node on the way down) or an attribute of an
        attribute, which the owning module's ``__all__`` does not govern.

        Args:
            node: The attribute access expression.
        """
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
    """Collect every violation in an already-parsed module.

    Args:
        tree: The parsed module.
        path: Path string used to key findings.
        file: Absolute path of the module, used to anchor relative imports.
        select: The rule names to report.
        packages: The ``{package_name: import_root}`` map.
        cache: Cross-file memo of module ``__all__`` sets.

    Returns:
        One finding per violation, in source order.
    """
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
    """Parse *path* and return its findings.

    Args:
        path: The Python file to scan.
        select: The rule names to report.
        packages: The ``{package_name: import_root}`` map.
        cache: Cross-file memo of module ``__all__`` sets.

    Returns:
        One finding per violation, in source order.

    Raises:
        SyntaxError: When the RUNNING interpreter cannot parse *path* or a module
            it imports from. This is deliberately NOT swallowed — see the PARSER
            NOTE in the module docstring. A file the checker could not read is a
            file it did not check; returning ``[]`` would report it clean.
        ValueError: On a null byte or similar unreadable source.
        UnicodeDecodeError: When the file is not valid UTF-8.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return check_tree(tree, path.as_posix(), path.resolve(), select, packages, cache)


def iter_py_files(roots: list[Path]) -> list[Path]:
    """Yield every ``*.py`` under *roots* (files or dirs).

    Args:
        roots: Files or directories to scan.

    Returns:
        The matching files, directory contents in sorted order.
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
        0 when clean, 1 when there are findings (unless ``--exit-zero``), 2 when
        a file could not be parsed.
    """
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
