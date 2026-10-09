"""Tests for the aws-architecture `lambda_reserved_env.py` checker."""

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

from lambda_reserved_env import main

LAMBDA = """
resource "aws_lambda_function" "worker" {
  function_name = "myapp-dev-worker"
  # AWS_REGION = "commented out"
  environment {
    variables = merge(local.common_env, {
      QUEUE_URL = aws_sqs_queue.q.url
      %s
    })
  }
}
"""


def test_reserved_var_bites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "main.tf"
    target.write_text(LAMBDA % 'AWS_REGION = "us-east-1"')
    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert f"{target.as_posix()}:8: aws_lambda_function.worker sets reserved env var" in out
    assert "AWS_REGION" in out


def test_clean_lambda_passes(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(LAMBDA % 'LOG_LEVEL = "INFO"')
    assert main([str(tmp_path)]) == 0


def test_ecs_task_may_set_region(tmp_path: Path) -> None:
    (tmp_path / "ecs.tf").write_text(
        'resource "aws_ecs_task_definition" "t" {\n  family = "AWS_REGION"\n}\n'
    )
    assert main([str(tmp_path)]) == 0


def test_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(LAMBDA % '"AWS_LAMBDA_FUNCTION_NAME" = "x"')
    assert main([str(tmp_path), "--exit-zero"]) == 0


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
