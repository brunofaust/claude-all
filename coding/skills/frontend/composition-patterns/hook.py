#!/usr/bin/env python3
"""Reminder hook for vercel-composition-patterns skill."""
from __future__ import annotations

import json
import sys

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
    # Trigger only when adding/editing prop signatures or boolean props show up.
    if not any(t in new_string for t in ("interface Props", "type Props", "Props =", "Props:", "boolean", ": false", ": true")):
        return 0

    print(
        "Reminder (vercel-composition-patterns): "
        "if you are adding 3+ boolean props OR conditional render branches, "
        "prefer slot / compound / asChild composition over prop sprawl. "
        "Map: 3+ booleans → variant prop; render-branch sprawl → children slots.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
