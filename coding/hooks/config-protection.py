#!/usr/bin/env python3
"""PreToolUse hook — block Claude from weakening linter/formatter configs.

Fires on Edit|Write|MultiEdit. Blocks edits to prek.toml and .pre-commit-config.yaml
(pure lint configs — no legitimate mid-task reason to touch them). Warns on
pyproject.toml (has both valid edits AND lint config sections).

The goal: steer Claude to fix the CODE, not suppress the linting rule.
"""

from __future__ import annotations

import json
import sys

# Files that are pure hook/lint config — hard-block edits.
BLOCKED: frozenset[str] = frozenset(
    [
        "prek.toml",
        ".pre-commit-config.yaml",
        ".ruff.toml",
        "ruff.toml",
    ]
)

# Files that have legitimate edits but also contain lint config — warn only.
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

    if filename in BLOCKED:
        print(
            f"[config-protection] BLOCKED: editing `{filename}` is not allowed mid-task. "
            "Fix the CODE that triggers the lint error — do not weaken the linter config. "
            "If this is intentional setup work, edit the file manually.",
            file=sys.stderr,
        )
        return 2  # hard block

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
