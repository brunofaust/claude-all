#!/usr/bin/env python3
"""PreToolUse hook — block long-running dev server commands outside tmux.

Fires on Bash. If the command starts a dev server or long-running process
and the session is NOT inside tmux, block with a reminder to use tmux.

Without tmux, a dev server run by Claude will:
  - Block the Claude session (no further tool calls until Ctrl+C)
  - Produce logs that are invisible to Claude after the first screen
  - Be unkillable without user intervention

TMUX detection: TMUX env var is set inside any tmux session.
Backgrounded commands (`run_in_background: true`) are exempt — they don't block
the session, which is this hook's whole rationale.
Bypass: prefix the command with `CC_ALLOW_DEV_SERVER=1 ` (inline marker in the
command string — the primary escape hatch). Setting CC_ALLOW_DEV_SERVER in the
hook's own environment also works.
"""

from __future__ import annotations

import json
import os
import re
import sys

# Patterns that indicate a long-running dev server or watcher
DEV_SERVER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bnpm\s+(?:run\s+)?(?:dev|start|serve|watch)\b"),
    re.compile(r"\bpnpm\s+(?:run\s+)?(?:dev|start|serve|watch)\b"),
    re.compile(r"\byarn\s+(?:run\s+)?(?:dev|start|serve|watch)\b"),
    re.compile(r"\bnpx?\s+vite\b"),
    re.compile(r"\bnext\s+dev\b"),
    re.compile(r"\buvicorn\b.*--reload\b"),
    re.compile(r"\bfastapi\s+dev\b"),
    re.compile(r"\bflask\s+run\b"),
    re.compile(r"\bdjango.*runserver\b"),
    re.compile(r"\bpython\s+-m\s+(?:http\.server|uvicorn|flask)\b"),
    re.compile(r"\bmkdocs\s+serve\b"),
    re.compile(r"\bnodemon\b"),
    re.compile(r"\bwatchmedo\b"),
]


def strip_heredoc(command: str) -> str:
    """Remove heredoc body (<<'EOF' ... EOF) to avoid matching content inside strings.

    Args:
        command: The shell command string to strip heredoc content from.
    """
    return re.sub(r"<<['\"]?\w+['\"]?.*", "", command, flags=re.DOTALL)


def is_dev_server_command(command: str) -> bool:
    # Never trigger on git commands — commit messages / PR bodies can contain dev server examples
    first_word = command.strip().split()[0] if command.strip() else ""
    if first_word in ("git", "gh", "rtk"):
        return False
    cmd = strip_heredoc(command).strip().lower()
    return any(p.search(cmd) for p in DEV_SERVER_PATTERNS)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if os.environ.get("CC_ALLOW_DEV_SERVER"):
        return 0  # explicit bypass via the hook's own environment

    tool_input = data.get("tool_input", {})

    command: str = tool_input.get("command", "")
    if not command:
        return 0

    # Inline marker bypass: `CC_ALLOW_DEV_SERVER=1 npm run dev` sets the var in the
    # COMMAND's env, not the hook's — accept it as an explicit, auditable override.
    # Anchored to a LEADING env assignment: a mere mention of the marker (grep
    # pattern, commit message) must not bypass.
    if re.match(r"\s*(?:\w+=\S*\s+)*CC_ALLOW_DEV_SERVER=1\b", command):
        return 0

    # A backgrounded dev server doesn't block the session — the hook's whole rationale.
    if tool_input.get("run_in_background"):
        return 0

    if not is_dev_server_command(command):
        return 0

    in_tmux = bool(os.environ.get("TMUX"))
    if in_tmux:
        return 0  # already inside tmux — fine

    print(
        "[dev-server-tmux] BLOCKED: long-running dev server detected outside tmux. "
        "Starting a dev server in the main session will block Claude and hide logs. "
        "Instead: open a terminal pane, run `tmux` (or attach to an existing session), "
        "then start the server there. "
        "To bypass this check, prefix the command with `CC_ALLOW_DEV_SERVER=1 ` "
        "(or run it with run_in_background: true).",
        file=sys.stderr,
    )
    return 2  # hard block


if __name__ == "__main__":
    sys.exit(main())
