#!/usr/bin/env python3
"""PreToolUse hook — suggest /compact every N tool calls.

Fires on all tools (matcher ""). Counts tool calls per session in a temp file.
Every SUGGEST_EVERY calls, emits a `systemMessage` (exit 0) suggesting /compact
before the context window fills up and forces an abrupt compaction. Counting all
tool calls (not just edits) tracks context pressure more faithfully, since any
tool's output consumes the window.

Using exit 0 + JSON `systemMessage` (rather than exit 1 + stderr) surfaces this
as a normal warning to the user, not a "hook error / non-blocking status code".

Does NOT print on every call — only when the threshold is crossed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

SUGGEST_EVERY = 50  # suggest compact after this many tool calls


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    session_id: str = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "no-session")
    counter_file = os.path.join(tempfile.gettempdir(), f"cc-compact-count-{session_id}.txt")

    # Read and increment counter
    count = 0
    try:
        if os.path.exists(counter_file):
            with open(counter_file) as f:
                count = int(f.read().strip() or "0")
    except (ValueError, OSError):
        count = 0

    count += 1

    try:
        with open(counter_file, "w") as f:
            f.write(str(count))
    except OSError:
        return 0  # can't write — skip silently

    if count % SUGGEST_EVERY == 0:
        json.dump(
            {
                "systemMessage": (
                    f"[suggest-compact] {count} tool calls this session. "
                    "Consider running /compact now to keep the context window healthy "
                    "before it fills up and forces an abrupt compaction mid-task."
                )
            },
            sys.stdout,
        )
        return 0  # surfaced as a normal warning, not a hook error

    return 0


if __name__ == "__main__":
    sys.exit(main())
