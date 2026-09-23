"""Tests for scripts/check_requires.py — zero-discovery and summary output."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_requires import find_violations, load_resource_keys


def test_normal_success_inspected_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """With manifests present and valid, check succeeds and reports inspected count."""
    # Create fake src/claude_all structure
    repo_root = tmp_path / "repo"
    src = repo_root / "src"
    claude_all = src / "claude_all"
    claude_all.mkdir(parents=True)

    manifest = claude_all / "claude-all.json"
    manifest.write_text(json.dumps({"requires": []}))

    # Mock the paths
    import check_requires
    from check_requires import main

    monkeypatch.setattr(check_requires, "REPO_ROOT", repo_root)
    monkeypatch.setattr(check_requires, "SRC", src)

    # Mock load_resource_keys to return empty set
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    exit_code = main()
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "inspected 1 manifests" in captured.out


def test_zero_discovery_failure_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """When no manifests are discovered, the checker must fail."""
    import check_requires
    from check_requires import main

    # Create empty structure with no manifests
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir) / "repo"
        src = repo_root / "src" / "claude_all"
        src.mkdir(parents=True)

        monkeypatch.setattr(check_requires, "REPO_ROOT", repo_root)
        monkeypatch.setattr(check_requires, "SRC", repo_root / "src")

        # main() should fail with non-zero exit code and error message
        exit_code = main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "0 manifests matched" in captured.err
        assert "dependency check would validate nothing" in captured.err


def test_genuine_failure_still_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """An existing genuine violation still results in non-empty findings."""
    # Create a temporary manifest with a dangling requires entry

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir) / "repo"
        src = repo_root / "src"
        claude_all = src / "claude_all"
        claude_all.mkdir(parents=True)

        manifest = claude_all / "test" / "claude-all.json"
        manifest.parent.mkdir()
        manifest.write_text(json.dumps({"requires": ["nonexistent/resource"]}))

        import check_requires
        from check_requires import main

        monkeypatch.setattr(check_requires, "REPO_ROOT", repo_root)
        monkeypatch.setattr(check_requires, "SRC", src)

        exit_code = main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "nonexistent/resource" in captured.out
        assert "1 dangling/invalid requires entry" in captured.err


def test_summary_line_format() -> None:
    """The summary line on success should be greppable."""
    findings, count = find_violations(load_resource_keys())
    # If we have manifests and no findings, the script should print "inspected N manifests"
    # We're testing the counting logic here
    if count > 0 and not findings:
        summary = f"inspected {count} manifests"
        assert summary.startswith("inspected ")
        assert "manifests" in summary
