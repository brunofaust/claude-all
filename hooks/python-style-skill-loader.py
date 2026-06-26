#!/usr/bin/env python3
"""SessionStart reminder to load the brunofaust-python-style skill.

Fires once at session start. If the session's cwd looks like a Python project
(pyproject.toml / setup.py / setup.cfg / a top-level or src/ ``*.py``), emit a
non-blocking reminder telling Claude to invoke the ``brunofaust-python-style``
skill before writing Python — the proactive bookend to the skill's own
edit-time reminder hook (``skills/python/brunofaust-python-style/hook.py``).

Dedup: writes the SAME per-session flag the edit-time hook checks
(``claude-all-brunofaust-py-<session_id>.flag``). So if this fires first, the
first ``.py`` edit stays silent — the two reminders never stack (repo rule).
In a non-Python project this writes nothing, leaving the edit hook free to fire
if a ``.py`` file is touched later.

Utility archetype: any unexpected condition → exit 0. A session-init hook must
never break the turn.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Match the edit-time companion hook's flag name so the two dedup against each other.
FLAG_TEMPLATE = "claude-all-brunofaust-py-{session_id}.flag"


def looks_like_python_project(cwd: str) -> bool:
    """True if the session's cwd resembles a Python project.

    Cheap, bounded checks only — marker files first, then a shallow scan of the
    project root and ``src/`` for any ``*.py`` (no recursive walk).

    Args:
        cwd: The session working directory reported by the hook input.
    """
    if not cwd:
        return False
    root = Path(cwd)
    for marker in ("pyproject.toml", "setup.py", "setup.cfg"):
        if (root / marker).is_file():
            return True
    for directory in (root, root / "src"):
        if not directory.is_dir():
            continue
        with contextlib.suppress(OSError):
            if any(entry.suffix == ".py" for entry in directory.iterdir()):
                return True
    return False


def main() -> int:
    """Emit the once-per-session skill-load reminder for Python projects."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — never break the turn

    cwd = data.get("cwd") or os.getcwd()
    if not looks_like_python_project(cwd):
        return 0  # match narrowly — silent in non-Python sessions

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), FLAG_TEMPLATE.format(session_id=session_id))
    if os.path.exists(flag):
        return 0  # already reminded this session (here or by the edit-time hook)
    # best-effort flag write: unwritable FS → skip the dedup, never crash
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as handle:
        handle.write("session-start")

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "Session start (Python project detected): before writing or editing "
                    "Python, invoke the brunofaust-python-style skill (Skill tool) and read "
                    "the matching references/<topic>.md (type-hints, error-handling, "
                    "async-patterns, class-design, config, testing) — don't rely on the inline "
                    "summary alone. Reminder: e2e/integration tests verify REQUIREMENTS "
                    "(the initial prompt + brainstorming + the plan/tasks before coding), "
                    "unit tests verify code."
                ),
            }
        },
        sys.stdout,
    )
    return 0  # non-blocking reminder, once per session


if __name__ == "__main__":
    sys.exit(main())
