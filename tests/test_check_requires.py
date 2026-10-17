"""Tests for the `check_requires` gate's instruction-reference rule.

A standalone instruction snippet has no agent or skill of its own to carry a
dependency, so every resource it names must be declared in its `claude-all.json`
or installing the instruction ships a rule pointing at nothing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "check_requires", REPO_ROOT / "scripts" / "check_requires.py"
)
assert SPEC is not None and SPEC.loader is not None
check_requires = importlib.util.module_from_spec(SPEC)
sys.modules["check_requires"] = check_requires
SPEC.loader.exec_module(check_requires)

KNOWN = {"skills/foo-skill", "agents/bar-agent", "instructions/demo"}


def snippet(root: Path, body: str, requires: list[str] | None = None) -> Path:
    folder = root / "demo"
    folder.mkdir(parents=True)
    (folder / "claude_md.md").write_text(body, encoding="utf-8")
    if requires is not None:
        (folder / "claude-all.json").write_text(json.dumps({"requires": requires}))
    return root


class TestCheckRequires(unittest.TestCase):
    def test_undeclared_reference_is_reported(self):
        """A named resource missing from ``requires`` is a finding."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            root = snippet(
                tmp_path, "Load `foo-skill`; delegate to `bar-agent`.\n", ["agents/bar-agent"]
            )

            findings, _ = check_requires.find_undeclared_instruction_refs(KNOWN, root)

            self.assertEqual(len(findings), 1)
            self.assertIn("`foo-skill`", findings[0])
            self.assertIn("skills/foo-skill", findings[0])

    def test_declared_and_non_resource_tokens_pass(self):
        """Declared resources, the snippet itself and plain code spans are fine."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            root = snippet(
                tmp_path,
                "Load `foo-skill`; see `demo`; set `MY_FLAG=1`.\n",
                ["skills/foo-skill"],
            )

            findings, _ = check_requires.find_undeclared_instruction_refs(KNOWN, root)
            self.assertEqual(findings, [])

    def test_shipped_instructions_declare_every_reference(self):
        """Every shipped instruction requires each resource it names."""
        known = check_requires.load_resource_keys()

        findings, _ = check_requires.find_undeclared_instruction_refs(known)
        self.assertEqual(findings, [])

    def test_find_violations_zero_manifests(self):
        """Test that find_violations returns zero count when no manifests exist."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Temporarily override SRC to point to empty directory
            original_src = check_requires.SRC
            check_requires.SRC = tmp_path

            try:
                findings, count = check_requires.find_violations(KNOWN)
                self.assertEqual(count, 0)
                self.assertEqual(findings, [])
            finally:
                check_requires.SRC = original_src

    def test_find_undeclared_instruction_refs_zero_snippets(self):
        """Test that find_undeclared_instruction_refs returns zero count when no snippets exist."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Temporarily override INSTRUCTIONS_DIR to point to empty directory
            original_instructions_dir = check_requires.INSTRUCTIONS_DIR
            check_requires.INSTRUCTIONS_DIR = tmp_path / "instructions"
            # Ensure the directory exists
            check_requires.INSTRUCTIONS_DIR.mkdir(parents=True)

            try:
                findings, count = check_requires.find_undeclared_instruction_refs(KNOWN)
                self.assertEqual(count, 0)
                self.assertEqual(findings, [])
            finally:
                check_requires.INSTRUCTIONS_DIR = original_instructions_dir

    def test_main_zero_manifests_exits_with_error(self):
        """When no manifest files are found, the script exits with error message."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a minimal instructions directory to avoid zero snippet count
            instructions_dir = tmp_path / "src" / "claude_all" / "instructions"
            instructions_dir.mkdir(parents=True)
            (instructions_dir / "demo" / "claude_md.md").write_text("test")
            (instructions_dir / "demo" / "claude-all.json").write_text('{"requires": []}')

            # Temporarily override SRC to point to directory with no manifests
            original_src = check_requires.SRC
            check_requires.SRC = tmp_path

            try:
                # Capture stderr to verify error message
                import io
                from contextlib import redirect_stderr

                stderr_buffer = io.StringIO()
                with redirect_stderr(stderr_buffer):
                    result = check_requires.main()

                self.assertEqual(result, 1)
                self.assertIn("error: no claude-all.json manifests found", stderr_buffer.getvalue())
            finally:
                check_requires.SRC = original_src

    def test_main_zero_snippets_exits_with_error(self):
        """When no instruction snippets are found, the script exits with error message."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create a minimal SRC directory with at least one manifest
            src_dir = tmp_path / "src" / "claude_all"
            src_dir.mkdir(parents=True)
            (src_dir / "test-skill" / "claude-all.json").write_text('{"requires": []}')

            # Temporarily override INSTRUCTIONS_DIR to point to directory with no snippets
            original_instructions_dir = check_requires.INSTRUCTIONS_DIR
            check_requires.INSTRUCTIONS_DIR = tmp_path / "instructions"
            check_requires.INSTRUCTIONS_DIR.mkdir(parents=True)  # Create empty dir

            try:
                # Capture stderr to verify error message
                import io
                from contextlib import redirect_stderr

                stderr_buffer = io.StringIO()
                with redirect_stderr(stderr_buffer):
                    result = check_requires.main()

                self.assertEqual(result, 1)
                self.assertIn("error: no instruction snippets found", stderr_buffer.getvalue())
            finally:
                check_requires.INSTRUCTIONS_DIR = original_instructions_dir

    def test_main_success_prints_summary(self):
        """Successful run prints summary line with counts."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create directory structure
            src_base = tmp_path / "src" / "claude_all"
            src_base.mkdir(parents=True)

            # Create one manifest
            manifest_dir = src_base / "test-skill"
            manifest_dir.mkdir()
            (manifest_dir / "claude-all.json").write_text('{"requires": []}')

            # Create one snippet
            snippet_dir = src_base / "instructions" / "test-snippet"
            snippet_dir.mkdir(parents=True)
            (snippet_dir / "claude_md.md").write_text("test")
            (snippet_dir / "claude-all.json").write_text('{"requires": []}')

            # Temporarily override the paths
            original_src = check_requires.SRC
            original_instructions_dir = check_requires.INSTRUCTIONS_DIR
            check_requires.SRC = src_base
            check_requires.INSTRUCTIONS_DIR = src_base / "instructions"

            try:
                # Capture stdout to verify summary line
                import io
                from contextlib import redirect_stdout

                stdout_buffer = io.StringIO()
                with redirect_stdout(stdout_buffer):
                    result = check_requires.main()

                self.assertEqual(result, 0)
                output = stdout_buffer.getvalue().strip()
                # Should contain the summary line
                self.assertIn("checked 1 manifest and 1 instruction snippet", output)
            finally:
                check_requires.SRC = original_src
                check_requires.INSTRUCTIONS_DIR = original_instructions_dir

    def test_main_existing_failure_still_fails(self):
        """A genuine validation failure still causes exit code 1."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create directory structure
            src_base = tmp_path / "src" / "claude_all"
            src_base.mkdir(parents=True)

            # Create a manifest with a bad requires entry
            manifest_dir = src_base / "test-skill"
            manifest_dir.mkdir()
            (manifest_dir / "claude-all.json").write_text('{"requires": ["nonexistent/resource"]}')

            # Create a corresponding snippet directory to avoid zero snippet count
            snippet_dir = src_base / "instructions" / "test-snippet"
            snippet_dir.mkdir(parents=True)
            (snippet_dir / "claude_md.md").write_text("test")
            (snippet_dir / "claude-all.json").write_text('{"requires": []}')

            # Temporarily override the paths
            original_src = check_requires.SRC
            original_instructions_dir = check_requires.INSTRUCTIONS_DIR
            check_requires.SRC = src_base
            check_requires.INSTRUCTIONS_DIR = src_base / "instructions"

            try:
                result = check_requires.main()
                self.assertEqual(result, 1)
            finally:
                check_requires.SRC = original_src
                check_requires.INSTRUCTIONS_DIR = original_instructions_dir


if __name__ == "__main__":
    unittest.main()
