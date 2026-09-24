"""Tests for scripts/check_requires.py zero-discovery hardening."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src and scripts on path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_requires


def test_main_success_prints_inspected_summary(monkeypatch):
    """Normal success prints a greppable inspected summary line and exits 0."""

    # Force a non-empty manifest discovery by using the real repo
    # The real repo has manifests, and the current graph is clean.
    # We just verify the summary line appears and exit code is 0.
    # To keep the test fast and deterministic, we monkeypatch find_violations
    # to return [] so success is guaranteed regardless of repo state.
    monkeypatch.setattr(check_requires, "find_violations", lambda known: [])
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/x"})

    # Capture stdout
    from io import StringIO

    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        rc = check_requires.main()
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    assert rc == 0
    assert "Inspected" in out and "manifests" in out


def test_main_zero_discovery_is_hard_failure(monkeypatch):
    """Zero manifest discovery exits non-zero with a clear message."""

    # Patch SRC to a path with no manifests
    empty_src = Path("/tmp/check_requires_empty_src")
    empty_src.mkdir(parents=True, exist_ok=True)
    (empty_src / "claude_all").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(check_requires, "SRC", empty_src)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    from io import StringIO

    old_stderr = sys.stderr
    sys.stderr = StringIO()
    try:
        rc = check_requires.main()
        err = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    assert rc == 1
    assert "zero-discovery" in err.lower()
    assert "claude-all.json" in err


def test_main_genuine_violation_still_fails(monkeypatch):
    """An existing genuine violation still leads to exit 1 and findings printed."""

    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())
    # Simulate a finding
    monkeypatch.setattr(
        check_requires,
        "find_violations",
        lambda known: ["src/x/claude-all.json: requires 'missing'"],
    )

    from io import StringIO

    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        rc = check_requires.main()
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    assert rc == 1
    assert "requires 'missing'" in out
