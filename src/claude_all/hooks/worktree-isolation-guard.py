#!/usr/bin/env python3
"""PreToolUse hook — enforce worktree isolation before editing a shared repo.

Fires on `Edit`/`Write`/`MultiEdit`. Parallel Claude sessions on ONE checkout
corrupt each other: editing the primary working tree while it sits on the default
branch means another session sees your half-finished changes, and a tree-wide git
op can wipe theirs. This hook makes the "branch/worktree before you edit" rule
mechanical instead of prose.

Behaviour — it PAUSES the edit for user approval (`permissionDecision: "ask"`)
only when ALL of these hold:

- the target file is inside a git repository, AND
- that repository is the PRIMARY checkout (not a linked `git worktree`), AND
- HEAD is on a protected/default branch (`main` / `master` by default).

Every other case returns 0 silently: files outside a repo, linked worktrees
(already isolated), and any feature/topic branch (normal solo work). So the prompt
only appears exactly when you're about to edit the default branch of a shared
checkout — which is precisely when you should have made a worktree first.

`ask` (not exit-2) is deliberate: the edit still proceeds if the user approves, so
a solo repo where direct default-branch edits are fine is one click away — or set
the opt-out env var permanently.

## Configuration (env vars)

- `CLAUDE_ALL_ALLOW_MAIN_EDITS=1` — opt out entirely; the hook returns 0 always.
- `CLAUDE_ALL_PROTECTED_BRANCHES` — comma-separated branch names to treat as
  protected (default `main,master`).

Exit codes: 0 = allow (silent, or with the `ask` payload the harness acts on).
The hook never hard-blocks and never crashes a turn — any error → return 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

__all__ = ["main"]

_GIT_TIMEOUT_S = 1.5


def _ask(reason: str) -> int:
    """Pause the tool call and ask the user for explicit approval.

    Args:
        reason: Explanation shown to the user in the approval prompt.

    Returns:
        0 — the decision is carried in the emitted JSON payload.
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


def _nearest_existing_dir(file_path: str) -> str | None:
    """Return the deepest existing ancestor directory of ``file_path``.

    A `Write` may target a not-yet-created file, so walk up until a real
    directory is found. Returns None if nothing usable resolves.

    Args:
        file_path: The path the tool is about to edit or write.

    Returns:
        An existing directory to run git in, or None.
    """
    if not file_path:
        return None
    d = os.path.dirname(file_path) or "."
    for _ in range(64):  # bounded walk — never loop forever
        if os.path.isdir(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return None


def _git(cwd: str, *args: str) -> str | None:
    """Run a read-only git command in ``cwd``; return stdout stripped, or None.

    Args:
        cwd: Directory to run git in.
        *args: git arguments (no leading "git").

    Returns:
        Stripped stdout on success, else None (git absent, non-zero, timeout).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _protected_branches() -> frozenset[str]:
    """The set of branch names treated as protected (default main/master)."""
    raw = os.environ.get("CLAUDE_ALL_PROTECTED_BRANCHES", "main,master")
    return frozenset(b.strip() for b in raw.split(",") if b.strip())


def main() -> int:
    if os.environ.get("CLAUDE_ALL_ALLOW_MAIN_EDITS") == "1":
        return 0

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name") not in {"Edit", "Write", "MultiEdit"}:
        return 0

    file_path: str = data.get("tool_input", {}).get("file_path", "")
    cwd = _nearest_existing_dir(file_path)
    if cwd is None:
        return 0

    # Inside a git repo? A linked worktree is already isolated — allow it.
    git_dir = _git(cwd, "rev-parse", "--git-dir")
    if git_dir is None:
        return 0  # not a git repo (or git unavailable) — nothing to enforce
    if "/worktrees/" in git_dir.replace("\\", "/"):
        return 0  # linked worktree — isolated by construction

    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if branch is None or branch not in _protected_branches():
        return 0  # detached HEAD, or a feature branch — normal work

    toplevel = _git(cwd, "rev-parse", "--show-toplevel") or "this repo"
    return _ask(
        f"[worktree-isolation] You're about to edit the PRIMARY checkout of "
        f"`{toplevel}` while it's on `{branch}`. If parallel sessions may touch "
        "this repo, create a per-task worktree/branch first (editing the default "
        "branch of a shared checkout corrupts other sessions). Approve to edit "
        "here anyway, or set CLAUDE_ALL_ALLOW_MAIN_EDITS=1 to silence this for "
        "solo repos."
    )


if __name__ == "__main__":
    sys.exit(main())
