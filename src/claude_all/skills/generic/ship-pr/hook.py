#!/usr/bin/env python3
"""Nudge hook for the ship-pr skill.

Fires PreToolUse on Bash. If the command is a ``git commit`` or ``git push``,
emit a one-time, non-blocking reminder per Claude Code session to route the
change through the ``/ship-pr`` workflow (gates -> review -> docs -> PR)
instead of an ad-hoc commit + PR.

A hook cannot invoke a skill, so this only reminds Claude; Claude decides
whether to run ``/ship-pr``. Deduped once per session so it does NOT fire again
on ``/ship-pr``'s own commit/push (which it performs via ``git-committer``).

Session detection: Claude Code passes ``session_id`` in the hook input JSON.
We flag ``/tmp/claude-all-ship-pr-nudge-<session_id>`` after the first emit;
later git commit/push calls in the same session see the flag and exit silently.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
import time

# `git ... commit` or `git ... push` anywhere in the command (allows `-C path`, flags, args).
_GIT_COMMIT_OR_PUSH = re.compile(r"\bgit\b[^\n]*\b(?:commit|push)\b")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block

    command = data.get("tool_input", {}).get("command", "")
    if not _GIT_COMMIT_OR_PUSH.search(command):
        return 0  # not a git commit/push — nothing to nudge

    # One nudge per session
    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-ship-pr-nudge-{session_id}.flag")
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
                    "Reminder (ship-pr, first git commit/push this session): if this change is "
                    "going out for review, route it through the /ship-pr skill instead of an "
                    "ad-hoc commit + PR — it runs simplify -> lint -> tests -> verification -> "
                    "code-review (gate) -> docs/CLAUDE.md refresh, then opens a PR (ready for "
                    "review) after confirmation. For a quick local commit with no review/PR, /ship "
                    "is lighter. "
                    "If you are ALREADY inside /ship-pr (or the user asked for a plain commit), "
                    "ignore this and proceed."
                ),
            }
        },
        sys.stdout,
    )
    return 0  # non-blocking nudge, fires once per session


if __name__ == "__main__":
    sys.exit(main())
