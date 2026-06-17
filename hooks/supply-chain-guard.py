#!/usr/bin/env python3
"""PreToolUse hook — flag supply-chain risks in package-install commands.

Fires on the `Bash` tool. When the command installs packages
(`npm/pnpm/yarn/bun install|add|ci`, `pip install`, `uv add`, `uv pip install`,
`poetry add`, `pipx install`), it emits a NON-BLOCKING reminder (exit 0 + JSON
`additionalContext`, so it is NOT rendered as a hook error) pointing out the
applicable risks and the safer invocation:

- **git/URL sources** (`git+https://`, `github:owner/repo`, `git://`) bypass
  registry review and run arbitrary code — strongly avoid.
- **lifecycle scripts** run arbitrary code at install time — pass
  `--ignore-scripts` on npm/pnpm/yarn/bun and run the build deliberately.
- **lockfile drift** — a bare `npm install` with a lockfile present mutates it;
  use the frozen/`ci` variant for a reproducible install.
- **new-package cooldown** — most malicious package versions are caught within
  days of publish; verify provenance and avoid brand-new versions of a new dep.
- **alternate Python indexes** — `--index-url`/`--extra-index-url` can shadow
  public names (dependency confusion); `--trusted-host` disables TLS verification.

Covers npm/pnpm/yarn/bun and pip/pipx/uv/poetry. The ecosystem-agnostic checks
(git/URL source, provenance/cooldown) apply to all; `--ignore-scripts` and the
lockfile→`ci` steering are npm-only; the index / `--trusted-host` checks are
pip/uv/poetry-only.

This mechanically reinforces the supply-chain criteria in the `research-before-build`
and `security-audit` skills. It is advisory by design (installs still proceed) so
it never breaks a workflow; set CC_SUPPLY_CHAIN_OK=1 to silence it.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

__all__ = ["analyze", "main"]

# Node package managers adding/installing dependencies.
JS_INSTALL_RE = re.compile(r"\b(npm|pnpm|yarn|bun)\s+(install|i|add|ci)\b")
# Python installers: pip/pipx install, uv add, uv pip install, poetry add.
PY_INSTALL_RE = re.compile(
    r"\b(pip3?|pipx)\s+install\b|\buv\s+(pip\s+install|add)\b|\bpoetry\s+add\b"
)
# Dependency pulled straight from a git repo / URL (no registry review).
GIT_URL_RE = re.compile(r"git\+(?:https?|ssh)://|(?<![\w-])github:[\w.-]+/[\w.-]+|(?<![\w/])git://")
# Python: a custom package index can shadow public names (dependency confusion).
PY_INDEX_RE = re.compile(r"--(?:extra-)?index-url\b")
# A bare `<mgr> install` with no package argument (operates on the manifest/lock).
BARE_INSTALL_RE = re.compile(r"\b(npm|pnpm|yarn|bun)\s+(install|i)\b(?!\s+[\w@./-])")

# Lockfile → the frozen/reproducible install command for that ecosystem.
LOCKFILES: dict[str, tuple[str, str]] = {
    "package-lock.json": ("npm", "npm ci"),
    "pnpm-lock.yaml": ("pnpm", "pnpm install --frozen-lockfile"),
    "yarn.lock": ("yarn", "yarn install --immutable"),
    "bun.lockb": ("bun", "bun install --frozen-lockfile"),
}


def nudge(message: str) -> int:
    """Emit a non-error reminder into Claude's context, then allow the tool."""
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}},
        sys.stdout,
    )
    return 0


def analyze(command: str, cwd: Path) -> list[str]:
    """Return the supply-chain findings for one Bash command (empty = nothing to flag)."""
    js = JS_INSTALL_RE.search(command)
    py = PY_INSTALL_RE.search(command)
    if not (js or py):
        return []

    findings: list[str] = []

    if GIT_URL_RE.search(command):
        findings.append(
            "⛔ installing from a git/URL source bypasses registry review and runs that repo's "
            "code — avoid it; prefer a published, pinned package."
        )

    if js and js.group(2) != "ci" and "--ignore-scripts" not in command:
        findings.append(
            "add `--ignore-scripts` — install/postinstall lifecycle hooks run arbitrary code; "
            "install with scripts off, then run the build step deliberately."
        )

    if py and PY_INDEX_RE.search(command):
        findings.append(
            "a custom package index (`--index-url`/`--extra-index-url`) can shadow public names "
            "(dependency confusion) — pin exact versions + hashes and prefer one trusted index."
        )
    if py and "--trusted-host" in command:
        findings.append(
            "`--trusted-host` disables TLS/certificate verification for that host — avoid it; "
            "fix the index's certificate instead of trusting it blindly."
        )

    bare = BARE_INSTALL_RE.search(command)
    if bare:
        present = [spec for name, spec in LOCKFILES.items() if (cwd / name).is_file()]
        for mgr, frozen in present:
            if bare.group(1) == mgr:
                findings.append(
                    f"a lockfile is present — use `{frozen}` for a reproducible install instead of "
                    "a bare `install` (which can mutate the lockfile / resolve unpinned versions)."
                )

    if findings or py or (js and js.group(2) in {"add", "install", "i"}):
        findings.append(
            "verify the package's provenance and pin the version; be wary of a brand-new package "
            "or version (most malicious releases are caught within days of publish), and commit "
            "the lockfile."
        )

    return findings


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name") != "Bash" or os.environ.get("CC_SUPPLY_CHAIN_OK"):
        return 0

    command: str = data.get("tool_input", {}).get("command", "")
    if not command:
        return 0

    cwd = Path(data.get("cwd") or os.getcwd())
    findings = analyze(command, cwd)
    if not findings:
        return 0

    body = "\n".join(f"  - {f}" for f in findings)
    return nudge(
        "[supply-chain-guard] This command installs packages. Supply-chain checks:\n"
        f"{body}\n"
        "Proceed only if the change is intended. Set CC_SUPPLY_CHAIN_OK=1 to silence this reminder."
    )


if __name__ == "__main__":
    sys.exit(main())
