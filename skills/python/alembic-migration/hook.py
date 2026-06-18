#!/usr/bin/env python3
"""Reminder hook for the alembic-migration skill. One reminder per session.

Fires PreToolUse on Edit|Write. If the target looks like an Alembic migration
(a `.py` file under a `versions/` / `alembic/` / `migrations/` directory), emit a
one-time, non-blocking reminder of the migration safety rules and to load the
skill. Addressed to Claude (stdout additionalContext), never the user.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

# Alembic revision files live under one of these path segments.
_MIGRATION_SEGMENTS = ("/versions/", "/alembic/", "/migrations/")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0
    if not any(seg in file_path for seg in _MIGRATION_SEGMENTS):
        return 0  # not in a migrations tree — nothing to remind

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-alembic-{session_id}.flag")
    if os.path.exists(flag):
        return 0  # already reminded this session
    # best-effort flag write: if the FS is unwritable, skip the once-per-session dedup
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(file_path)

    # exit 0 + JSON additionalContext: exit 1 stderr is shown to the USER as a hook
    # error, never to Claude — this reminder is addressed to Claude.
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "Reminder (alembic-migration, first migration edit this session): "
                    "new NOT NULL column needs a server_default (drop it in a follow-up "
                    "migration); no million-row UPDATE inside upgrade() — backfill in a "
                    "background job; ALTER TYPE ... ADD VALUE is non-transactional → its own "
                    "migration in an autocommit_block(); preview with `alembic upgrade head "
                    "--sql` and round-trip the downgrade. For non-trivial migrations invoke "
                    "the alembic-migration skill (Skill tool) for the full checklist."
                ),
            }
        },
        sys.stdout,
    )
    return 0  # non-blocking reminder, fires once per session


if __name__ == "__main__":
    sys.exit(main())
