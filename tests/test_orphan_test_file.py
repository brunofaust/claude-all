"""Tests for the mock-drift-sweep `orphan_test_file.py` checker."""

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

from orphan_test_file import main, stem_candidates


def make_repo(tmp_path: Path, tests: list[str]) -> list[str]:
    pkg = tmp_path / "src" / "myapp"
    (pkg / "core").mkdir(parents=True)
    (pkg / "core" / "__init__.py").write_text("")
    (pkg / "core" / "job_runner.py").write_text("")
    unit = tmp_path / "tests" / "unit"
    unit.mkdir(parents=True)
    for name in tests:
        (unit / name).write_text("")
    return ["--unit-tests", str(unit), "--src", str(tmp_path / "src"), "--package", "myapp"]


def test_stem_candidates() -> None:
    assert stem_candidates("a_b") == {"a_b", "a/b"}


def test_bites_on_orphan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = make_repo(tmp_path, ["test_core_job_runner.py", "test_core_gone.py"])
    assert main(args) == 1
    out, err = capsys.readouterr()
    assert "test_core_gone.py:1: orphan-test" in out
    assert "job_runner" not in out
    assert "scanned=2" in err


def test_clean_mirrors_module_and_package(tmp_path: Path) -> None:
    assert main(make_repo(tmp_path, ["test_core_job_runner.py", "test_core.py"])) == 0


def test_allow_and_exit_zero(tmp_path: Path) -> None:
    args = make_repo(tmp_path, ["test_core.py", "test_contract.py"])
    assert main([*args, "--exit-zero"]) == 0
    assert main([*args, "--allow", "test_contract.py"]) == 0


def test_zero_files_fails_closed(tmp_path: Path) -> None:
    assert main(make_repo(tmp_path, [])) == 2
    args = make_repo(tmp_path / "other", ["test_core.py"])
    assert main([*args[:2], "--src", str(tmp_path / "missing")]) == 2
