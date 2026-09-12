"""Tests for scripts/check_requires.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Add the scripts directory to sys.path so we can import check_requires
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import check_requires


def test_success_no_violations_with_capsys(capsys):
    """When resources are discovered and no violations, exit 0 with summary line."""
    with (
        patch.object(check_requires, "load_resource_keys", return_value={"a/b", "c/d", "e/f"}),
        patch.object(check_requires, "find_violations", return_value=[]),
    ):
        exit_code = check_requires.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        # Check stdout for the summary line
        assert "Inspected 3 resources" in captured.out
        # No findings should be printed
        assert captured.out.strip() == "Inspected 3 resources"
        # stderr should be empty
        assert captured.err == ""


def test_zero_discovery_failure(capsys):
    """When discovery returns zero resources, exit non-zero with error message."""
    with patch.object(check_requires, "load_resource_keys", return_value=set()):
        exit_code = check_requires.main()
        assert exit_code == 1
        captured = capsys.readouterr()
        # stdout should be empty (no summary line printed)
        assert captured.out == ""
        # stderr should contain the error message
        assert "0 resources matched the discovery pattern" in captured.err
        assert "dependency manifest that references no resources is unsafe" in captured.err


def test_failure_with_violations(capsys):
    """When resources are discovered and violations exist, exit non-zero with summary line,
    findings, and error."""
    # Mock load_resource_keys to return a set with 2 resources
    with (
        patch.object(check_requires, "load_resource_keys", return_value={"a/b", "c/d"}),
        patch.object(
            check_requires,
            "find_violations",
            return_value=[
                "some/claude-all.json: requires 'x/y' — no such resource",
                "another/claude-all.json: not valid JSON — bad json",
            ],
        ),
    ):
        exit_code = check_requires.main()
        assert exit_code == 1
        captured = capsys.readouterr()
        # stdout should contain the summary line and the findings
        assert "Inspected 2 resources" in captured.out
        assert "some/claude-all.json: requires 'x/y' — no such resource" in captured.out
        assert "another/claude-all.json: not valid JSON — bad json" in captured.out
        # stderr should contain the error message about the findings
        assert "2 dangling/invalid requires entry(ies)" in captured.err
        assert "manifest points at a resource the installer cannot discover" in captured.err


def test_zero_discovery_with_violations(capsys):
    """Edge case: zero discovery but violations? Actually, if discovery is zero, known is empty,
    then any requires entry will be a violation. However, we exit early on zero discovery.
    So we should still exit with the zero-discovery error, not proceed to check violations.
    """
    with (
        patch.object(check_requires, "load_resource_keys", return_value=set()),
        patch.object(check_requires, "find_violations", return_value=["fake finding"]),
    ):
        exit_code = check_requires.main()
        assert exit_code == 1
        captured = capsys.readouterr()
        # Should have exited early due to zero discovery, so no summary line, no findings printed
        assert captured.out == ""
        assert "0 resources matched the discovery pattern" in captured.err
        # The error message about findings should not appear because we exited early
        assert "dangling/invalid requires entry(ies)" not in captured.err
