#!/usr/bin/env python3
"""PreToolUse hook — block catastrophic / irreversible shell commands.

Fires on the `Bash` tool. Inspects the command and:

- **BLOCKS** (exit 2 — the command does NOT run) clearly catastrophic or
  irreversible operations: `rm -rf /` and friends, disk wipes, fork bombs,
  destructive DB statements (`DROP`/`TRUNCATE`), history-rewriting force pushes,
  `git reset --hard` / `git clean -fdx`, `docker`/`kubectl`/volume destruction,
  and cloud-resource deletion (`terraform destroy`, `aws ... delete-*`,
  `aws s3 rm --recursive` / `rb`).
- **WARNS** (exit 0 + `additionalContext`) on risky-but-sometimes-legitimate
  commands (broad `rm -rf`, `chmod -R 777`, `curl | sh`). Claude sees the warning
  as a system reminder and must justify proceeding. Exit 0 + JSON keeps this from
  being rendered as a "hook error"; the command still runs (non-blocking).

`rm -rf` of well-known build/cache dirs (`node_modules`, `dist`, `.venv`, …) is
allowed — those are routine cleanup, not data loss.

## Override (intentional destructive op)

The hook is mechanical; it can't run an interactive prompt. When a destructive
command is genuinely intended AND the user has confirmed, re-run it with an
explicit, auditable override marker — either:

- prefix the command with `GUARD_OK=1 `, or
- append a `# guard:allow` comment.

The override is deliberately visible so it shows up in the transcript as a
conscious decision, never a silent bypass.

## Wiring (this hook is a source script — activate it yourself)

Add to `.claude/settings.json` (project) or `~/.claude/settings.json` (user):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command",
                   "command": "python3 /abs/path/to/destructive-command-guard.py"}]
      }
    ]
  }
}
```

Exit codes: 0 = allow (optionally with a non-blocking `additionalContext`
warning) · 2 = block (stderr shown to Claude, command skipped).
"""

from __future__ import annotations

import json
import re
import sys

__all__ = ["main"]


# `rm -rf <dir>` of these is routine cleanup — never block it.
SAFE_RM_DIRS: frozenset[str] = frozenset(
    [
        "node_modules",
        "dist",
        "build",
        "out",
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        ".parcel-cache",
        "coverage",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "target",
        ".gradle",
        ".terraform",
    ]
)

# Explicit, auditable override markers.
OVERRIDE_MARKERS: tuple[str, ...] = ("GUARD_OK=1", "# guard:allow", "#guard:allow")

# (compiled regex, human reason) — BLOCK these (exit 2).
BLOCK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\s+(-[a-z]*\s+)*-?[a-z]*[rf][a-z]*\s+(-[a-z]+\s+)*(/|~|\$HOME)(\s|/|$)"),
        "recursive delete of / ~ or $HOME",
    ),
    (
        re.compile(r"\brm\s+(-[a-z]*\s+)*-?[a-z]*[rf][a-z]*\s+(-[a-z]+\s+)*(\*|\.|\.\.)(\s|$)"),
        "recursive delete of '*', '.', or '..' (whole tree)",
    ),
    (
        re.compile(r"\brm\s+(-[a-z]*\s+)*-?[a-z]*[rf][a-z]*\s+(--no-preserve-root)"),
        "rm --no-preserve-root",
    ),
    (re.compile(r"\b(mkfs|fdisk|wipefs)\b"), "disk format / partition"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|disk|hd)"), "dd write to a raw disk device"),
    (re.compile(r">\s*/dev/(sd|nvme|disk|hd)\w*"), "redirect to a raw disk device"),
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (
        re.compile(r"\b(DROP|TRUNCATE)\s+(TABLE|DATABASE|SCHEMA)\b", re.IGNORECASE),
        "destructive SQL (DROP/TRUNCATE)",
    ),
    (
        re.compile(r"\bgit\s+push\b[^\n]*(--force(?!-with-lease)|\s-f\b)"),
        "git push --force (history rewrite; use --force-with-lease)",
    ),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard (discards uncommitted work)"),
    (
        re.compile(r"\bgit\s+clean\s+[^\n]*(?:-[a-z]*f[a-z]*\b|--force\b)"),
        "git clean -f (deletes untracked files)",
    ),
    (
        re.compile(r"\bdocker\s+system\s+prune\b[^\n]*(--volumes|-a)"),
        "docker system prune (volumes/all)",
    ),
    (re.compile(r"\bdocker\s+volume\s+rm\b"), "docker volume rm (data loss)"),
    (
        re.compile(r"\bdocker(\s+compose|-compose)\s+down\b[^\n]*(-v|--volumes)"),
        "docker compose down -v (removes volumes)",
    ),
    (re.compile(r"\bkubectl\s+delete\b"), "kubectl delete (cluster resource removal)"),
    (re.compile(r"\bterraform\s+destroy\b"), "terraform destroy (tears down infra)"),
    (
        re.compile(r"\baws\s+s3\s+(rb|rm)\b[^\n]*(--recursive|--force|s3://)"),
        "aws s3 bucket/recursive delete",
    ),
    (
        re.compile(r"\baws\s+\w[\w-]*\s+(delete|terminate|destroy|purge)-[\w-]+"),
        "aws ...delete/terminate/purge resource",
    ),
]

