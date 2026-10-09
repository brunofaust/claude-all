"""Tests for the python-style `adhoc_cache.py` checker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent
        / "src"
        / "claude_all"
        / "skills"
        / "python"
        / "brunofaust-python-style"
        / "checkers"
    ),
)

from adhoc_cache import main


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("import functools\n\n@functools.lru_cache\ndef f(): ...\n", "lru-cache-decorator"),
        (
            "import functools\n\n@functools.lru_cache(maxsize=1)\ndef f(): ...\n",
            "lru-cache-decorator",
        ),
        ("from functools import lru_cache\n\n@lru_cache()\ndef f(): ...\n", "lru-cache-decorator"),
        ("from functools import cache\n\n@cache\nasync def f(): ...\n", "cache-decorator"),
        ("from functools import cache as memo\n\n@memo\ndef f(): ...\n", "cache-decorator"),
        ("import cachetools\n", "cache-library-import"),
        ("from diskcache import Cache\n", "cache-library-import"),
        ("import aiocache.backends\n", "cache-library-import"),
        ("from beaker.cache import CacheManager\n", "cache-library-import"),
    ],
)
def test_each_shape_bites(
    tmp_path: Path, source: str, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "mod.py"
    target.write_text(source)

    assert main([str(target)]) == 1
    out = capsys.readouterr()
    assert f"[{kind}]" in out.out
    assert f"{target.as_posix()}:" in out.out
    assert "scanned=1" in out.err


def test_cached_property_is_clean(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text(
        "import functools\nfrom functools import cached_property\n\n"
        "class A:\n"
        "    @functools.cached_property\n    def x(self): ...\n\n"
        "    @cached_property\n    def y(self): ...\n"
    )

    assert main([str(target)]) == 0


def test_allow_path_and_exit_zero(tmp_path: Path) -> None:
    target = tmp_path / "cache.py"
    target.write_text("import cachetools\n")

    (tmp_path / "other.py").write_text("X = 1\n")

    assert main([str(tmp_path)]) == 1
    assert main(["--allow-path", "*/cache.py", str(tmp_path)]) == 0
    assert main(["--exit-zero", str(target)]) == 0


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
