import json
import subprocess
import sys
from pathlib import Path


def test_json_output_clean_tree(tmp_path: Path, monkeypatch):
    """Test --json on a clean tree."""
    # Create a simple markdown file with no broken links
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\nThis is a test.")

    # Mock git to return our file
    monkeypatch.setattr("scripts.check_md_links.tracked_markdown", lambda: [md_file])

    # Run with --json
    result = subprocess.run(
        [sys.executable, "scripts/check_md_links.py", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    # Check output is valid JSON
    data = json.loads(result.stdout)

    # Verify structure
    assert "pass" in data
    assert "counts" in data
    assert "broken_links" in data
    assert "unlinked_resources" in data

    # Verify counts
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] >= 0
    assert data["counts"]["files_skipped_as_vendored"] == 0

    # Should pass
    assert data["pass"] is True
    assert result.returncode == 0


def test_json_output_with_broken_link(tmp_path: Path, monkeypatch):
    """Test --json with a broken link."""
    # Create a markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\n[Broken link](missing.md)")

    # Mock git to return our file
    monkeypatch.setattr("scripts.check_md_links.tracked_markdown", lambda: [md_file])

    # Run with --json
    result = subprocess.run(
        [sys.executable, "scripts/check_md_links.py", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    # Check output is valid JSON
    data = json.loads(result.stdout)

    # Verify structure
    assert "pass" in data
    assert "counts" in data
    assert "broken_links" in data
    assert "unlinked_resources" in data

    # Verify counts
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 1
    assert data["counts"]["resources_checked"] >= 0
    assert data["counts"]["files_skipped_as_vendored"] == 0

    # Should fail
    assert data["pass"] is False
    assert result.returncode == 1

    # Verify broken link details
    assert len(data["broken_links"]) == 1
    link = data["broken_links"][0]
    assert link["file"] == "test.md"
    assert link["target"] == "missing.md"
    # resolved_path should be absolute or relative path that doesn't exist
    assert "resolved_path" in link


def test_json_output_with_unlinked_resource(tmp_path: Path, monkeypatch):
    """Test --json with an unlinked resource."""
    # Create a simple markdown file
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\nThis is a test.")

    # Mock git to return our file
    monkeypatch.setattr("scripts.check_md_links.tracked_markdown", lambda: [md_file])

    # Mock claude_all.cli.discover to return a resource
    class MockItem:
        kind = "skill"
        name = "test"
        src = tmp_path / "test" / "SKILL.md"

    def mock_discover(_):
        return [MockItem()]

    monkeypatch.setattr("claude_all.cli.discover", mock_discover)

    # Run with --json
    result = subprocess.run(
        [sys.executable, "scripts/check_md_links.py", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    # Check output is valid JSON
    data = json.loads(result.stdout)

    # Verify structure
    assert "pass" in data
    assert "counts" in data
    assert "broken_links" in data
    assert "unlinked_resources" in data

    # Verify counts
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 0
    # Should have 1 resource checked (our mock item)
    assert data["counts"]["resources_checked"] == 1
    assert data["counts"]["files_skipped_as_vendored"] == 0

    # Should fail due to unlinked resource
    assert data["pass"] is False
    assert result.returncode == 1

    # Verify unlinked resource
    assert len(data["unlinked_resources"]) == 1
    assert data["unlinked_resources"][0] == "test/SKILL.md"


def test_default_output_unaffected(tmp_path: Path, monkeypatch):
    """Test that default (non-JSON) output is unaffected."""
    # Create a markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\n[Broken link](missing.md)")

    # Mock git to return our file
    monkeypatch.setattr("scripts.check_md_links.tracked_markdown", lambda: [md_file])

    # Run without --json
    result = subprocess.run(
        [sys.executable, "scripts/check_md_links.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    # Should output human-readable format
    assert "test.md:1: broken-link -> missing.md" in result.stdout
    assert result.returncode == 1
    # Should have stderr output with count
    assert "1 finding(s)." in result.stderr
