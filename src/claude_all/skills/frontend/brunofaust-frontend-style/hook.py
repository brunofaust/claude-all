#!/usr/bin/env python3
"""Reminder hook for the brunofaust-frontend-style skill. One reminder per session.

Fires PreToolUse on Edit|Write. When the target is a frontend source file, emits a
one-time, non-blocking reminder to load the skill (the ONE entry point for React /
browser work) with its highest-value rules. Addressed to Claude, never the user.

Covers frontend SOURCE and TEST files — the folded-in react-testing skill's own
hook is retired with it, so this one carries the testing reminder too (a test-file
edit gets the query-priority / userEvent / MSW line appended).

De-confliction — this skill sits ALONGSIDE the vendored frontend skills, which ship
their own reminder hooks. Per the "don't stack overlapping reminders" rule this
fires at most ONCE per session, so a single reminder lands per session regardless
of how many frontend files are touched.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

_FRONTEND_EXTS = (".tsx", ".jsx", ".ts", ".js", ".mjs", ".vue", ".svelte")
# Matched against the path with a leading "/" prepended, so these hit both an
# absolute path and a repo-relative one ("node_modules/x.tsx").
_SKIP_DIRS = ("/node_modules/", "/dist/", "/build/", "/.next/", "/coverage/", "/.venv/")

_REMINDER = (
    "Editing a frontend file — load the `brunofaust-frontend-style` skill (Skill tool) before "
    "non-trivial work; it is the single entry point and routes to correctness, testing, security, "
    "a11y, composition, performance and view-transitions.\n"
    "Highest-value rules: `useEffect` ONLY to sync with an external system (not derived state — "
    "compute during render; not reset-on-prop-change — use `key={id}`); state at the LOWEST level "
    "that works (local -> lift -> URL -> server-state -> context -> global); no memoization by "
    "default (React 19 compiler) — measure first; never array `index` as key on a reorderable "
    "list; `dangerouslySetInnerHTML` only on sanitized content and scheme-allowlist user URLs; "
    "no token in localStorage; semantic elements + real labels + a working keyboard path. "
    "Minimalism applies to components: no wrapper that only forwards props, no boolean-prop "
    "proliferation (compose instead)."
)


_TEST_REMINDER = (
    "\nThis is a TEST file — query priority `getByRole` -> `getByLabelText` -> text -> "
    "`getByTestId`; `userEvent` over `fireEvent`; mock at the network layer (MSW), not the "
    "component's own module; async via `findBy*`/`waitFor`, never a sleep; assert behaviour, "
    "not snapshots. -> references/react-testing.md"
)


def is_frontend_file(file_path: str) -> bool:
    """True when the path is a frontend file this skill should remind on.

    Excludes vendor/build output only — both source AND test files are covered,
    since the folded react-testing skill's own hook is retired with it.

    Args:
        file_path: The Edit/Write target path.
    """
    if not file_path.endswith(_FRONTEND_EXTS):
        return False
    # Prepend "/" so a repo-relative path ("node_modules/x.tsx") matches too.
    probe = file_path if file_path.startswith("/") else f"/{file_path}"
    return not any(skip in probe for skip in _SKIP_DIRS)


def is_test_file(file_path: str) -> bool:
    """True when the path looks like a frontend test file.

    Args:
        file_path: The Edit/Write target path.
    """
    base = file_path.rsplit("/", 1)[-1]
    return ".test." in base or ".spec." in base or "/__tests__/" in file_path


def main() -> int:
    """Emit the one-per-session reminder, or stay silent. Never breaks a turn."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name", "") not in {"Edit", "Write", "MultiEdit"}:
        return 0
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0
    file_path = tool_input.get("file_path", "")
    if not isinstance(file_path, str) or not is_frontend_file(file_path):
        return 0

    session_id = str(data.get("session_id", "unknown"))
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-frontend-style-{session_id}.flag")
    if os.path.exists(flag):
        return 0
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as fh:
        fh.write("1")

    message = _REMINDER + (_TEST_REMINDER if is_test_file(file_path) else "")
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}},
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
