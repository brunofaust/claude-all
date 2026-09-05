import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import check_md_links


def _run_check_md_links(args, tmp_path, monkeypatch):
    """Helper to run check_md_links.py without --json and capture output and exit code."""
    # Save original sys.stdout, sys.stderr, sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    old_argv = sys.argv
    try:
        # Redirect stdout and stderr to capture output
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        # Set sys.argv to simulate command line arguments (no --json)
        sys.argv = ["check_md_links.py", *list(args)]
        # Call main
        check_md_links.main()
        # If we get here, main returned normally (exit code 0)
        exit_code = 0
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    finally:
        # Get the output
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        # Restore
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        sys.argv = old_argv
    return stdout, stderr, exit_code


def _run_check_md_links_json(args, tmp_path, monkeypatch):
    """Helper to run check_md_links.py with --json and capture output and exit code."""
    # Save original sys.stdout, sys.stderr, sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    old_argv = sys.argv
    try:
        # Redirect stdout and stderr to capture output
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        # Set sys.argv to simulate command line arguments (with --json)
        sys.argv = ["check_md_links.py", "--json", *list(args)]
        # Call main
        check_md_links.main()
        # If we get here, main returned normally (exit code 0)
        exit_code = 0
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    finally:
        # Get the output
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        # Restore
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        sys.argv = old_argv
    return stdout, stderr, exit_code


def test_json_output_clean_tree(tmp_path: Path, monkeypatch) -> None:
    """Test --json on a clean tree."""
    # Create a simple markdown file with no broken links
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\nThis is a test.")

    # Initialize a git repo in tmp_path
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "test.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Create a vendored.json file
    vendored = tmp_path / "vendored.json"
    vendored.write_text('{"vendored": []}')

    # Mock the ROOT variable in check_md_links to point to tmp_path
    monkeypatch.setattr(check_md_links, "ROOT", tmp_path)

    stdout, stderr, exit_code = _run_check_md_links_json([], tmp_path, monkeypatch)

    # Check that the output is valid JSON
    data = json.loads(stdout)
    assert data["pass"] is True
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] == 0
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []
    assert exit_code == 0
    assert stderr == ""


def test_json_output_with_broken_link(tmp_path: Path, monkeypatch) -> None:
    """Test --json with a broken link."""
    # Create a markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\n[Broken link](missing.md)")

    # Initialize a git repo in tmp_path
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "test.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Create a vendored.json file
    vendored = tmp_path / "vendored.json"
    vendored.write_text('{"vendored": []}')

    # Mock the ROOT variable in check_md_links to point to tmp_path
    monkeypatch.setattr(check_md_links, "ROOT", tmp_path)

    stdout, stderr, exit_code = _run_check_md_links_json([], tmp_path, monkeypatch)

    # Check that the output is valid JSON
    data = json.loads(stdout)
    assert data["pass"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 1
    assert data["counts"]["resources_checked"] == 0
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert len(data["broken_links"]) == 1
    broken_link = data["broken_links"][0]
    assert broken_link["file"] == "test.md"
    assert broken_link["target"] == "missing.md"
    # The resolved path should be absolute, but we'll check it ends with missing.md
    assert broken_link["resolved_path"].endswith("missing.md")
    assert exit_code == 1
    assert stderr == ""


def test_json_output_with_unlinked_resource(tmp_path: Path, monkeypatch) -> None:
    """Test --json with an unlinked resource."""
    # Create a simple markdown file
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\nThis is a test.")

    # Initialize a git repo in tmp_path
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "test.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Create a vendored.json file
    vendored = tmp_path / "vendored.json"
    vendored.write_text('{"vendored": []}')

    # Mock the ROOT variable in check_md_links to point to tmp_path
    monkeypatch.setattr(check_md_links, "ROOT", tmp_path)
    monkeypatch.setattr(check_md_links, "check_links", lambda registry: [])

    # Mock cli.discover to return a resource that is not linked from README
    class MockItem:
        kind = "skill"
        name = "test"
        src = tmp_path / "test.md"

    def mock_discover(_):
        return [MockItem()]

    monkeypatch.setattr("claude_all.cli.discover", mock_discover)

    stdout, stderr, exit_code = _run_check_md_links_json([], tmp_path, monkeypatch)

    # Check that the output is valid JSON
    data = json.loads(stdout)
    assert data["pass"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] == 1
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == ["test.md"]
    assert exit_code == 1
    assert stderr == ""


def test_default_output_unaffected(tmp_path: Path, monkeypatch) -> None:
    """Test that default (non-JSON) output is unaffected."""
    # Create a markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\n[Broken link](missing.md)")

    # Initialize a git repo in tmp_path
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "test.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Create a vendored.json file
    vendored = tmp_path / "vendored.json"
    vendored.write_text('{"vendored": []}')

    # Mock the ROOT variable in check_md_links to point to tmp_path
    monkeypatch.setattr(check_md_links, "ROOT", tmp_path)

    stdout, stderr, exit_code = _run_check_md_links([], tmp_path, monkeypatch)

    # Check that the output is as expected (human-readable format)
    assert "test.md:1: broken-link -> missing.md" in stdout
    assert "1 finding(s)." in stderr
    assert exit_code == 1
