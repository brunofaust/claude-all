"""Tests for the regression-gates `gate_denominator.py` checker."""

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
        / "regression-gates"
        / "checkers"
    ),
)

from gate_denominator import main


def write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_checker_without_denominator_bites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "scripts/check_good.py", 'print(f"scanned={n}", file=sys.stderr)\n')
    write(tmp_path, "tools/checkers/silent.py", "print('ok')\n")

    assert main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("tools/checkers/silent.py:")
    assert "scanned=2" in captured.err


def test_exit_zero_reports_but_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path, "scripts/check_silent.py", "print('ok')\n")

    assert main(["--root", str(tmp_path), "--exit-zero"]) == 0
    assert "scripts/check_silent.py:" in capsys.readouterr().out


def test_all_conforming_is_clean(tmp_path: Path) -> None:
    write(tmp_path, "scripts/check_a.py", "print('scanned=1')\n")
    write(tmp_path, "scripts/check_b.py", "report_denominator(n)\n")

    assert main(["--root", str(tmp_path), "--marker", "report_denominator("]) == 0


def test_excluded_dirs_are_skipped(tmp_path: Path) -> None:
    write(tmp_path, "scripts/check_a.py", "print('scanned=1')\n")
    write(tmp_path, ".venv/lib/pkg/checkers/vendored.py", "print('ok')\n")

    assert main(["--root", str(tmp_path)]) == 0


def test_zero_scripts_fails_closed(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path)]) == 2
