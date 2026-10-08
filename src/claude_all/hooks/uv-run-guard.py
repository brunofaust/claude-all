#!/usr/bin/env python3
"""PreToolUse hook — keep agent Bash commands on the project's locked uv environment.

Fires on the `Bash` tool and BLOCKS (exit 2, with the fix on stderr):

- In a uv project (a `uv.lock` in the working directory or a parent), a
  project tool invoked outside `uv run` while the project's `.venv` provides
  it: bare `pytest`, `.venv/bin/pytest`, `uvx ruff`, `python -m mypy`. Those
  resolve a global or unlocked version, so results drift from CI and the lock.
  A tool the `.venv` does not provide (e.g. a globally installed `prek` the
  project never declared) stays allowed.
- Anywhere: `pgrep -f`, which matches the polling shell's own command line and
  reports a process that is not running. Use `pgrep -x <process-name>`.

Commands are split on `;`, `|`, `&&`, `||`, `&` and parentheses; env
assignments and wrappers (`nohup`, `nice`, `time`, `env`, `command`, `exec`,
`rtk`, `rtk proxy`) are skipped, and `bash -c` / `sh -c` / `zsh -c` / `eval`
payloads are inspected too. A command the hook cannot parse is allowed.

## Override

Prefix the command with `GUARD_OK=1 ` or append a `# guard:allow` comment.

Exit codes: 0 = allow · 2 = block (stderr shown to Claude, command skipped).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path

UV_TOOLS = frozenset(
    {
        "alembic",
        "bandit",
        "interrogate",
        "mypy",
        "prek",
        "pyright",
        "pytest",
        "ruff",
        "ty",
        "vulture",
    }
)
PYTHON_NAME = re.compile(r"^python(3(\.\d+)?)?$")
SHELLS = frozenset({"sh", "bash", "zsh"})
WRAPPERS = frozenset({"nohup", "nice", "time", "env", "command", "exec", "rtk", "proxy"})
SEPARATORS = frozenset({";", "|", "||", "&", "&&", "(", ")", "{", "}"})
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OVERRIDE = re.compile(r"^\s*(?:\w+=\S*\s+)*GUARD_OK=1\b|(?:^|\s)#\s?guard:allow\s*$")


def find_venv_bin(start: Path) -> Path | None:
    """Return the ``.venv/bin`` of the nearest uv project at or above *start*.

    Args:
        start: Directory the command runs in.

    Returns:
        The virtualenv's ``bin`` directory, or None outside a uv project.
    """
    for directory in (start, *start.parents):
        if (directory / "uv.lock").is_file():
            return directory / ".venv" / "bin"
    return None


def split_words(command: str) -> list[str] | None:
    """Split a command into shell words with separators as their own tokens.

    Args:
        command: Raw command text.

    Returns:
        The words, or None when the text is not parseable shell.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";|&(){}")
    try:
        return list(lexer)
    except ValueError:
        return None


def segments(words: Sequence[str]) -> list[list[str]]:
    """Group words into the simple commands between control operators.

    Args:
        words: Output of :func:`split_words`.

    Returns:
        One word list per simple command.
    """
    groups: list[list[str]] = [[]]
    for word in words:
        if word in SEPARATORS:
            groups.append([])
        else:
            groups[-1].append(word)
    return [group for group in groups if group]


def segment_reasons(words: Sequence[str], venv_bin: Path | None) -> list[str]:
    """Return why one simple command is refused.

    Args:
        words: One simple command's words.
        venv_bin: Project ``.venv/bin``, or None outside a uv project.

    Returns:
        Block reasons (empty when allowed).
    """
    index = 0
    while index < len(words) and (ASSIGNMENT.match(words[index]) or words[index] in WRAPPERS):
        index += 1
    if index >= len(words):
        return []
    executable, arguments = words[index], list(words[index + 1 :])
    name = executable.rsplit("/", 1)[-1]
    if name in SHELLS and "-c" in arguments[:-1]:
        return command_reasons(arguments[arguments.index("-c") + 1], venv_bin)
    if name == "eval":
        return command_reasons(" ".join(arguments), venv_bin)
    if name == "pgrep" and "-f" in arguments:
        return [
            "`pgrep -f` matches the polling shell's own command line; "
            "use `pgrep -x <process-name>`."
        ]
    if venv_bin is None:
        return []
    if "/.venv/bin/" in executable or executable.startswith(".venv/bin/"):
        return [f"`{executable}` bypasses uv. Run `uv run {name} ...`."]
    tool = None
    if name in UV_TOOLS:
        tool, how = name, f"`{name}`"
    elif name == "uvx" and arguments[:1] and arguments[0] in UV_TOOLS:
        tool, how = arguments[0], f"`uvx {arguments[0]}` ignores uv.lock;"
    elif (
        PYTHON_NAME.match(name)
        and arguments[:1] == ["-m"]
        and arguments[1:2]
        and arguments[1] in UV_TOOLS
    ):
        tool, how = arguments[1], f"`{name} -m {arguments[1]}` bypasses uv;"
    if tool is not None and (venv_bin / tool).exists():
        return [f"{how} run the project's locked tool with `uv run {tool} ...`."]
    return []


def command_reasons(command: str, venv_bin: Path | None) -> list[str]:
    """Inspect every simple command in *command*.

    Args:
        command: Raw command text.
        venv_bin: Project ``.venv/bin``, or None outside a uv project.

    Returns:
        Block reasons (empty when allowed or unparsable).
    """
    words = split_words(command)
    if words is None:
        return []
    return [reason for segment in segments(words) for reason in segment_reasons(segment, venv_bin)]


def main() -> int:
    """Read the PreToolUse payload and block lock-bypassing commands.

    Returns:
        0 to allow, 2 to block.
    """
    try:
        data = json.load(sys.stdin)
        command = data["tool_input"]["command"]
        cwd = Path(data.get("cwd") or os.getcwd())
    except (json.JSONDecodeError, KeyError, TypeError):
        return 0
    if not isinstance(command, str) or OVERRIDE.search(command):
        return 0
    reasons = command_reasons(command, find_venv_bin(cwd))
    if not reasons:
        return 0
    print(
        "BLOCK: "
        + " ".join(dict.fromkeys(reasons))
        + " Override only when intended: prefix `GUARD_OK=1 ` or append `# guard:allow`.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
