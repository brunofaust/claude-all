#!/usr/bin/env python3
"""SessionStart reminder — warn when the repo has accumulated too many git worktrees. Fires once
per session, right as a new agent worktree is typically added, which is exactly how the pile
grows. It is a nudge, never a gate: SessionStart cannot block a tool call in Claude Code, and
this hook always exits 0 even when `git` itself fails, so a broken checkout can never break a
session start.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile

DEFAULT_WORKTREE_COUNT_THRESHOLD = 10
FLAG_TEMPLATE = "claude-all-worktree-count-nudge-{session_id}.flag"


def get_threshold() -> int:
    """Read the worktree-count warning threshold from the environment."""
    raw = os.environ.get("CLAUDE_WORKTREE_COUNT_THRESHOLD", "")
    if not raw:
        return DEFAULT_WORKTREE_COUNT_THRESHOLD
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_WORKTREE_COUNT_THRESHOLD


def count_worktrees(cwd: str) -> int | None:
    try:
        result = subprocess.run(
            ["git", "worktree", "list"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=cwd or None,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return len([line for line in result.stdout.splitlines() if line.strip()])


def build_warning(count: int, threshold: int) -> str:
    """Build the actionable reminder text shown when the count exceeds the threshold."""
    return (
        f"Worktree housekeeping: {count} git worktrees found (threshold {threshold}). "
        "Consider running a worktree/branch cleanup pass before starting new work "
        "(e.g. a git-cleanup or git-audit agent, if this project has one) — cleanup "
        "is typically blocked by uncommitted work in the primary checkout, so commit "
        "or extract that first."
    )


def main() -> int:
    """Emit the once-per-session worktree-count nudge.

    Returns:
        0 unconditionally — a session-init hook must never break the turn.
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    cwd = data.get("cwd") or os.getcwd()
    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), FLAG_TEMPLATE.format(session_id=session_id))
    if os.path.exists(flag):
        return 0  # already fired this session
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as handle:
        handle.write("worktree-count-nudge")

    threshold = get_threshold()
    count = count_worktrees(cwd)
    if count is None or count <= threshold:
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": build_warning(count, threshold),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
