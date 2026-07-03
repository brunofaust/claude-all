#!/usr/bin/env python3
"""PreToolUse hook — require user confirmation before editing linter/formatter configs.

Fires on Edit|Write|MultiEdit. Pauses on prek.toml / .pre-commit-config.yaml /
.ruff.toml / ruff.toml — these are lint configs and should only be changed when
the user explicitly asks, not as a side-effect of a coding task.

On a confirm-required match (lint configs, Claude Code hooks/settings): exits 0
and emits `hookSpecificOutput.permissionDecision: "ask"` — the harness PAUSES the
tool call and asks the user for approval, with the explanation shown as the
`permissionDecisionReason`. The edit only proceeds if the user explicitly
approves it.

On a warn-only match (mixed-purpose files like pyproject.toml): exits 0 and emits
`hookSpecificOutput.additionalContext` (a system reminder injected into Claude's
context). Using exit 0 + JSON (rather than exit 1 + stderr) keeps the reminder
from being rendered as a "hook error" — it is guidance, not a failure, and the
edit still proceeds.

The goal: lint configs change only when the user consciously decides to change
them, not when Claude is trying to silence a failing check.
"""

from __future__ import annotations

import json
import sys

__all__ = ["main"]


def remind(message: str) -> int:
    """Emit a non-error reminder into Claude's context, then allow the tool.

    Prints PreToolUse JSON to stdout (exit 0) so the message appears as a system
    reminder rather than a "hook error". Non-blocking: the edit still proceeds.

    Args:
        message: The guidance text injected into Claude's context.

    Returns:
        0 — always (the hook never blocks; it only nudges).
    """
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": message,
            }
        },
        sys.stdout,
    )
    return 0


def ask(reason: str) -> int:
    """Pause the tool call and ask the user for explicit approval.

    Prints PreToolUse JSON with `permissionDecision: "ask"` to stdout (exit 0) so
    the harness halts the edit and shows `reason` to the user as the approval
    prompt. Unlike `remind`, the edit does NOT proceed unless the user approves.

    Args:
        reason: Explanation shown to the user in the approval prompt.

    Returns:
        0 — always (the decision itself is carried in the JSON payload).
    """
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    return 0


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
        return ask(
            f"[config-protection] `{filename}` is a Claude Code hook/settings file "
            "(the safety/quality gate). Editing, disabling, or rewiring it requires explicit "
            "user approval."
        )

    if filename in CONFIRM_REQUIRED:
        return ask(
            f"[config-protection] `{filename}` is a linter/hook config. It should only change "
            "when the user consciously decides to change it (not to silence a failing check). "
            "Approve to allow this edit."
        )

    if filename in WARNED:
        return remind(
            f"[config-protection] Warning: editing `{filename}`. "
            "If you're fixing a lint error, fix the CODE instead of loosening the config rule. "
            "Proceed only if this is a legitimate project-metadata or dependency change."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
