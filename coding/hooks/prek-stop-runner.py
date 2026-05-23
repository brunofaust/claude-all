#!/usr/bin/env python3
"""Stop hook — run prek on files edited this response, then clear the list.

Reads the accumulator file written by edited-files-accumulator.py, runs
`prek run --files <files>` from the project root, then clears the accumulator
so the next response starts fresh.

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


def find_project_root(file_path: str) -> Path | None:
    """Walk up from file_path to find the directory containing prek.toml."""
    p = Path(file_path).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / "prek.toml").exists():
            return parent
        if (parent / ".git").exists():
            # Reached git root without finding prek.toml
            return None
    return None


def main() -> int:
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
        result = subprocess.run(
            ["uv", "run", "prek", "run", "--files", *root_files],
            cwd=root,
            capture_output=True,
            text=True,
            env=os.environ,
        )
        if result.returncode != 0:
            combined = result.stdout + result.stderr
            lines_out = combined.splitlines()
            # Filter check-added-large-files exit 128 (prek 0.4.1 bug in --files mode)
            real_failures = [
                ln
                for ln in lines_out
                if "Failed to run hook" in ln and "check-added-large-files" not in ln
            ]
            if real_failures or "check-added-large-files" not in combined:
                print(
                    f"[prek-stop-runner] prek failed in {root}. Fix before continuing.",
                    file=sys.stderr,
                )
                print("\n".join(lines_out[-30:]), file=sys.stderr)
                exit_code = 2

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
