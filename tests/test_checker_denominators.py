"""Denominator contract: each checker prints `scanned=N` on stderr and exits 2 when N == 0."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / "src" / "claude_all" / "skills"
GATES = SKILLS / "generic" / "regression-gates" / "checkers"
STYLE = SKILLS / "python" / "brunofaust-python-style" / "checkers"

MIGRATION = 'revision = "0001"\ndown_revision = None\n'
PKG_INIT = '__all__ = ["X"]\nX = 1\n'

# (script, relative clean-file path, clean-file content, extra args, root is --root)
CASES: list[tuple[Path, str, str, list[str], bool]] = [
    (GATES / "ci_env_guard.py", "test_clean.py", "x = 1\n", [], False),
    (GATES / "junk_drawer.py", "clean.py", "x = 1\n", [], False),
    (GATES / "migration_head.py", "0001_init.py", MIGRATION, [], False),
    (GATES / "module_private.py", "clean.py", "x = 1\n", [], False),
    (STYLE / "all_contract.py", "mypkg/__init__.py", PKG_INIT, ["--package", "mypkg"], False),
    (STYLE / "flat_test_mirror.py", "test_clean.py", "x = 1\n", [], True),
    (STYLE / "lambda_event_validation.py", "handler.py", "x = 1\n", [], False),
    (STYLE / "model_contract.py", "clean.py", "x = 1\n", [], False),
    (STYLE / "pydantic_contract.py", "clean.py", "x = 1\n", [], False),
]
IDS = [case[0].stem for case in CASES]


def run(
    script: Path, root: Path, extra: list[str], as_option: bool
) -> subprocess.CompletedProcess[str]:
    target = ["--root", str(root)] if as_option else [str(root)]
    return subprocess.run(
        [sys.executable, str(script), *target, *extra],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(("script", "rel", "content", "extra", "as_option"), CASES, ids=IDS)
def test_empty_input_fails_closed(
    tmp_path: Path, script: Path, rel: str, content: str, extra: list[str], as_option: bool
) -> None:
    result = run(script, tmp_path, extra, as_option)
    assert result.returncode == 2, result.stderr
    assert "scanned=0" in result.stderr.splitlines()
    assert result.stdout == ""


@pytest.mark.parametrize(("script", "rel", "content", "extra", "as_option"), CASES, ids=IDS)
def test_empty_input_fails_closed_even_with_exit_zero(
    tmp_path: Path, script: Path, rel: str, content: str, extra: list[str], as_option: bool
) -> None:
    if "--exit-zero" not in script.read_text(encoding="utf-8"):
        pytest.skip("checker has no --exit-zero flag")
    result = run(script, tmp_path, [*extra, "--exit-zero"], as_option)
    assert result.returncode == 2, result.stderr
    assert "scanned=0" in result.stderr.splitlines()


@pytest.mark.parametrize(("script", "rel", "content", "extra", "as_option"), CASES, ids=IDS)
def test_one_clean_file_is_counted(
    tmp_path: Path, script: Path, rel: str, content: str, extra: list[str], as_option: bool
) -> None:
    clean = tmp_path / rel
    clean.parent.mkdir(parents=True, exist_ok=True)
    clean.write_text(content, encoding="utf-8")
    root = clean.parent if script.stem == "all_contract" else tmp_path
    result = run(script, root, extra, as_option)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "scanned=1" in result.stderr.splitlines()
    assert result.stdout == ""
