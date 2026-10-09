"""Tests for the python-style `unlocked_singleton.py` checker."""

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

from unlocked_singleton import main

UNLOCKED = (
    "POOL = None\n\n"
    "def get_pool():\n"
    "    global POOL\n"
    "    if POOL is None:\n"
    "        POOL = build()\n"
    "    return POOL\n"
)


@pytest.mark.parametrize(
    "source",
    [
        UNLOCKED,
        "POOL = None\n\nasync def get():\n    global POOL\n    if not POOL:\n"
        "        POOL = await build()\n    return POOL\n",
    ],
)
def test_unlocked_lazy_singleton_bites(
    tmp_path: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "mod.py"
    target.write_text(source)

    assert main([str(target)]) == 1
    out = capsys.readouterr()
    assert f"{target.as_posix()}:" in out.out
    assert "'POOL'" in out.out
    assert "scanned=1" in out.err


@pytest.mark.parametrize(
    "source",
    [
        "import threading\n\nPOOL = None\nLOCK = threading.Lock()\n\n"
        "def get_pool():\n    global POOL\n    if POOL is None:\n"
        "        with LOCK:\n            if POOL is None:\n                POOL = build()\n"
        "    return POOL\n",
        "POOL = None\n\nasync def get(self):\n    global POOL\n"
        "    async with self._init_lock:\n        if POOL is None:\n            POOL = build()\n",
        "def f(x):\n    if x is None:\n        x = 1\n    return x\n",
    ],
)
def test_locked_or_local_is_clean(tmp_path: Path, source: str) -> None:
    target = tmp_path / "mod.py"
    target.write_text(source)

    assert main([str(target)]) == 0


def test_lock_hint_flag_and_exit_zero(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text(
        "POOL = None\n\ndef get():\n    global POOL\n    with ONCE:\n"
        "        if POOL is None:\n            POOL = build()\n"
    )

    assert main([str(target)]) == 1
    assert main(["--lock-hint", "ONCE", str(target)]) == 0
    assert main(["--exit-zero", str(target)]) == 0


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
