"""Shared file discovery for the AST checkers in this directory (imported as a sibling)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

__all__ = ["iter_py_files"]


def iter_py_files(paths: Iterable[str]) -> Iterator[Path]:
    """Yield every `*.py` under paths (files or directories), sorted."""
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from (p for p in sorted(path.rglob("*.py")) if "__pycache__" not in p.parts)
        elif path.suffix == ".py" and path.is_file():
            yield path
