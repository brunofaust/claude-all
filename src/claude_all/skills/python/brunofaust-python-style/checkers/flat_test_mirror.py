#!/usr/bin/env python3
"""Checker: enforce the FLAT source-mirrored unit-test convention.
Rules: references/enforcement.md."""

# NOTE: on the skill's 3.12 baseline (no PEP 649 lazy annotations — that is
# 3.14-only), `from __future__ import annotations` is the recommended way to keep
# forward references and TYPE_CHECKING-only imports free at runtime.
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

__all__ = ["ALLOWED_NON_TEST", "GRAB_BAG", "RULES", "Finding", "find_violations", "main"]

RULES: tuple[str, ...] = (
    "not-flat",
    "non-test-file",
    "grab-bag",
)

#: The only non-mirror filenames that may live in the unit tier. `conftest.py` is
#: pytest's own shared-fixture seam; `__init__.py` makes the tier importable.
ALLOWED_NON_TEST: frozenset[str] = frozenset({"__init__.py", "conftest.py"})

#: Suffixes that mark a parallel "somewhere else to put it" file. Deliberately
#: matched on the STEM's tail so `test_core_aws_s3_extra.py` fires while a module
#: legitimately named `test_features_extras_service.py` (mirroring
#: `features/extras/service.py`) does not.
GRAB_BAG: re.Pattern[str] = re.compile(
    r"_(extra|edges|coverage\d*|boost\d*|remaining|near_threshold)\.py$"
)

#: Directory names that are build/tool output, not authored test layout.
IGNORED_DIRS: frozenset[str] = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache"})


class Finding(str):
    """A finding key."""

    __slots__ = ()


def _relative_hint(path: Path, root: Path) -> str:
    return (root / path.name).as_posix()


def iter_test_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in sorted(root.rglob("*.py")) if not IGNORED_DIRS & set(p.parts)]


def find_violations(root: Path, select: frozenset[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_test_files(root):
        rel = path.relative_to(root)
        key = path.as_posix()

        if len(rel.parts) > 1:
            if "not-flat" in select:
                findings.append(
                    Finding(
                        f"{key}: [not-flat] nested under {root.as_posix()}/ — the unit tier is "
                        f"ONE flat folder. Move it to {_relative_hint(path, root)} (name it "
                        "test_<source path with '/' -> '_'>.py) or merge it into the matching "
                        "mirror."
                    )
                )
            continue

        name = path.name
        if name in ALLOWED_NON_TEST:
            continue

        if not name.startswith("test_"):
            if "non-test-file" in select:
                findings.append(
                    Finding(
                        f"{key}: [non-test-file] not a mirror — only test_<module>.py files "
                        "belong in the unit tier (plus conftest.py / __init__.py). Put shared "
                        "helpers in conftest.py or a real package."
                    )
                )
            continue

        if GRAB_BAG.search(name) and "grab-bag" in select:
            findings.append(
                Finding(
                    f"{key}: [grab-bag] parallel catch-all file — add these tests to the "
                    "module's mirror, not a *_extra/*_edges/*_coverage file. One module, one "
                    "test file; a second file splits the module's tests where nobody looks."
                )
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enforce the flat source-mirrored unit-test convention.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("tests/unit"),
        help="unit-test directory to scan (default: tests/unit)",
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

    scanned = len(iter_test_files(args.root))
    print(f"scanned={scanned}", file=sys.stderr)
    if not scanned:
        print("ERROR: scanned 0 files — refusing a vacuous pass", file=sys.stderr)
        return 2

    findings = find_violations(args.root, select)
    for finding in findings:
        print(finding)

    if findings and not args.exit_zero:
        print(
            f"\n{len(findings)} finding(s) — the unit tier is ONE flat folder, one file per "
            "source module, named test_<source path with '/' -> '_'>.py.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
