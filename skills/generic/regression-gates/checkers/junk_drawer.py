#!/usr/bin/env python3
"""Checker: ban junk-drawer module names (helpers / utils / common / misc / shared).

WHY
---
A file called ``utils`` has no owner and no contract — it is an attractor that
collects unrelated functions until it becomes a hidden god-module that everything
imports and nothing can be split. Name a module for what it OWNS. Extract the
behaviour into a named, single-purpose module instead.

This check is language-agnostic (it is purely filename-based); extend
``CODE_SUFFIXES`` for your stack.

CONTRACT
--------
Prints one ``path: message`` finding per offending file to stdout; exits 0 on
success so it composes with ``baseline_gate.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

__all__ = ["find_violations", "main"]

BANNED_STEMS: frozenset[str] = frozenset({"helpers", "utils", "util", "common", "misc", "shared"})
CODE_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb", ".java", ".kt"}
)


def find_violations(roots: list[Path]) -> list[str]:
    findings: list[str] = []
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(p for p in root.rglob("*") if p.is_file())
    for file in files:
        if file.suffix in CODE_SUFFIXES and file.stem.lower() in BANNED_STEMS:
            findings.append(
                f"{file}: junk-drawer module name {file.stem!r} — give it a name for what it "
                "owns, or fold its contents into the module that owns them"
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ban junk-drawer module names.")
    parser.add_argument("roots", nargs="+", type=Path, help="files or dirs to scan")
    args = parser.parse_args(argv)
    for finding in find_violations(args.roots):
        print(finding)
    return 0


if __name__ == "__main__":
    sys.exit(main())
