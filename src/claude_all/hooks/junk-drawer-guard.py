#!/usr/bin/env python3
"""PreToolUse hook — block CREATING a new junk-drawer module (helpers/utils/common/…).

Fires on `Write`/`Edit`/`MultiEdit`. A file called `utils`/`helpers`/`common` has
no owner and no contract — it is an attractor that collects unrelated functions
until it becomes a hidden god-module everything imports and nothing can split.
This is the edit-time layer complementing the CI-time
`regression-gates/checkers/junk_drawer.py` checker (same banned-stem list, kept
in sync): that one ratchets existing violations to zero over time; this one
stops a NEW one from being created in the first place.

Only fires when the TARGET FILE DOES NOT YET EXIST — an edit to an
already-existing legacy `utils.py` in a brownfield repo is exactly what the
CI-time ratchet is for, and blocking every edit to it forever would make the
file impossible to even shrink. Creating a brand-new file at that path is the
one moment worth stopping.

## Override

- add a `# guard:allow` comment to the content, or
- set `CLAUDE_ALL_ALLOW_JUNK_DRAWER=1`.

Exit codes: 0 = allow · 2 = block (stderr shown to Claude, edit skipped). Any
malformed input / missing key / existing file / non-code suffix / non-banned
stem -> 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

__all__ = ["main"]

# Kept in sync with regression-gates/checkers/junk_drawer.py's BANNED_STEMS.
_BANNED_STEMS: frozenset[str] = frozenset(
    {"helper", "helpers", "utils", "util", "common", "misc", "shared"}
)
_CODE_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb", ".java", ".kt"}
)
# Barrel files — the name identifies the PACKAGE, not the module, so a banned
# name one level up is the real finding. NOTE: this is deliberately a SUPERSET
# of the CI-time junk_drawer.py checker, which is stem-only and so misses
# `utils/__init__.py`. Catching it at creation is the cheap moment; widening the
# CI checker would surface pre-existing packages and needs a baseline, so that
# is a separate change.
_BARREL_STEMS: frozenset[str] = frozenset({"__init__", "index", "mod"})
# A `# guard:allow` comment anywhere in the content bypasses the guard.
_ALLOW_RE: re.Pattern[str] = re.compile(r"#\s?guard:allow")


def _message(stem: str) -> str:
    return (
        f"Creating `{stem}` — a junk-drawer module name with no owner and no contract. "
        "Name it for what it OWNS, or fold the code into the module that owns it. "
        "(Escape hatch: add `# guard:allow` or set CLAUDE_ALL_ALLOW_JUNK_DRAWER=1.)"
    )


def _junk_drawer_name(path: Path) -> str | None:
    """Return the offending name when `path` creates a junk drawer, else `None`.

    Two shapes, not one — the module form and the PACKAGE form:

    - `utils.py`            -> the stem is banned
    - `utils/__init__.py`   -> the stem is `__init__`, so a stem-only check misses
      it entirely; the banned name is the PARENT directory. This is the commonest
      Python junk drawer of the two, so missing it would gut the guard.

    Args:
        path: The file being written.

    Returns:
        The banned name to report, or `None` when this path is fine.
    """
    if path.suffix not in _CODE_SUFFIXES:
        return None
    if path.stem.lower() in _BANNED_STEMS:
        return path.stem
    # Package form: the barrel file of a directory that is itself a junk drawer.
    # Both halves lower-cased, same as the module form above — otherwise
    # `Utils/Index.ts` slips past while `UTILS.ts` is caught.
    if path.stem.lower() in _BARREL_STEMS and path.parent.name.lower() in _BANNED_STEMS:
        return path.parent.name
    return None


def _block(reason: str) -> int:
    """Print the block reason to stderr (shown to Claude) and return exit code 2.

    Args:
        reason: Human-readable explanation of why the edit was blocked.

    Returns:
        2 — the PreToolUse block exit code (the edit does NOT run).
    """
    print(f"[junk-drawer-guard] BLOCKED — {reason}", file=sys.stderr)
    return 2


def main() -> int:
    if os.environ.get("CLAUDE_ALL_ALLOW_JUNK_DRAWER") == "1":
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

    path = Path(file_path)
    if path.exists():
        return 0  # existing file — the CI-time ratchet owns this, not this guard

    offender = _junk_drawer_name(path)
    if offender is None:
        return 0

    # Only `Write` can reach here: the path does not exist yet, and Edit/MultiEdit
    # both require an existing file. So the new text is always `content` — there is
    # no `new_string`/`edits[]` shape to handle at file-creation time.
    content = str(tool_input.get("content") or "")
    if _ALLOW_RE.search(content):
        return 0

    return _block(_message(path.stem))


if __name__ == "__main__":
    sys.exit(main())
