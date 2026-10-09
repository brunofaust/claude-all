"""Tests for the aws-architecture `ecs_task_def_ownership.py` checker."""

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

from ecs_task_def_ownership import main


def task_def(lifecycle: str) -> str:
    return (
        'resource "aws_ecs_task_definition" "app" {\n'
        '  family = "myapp"\n'
        f"  lifecycle {{\n    {lifecycle}\n  }}\n"
        "}\n"
    )


@pytest.mark.parametrize(
    "lifecycle",
    ["ignore_changes = [container_definitions]", "ignore_changes = all"],
)
def test_frozen_container_definitions_bite(
    tmp_path: Path, lifecycle: str, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "ecs.tf"
    target.write_text(task_def(lifecycle))
    assert main([str(tmp_path)]) == 1
    assert f"{target.as_posix()}:4: aws_ecs_task_definition.app" in capsys.readouterr().out


@pytest.mark.parametrize(
    "lifecycle",
    ["ignore_changes = [tags]", "# ignore_changes = [container_definitions]"],
)
def test_other_ignores_are_clean(tmp_path: Path, lifecycle: str) -> None:
    (tmp_path / "ecs.tf").write_text(task_def(lifecycle))
    assert main([str(tmp_path)]) == 0


def test_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "ecs.tf").write_text(task_def("ignore_changes = all"))
    assert main([str(tmp_path), "--exit-zero"]) == 0


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
