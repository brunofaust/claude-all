#!/usr/bin/env python3
"""Reminder hook for vercel-react-best-practices skill."""
from __future__ import annotations

import json
import sys

FRONTEND_EXTS = (".tsx", ".jsx", ".ts", ".js", ".mjs")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(FRONTEND_EXTS):
        return 0

    # Heuristic: skip pure server/library/test files unless obviously React.
    lower = file_path.lower()
    if "/node_modules/" in file_path or "/dist/" in file_path:
        return 0

    print(
        "Reminder (vercel-react-best-practices): "
        "watch inline-object props (new ref → re-render — useMemo); "
        "avoid unnecessary useEffect (derive in render, lift state, or event handler); "
        "respect server/client component boundaries (Next.js); "
        "prefer Server Components for data fetching; "
        "code-split heavy client trees via dynamic import.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
