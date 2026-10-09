#!/usr/bin/env python3
"""Checker: a flat-mirrored unit test whose source module no longer exists.

Under the flat-mirror convention ``tests/unit/test_<a>_<b>.py`` tests ``src/<pkg>/a/b.py``.
When the module is renamed, moved or deleted the test keeps passing against nothing, so it
protects nothing. Every ``_`` in the stem may be a path separator or a literal underscore.
"""

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "Finding",
    "existing_module_paths",
    "find_violations",
    "main",
    "stem_candidates",
    "stem_is_orphan",
]

MESSAGE = (
    "orphan-test: no source module under {roots} matches this test file's name — the module "
    "was renamed/moved/deleted, or the file does not mirror one (exempt it with --allow)"
)


class Finding(NamedTuple):
    path: str
    roots: str

    def render(self) -> str:
        return f"{self.path}:1: {MESSAGE.format(roots=self.roots)}"


def stem_candidates(stem: str) -> set[str]:
    """Every reading of *stem* with each ``_`` as either ``/`` or ``_``."""
    tokens = stem.split("_")
    candidates: set[str] = set()
    for mask in range(1 << (len(tokens) - 1)):
        parts = [tokens[0]]
        for i, token in enumerate(tokens[1:]):
            parts.extend(("/" if (mask >> i) & 1 else "_", token))
        candidates.add("".join(parts))
    return candidates


def existing_module_paths(root: Path) -> set[str]:
    """Every module under *root* as an extension-less posix path (packages too)."""
    paths: set[str] = set()
    for file in root.rglob("*.py"):
        rel = file.relative_to(root).with_suffix("")
        paths.add(rel.as_posix())
        if rel.name == "__init__" and len(rel.parts) > 1:
            paths.add(rel.parent.as_posix())
    return paths


def stem_is_orphan(stem: str, existing: set[str]) -> bool:
    """True when no reading of *stem* is in *existing*."""
    return existing.isdisjoint(stem_candidates(stem))


def find_violations(tests: list[Path], roots: list[Path]) -> list[Finding]:
    """Return one finding per file in *tests* that mirrors no module under *roots*."""
    existing = set().union(*(existing_module_paths(root) for root in roots))
    label = ", ".join(root.as_posix() for root in roots)
    return [
        Finding(test.as_posix(), label)
        for test in tests
        if stem_is_orphan(test.stem.removeprefix("test_"), existing)
    ]


def main(argv: list[str] | None = None) -> int:
    """Check every ``test_*.py`` directly in ``--unit-tests`` against the roots in *argv*."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit-tests", type=Path, required=True, help="flat unit-test dir")
    parser.add_argument("--src", type=Path, required=True, help="source dir, e.g. src")
    parser.add_argument("--package", default="", help="package under --src, e.g. myapp")
    parser.add_argument(
        "--extra-root", action="append", type=Path, default=[], help="another mirrored root"
    )
    parser.add_argument("--allow", action="append", default=[], help="non-mirroring test file name")
    parser.add_argument("--exit-zero", action="store_true", help="report findings, exit 0")
    args = parser.parse_args(argv)

    roots = [args.src / args.package if args.package else args.src, *args.extra_root]
    missing = [root.as_posix() for root in [args.unit_tests, *roots] if not root.is_dir()]
    if missing:
        print(f"CANNOT CHECK: not a directory: {', '.join(missing)}", file=sys.stderr)
        return 2
    tests = sorted(
        test
        for test in args.unit_tests.glob("test_*.py")
        if test.name not in args.allow and test.stem != "test_"
    )
    print(f"scanned={len(tests)}", file=sys.stderr)
    if not tests:
        print("CANNOT CHECK: zero unit test files scanned — fix the paths.", file=sys.stderr)
        return 2

    findings = find_violations(tests, roots)
    for finding in findings:
        print(finding.render())
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
