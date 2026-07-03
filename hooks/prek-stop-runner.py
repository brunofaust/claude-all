#!/usr/bin/env python3
"""Stop hook — run prek on files edited this response, then clear the list.

Reads the accumulator file written by edited-files-accumulator.py, runs
prek for BOTH the `pre-commit` AND `pre-push` hook stages against the
edited files, then clears the accumulator so the next response starts fresh.

Why both stages: hooks declared `stages = ["push"]` (or the modern
`stages = ["pre-push"]`) — typically mypy, import-linter, frontend
typecheck/lint/format — are skipped by the default `pre-commit` stage.
Running both at end-of-turn catches type errors, layering violations, and
frontend issues BEFORE you push, instead of letting them slip through until
`git push` actually fires.

Only runs if:
  - The Stop payload does NOT have `stop_hook_active: true` (that flag means we
    are already inside a stop-hook fix loop — bail immediately to avoid cycling)
  - The accumulator file exists and has entries
  - A prek.toml exists at the project root (skip non-prek projects)

On prek failure: prints the last 30 lines of output to stderr (shown to Claude),
exits 2 to surface the error. Claude must fix before moving on. If prek itself
cannot run (missing `uv`, timeout), the hook prints ONE short notice and exits 1
(non-blocking, visible to the user) — the gate being broken must be loud, but a
Stop hook must never crash the turn with a traceback.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

__all__ = ["main"]


# Stages run at end-of-turn. Order matters for output ordering only; both run.
# `pre-commit` is the default + most common stage.
# `pre-push` catches heavier hooks (mypy, import-linter, tsc) that opt out of
# per-commit speed cost. Modern prek accepts both `pre-push` and the legacy
# `push` alias; we use the modern name.
STAGES: tuple[str, ...] = ("pre-commit", "pre-push")

# Stop hooks get a 60s budget (hooks.json). This is the TOTAL budget shared by
# all stage runs across all project roots — a single deadline, not a per-call
# timeout, so N sequential runs can't overflow the harness budget and get the
# whole hook killed mid-run. Headroom below 60s so we kill prek, not vice versa.
TOTAL_BUDGET_SECONDS = 50


def find_project_root(file_path: str) -> Path | None:
    """Walk up from file_path to find the directory containing prek.toml.

    Args:
        file_path: Path to start walking upward from.

    Returns:
        Path to the project root (containing prek.toml), or None if not found.
    """
    p = Path(file_path).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / "prek.toml").exists():
            return parent
        if (parent / ".git").exists():
            # Reached git root without finding prek.toml
            return None
    return None


def is_linked_worktree(root: Path) -> bool:
    """Return True if *root* is a linked git worktree (not the main checkout).

    A linked worktree's ``.git`` is a FILE (a ``gitdir:`` pointer); the main
    checkout's ``.git`` is a directory. Edits in a linked worktree are
    work-in-progress on a feature branch whose authoritative prek gate runs at
    its real commit/push (or /ship-pr), so the end-of-turn lint batch skips it.
    Generalises the ``/.worktrees/`` path exclusion to worktrees created
    anywhere on disk (e.g. a sibling ``../repo-feature`` dir).

    Args:
        root: Project root (directory containing prek.toml).

    Returns:
        True if *root* is a linked worktree and should be skipped.
    """
    return (root / ".git").is_file()


# Hooks that gate the COMMIT itself, not the edited files. They false-fail in a
# Stop lint-batch — e.g. `no-commit-to-branch` fails purely because you're on `main`,
# though no commit is happening. Skip them here; they still run on a real `git commit`.
COMMIT_CEREMONY_HOOKS: tuple[str, ...] = ("no-commit-to-branch",)


def run_prek_stage(
    root: Path, files: list[str], stage: str, timeout: float
) -> subprocess.CompletedProcess[str] | str:
    """Run prek for a single hook stage and return the CompletedProcess.

    Commit-ceremony hooks (see ``COMMIT_CEREMONY_HOOKS``) are skipped via the ``SKIP``
    env var, merged with any ``SKIP`` the user already set.

    Args:
        root: Project root where prek.toml exists.
        files: List of file paths to check.
        stage: Hook stage name (e.g., 'pre-commit', 'pre-push').
        timeout: Seconds left in the hook's total budget for this run.

    Returns:
        CompletedProcess with prek output captured, or a short error string if
        prek could not run at all (missing `uv`, timeout) — a Stop hook must
        never crash the turn with a traceback, but the broken gate must be
        surfaced, so the caller reports the string to the user.
    """
    env = dict(os.environ)
    skip = [s for s in env.get("SKIP", "").split(",") if s.strip()]
    skip.extend(h for h in COMMIT_CEREMONY_HOOKS if h not in skip)
    env["SKIP"] = ",".join(skip)
    try:
        return subprocess.run(
            ["uv", "run", "prek", "run", "--hook-stage", stage, "--files", *files],
            cwd=root,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"prek (stage={stage}) timed out after {int(timeout)}s in {root}"
    except OSError as exc:
        return f"could not launch `uv run prek` ({exc})"


def is_real_failure(combined: str) -> bool:
    """Return True if the prek output contains real failures.

    Filters out the `check-added-large-files` exit 128 (prek 0.4.1 bug in
    --files mode): lines mentioning that hook are ignored, every other
    failure line counts. A non-zero exit with no recognizable failure line
    is surfaced too — unknown output must not be silently swallowed.

    Args:
        combined: Stdout + stderr from prek run.

    Returns:
        True if a real failure (not just check-added-large-files noise).
    """
    failed_lines = [ln for ln in combined.splitlines() if "Failed" in ln]
    if not failed_lines:
        return True  # non-zero exit with no recognizable hook output — surface it
    return any("check-added-large-files" not in ln for ln in failed_lines)


def main() -> int:
    """Main entry point."""
    raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0

    # Already inside a stop-hook continuation — running again would loop:
    # fail → Claude fixes → Stop fires → fail → …  Break the cycle here.
    if data.get("stop_hook_active"):
        return 0

    session_id: str = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "no-session")
    accumulator = os.path.join(tempfile.gettempdir(), f"cc-edited-{session_id}.txt")

    if not os.path.exists(accumulator):
        return 0

    try:
        lines = Path(accumulator).read_text(encoding="utf-8").splitlines()
        Path(accumulator).unlink(missing_ok=True)
    except OSError:
        return 0

    # Unique real files, exclude worktrees
    files = list(
        {
            f
            for f in lines
            if f.strip()
            and Path(f).exists()
            and "/.worktrees/" not in f
            and "/.claude/worktrees/" not in f
        }
    )
    if not files:
        return 0

    # Group by project root — run prek once per project touched this response
    roots: dict[Path, list[str]] = {}
    for f in files:
        root = find_project_root(f)
        if root and not is_linked_worktree(root):
            roots.setdefault(root, []).append(f)

    if not roots:
        return 0  # no prek.toml found for any edited file

    exit_code = 0
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    for root, root_files in roots.items():
        for stage in STAGES:
            remaining = deadline - time.monotonic()
            if remaining < 5:
                # Out of budget — say so rather than getting killed mid-run by
                # the harness (which would silently drop remaining stages).
                print(
                    "[prek-stop-runner] gate incomplete: time budget exhausted; "
                    f"skipped remaining stages ({stage} in {root} onward).",
                    file=sys.stderr,
                )
                return max(exit_code, 1)

            result = run_prek_stage(root, root_files, stage, timeout=remaining)
            if isinstance(result, str):
                # Infra failure (missing uv / timeout): the lint gate did NOT
                # run. Exit 1 — visible to the user, non-blocking, no traceback.
                print(f"[prek-stop-runner] gate did not run: {result}", file=sys.stderr)
                return max(exit_code, 1)
            if result.returncode == 0:
                continue

            combined = result.stdout + result.stderr
            if not is_real_failure(combined):
                continue

            print(
                f"[prek-stop-runner] prek (stage={stage}) failed in {root}. Fix before continuing.",
                file=sys.stderr,
            )
            print("\n".join(combined.splitlines()[-30:]), file=sys.stderr)
            exit_code = 2

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
