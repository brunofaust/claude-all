#!/usr/bin/env python3
"""Checker: every gate/checker script must print a `scanned=N` denominator line.

WHY: a gate that prints nothing when it scanned zero files looks identical to a clean pass.
The denominator makes a vacuous pass visible. Static source check: the script passes when its
source contains a `scanned=` marker (or an extra `--marker`).
"""

import argparse
import sys
from pathlib import Path

__all__ = ["DEFAULT_GLOBS", "EXCLUDED_DIRS", "conforms", "find_scripts", "main"]

DEFAULT_GLOBS: tuple[str, ...] = ("scripts/check_*.py", "**/checkers/*.py")
EXCLUDED_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", "build"}
)


def find_scripts(root: Path, globs: list[str]) -> list[Path]:
    found: set[Path] = set()
    for pattern in globs:
        for path in root.glob(pattern):
            rel = path.relative_to(root)
            if path.is_file() and path.name != "__init__.py" and not EXCLUDED_DIRS & set(rel.parts):
                found.add(path)
    return sorted(found)


def conforms(text: str, markers: list[str]) -> bool:
    return any(marker in text for marker in markers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flag checker scripts with no scanned=N line.")
    parser.add_argument("--root", type=Path, default=Path(), help="repo root (default: cwd)")
    parser.add_argument("--glob", action="append", dest="globs", help="checker glob (repeatable)")
    parser.add_argument(
        "--marker", action="append", default=[], help="extra conforming source marker"
    )
    parser.add_argument("--exit-zero", action="store_true", help="report but exit 0")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"CANNOT CHECK: {root} is not a directory", file=sys.stderr)
        return 2
    scripts = find_scripts(root, args.globs or list(DEFAULT_GLOBS))
    print(f"scanned={len(scripts)} checker script(s)", file=sys.stderr)
    if not scripts:
        print("CANNOT CHECK: no checker scripts matched — fix the globs", file=sys.stderr)
        return 2
    markers = ["scanned=", *args.marker]
    findings = 0
    for path in scripts:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"CANNOT CHECK: {path}: {exc}", file=sys.stderr)
            return 2
        if not conforms(text, markers):
            findings += 1
            print(
                f"{path.relative_to(root).as_posix()}: never prints a `scanned=N` denominator "
                "— a zero-input run is indistinguishable from a clean pass"
            )
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
