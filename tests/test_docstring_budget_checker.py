"""Tests for the python-style `docstring_budget.py` checker.

Docs are optional (absence is clean); only oversize is a finding. Zero files or
an invalid config must fail closed with exit 2, never pass.
"""

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

from docstring_budget import main

BODY = (
    "    total = 0\n"
    + "".join(f"    total += {i} * value_{i}\n" for i in range(20))
    + "    return total\n"
)


def run(tmp_path: Path, source: str, *extra: str) -> int:
    target = tmp_path / "mod.py"
    target.write_text(source)
    return main(["--config", str(tmp_path / "pyproject.toml"), *extra, str(target)])


def test_missing_docstrings_and_comments_are_clean(tmp_path: Path) -> None:
    assert run(tmp_path, f"def compute(value):\n{BODY}") == 0


def test_short_docstring_is_clean(tmp_path: Path) -> None:
    assert (
        run(tmp_path, f'"""Short module."""\n\n\ndef compute(value):\n    """Sum it."""\n{BODY}')
        == 0
    )


def test_oversize_function_docstring_is_flagged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = "x" * 200
    assert run(tmp_path, f'def compute(value):\n    """{doc}"""\n{BODY}') == 1
    assert "function compute: docstring" in capsys.readouterr().out


def test_docstring_capped_by_code_ratio(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 60-char docstring is under the 150 max but longer than the tiny function's code.
    doc = "y" * 60
    assert run(tmp_path, f'def f():\n    """{doc}"""\n    return 1\n') == 1
    assert "function f: docstring" in capsys.readouterr().out


def test_oversize_comment_block_is_flagged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    comments = "".join(f"    # {'z' * 60}\n" for _ in range(6))
    assert run(tmp_path, f"def f():\n{comments}    return 1\n") == 1
    assert "function f: comments" in capsys.readouterr().out


@pytest.mark.parametrize(("size", "expected"), [(490, 0), (520, 1)])
def test_module_docstring_limit_is_500(tmp_path: Path, size: int, expected: int) -> None:
    assert run(tmp_path, f'"""{"m" * size}"""\n') == expected


def test_zero_files_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "empty").mkdir()
    assert main(["--config", str(tmp_path / "pyproject.toml"), str(tmp_path / "empty")]) == 2
    assert "scanned=0" in capsys.readouterr().out


def test_invalid_config_key_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.docstring-budget]\nfunction.docstring_max = 10\n"
    )
    assert run(tmp_path, "x = 1\n") == 2
    assert "unknown key" in capsys.readouterr().out


def test_wrong_config_type_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.docstring-budget]\nfunction.docstring_max_chars = "10"\n'
    )
    assert run(tmp_path, "x = 1\n") == 2


def test_config_overrides_default(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.docstring-budget]\nmodule.docstring_max_chars = 10\n"
    )
    assert run(tmp_path, '"""A module docstring past ten."""\n') == 1


def test_parse_failure_is_an_error(tmp_path: Path) -> None:
    assert run(tmp_path, "def broken(:\n") == 2


def test_scanned_denominator_is_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, "x = 1\n") == 0
    assert "scanned=1" in capsys.readouterr().out
