"""Tests for the `destructive-command-guard.py` PreToolUse hook.

Drives the hook the way `claude-hooks/SKILL.md` documents testing it: pipe a
synthetic `{"tool_name": "Bash", "tool_input": {"command": ...}}` payload on
stdin and assert the exit code (0 = allow, 2 = block) — no live session
needed. This suite pins the `git stash` addition: the most important
correctness property is that `pop`/`apply`/`list`/`show`/`branch` — the
RECOVERY and read-only forms — must never block, because trapping
already-stashed work with no way back out would be worse than the bug the
block exists to prevent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "claude_all"
    / "hooks"
    / "destructive-command-guard.py"
)


def run_hook(command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the guard hook as a subprocess with a synthetic Bash payload.

    Args:
        command: The shell command string to place in `tool_input.command`.
        env: Extra environment variables to pass to the subprocess (e.g. an
            override marker), merged over a minimal clean environment.

    Returns:
        The completed subprocess, with `returncode` and captured `stdout`/`stderr`.
    """
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


# The eight forms from the task's semantics table, plus the flag-before-subcommand
# and stash-branch-recovery variants that a naive lookahead gets wrong.
BLOCKED_STASH_COMMANDS = [
    "git stash",
    "git stash push",
    "git stash save wip",
    "git stash -u",
    "git stash --include-untracked",
    "git stash drop",
    "git stash clear",
    "git -C /repo stash",  # flags before the subcommand must not slip past the anchor
    "git --no-pager stash",
]

ALLOWED_STASH_COMMANDS = [
    "git stash pop",
    "git stash apply",
    "git stash apply stash@{0}",
    "git stash list",
    "git stash show",
    "git stash show -p",
    "git -C /repo stash pop",  # flags before the subcommand must not defeat the negative lookahead
    "git --no-pager stash list",
    "git stash branch recovery-branch",  # restores an EXISTING stash — recovery, not removal
    "git stash branch recovery-branch stash@{0}",
]


@pytest.mark.parametrize("command", BLOCKED_STASH_COMMANDS)
def test_git_stash_creating_or_destroying_forms_are_blocked(command: str) -> None:
    """`git stash` forms that pull work out of, or destroy, the working tree BLOCK.

    Args:
        command: A stash-creating or stash-destroying command string.
    """
    result = run_hook(command)
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert "git stash" in result.stderr


@pytest.mark.parametrize("command", ALLOWED_STASH_COMMANDS)
def test_git_stash_recovery_or_readonly_forms_stay_allowed(command: str) -> None:
    """`git stash pop`/`apply`/`list`/`show`/`branch` never block — the critical property.

    Blocking these would trap already-stashed work with no recovery path, which
    is strictly worse than the bug the block exists to prevent. Exit 0 alone is
    not sufficient proof — a WARN path also exits 0 — so also assert the guard
    stayed silent about this command.

    Args:
        command: A recovery (`pop`/`apply`/`branch`) or read-only (`list`/`show`) command string.
    """
    result = run_hook(command)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert "git stash" not in result.stderr
    assert "git stash" not in result.stdout


def test_git_stash_override_still_bypasses_the_block() -> None:
    """`GUARD_OK=1` prefix still lets a genuinely-intended `git stash` through."""
    result = run_hook("GUARD_OK=1 git stash")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)


def test_git_stash_guard_allow_comment_still_bypasses_the_block() -> None:
    """The `# guard:allow` trailing-comment override still bypasses the block."""
    result = run_hook("git stash  # guard:allow")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
