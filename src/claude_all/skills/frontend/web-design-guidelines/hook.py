#!/usr/bin/env python3
"""Reminder hook for web-design-guidelines skill — fires on UI-touching files."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

UI_EXTS = (
    ".tsx",
    ".jsx",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".html",
    ".astro",
    ".vue",
    ".svelte",
)

# Markers that suggest interactive / accessibility-relevant UI changes.
UI_MARKERS = (
    "<button",
    "<Button",
    "<input",
    "<Input",
    "<a ",
    "<Link",
    "<form",
    "<Form",
    "<dialog",
    "<Dialog",
    "<Modal",
    "<select",
    "<Select",
    "aria-",
    "role=",
    "tabIndex",
    "className=",
    "style=",
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(UI_EXTS):
        return 0
    if "/node_modules/" in file_path or "/dist/" in file_path:
        return 0

    tool_input = data.get("tool_input", {})
    # Edit sends `new_string`; Write sends `content` — cover both.
    new_string = tool_input.get("new_string") or tool_input.get("content") or ""
    # CSS / Astro / Vue / Svelte files: always remind. JSX/TSX: only if UI markers present.
    is_jsx = file_path.endswith((".tsx", ".jsx"))
    if is_jsx and not any(m in new_string for m in UI_MARKERS):
        return 0

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-web-design-{session_id}.flag")
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
                    "Reminder (web-design-guidelines, first UI edit this session): "
                    "verify a11y (keyboard nav, focus rings, ARIA roles), "
                    "color contrast (>= 4.5:1 normal, >= 3:1 large), "
                    "interactive target size (>= 44x44px), reduced-motion "
                    "(prefers-reduced-motion), consistent spacing scale, "
                    "semantic HTML over generic <div>."
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
