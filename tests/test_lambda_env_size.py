"""Tests for the aws-architecture `lambda_env_size.py` checker."""

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
        / "aws"
        / "aws-architecture"
        / "checkers"
    ),
)

from lambda_env_size import main


def lambda_tf(variables: str) -> str:
    return (
        'resource "aws_lambda_function" "worker" {\n'
        "  environment {\n"
        f"    variables = {{\n{variables}\n    }}\n"
        "  }\n"
        "}\n"
    )


def test_oversized_literal_env_bites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    big = "\n".join(f'      VAR_{i} = "{"x" * 100}"' for i in range(40))
    (tmp_path / "main.tf").write_text(lambda_tf(big))
    assert main([str(tmp_path)]) == 1
    assert "aws_lambda_function.worker env is ~" in capsys.readouterr().out


def test_computed_values_count_unknown_bytes(tmp_path: Path) -> None:
    computed = "\n".join(f"      VAR_{i} = var.v{i}" for i in range(10))
    (tmp_path / "main.tf").write_text(lambda_tf(computed))
    assert main([str(tmp_path)]) == 0
    assert main([str(tmp_path), "--unknown-value-bytes", "500"]) == 1


def test_small_env_is_clean(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(lambda_tf('      LOG_LEVEL = "INFO"'))
    assert main([str(tmp_path)]) == 0


def test_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(lambda_tf('      LOG_LEVEL = "INFO"'))
    assert main([str(tmp_path), "--max-bytes", "5", "--exit-zero"]) == 0


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
