#!/usr/bin/env python3
"""Reminder hook for brunofaust-python-style skill.

Fires PreToolUse on Edit|Write. If target file is Python, emit a one-time
non-blocking reminder per Claude Code session so Sonnet remembers the skill's
conventions WITHOUT flooding the transcript with the same message on every edit.

This is the HIGH-SIGNAL trigger: it fires at the moment Python is actually being
written, which is when the skill most needs loading. It dedups on its OWN flag
(`claude-all-brunofaust-py-edit-<session_id>`), independent of the SessionStart
loader (`python-style-skill-loader.py`) — so the reminder still lands on the
first real `.py` edit even when the session-start nudge already fired (that early
nudge is easy to forget dozens of turns before any Python work). At most one
session-start reminder + one first-edit reminder per session; they never pile
onto the same edit.

Session detection: Claude Code passes `session_id` in the hook input JSON.
We flag `<tmpdir>/claude-all-brunofaust-py-edit-<session_id>` on each emit and
re-fire at most **once per hour** — the flag's mtime is the last-fired time, so a
long session keeps the conventions fresh instead of being reminded only once.
Edits within the hour see a fresh flag and exit silently.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time

# Re-fire the reminder at most this often per session. A long session keeps the
# skill's conventions fresh instead of being reminded only once, hours earlier.
_REMIND_TTL_SECONDS = 3600  # 1 hour


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    # Remind at most once per hour per session (flag mtime is the last-fired time).
    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-brunofaust-py-edit-{session_id}.flag")
    with contextlib.suppress(OSError):
        if os.path.exists(flag) and (time.time() - os.path.getmtime(flag)) < _REMIND_TTL_SECONDS:
            return 0  # reminded within the last hour — stay silent
    # best-effort flag write (also resets the hourly TTL): unwritable FS → skip dedup, never crash
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(file_path)

    # exit 0 + JSON additionalContext: exit 1 stderr is shown to the USER as a hook
    # error, never to Claude — this reminder is addressed to Claude.
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "Reminder (brunofaust-python-style, Python edit — re-fires hourly): "
                    "for non-trivial Python work, invoke the brunofaust-python-style skill "
                    "(Skill tool) and read the matching references/<topic>.md "
                    "(type-hints, error-handling, async-patterns, class-design, config, testing) "
                    "before editing — don't rely on this summary alone. "
                    "Quick rules: Python 3.11+ syntax (pipe unions, match, asyncio.TaskGroup, "
                    "exception.add_note); "
                    "strict type hints (TypedDict, Literal, @overload); "
                    "structured logging via structlog; "
                    "settings singleton (Pydantic) — don't sprinkle os.getenv across code; "
                    "NEVER block the event loop in async — use run_in_thread()."
                ),
            }
        },
        sys.stdout,
    )
    return 0  # non-blocking reminder, re-fires at most once per hour


if __name__ == "__main__":
    sys.exit(main())
