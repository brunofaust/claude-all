"""Tests for the python-style `process_globals.py` checker."""

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

from process_globals import main


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("class Engine: ...\n\nengine: Engine | None = None\n", "module-lazy-slot"),
        ("from typing import Optional\n\nx: Optional[int] = None\n", "module-lazy-slot"),
        ("REGISTRY = {}\n", "module-mutable-literal"),
        ("SEEN = dict()\n", "module-mutable-literal"),
        ("from collections import defaultdict\n\nBY = defaultdict()\n", "module-mutable-literal"),
        ("import asyncio\n\nLOCK = asyncio.Lock()\n", "module-resource-instance"),
        ("from threading import RLock\n\nLOCK = RLock()\n", "module-resource-instance"),
        (
            "from contextvars import ContextVar\n\nCTX = ContextVar('c')\n",
            "module-resource-instance",
        ),
        ("import httpx\n\nclient = httpx.AsyncClient()\n", "module-resource-instance"),
        ("from lib import AsyncThing\n\nthing = AsyncThing()\n", "module-resource-instance"),
        ("class Svc: ...\n\nsvc = Svc()\n", "module-first-party-instance"),
        ("def f():\n    global X\n    X = 1\n", "global-statement"),
        ("class Reg:\n    items = []\n\n    def __init__(self): ...\n", "class-mutable-attribute"),
        (
            "class C:\n    def __init__(self): ...\n\n"
            "    @classmethod\n    def set(cls, v):\n        cls.v = v\n",
            "classmethod-mutates-class",
        ),
        (
            "class S:\n    def __new__(cls):\n        if cls.inst is None:\n"
            "            return super().__new__(cls)\n",
            "singleton-new",
        ),
        ("class Utils:\n    @staticmethod\n    def a(): ...\n", "namespace-class"),
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


def test_package_flag_flags_first_party_instance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "mod.py"
    target.write_text("from myapp.services import Billing\n\nbilling = Billing()\n")

    assert main([str(target)]) == 0
    assert main(["--package", "myapp", str(target)]) == 1
    assert "[module-first-party-instance]" in capsys.readouterr().out


def test_resource_call_flag_extends_the_list(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text("import redis\n\nPOOL = redis.ConnectionPool()\n")

    assert main([str(target)]) == 0
    assert main(["--resource-call", "redis.ConnectionPool", str(target)]) == 1


def test_clean_module(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text(
        "from collections.abc import Mapping\n"
        "from typing import Final\n"
        "from pydantic import BaseModel\n\n"
        "LIMIT: Final = {}\n"
        "TABLE: Mapping[str, int] = {}\n"
        "NAMES: tuple[str, ...] = ()\n"
        "TIMEOUT = 30\n\n"
        "class Settings(BaseModel):\n"
        "    tags: list[str] = []\n\n"
        "class Svc:\n"
        "    def __init__(self) -> None:\n"
        "        self.cache: dict[str, int] = {}\n\n"
        "async def main() -> None:\n"
        "    registry = {}\n"
    )

    assert main([str(target)]) == 0


def test_exempt_glob_and_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "mod.py"
    target.write_text("REGISTRY = {}\n")

    assert main(["--exempt", "REGISTRY", str(target)]) == 0
    assert main(["--exit-zero", str(target)]) == 0
    assert "[module-mutable-literal]" in capsys.readouterr().out


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
    assert main([]) == 2
