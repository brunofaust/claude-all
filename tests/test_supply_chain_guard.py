"""Tests for the `supply-chain-guard.py` PreToolUse hook.

Drives the hook the way `hook-authoring` documents testing it: pipe a
synthetic `{"tool_name": "Bash", "tool_input": {"command": ...}}` payload on
stdin and assert on stdout — no live session needed.

The property pinned here is FALSE-POSITIVE freedom. The guard triggers on
install commands, but it used to match the raw command string, so any command
that merely *mentioned* an install phrase — a `grep` pattern searching for it,
a heredoc documenting it, a shell comment — fired the reminder. A guard that
cries wolf on `grep "pip install"` trains the reader to ignore it, which is
strictly worse than not having it. Trigger detection therefore runs against
EXECUTABLE text only: quoted spans, heredoc bodies and comments are stripped
first.

The symmetric risk is over-stripping: a real install must still fire even when
its arguments are quoted (`pip install "requests==2.31.0"`), so both directions
are asserted.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "claude_all"
    / "hooks"
    / "supply-chain-guard.py"
)


def run_hook(command: str, cwd: Path) -> tuple[int, str]:
    """Run the guard against one Bash command; return (exit_code, stdout).

    Args:
        command: The Bash command string to test.
        cwd: Working directory for the hook subprocess.

    Returns:
        Tuple of (exit code, stdout text).
    """
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "CC_SUPPLY_CHAIN_COOLDOWN_DAYS": "0"},
    )
    return proc.returncode, proc.stdout


def fired(stdout: str) -> bool:
    """True when the guard emitted a supply-chain reminder.

    Args:
        stdout: The hook's stdout text.

    Returns:
        True if a supply-chain reminder was emitted.
    """
    return "supply-chain-guard" in stdout


# ── false positives: the command only MENTIONS an install ────────────────────
@pytest.mark.parametrize(
    "command",
    [
        # a grep pattern searching transcripts for install commands
        'grep -rhoE "pip install|npm install" ~/logs | sort -u',
        "grep -c 'uv add' report.txt",
        # single-quoted awk/sed program mentioning an install
        "awk '/npm install/ {print}' build.log",
        # a heredoc writing documentation ABOUT installs
        "cat > doc.md <<'EOF'\nRun `pip install foo` to set up.\nEOF",
        # a shell comment
        "ls -la  # remember to run npm install later",
        # echoing instructions rather than executing them
        'echo "next step: poetry add httpx"',
    ],
)
def test_mention_only_does_not_fire(command: str, tmp_path: Path) -> None:
    """A command that only mentions an install must NOT trigger the guard.

    Args:
        command: A command string that mentions but does not execute an install.
        tmp_path: Pytest-provided temporary directory.
    """
    _, out = run_hook(command, tmp_path)
    assert not fired(out), f"false positive on: {command!r}\nstdout={out!r}"


# ── true positives: a real install must still fire ───────────────────────────
@pytest.mark.parametrize(
    "command",
    [
        "pip install requests",
        'pip install "requests==2.31.0"',  # quoted ARGS, unquoted trigger
        "uv add httpx",
        "npm install left-pad",
        "cd frontend && npm install",
        "poetry add 'httpx[http2]'",
        "pipx install ruff",
    ],
)
def test_real_install_still_fires(command: str, tmp_path: Path) -> None:
    """A genuine install command must still trigger the guard.

    Args:
        command: A command string that executes a real install.
        tmp_path: Pytest-provided temporary directory.
    """
    _, out = run_hook(command, tmp_path)
    assert fired(out), f"false negative on: {command!r}\nstdout={out!r}"


def test_hook_never_breaks_the_turn(tmp_path: Path) -> None:
    """The guard is a reminder: it must always exit 0, even on junk input.

    Args:
        tmp_path: Pytest-provided temporary directory.
    """
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not json at all",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert proc.returncode == 0


def test_bypass_marker_silences(tmp_path: Path) -> None:
    """`CC_SUPPLY_CHAIN_OK=1` must remain an escape hatch.

    Args:
        tmp_path: Pytest-provided temporary directory.
    """
    _, out = run_hook("CC_SUPPLY_CHAIN_OK=1 pip install requests", tmp_path)
    assert not fired(out)
