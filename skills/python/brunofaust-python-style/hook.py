#!/usr/bin/env python3
"""Reminder hook for brunofaust-python-style skill.

Fires PreToolUse on Edit|Write. If target file is Python, emit a one-time
non-blocking reminder per Claude Code session so Sonnet remembers the skill's
conventions WITHOUT flooding the transcript with the same message on every edit.

Session detection: Claude Code passes `session_id` in the hook input JSON.
We flag `/tmp/claude-all-brunofaust-py-<session_id>` after the first emit; later
edits in the same session see the flag and exit silently.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    # One reminder per session
    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-brunofaust-py-{session_id}.flag")
    if os.path.exists(flag):
        return 0  # already reminded this session
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(file_path)

    print(
        "Reminder (brunofaust-python-style, first Python edit this session): "
        "Python 3.14+ syntax (pipe unions, match, asyncio.TaskGroup, exception.add_note); "
        "strict type hints (TypedDict, Literal, @overload); "
        "structured logging via structlog; "
        "settings singleton (Pydantic) — don't sprinkle os.getenv across code; "
        "NEVER block the event loop in async — use run_in_thread(). "
        "Read references/<topic>.md for deep coverage on: "
        "type-hints, error-handling, async-patterns, class-design, config, testing.",
        file=sys.stderr,
    )
    return 1  # non-blocking warning, but only fires once per session


if __name__ == "__main__":
    sys.exit(main())