# (compiled regex, human reason) — WARN only (exit 0 + additionalContext, non-blocking).
WARN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[a-z]*\s+)*-?[a-z]*[rf][a-z]*\s"), "broad recursive delete (rm -rf)"),
    (re.compile(r"\bchmod\s+-R\s+777\b"), "chmod -R 777 (world-writable)"),
    (
        # match a pipe into any shell: sh, bash, zsh, dash, ksh
        re.compile(r"\b(curl|wget)\b[^\n]*\|\s*(sudo\s+)?\w*sh\b"),
        "pipe-to-shell install (supply-chain risk)",
    ),
    (re.compile(r"\bgit\s+checkout\s+(--\s+)?\.\s*$"), "git checkout . (discards local changes)"),
]


def rm_rf_targets_are_safe(command: str) -> bool:
    """True if every `rm -rf` target is a known build/cache dir (routine cleanup).

    Args:
        command: Shell command string to analyze for rm -rf targets.

    Returns:
        True if all rm -rf targets are in SAFE_RM_DIRS.
    """
    found_safe = False
    for m in re.finditer(r"\brm\s+(?:-[a-z]+\s+)*(.+?)(?:&&|;|\||$)", command):
        targets = m.group(1).split()
        # strip flags
        targets = [t for t in targets if not t.startswith("-")]
        if not targets:
            return False
        for t in targets:
            base = t.strip("'\"").rstrip("/").rsplit("/", 1)[-1]
            if base not in SAFE_RM_DIRS:
                return False
            found_safe = True
    return found_safe


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name") != "Bash":
        return 0

    command: str = data.get("tool_input", {}).get("command", "")
    if not command:
        return 0

    if any(marker in command for marker in OVERRIDE_MARKERS):
        return 0  # explicit, auditable override

    # Allow routine `rm -rf <build-dir>` even though it matches a block/warn pattern.
    rm_is_safe = ("rm " in command) and rm_rf_targets_are_safe(command)

    for pattern, reason in BLOCK_PATTERNS:
        if pattern.search(command):
            if rm_is_safe and reason.startswith(("recursive delete", "rm")):
                continue
            print(
                f"[destructive-guard] BLOCKED — {reason}.\n"
                "This command is catastrophic/irreversible and was NOT run. If it is "
                "genuinely intended, surface it to the user, get an explicit yes, then re-run "
                "with `GUARD_OK=1 ` prefixed (or a `# guard:allow` comment).",
                file=sys.stderr,
            )
            return 2  # BLOCK

    for pattern, reason in WARN_PATTERNS:
        if pattern.search(command):
            if rm_is_safe:
                continue
            json.dump(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": (
                            f"[destructive-guard] Warning — {reason}. Proceed only if you've "
                            "confirmed this is intended and scoped correctly."
                        ),
                    }
                },
                sys.stdout,
            )
            return 0  # non-blocking warning surfaced as a system reminder

    return 0


if __name__ == "__main__":
    sys.exit(main())
