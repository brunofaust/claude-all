"""Tests for the alembic-migration `insert_column_list.py` checker."""

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
        / "alembic-migration"
        / "checkers"
    ),
)

from insert_column_list import main


def test_column_less_insert_bites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "m.py"
    target.write_text('def up(t):\n    run(f"INSERT INTO {t} VALUES (1, 2)")\n')
    assert main([str(target)]) == 1
    assert f"{target.as_posix()}:2: column-less" in capsys.readouterr().out


@pytest.mark.parametrize(
    "source",
    [
        'SQL = "INSERT INTO t (a, b) VALUES (1, 2)"\n',
        'SQL = "INSERT INTO t SELECT * FROM s"\n',
        'SQL = "INSERT INTO t DEFAULT VALUES"\n',
        '"""INSERT INTO t VALUES (1) is fine in a docstring."""\n',
    ],
)
def test_explicit_columns_are_clean(tmp_path: Path, source: str) -> None:
    target = tmp_path / "m.py"
    target.write_text(source)
    assert main([str(target)]) == 0


def test_exit_zero(tmp_path: Path) -> None:
    target = tmp_path / "m.py"
    target.write_text('SQL = "INSERT INTO t VALUES (1)"\n')
    assert main([str(target), "--exit-zero"]) == 0


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
