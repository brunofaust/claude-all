"""Tests for the `supply-chain-guard.py` PreToolUse hook.

Pipes a synthetic Bash payload on stdin and asserts on stdout. Pins false-positive
freedom: commands that merely mention an install (grep pattern, heredoc, comment)
must not fire, since trigger detection strips quoted spans, heredocs and comments.
A real install with quoted args must still fire.
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
    return "supply-chain-guard" in stdout


# ── false positives: the command only MENTIONS an install ────────────────────
@pytest.mark.parametrize(
    "command",
    [
        # a grep pattern searching transcripts for install commands
        'grep -rhoE "pip install|npm install" ~/logs | sort -u',
        "grep -c 'uv add' report.txt",
        "awk '/npm install/ {print}' build.log",
        "cat > doc.md <<'EOF'\nRun `pip install foo` to set up.\nEOF",
        "ls -la  # remember to run npm install later",
        'echo "next step: poetry add httpx"',
    ],
)
def test_mention_only_does_not_fire(command: str, tmp_path: Path) -> None:
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
