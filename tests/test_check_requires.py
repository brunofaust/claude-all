"""Tests for scripts/check_requires.py gate behaviour."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_requires import main


def test_success_prints_summary_and_exits_zero(monkeypatch, capsys):
    """Normal run with resources discovered and no violations succeeds with summary."""

    # Simulate discovering some resources
    monkeypatch.setattr(
        "check_requires.load_resource_keys",
        lambda: {"skills/a", "skills/b"},
    )
    # No violations for those known keys
    monkeypatch.setattr(
        "check_requires.find_violations",
        lambda known: [],
    )
    rc = main()
    out = capsys.readouterr()
    assert rc == 0
    # summary line must be present
    assert "inspected 2 units" in out.out


def test_zero_discovery_fails_hard(monkeypatch, capsys):
    """A run where discovery matches zero resources must exit non-zero."""

    monkeypatch.setattr(
        "check_requires.load_resource_keys",
        lambda: set(),
    )
    rc = main()
    err = capsys.readouterr().err
    assert rc == 1
    assert "0 resources matched the discovery pattern" in err
    # No success summary should be printed
    assert "inspected" not in capsys.readouterr().out


def test_genuine_violation_still_fails(monkeypatch, capsys):
    """Existing violation detection is unchanged: a dangling requires fails."""

    monkeypatch.setattr(
        "check_requires.load_resource_keys",
        lambda: {"skills/a"},
    )
    monkeypatch.setattr(
        "check_requires.find_violations",
        lambda known: [
            "src/claude_all/skills/x/claude-all.json: requires 'skills/missing' — no such resource"
        ],
    )
    rc = main()
    out = capsys.readouterr()
    assert rc == 1
    assert "dangling/invalid requires entry" in out.err
    # No success summary
    assert "inspected" not in out.out
