#!/usr/bin/env python3
"""Reminder hook for web-design-guidelines skill — fires on UI-touching files."""
from __future__ import annotations

import json
import sys

UI_EXTS = (".tsx", ".jsx", ".css", ".scss", ".sass", ".less", ".html", ".astro", ".vue", ".svelte")

# Markers that suggest interactive / accessibility-relevant UI changes.
UI_MARKERS = (
    "<button", "<Button",
    "<input", "<Input",
    "<a ", "<Link",
    "<form", "<Form",
    "<dialog", "<Dialog", "<Modal",
    "<select", "<Select",
    "aria-", "role=", "tabIndex",
    "className=", "style=",
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

    new_string = data.get("tool_input", {}).get("new_string", "") or ""
    # CSS / Astro / Vue / Svelte files: always remind. JSX/TSX: only if UI markers present.
    is_jsx = file_path.endswith((".tsx", ".jsx"))
    if is_jsx and not any(m in new_string for m in UI_MARKERS):
        return 0

    print(
        "Reminder (web-design-guidelines): "
        "verify a11y (keyboard nav, focus rings, ARIA roles), color contrast (≥ 4.5:1 normal, ≥ 3:1 large), "
        "interactive target size (≥ 44×44px), reduced-motion respect (prefers-reduced-motion), "
        "consistent spacing scale, semantic HTML over generic <div>.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
