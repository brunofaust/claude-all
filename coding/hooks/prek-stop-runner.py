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
  - The accumulator file exists and has entries
  - A prek.toml exists at the project root (skip non-prek projects)

On prek failure: prints the last 30 lines of output to stderr (shown to Claude),
exits 2 to surface the error. Claude must fix before moving on.

The Stop hook must pass stdin through to stdout unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Stages run at end-of-turn. Order matters for output ordering only; both run.
# `pre-commit` is the default + most common stage.
# `pre-push` catches heavier hooks (mypy, import-linter, tsc) that opt out of
# per-commit speed cost. Modern prek accepts both `pre-push` and the legacy
# `push` alias; we use the modern name.
STAGES: tuple[str, ...] = ("pre-commit", "pre-push")


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


def _run_prek_stage(root: Path, files: list[str], stage: str) -> subprocess.CompletedProcess[str]:
    """Run prek for a single hook stage and return the CompletedProcess.

    Args:
        root: Project root where prek.toml exists.
        files: List of file paths to check.
        stage: Hook stage name (e.g., 'pre-commit', 'pre-push').

    Returns:
        CompletedProcess with prek output captured.
    """
    return subprocess.run(
        ["uv", "run", "prek", "run", "--hook-stage", stage, "--files", *files],
        cwd=root,
        capture_output=True,
        text=True,
        env=os.environ,
    )


def _is_real_failure(combined: str) -> bool:
    """Return True if the prek output contains real failures.

    Filters out the `check-added-large-files` exit 128 (prek 0.4.1 bug in
    --files mode). Treats output as a real failure if any OTHER hook failed,
    OR if `check-added-large-files` is not the only thing mentioned.

    Args:
        combined: Stdout + stderr from prek run.

    Returns:
        True if a real failure (not just check-added-large-files noise).
    """
    lines_out = combined.splitlines()
    real_failures = [
        ln for ln in lines_out if "Failed to run hook" in ln and "check-added-large-files" not in ln
    ]
    return bool(real_failures) or "check-added-large-files" not in combined


def main() -> int:
    """Main entry point."""
    raw = sys.stdin.read()
    sys.stdout.write(raw)  # always pass through to stdout

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
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
        if root:
            roots.setdefault(root, []).append(f)

    if not roots:
        return 0  # no prek.toml found for any edited file

    exit_code = 0
    for root, root_files in roots.items():
        for stage in STAGES:
            result = _run_prek_stage(root, root_files, stage)
            if result.returncode == 0:
                continue

            combined = result.stdout + result.stderr
            if not _is_real_failure(combined):
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
