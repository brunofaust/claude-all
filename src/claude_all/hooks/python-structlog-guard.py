#!/usr/bin/env python3
"""PreToolUse hook — block stdlib ``logging`` in production Python (prefer structlog).

Fires on `Edit`/`Write`/`MultiEdit`. When the new Python content imports stdlib
``logging`` (``import logging`` / ``from logging import``) or calls
``logging.getLogger``, the edit is **BLOCKED** (exit 2) so Claude rewrites using
``structlog.get_logger()`` — the logger the brunofaust-python-style skill
mandates. This is the edit-time layer complementing the skill's prek/ruff
``banned-api`` CI layer.

Exempt (allowed): non-``.py`` files, and paths under ``tests`` / ``scripts`` /
``migrations`` / ``alembic`` or a ``test_*`` basename — those legitimately use
stdlib.

## Override

- add a ``# guard:allow`` comment to the content (the logging-bootstrap module
  may legitimately keep stdlib logging), or
- set ``CLAUDE_ALL_ALLOW_STDLIB_LOGGING=1``.

Exit codes: 0 = allow · 2 = block (stderr shown to Claude, edit skipped). Any
malformed input / missing key / non-``.py`` / exempt path → 0.
"""

from __future__ import annotations

import json
import os
import re
import sys

__all__ = ["main"]

# stdlib logging import or getLogger call — the construct structlog replaces.
_BANNED_RE: re.Pattern[str] = re.compile(
    r"^import logging$|^from logging import|logging\.getLogger",
    re.MULTILINE,
)
# A `# guard:allow` comment anywhere in the content bypasses the guard.
_ALLOW_RE: re.Pattern[str] = re.compile(r"#\s?guard:allow")

_MESSAGE = (
    "stdlib `logging` is banned — use `structlog.get_logger()`. "
    "(The logging-bootstrap module may keep it: `# guard:allow` or "
    "CLAUDE_ALL_ALLOW_STDLIB_LOGGING=1.)"
)


def _is_exempt(path: str) -> bool:
    """True if the guard should skip this path (non-.py or a stdlib-legit dir).

    Args:
        path: The ``file_path`` from the tool input.

    Returns:
        True when the file is not Python or lives under tests/scripts/migrations/
        alembic (or has a ``test_*`` basename) — the guard stays silent.
    """
    norm = path.replace("\\", "/")
    if not norm.endswith(".py"):
        return True
    parts = norm.split("/")
    base = parts[-1]
    if base.startswith("test_"):
        return True
    return bool({"tests", "scripts", "migrations", "alembic"} & set(parts))


def _block(reason: str) -> int:
    """Print the block reason to stderr (shown to Claude) and return exit code 2.

    Args:
        reason: Human-readable explanation of why the edit was blocked.

    Returns:
        2 — the PreToolUse block exit code (the edit does NOT run).
    """
    print(f"[python-structlog-guard] BLOCKED — {reason}", file=sys.stderr)
    return 2


def _edited_text(tool_name: str, tool_input: dict[str, object]) -> str:
    """Return the new text this call writes, across Write / Edit / MultiEdit shapes.

    A ``MultiEdit`` carries its content in an ``edits[]`` array, not a top-level
    ``new_string`` — miss that and a MultiEdit adding the banned construct slips
    through the guard.

    Args:
        tool_name: The tool being called (``Write`` / ``Edit`` / ``MultiEdit``).
        tool_input: The tool input dict.

    Returns:
        The concatenated new text, or ``""`` when there is none.
    """
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if isinstance(edits, list):
            return "\n".join(str(e.get("new_string", "")) for e in edits if isinstance(e, dict))
        return ""
    return str(tool_input.get("new_string") or tool_input.get("content") or "")


def main() -> int:
    if os.environ.get("CLAUDE_ALL_ALLOW_STDLIB_LOGGING") == "1":
        return 0

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name not in {"Edit", "Write", "MultiEdit"}:
        return 0

    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path", "")
    if not isinstance(file_path, str) or _is_exempt(file_path):
        return 0

    content = _edited_text(tool_name, tool_input)
    if not isinstance(content, str):
        return 0

    if _ALLOW_RE.search(content):
        return 0
    if _BANNED_RE.search(content):
        return _block(_MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
