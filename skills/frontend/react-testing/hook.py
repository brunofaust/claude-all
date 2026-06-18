#!/usr/bin/env python3
"""Reminder hook for the react-testing skill. One reminder per session.

Fires PreToolUse on Edit|Write. If the target is a frontend test file
(`*.test.*` / `*.spec.*` with a JS/TS extension, or anything under a
`__tests__/` directory), emit a one-time, non-blocking reminder of the testing
conventions and to load the skill. Addressed to Claude, never the user.

Complementary to react-best-practices: this fires only on test files, and that
hook bails on test files (`.test.`/`.spec.`/`__tests__/`), so exactly one
reminder fires per edit — never both on the same file.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

_TEST_EXTS = (".tsx", ".ts", ".jsx", ".js", ".mjs")


def _is_test_file(file_path: str) -> bool:
    """True if the path looks like a frontend test file.

    Args:
        file_path: The Edit/Write target path.
    """
    if "/node_modules/" in file_path or "/dist/" in file_path:
        return False
    if not file_path.endswith(_TEST_EXTS):
        return False
    base = file_path.rsplit("/", 1)[-1]
    return ".test." in base or ".spec." in base or "/__tests__/" in file_path


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not _is_test_file(file_path):
        return 0  # not a frontend test file — nothing to remind

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-react-testing-{session_id}.flag")
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
                    "Reminder (react-testing, first test-file edit this session): "
                    "query priority getByRole → getByLabelText → text → getByTestId; "
                    "prefer userEvent over fireEvent; mock at the network layer (MSW), not "
                    "modules; await findBy*/waitFor for async — never fixed sleeps; avoid "
                    "snapshot tests, assert behavior. Invoke the react-testing skill "
                    "(Skill tool) for the full guide."
                ),
            }
        },
        sys.stdout,
    )
    return 0  # non-blocking reminder, fires once per session


if __name__ == "__main__":
    sys.exit(main())
