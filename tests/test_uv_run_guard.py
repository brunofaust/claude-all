"""Tests for the `uv-run-guard.py` PreToolUse hook.

Pipes a synthetic Bash payload on stdin (with `cwd` pointing at a temp project)
and asserts the exit code: 0 = allow, 2 = block. The guard must only fire in a
uv project whose `.venv` actually provides the tool, so every block case is
paired with the case that must stay allowed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "claude_all" / "hooks" / "uv-run-guard.py"
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    for tool in ("pytest", "ruff"):
        (bin_dir / tool).write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    return tmp_path


def run_hook(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q",
        "cd src && ruff check .",
        ".venv/bin/pytest -q",
        "uvx ruff check .",
        "python3 -m pytest tests",
        "bash -c 'pytest -x'",
        "FOO=1 nohup pytest",
        "rtk pytest -q",
        "pgrep -f myapp",
    ],
)
def test_blocks_lock_bypassing_commands(project: Path, command: str) -> None:
    result = run_hook(command, project)

    assert result.returncode == 2, result.stderr
    assert "BLOCK" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest -q",
        "rtk uv run ruff check .",
        "echo pytest",
        "mypy src",
        "python3 -c 'print(1)'",
        "pgrep -x myapp",
        "GUARD_OK=1 pytest -q",
        "pytest -q # guard:allow",
        "pytest 'unterminated",
    ],
)
def test_allows_locked_or_unrelated_commands(project: Path, command: str) -> None:
    assert run_hook(command, project).returncode == 0


def test_bare_tool_is_allowed_outside_a_uv_project(tmp_path: Path) -> None:
    """Without a uv.lock there is no locked environment to bypass.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    assert run_hook("pytest -q", tmp_path).returncode == 0


def test_malformed_payload_never_blocks(tmp_path: Path) -> None:
    """A payload the hook cannot read lets the command through.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
