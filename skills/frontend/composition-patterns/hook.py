#!/usr/bin/env python3
"""Reminder hook for vercel-composition-patterns skill. One reminder per session."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

FRONTEND_EXTS = (".tsx", ".jsx")


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

    new_string = data.get("tool_input", {}).get("new_string", "") or ""
    if not any(
        t in new_string
        for t in (
            "interface Props",
            "type Props",
            "Props =",
            "Props:",
            "boolean",
            ": false",
            ": true",
        )
    ):
        return 0

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-composition-{session_id}.flag")
    if os.path.exists(flag):
        return 0
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(file_path)

    print(
        "Reminder (vercel-composition-patterns, first prop-touching edit this session): "
        "if adding 3+ boolean props OR conditional render branches, "
        "prefer slot / compound / asChild composition over prop sprawl. "
        "Map: 3+ booleans → variant prop; render-branch sprawl → children slots.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
