#!/usr/bin/env python3
"""PreToolUse hook — block raw threads/subprocess (prefer the owner wrappers). Fires on
`Edit`/`Write`/`MultiEdit`.
"""

from __future__ import annotations

import json
import os
import re
import sys

__all__ = ["main"]

# (compiled regex, replacement guidance) — each raw primitive and its owner wrapper.
_BANNED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"asyncio\.create_subprocess"),
        "`asyncio.create_subprocess*` — use `run_exec()`/`run_shell()` from the "
        "subprocess owner module",
    ),
    (
        re.compile(r"asyncio\.to_thread"),
        "`asyncio.to_thread` — use `run_in_thread()` from the thread-pool owner",
    ),
    (
        re.compile(r"ThreadPoolExecutor"),
        "`ThreadPoolExecutor` — use the `ThreadPool` owner wrapper",
    ),
]
# A `# guard:allow` comment anywhere in the content bypasses the guard.
_ALLOW_RE: re.Pattern[str] = re.compile(r"#\s?guard:allow")

_ESCAPE = (
    " (The owner module itself may keep it: `# guard:allow` or CLAUDE_ALL_ALLOW_RAW_CONCURRENCY=1.)"
)


def _is_exempt(path: str) -> bool:
    """True if the guard should skip this path (non-.py or a stdlib-legit dir). Args: path: The
    ``file_path`` from the tool input.
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
    """Print the block reason to stderr (shown to Claude) and return exit code 2."""
    print(f"[python-thread-subprocess-guard] BLOCKED — {reason}", file=sys.stderr)
    return 2


def _edited_text(tool_name: str, tool_input: dict[str, object]) -> str:
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if isinstance(edits, list):
            return "\n".join(str(e.get("new_string", "")) for e in edits if isinstance(e, dict))
        return ""
    return str(tool_input.get("new_string") or tool_input.get("content") or "")


def main() -> int:
    if os.environ.get("CLAUDE_ALL_ALLOW_RAW_CONCURRENCY") == "1":
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
    for pattern, guidance in _BANNED_PATTERNS:
        if pattern.search(content):
            return _block(guidance + _ESCAPE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
