#!/usr/bin/env python3
"""Nudge hook for the merge-main skill.

Fires PreToolUse on Bash. If the command merges or pulls ``origin/main`` (a bare
``git merge origin/main`` / ``git pull origin main`` and friends), emit a
one-time, non-blocking reminder per Claude Code session to route the merge
through the ``/merge-main`` workflow (no-commit merge -> semantic conflict pass
-> gates -> finalize) instead of a bare merge that trusts a clean textual result.

A hook cannot invoke a skill, so this only reminds Claude; Claude decides
whether to run ``/merge-main``. Deduped once per session so it does NOT fire
again on ``/merge-main``'s own merge command.

Session detection: Claude Code passes ``session_id`` in the hook input JSON.
We flag ``/tmp/claude-all-merge-main-nudge-<session_id>`` after the first emit;
later matching calls in the same session see the flag and exit silently.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
import time

# `git ... merge ... origin/main` or `git ... pull ... origin ... main` anywhere
# in the command (allows `-C path`, flags, args, and `origin/main` or `origin main`).
_GIT_MERGE_MAIN = re.compile(r"\bgit\b[^\n]*\b(?:merge|pull)\b[^\n]*\borigin[\s/]+main\b")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block

    command = data.get("tool_input", {}).get("command", "")
    if not _GIT_MERGE_MAIN.search(command):
        return 0  # not a merge/pull of origin/main — nothing to nudge

    # One nudge per session
    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-merge-main-nudge-{session_id}.flag")
    # re-fire at most once per hour (flag mtime = last-fired time), so a long
    # session keeps the conventions fresh instead of being reminded only once.
    with contextlib.suppress(OSError):
        if os.path.exists(flag) and (time.time() - os.path.getmtime(flag)) < 3600:
            return 0  # reminded within the last hour
    # best-effort flag write: if the FS is unwritable, skip the once-per-session dedup
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(command[:200])

    # exit 0 + JSON additionalContext: the message is addressed to Claude, not the user
    # (exit 1 stderr is shown to the USER as a hook error, never to Claude).
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "Reminder (merge-main, first origin/main merge this session): a clean "
                    "textual merge can still be semantically broken (main touched a file this "
                    "branch deleted, changed a contract this branch still calls, or removed a "
                    "symbol this branch references). Consider routing this through the "
                    "/merge-main skill instead of a bare merge — it checks the incoming change "
                    "semantically before merging, then resolves both textual and semantic "
                    "conflicts and validates with the lint/test gates, only stopping to ask on "
                    "huge/high-risk differences. If you are ALREADY inside /merge-main (or the "
                    "user explicitly asked for a plain merge), ignore this and proceed."
                ),
            }
        },
        sys.stdout,
    )
    return 0  # non-blocking nudge, fires once per session


if __name__ == "__main__":
    sys.exit(main())
