"""Tests for the alembic-migration `assertive_sql.py` checker."""

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

from assertive_sql import main


def write(tmp_path: Path, source: str) -> Path:
    target = tmp_path / "m.py"
    target.write_text(source)
    return target


@pytest.mark.parametrize(
    "source",
    [
        'def up():\n    op.execute("INSERT INTO t (id) VALUES (1) ON CONFLICT DO NOTHING")\n',
        "def up():\n    stmt.on_conflict_do_nothing()\n",
    ],
)
def test_bare_on_conflict_is_banned(
    tmp_path: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write(tmp_path, source))]) == 1
    assert "banned `on-conflict-bare`" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("source", "construct"),
    [
        (
            'def up():\n    op.execute("CREATE TABLE IF NOT EXISTS t (id int)")\n',
            "ddl-if-not-exists",
        ),
        ('def up():\n    op.execute("DROP TABLE t CASCADE")\n', "drop-cascade"),
        (
            "def up():\n    op.create_index('i', 't', ['c'], if_not_exists=True)\n",
            "ddl-if-not-exists",
        ),
        (
            "def up():\n    try:\n        f()\n    except IntegrityError:\n        pass\n",
            "suppressed-integrity-error",
        ),
        (
            'def up():\n    op.execute("INSERT INTO t (id) VALUES (1) "\n'
            '"ON CONFLICT (id) DO NOTHING")\n',
            "on-conflict-target",
        ),
    ],
)
def test_tolerant_construct_without_allowance_bites(
    tmp_path: Path, source: str, construct: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write(tmp_path, source))]) == 1
    assert f"unauthorized `{construct}`" in capsys.readouterr().out


def test_allowance_with_reason_clears_and_stale_entry_bites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = write(tmp_path, 'def up():\n    op.execute("DROP TABLE t CASCADE")\n')
    site = f"{target.as_posix()}::up"
    allow = tmp_path / "allow.toml"
    allow.write_text(
        f'[[allow]]\nsite = "{site}"\nconstruct = "drop-cascade"\nreason = "drops a view"\n'
    )
    assert main([str(target), "--allowlist", str(allow)]) == 0
    target.write_text("def up():\n    pass\n")
    assert main([str(target), "--allowlist", str(allow)]) == 1
    assert "stale allow entry" in capsys.readouterr().out


def test_bare_on_conflict_cannot_be_allowlisted(tmp_path: Path) -> None:
    target = write(tmp_path, "x = 1\n")
    allow = tmp_path / "allow.toml"
    allow.write_text('[[allow]]\nsite = "a::b"\nconstruct = "on-conflict-bare"\nreason = "r"\n')
    assert main([str(target), "--allowlist", str(allow)]) == 2


def test_clean_file_and_referential_cascade_pass(tmp_path: Path) -> None:
    source = (
        '"""DROP TABLE t CASCADE in a docstring is prose."""\n'
        'SQL = "CREATE TABLE t (p int REFERENCES p(id) ON DELETE CASCADE)"\n'
    )
    assert main([str(write(tmp_path, source))]) == 0


def test_exit_zero_reports_without_failing(tmp_path: Path) -> None:
    target = write(tmp_path, 'X = "DROP TABLE t CASCADE"\n')
    assert main([str(target), "--exit-zero"]) == 0


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
