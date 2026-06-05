#!/usr/bin/env python3
"""PostToolUse hook — accumulate edited file paths for per-response prek check.

Fires on Edit|Write|MultiEdit after the tool completes. Appends the edited
file path to a per-session temp file. The companion prek-stop-runner.py
reads this file at each Stop event, runs prek on the batch, then clears it.

This gives per-response prek feedback instead of per-session (finer feedback,
faster iteration loop) without running prek after every single file edit.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path: str = data.get("tool_input", {}).get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return 0

    # Skip non-source files (binary, lock files, generated)
    skip_suffixes = (".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff", ".woff2")
    if any(file_path.endswith(s) for s in skip_suffixes):
        return 0

    session_id: str = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "no-session")
    accumulator = os.path.join(tempfile.gettempdir(), f"cc-edited-{session_id}.txt")

    try:
        with open(accumulator, "a", encoding="utf-8") as f:
            f.write(file_path + "\n")
    except OSError:
        pass  # non-critical — skip silently

    return 0


if __name__ == "__main__":
    sys.exit(main())
