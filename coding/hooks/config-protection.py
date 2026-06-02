#!/usr/bin/env python3
"""PreToolUse hook — require user confirmation before editing linter/formatter configs.

Fires on Edit|Write|MultiEdit. Pauses on prek.toml / .pre-commit-config.yaml /
.ruff.toml / ruff.toml — these are lint configs and should only be changed when
the user explicitly asks, not as a side-effect of a coding task.

On match: exits 1 (non-blocking) with a message that tells Claude to STOP and
ask the user for explicit confirmation before retrying. Claude must surface the
request to the user; it must not proceed on its own judgment.

The goal: lint configs change only when the user consciously decides to change
them, not when Claude is trying to silence a failing check.
"""

from __future__ import annotations

import json
import sys

# Files that are pure hook/lint config — pause and require user confirmation.
CONFIRM_REQUIRED: frozenset[str] = frozenset(
    [
        "prek.toml",
        ".pre-commit-config.yaml",
        ".ruff.toml",
        "ruff.toml",
    ]
)

# Files that mix legitimate edits with lint config — warn only.
WARNED: frozenset[str] = frozenset(
    [
        "pyproject.toml",
        "mypy.ini",
        "setup.cfg",
        ".flake8",
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".prettierrc",
        ".prettierrc.js",
        ".prettierrc.json",
        "tsconfig.json",
    ]
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path: str = data.get("tool_input", {}).get("file_path", "")
    filename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path

    # The Claude Code hooks + settings ARE the safety/quality gate. Neutering or
    # rewiring them (e.g. disabling a lint hook to unblock a refactor) must be a
    # conscious user decision, never a side effect. Guard them by path.
    in_claude = "/.claude/" in file_path
    if ("/.claude/hooks/" in file_path) or (
        in_claude and filename in {"settings.json", "settings.local.json"}
    ):
        print(
            f"[config-protection] STOP — `{filename}` is a Claude Code hook/settings file "
            "(the safety/quality gate). Do NOT edit, disable, or rewire it without explicit user "
            "confirmation. Surface the request to the user and wait for their yes before retrying.",
            file=sys.stderr,
        )
        return 1  # non-blocking: Claude must ask the user first

    if filename in CONFIRM_REQUIRED:
        print(
            f"[config-protection] STOP — do not edit `{filename}` without user confirmation. "
            f"Ask: 'Do you want me to modify {filename}? "
            "This is a linter/hook config.' "
            "Wait for their explicit yes before retrying.",
            file=sys.stderr,
        )
        return 1  # non-blocking: Claude must ask user, then retry

    if filename in WARNED:
        print(
            f"[config-protection] Warning: editing `{filename}`. "
            "If you're fixing a lint error, fix the CODE instead of loosening the config rule. "
            "Proceed only if this is a legitimate project-metadata or dependency change.",
            file=sys.stderr,
        )
        return 1  # non-blocking warning

    return 0


if __name__ == "__main__":
    sys.exit(main())
