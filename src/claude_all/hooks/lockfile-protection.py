#!/usr/bin/env python3
"""PreToolUse hook — block direct edits to package-manager lockfiles.

Fires on `Edit`/`Write`/`MultiEdit`. A lockfile (`uv.lock`, `package-lock.json`,
`poetry.lock`, `Cargo.lock`, `Gemfile.lock`, `yarn.lock`, `pnpm-lock.yaml`,
`composer.lock`, `Pipfile.lock`) is a generated, hash-pinned artifact — a hand
edit desyncs it from the manifest it's supposed to mirror, and the next install
either silently overwrites your edit or fails a hash check. The edit is
**BLOCKED** (exit 2) so Claude runs the package manager's own lock command
instead (`uv lock`, `npm install`, `poetry lock`, `cargo generate-lockfile`, …).

## Override

- set `CLAUDE_ALL_ALLOW_LOCKFILE_EDITS=1` (no `# guard:allow` content escape —
  the gate is on the file's identity, not its content, so a comment inside a
  lockfile has nothing to attach to).

Exit codes: 0 = allow · 2 = block (stderr shown to Claude, edit skipped). Any
malformed input / missing key / non-lockfile path -> 0.
"""

from __future__ import annotations

import json
import os
import sys

__all__ = ["main"]

# Basenames that are always a generated lockfile, never hand-authored.
_LOCKFILE_NAMES: frozenset[str] = frozenset(
    [
        "uv.lock",
        "package-lock.json",
        "poetry.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "yarn.lock",
        "pnpm-lock.yaml",
        "composer.lock",
        "Pipfile.lock",
    ]
)

_MESSAGE = (
    "Lockfiles are generated — a hand edit desyncs it from the manifest and the "
    "next install overwrites it or fails a hash check. Run the package manager's "
    "lock command instead (`uv lock`, `npm install`, `poetry lock`, "
    "`cargo generate-lockfile`, …). (Escape hatch: CLAUDE_ALL_ALLOW_LOCKFILE_EDITS=1.)"
)


def _block(reason: str) -> int:
    """Print the block reason to stderr (shown to Claude) and return exit code 2.

    Args:
        reason: Human-readable explanation of why the edit was blocked.

    Returns:
        2 — the PreToolUse block exit code (the edit does NOT run).
    """
    print(f"[lockfile-protection] BLOCKED — {reason}", file=sys.stderr)
    return 2


def main() -> int:
    if os.environ.get("CLAUDE_ALL_ALLOW_LOCKFILE_EDITS") == "1":
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
    if not isinstance(file_path, str) or not file_path:
        return 0

    basename = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    if basename in _LOCKFILE_NAMES:
        return _block(_MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
