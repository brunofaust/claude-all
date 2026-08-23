import json
import subprocess
import sys

from resolver import JsonOutput


class TestJsonOutput:
    def test_valid_schema(self):
        output = JsonOutput()
        output.passed = False
        output.counts = {
            'markdown_files_scanned': 10,
            'links_resolved': 50,
            'resources_checked': 20,
            'files_skipped_as_vendored': 5
        }
        output.broken_links = [
            {'file': 'README.md', 'raw_target': '#anchor', 'resolved_path': '/dev/null'}
        ]
        output.unlinked_resources = ['src/skill/SKILL.md']
        schema = {
            'passed': False,
            'counts': {
                'markdown_files_scanned': 10,
                'links_resolved': 50,
                'resources_checked': 20,
                'files_skipped_as_vendored': 5
            },
            'broken_links': [
                {'file': 'README.md', 'raw_target': '#anchor', 'resolved_path': '/dev/null'}
            ],
            'unlinked_resources': ['src/skill/SKILL.md']
        }
        assert json.loads(output.to_json()) == schema

    def test_exit_codes(self, monkeypatch):
        # Mock check_links and check_readme_coverage to return findings
        def mock_check_links(_):
            return ['README.md:1: broken-link -> #anchor']

        def mock_check_readme(_):
            return ['README.md: undocumented -> skill/name']

        monkeypatch.setattr('check_md_links.check_links', mock_check_links)
        monkeypatch.setattr('check_md_links.check_readme_coverage', mock_check_readme)

        # Run with --json flag
        result = subprocess.run(
            [sys.executable, 'scripts/check_md_links.py', '--json'],
            capture_output=True,
            text=True
        )

        # Verify JSON output and exit code
        assert result.returncode == 1
        assert 'broken_links' in result.stdout
        assert 'unlinked_resources' in result.stdout

    def test_human_output_unchanged(self, monkeypatch):
        # Same mocks as above
        monkeypatch.setattr('check_md_links.check_links', mock_check_links)
        monkeypatch.setattr('check_md_links.check_readme_coverage', mock_check_readme)

        # Run without --json
        result = subprocess.run(
            [sys.executable, 'scripts/check_md_links.py'],
            capture_output=True,
            text=True
        )

        # Verify human output remains unchanged
        assert 'README.md:1: broken-link -> #anchor' in result.stdout
        assert 'README.md: undocumented -> skill/name' in result.stdout
        assert result.returncode == 1
