#!/usr/bin/env python3
"""Reminder hook for vercel-react-best-practices skill. One reminder per session."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time

FRONTEND_EXTS = (".tsx", ".jsx", ".ts", ".js", ".mjs")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(FRONTEND_EXTS):
        return 0
    if "/node_modules/" in file_path or "/dist/" in file_path:
        return 0
    # Test files are owned by the react-testing hook — bail so the two reminders
    # don't stack on the same edit.
    base = file_path.rsplit("/", 1)[-1]
    if ".test." in base or ".spec." in base or "/__tests__/" in file_path:
        return 0

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-react-best-{session_id}.flag")
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
                    "Reminder (vercel-react-best-practices, first React/Next edit this session): "
                    "watch inline-object props (new ref → re-render — useMemo); "
                    "avoid unnecessary useEffect (derive in render, lift state, or event handler); "
                    "respect server/client component boundaries (Next.js); "
                    "prefer Server Components for data fetching; "
                    "code-split heavy client trees via dynamic import."
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
