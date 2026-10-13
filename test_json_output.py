#!/usr/bin/env python3
"""Quick test to verify JSON output functionality."""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add the scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from check_md_links import main


def test_json_output():
    # Create a temporary directory for our test
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Change to the temp directory
        old_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            # Initialize a git repo
            (tmp_path / ".git").mkdir()
            (tmp_path / ".git" / "config").write_text("[core]\n")

            # Create vendored.json
            (tmp_path / "vendored.json").write_text('{"vendored": []}')

            # Create a simple markdown file with a broken link
            (tmp_path / "test.md").write_text("# Test\n\n[link](nonexistent.md)\n")

            # Create a README that links to the markdown file
            (tmp_path / "README.md").write_text("# README\n\n[test](test.md)\n")

            # Capture stdout and stderr
            old_stdout = sys.stdout
            old_stderr = sys.stderr

            try:
                # Test JSON output
                import io

                sys.stdout = io.StringIO()
                sys.stderr = io.StringIO()

                # Set up argv for JSON mode
                old_argv = sys.argv
                sys.argv = ["check_md_links.py", "--json"]

                try:
                    exit_code = main()
                    json_output = sys.stdout.getvalue()
                    stderr_output = sys.stderr.getvalue()
                finally:
                    sys.argv = old_argv

                # Parse the JSON
                data = json.loads(json_output)

                # Verify the structure
                assert "passed" in data
                assert "markdown_files_scanned" in data
                assert "links_resolved" in data
                assert "resources_checked" in data
                assert "files_skipped_as_vendored" in data
                assert "broken_links" in data
                assert "unlinked_resources" in data

                # Verify values
                assert data["passed"] == False  # Should fail due to broken link
                assert data["markdown_files_scanned"] == 1
                assert data["links_resolved"] == 1
                assert data["resources_checked"] == 0
                assert data["files_skipped_as_vendored"] == 0
                assert len(data["broken_links"]) == 1
                assert data["broken_links"][0]["file"] == "test.md"
                assert data["broken_links"][0]["target"] == "nonexistent.md"
                assert data["unlinked_resources"] == []

                # Verify stderr output
                assert "1 finding(s)" in stderr_output

                # Verify exit code
                assert exit_code == 1

                print("JSON output test passed!")

            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    test_json_output()
