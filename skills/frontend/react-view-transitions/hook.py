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

    new_string = data.get("tool_input", {}).get("new_string", "") or ""
    if not any(marker in new_string for marker in TRANSITION_MARKERS):
        return 0

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-view-transitions-{session_id}.flag")
    if os.path.exists(flag):
        return 0
    # best-effort flag write: if the FS is unwritable, skip the once-per-session dedup
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(file_path)

    print(
        "Reminder (vercel-react-view-transitions, first transition-touching edit this session): "
        "use native React View Transitions API — "
        "<ViewTransition>, addTransitionType, CSS ::view-transition pseudo-elements — "
        "BEFORE pulling in framer-motion / react-spring / any third-party animation lib. "
        "Cheaper, smoother, fewer deps.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
