#!/usr/bin/env python3
"""Reminder hook for vercel-react-view-transitions skill — fires when transition APIs appear."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

FRONTEND_EXTS = (".tsx", ".jsx", ".ts", ".js", ".css")

TRANSITION_MARKERS = (
    "ViewTransition",
    "startViewTransition",
    "addTransitionType",
    "view-transition-name",
    "::view-transition",
    "framer-motion",
    "react-spring",
)


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

    tool_input = data.get("tool_input", {})
    # Edit sends `new_string`; Write sends `content` — cover both.
    new_string = tool_input.get("new_string") or tool_input.get("content") or ""
    if not any(marker in new_string for marker in TRANSITION_MARKERS):
        return 0

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-view-transitions-{session_id}.flag")
    if os.path.exists(flag):
        return 0
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
                    "Reminder (vercel-react-view-transitions, first transition-touching "
                    "edit this session): use native React View Transitions API — "
                    "<ViewTransition>, addTransitionType, CSS ::view-transition "
                    "pseudo-elements — BEFORE pulling in framer-motion / react-spring / "
                    "any third-party animation lib. Cheaper, smoother, fewer deps."
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
