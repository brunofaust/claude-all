"""Tests for the mock-drift-sweep `unconstrained_patch.py` checker."""

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
        / "generic"
        / "mock-drift-sweep"
        / "checkers"
    ),
)

from unconstrained_patch import main

SOURCE = """
LIMIT = 5


def fetch(x):
    return x


class Client:
    def send(self):
        return 1

    @property
    def name(self):
        return "n"
"""


def make_repo(tmp_path: Path, test_body: str) -> tuple[Path, Path]:
    src = tmp_path / "src" / "myapp"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "core.py").write_text(SOURCE)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text(
        "from unittest.mock import patch, PropertyMock\n" + test_body
    )
    return tmp_path / "src", tests


@pytest.mark.parametrize(
    "line",
    [
        'patch("myapp.core.fetch")',
        'patch("myapp.core.fetch", autospec=False)',
        'patch("myapp.core.Client.send")',
        'patch("myapp.core.LIMIT")',
        'patch("myapp.core.LIMIT", new=MagicMock())',
        'patch("myapp.core.Client.name")',
    ],
)
def test_bites_on_unconstrained_patch(
    tmp_path: Path, line: str, capsys: pytest.CaptureFixture[str]
) -> None:
    src, tests = make_repo(tmp_path, f"def test_x():\n    with {line}:\n        pass\n")
    assert main([str(tests), "--src", str(src)]) == 1
    out, err = capsys.readouterr()
    assert "test_core.py:3: unconstrained-patch" in out
    assert "scanned=1" in err


@pytest.mark.parametrize(
    "line",
    [
        'patch("myapp.core.fetch", autospec=True)',
        'patch("myapp.core.LIMIT", new=7)',
        'patch("myapp.core.Client.name", new_callable=PropertyMock)',
        'patch("os.getcwd")',
    ],
)
def test_clean_when_constrained_or_unresolvable(tmp_path: Path, line: str) -> None:
    src, tests = make_repo(tmp_path, f"def test_x():\n    with {line}:\n        pass\n")
    assert main([str(tests), "--src", str(src)]) == 0


def test_exit_zero_still_prints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src, tests = make_repo(
        tmp_path, 'def test_x():\n    with patch("myapp.core.fetch"):\n        pass\n'
    )
    assert main([str(tests), "--src", str(src), "--exit-zero"]) == 0
    assert "unconstrained-patch" in capsys.readouterr().out


def test_zero_files_fails_closed(tmp_path: Path) -> None:
    empty = tmp_path / "tests"
    empty.mkdir()
    src, _ = make_repo(tmp_path / "repo", "")
    assert main([str(empty), "--src", str(src)]) == 2
    assert main([str(tmp_path / "repo" / "tests"), "--src", str(empty)]) == 2
