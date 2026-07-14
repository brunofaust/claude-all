#!/usr/bin/env python3
"""Reminder hook for the alembic-migration skill. One reminder per session.

Fires PreToolUse on Edit|Write. If the target looks like an Alembic migration,
emit a one-time, non-blocking reminder of the migration safety rules and to load
the skill. Addressed to Claude (stdout additionalContext), never the user.

Matching avoids firing Alembic-specific advice on non-Alembic stacks: a
`versions/` or `alembic/` path segment is Alembic-specific and fires on its own,
but a bare `migrations/` (also used by Django, etc.) fires ONLY when the edited
content carries an Alembic signal (`down_revision`, `op.`, `import alembic`).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time

# Alembic-specific path segments — fire on their own.
_STRONG_SEGMENTS = ("/versions/", "/alembic/")
# Ambiguous segment (Django et al. also use it) — needs a content signal too.
_WEAK_SEGMENT = "/migrations/"
# Alembic fingerprints in the file body (revision graph + migration ops API).
_ALEMBIC_SIGNALS = ("down_revision", "from alembic", "import alembic", "op.", "revision =")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    strong = any(seg in file_path for seg in _STRONG_SEGMENTS)
    weak = _WEAK_SEGMENT in file_path
    if not (strong or weak):
        return 0  # not in a migrations tree — nothing to remind
    if not strong:
        # Only a bare `migrations/` match — require an Alembic signal in the edit
        # so we don't fire Alembic advice on a Django (etc.) migration.
        blob = " ".join(str(tool_input.get(k, "")) for k in ("content", "new_string", "old_string"))
        if not any(sig in blob for sig in _ALEMBIC_SIGNALS):
            return 0

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-alembic-{session_id}.flag")
    # re-fire at most once per hour (flag mtime = last-fired time), so a long
    # session keeps the conventions fresh instead of being reminded only once.
    with contextlib.suppress(OSError):
        if os.path.exists(flag) and (time.time() - os.path.getmtime(flag)) < 3600:
            return 0  # reminded within the last hour
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
