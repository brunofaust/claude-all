#!/usr/bin/env python3
"""Reminder hook for brunofaust-python-style skill.

Fires PreToolUse on Edit|Write. If target file is Python, emit a non-blocking
warning (exit 1) so Sonnet remembers to apply the skill's conventions.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return 0

    print(
        "Reminder (brunofaust-python-style): "
        "Python 3.14+ syntax (pipe unions, match, asyncio.TaskGroup, exception.add_note); "
        "strict type hints (TypedDict, Literal, @overload); "
        "structured logging via structlog; "
        "settings singleton (Pydantic) — don't sprinkle os.getenv across code; "
        "NEVER block the event loop in async — use run_in_thread().",
        file=sys.stderr,
    )
    return 1  # non-blocking warning


if __name__ == "__main__":
    sys.exit(main())
