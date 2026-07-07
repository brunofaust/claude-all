#!/usr/bin/env python3
"""PreToolUse hook — block a git commit/push that would leak credentials.

Fires on the `Bash` tool and inspects `git add` / `git commit` / `git push`
commands. It closes two gaps that a pattern-based scanner like `gitleaks` leaves
open, catching the leak at the moment it would enter (commit) or leave (push) the
branch:

1. **Credential FILE staged.** A private key, a real `.env`, `.aws/credentials`,
   `.netrc`, `.pgpass`, etc. added to the tree (`.env.example` / `.pub` are fine).
2. **Live env-var VALUE in the diff.** If the *value* of a sensitive environment
   variable (name matching SECRET / TOKEN / PASSWORD / *_KEY / CREDENTIAL … and a
   value long enough to be a real secret) appears verbatim in the outgoing diff —
   even reformatted enough to slip a regex — the commit is blocked. Only the
   variable NAME is ever reported; the value is never read into output.

On a hit it **hard-blocks** (exit 2 — the command does NOT run) and explains what
matched. It **fails open**: if the repo can't be resolved or git can't run, it
returns 0 rather than blocking legitimate work (a project's own `gitleaks` /
pre-commit stays the backstop).

## Override (intentional — you've reviewed it)

Re-run with an explicit, auditable marker: prefix `GUARD_OK=1 ` or append a
`# guard:allow` comment. The override is visible in the transcript on purpose.

Exit codes: 0 = allow (no git-write command, or nothing suspicious, or fail-open)
· 2 = block (stderr shown to Claude, command skipped).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

__all__ = ["main"]

_GIT_TIMEOUT_S = 4.0
_MAX_DIFF_CHARS = 4_000_000  # bound the scan on huge diffs

OVERRIDE_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:\w+=\S*\s+)*GUARD_OK=1\b|(?:^|\s)#\s?guard:allow\s*$"
)

# A git write we care about anywhere in the (possibly chained) command.
GIT_ADD_RE: re.Pattern[str] = re.compile(r"\bgit\b[^\n|&;]*\badd\b")
GIT_COMMIT_RE: re.Pattern[str] = re.compile(r"\bgit\b[^\n|&;]*\bcommit\b")
GIT_PUSH_RE: re.Pattern[str] = re.compile(r"\bgit\b[^\n|&;]*\bpush\b")
GIT_DIR_C_RE: re.Pattern[str] = re.compile(r"\bgit\s+(?:-C\s+|--git-dir=)(\S+)")

# Sensitive env-var NAME patterns — narrow, to keep false positives near zero.
SENSITIVE_NAME_RE: re.Pattern[str] = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|PASSPHRASE|PRIVATE_KEY|CREDENTIAL|"
    r"API_?KEY|ACCESS_KEY|SESSION_TOKEN|_KEY)$|^(AWS_SECRET|GH_TOKEN|GITHUB_TOKEN)"
)

# Values that are obviously placeholders, not real secrets.
_PLACEHOLDER_BITS: tuple[str, ...] = (
    "example",
    "redacted",
    "changeme",
    "placeholder",
    "dummy",
    "your_",
    "xxxx",
    "<",
    ">",
)


def _credential_file_reason(path: str) -> str | None:
    """Return a reason string if ``path`` looks like a credential file, else None.

    Args:
        path: A repo-relative or absolute path being staged/added.

    Returns:
        Human reason (naming the file only) or None.
    """
    norm = path.replace("\\", "/").strip().strip("'\"")
    base = norm.rsplit("/", 1)[-1]
    low = base.lower()

    if low.endswith(".pub"):
        return None  # public key — safe

    # .env and .env.<x>, but allow the shareable templates.
    if low == ".env" or (
        low.startswith(".env.") and not low.endswith((".example", ".sample", ".template", ".dist"))
    ):
        return f"stages `{base}` (a real .env — commit only `.env.example`)"

    if low.endswith((".pem", ".p12", ".pfx", ".keystore", ".jks")):
        return f"stages `{base}` (private key / keystore)"

    if base in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pgpass"}:
        return f"stages `{base}` (private credential file)"

    if norm.endswith("/.aws/credentials") or norm.endswith("/.aws/config"):
        return f"stages `{base}` (AWS credentials file)"

    if "/.ssh/" in norm and base.startswith("id_"):
        return f"stages `{base}` (SSH private key)"

    return None


def _looks_like_secret(value: str) -> bool:
    """True if ``value`` is long and non-placeholder enough to be a real secret."""
    if len(value) < 12:
        return False
    low = value.lower()
    if any(bit in low for bit in _PLACEHOLDER_BITS):
        return False
    # too few distinct chars to be a real secret — e.g. "xxxxxxxxxxxx", "------------"
    return len(set(value)) > 2


def _sensitive_env() -> list[tuple[str, str]]:
    """Return (name, value) pairs for secret-shaped env vars worth scanning for."""
    out: list[tuple[str, str]] = []
    for name, value in os.environ.items():
        if SENSITIVE_NAME_RE.search(name) and _looks_like_secret(value):
            out.append((name, value))
    return out


def _git(cwd: str, *args: str) -> str | None:
    """Run a read-only git command in ``cwd``; return stdout, or None on failure."""
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
    return proc.stdout


def _repo_dir(command: str, payload: dict[str, object]) -> str | None:
    """Resolve the directory to run git in for this command.

    Prefers an explicit `git -C <dir>` / `--git-dir=`, then the hook payload's
    `cwd`, then the process cwd. Returns None if none is a usable directory.
    """
    m = GIT_DIR_C_RE.search(command)
    candidates: list[str] = []
    if m:
        candidates.append(m.group(1).strip("'\""))
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        candidates.append(cwd)
    candidates.append(os.getcwd())
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return None


def _added_paths(command: str) -> list[str]:
    """Best-effort extract of explicit paths from a `git add` command."""
    paths: list[str] = []
    for m in re.finditer(r"\bgit\b[^\n|&;]*\badd\b([^\n|&;]*)", command):
        for tok in m.group(1).split():
            if tok.startswith("-") or tok in {".", "-A", "--all"}:
                continue
            paths.append(tok)
    return paths


def _block(reasons: list[str]) -> int:
    """Emit the block message to stderr and return exit code 2."""
    bullets = "\n".join(f"  - {r}" for r in reasons)
    print(
        "[secret-leak-guard] BLOCKED — this git command would commit/push "
        f"credentials:\n{bullets}\n"
        "The command was NOT run. Remove the secret (use a secret store / "
        "`.env.example`), or if you've reviewed it and it's genuinely safe, re-run "
        "with `GUARD_OK=1 ` prefixed (or a `# guard:allow` comment).",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name") != "Bash":
        return 0
    command: str = data.get("tool_input", {}).get("command", "")
    if not command or OVERRIDE_RE.search(command):
        return 0

    has_add = bool(GIT_ADD_RE.search(command))
    has_commit = bool(GIT_COMMIT_RE.search(command))
    has_push = bool(GIT_PUSH_RE.search(command))
    if not (has_add or has_commit or has_push):
        return 0

    reasons: list[str] = []

    # (1) Credential files named directly on a `git add`.
    if has_add:
        for p in _added_paths(command):
            reason = _credential_file_reason(p)
            if reason:
                reasons.append(reason)

    repo = _repo_dir(command, data)
    if repo is not None:
        # (1b) Credential files in the staged set (covers `git add .` + commit).
        name_only = (
            _git(repo, "diff", "--cached", "--name-only") if (has_commit or has_add) else None
        )
        if name_only:
            for p in name_only.splitlines():
                reason = _credential_file_reason(p)
                if reason and reason not in reasons:
                    reasons.append(reason)

        # (2) Live env-var value in the outgoing diff.
        envs = _sensitive_env()
        if envs:
            diff: str | None = None
            if has_commit:
                diff = _git(repo, "diff", "--cached")
            elif has_push:
                diff = _git(repo, "diff", "@{u}..HEAD")  # best-effort; None if no upstream
            if diff:
                hay = diff[:_MAX_DIFF_CHARS]
                for name, value in envs:
                    if value in hay:
                        note = f"the value of env var `${name}` appears in the diff"
                        if note not in reasons:
                            reasons.append(note)

    if reasons:
        return _block(reasons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
