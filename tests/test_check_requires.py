"""Tests for the `check_requires` gate's instruction-reference rule.

A standalone instruction snippet has no agent or skill of its own to carry a
dependency, so every resource it names must be declared in its `claude-all.json`
or installing the instruction ships a rule pointing at nothing.
"""

from __future__ import annotations

import importlib.util
import io
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
    def test_undeclared_reference_is_reported(self) -> None:
        """A named resource missing from ``requires`` is a finding."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            root = snippet(
                tmp_path, "Load `foo-skill`; delegate to `bar-agent`.\n", ["agents/bar-agent"]
            )

            findings = check_requires.find_undeclared_instruction_refs(KNOWN, root)

            self.assertEqual(len(findings), 1)
            self.assertIn("`foo-skill`", findings[0])
            self.assertIn("skills/foo-skill", findings[0])

    def test_declared_and_non_resource_tokens_pass(self) -> None:
        """Declared resources, the snippet itself and plain code spans are fine."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            root = snippet(
                tmp_path,
                "Load `foo-skill`; see `demo`; set `MY_FLAG=1`.\n",
                ["skills/foo-skill"],
            )

            self.assertEqual(check_requires.find_undeclared_instruction_refs(KNOWN, root), [])

    def test_shipped_instructions_declare_every_reference(self) -> None:
        """Every shipped instruction requires each resource it names."""
        known = check_requires.load_resource_keys()

        self.assertEqual(check_requires.find_undeclared_instruction_refs(known), [])

    def test_success_prints_summary_and_exits_zero(self) -> None:
        """When manifests are present and valid, the script exits 0
        with a summary line."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            # Monkey-patch the paths to point to the temporary directory.
            original_repo_root = check_requires.REPO_ROOT
            original_src = check_requires.SRC
            original_instructions_dir = check_requires.INSTRUCTIONS_DIR
            try:
                check_requires.REPO_ROOT = tmp_path  # type: ignore[attr-defined]
                check_requires.SRC = check_requires.REPO_ROOT / "src"  # type: ignore[attr-defined]
                check_requires.INSTRUCTIONS_DIR = check_requires.SRC / "claude_all" / "instructions"  # type: ignore[attr-defined]
                # Ensure the directories exist.
                check_requires.INSTRUCTIONS_DIR.mkdir(parents=True)
                (check_requires.SRC / "claude_all").mkdir(parents=True)

                # Create a valid manifest.
                manifest_dir = check_requires.SRC / "claude_all" / "skill"
                manifest_dir.mkdir(parents=True)
                manifest = manifest_dir / "claude-all.json"
                manifest.write_text('{"requires": ["skills/valid"]}', encoding="utf-8")

                # Monkey-patch load_resource_keys to return a known set that includes the require.
                original_load = check_requires.load_resource_keys
                check_requires.load_resource_keys = lambda: {"skills/valid"}

                # Capture stdout and stderr.
                stdout_capture = io.StringIO()
                stderr_capture = io.StringIO()
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                sys.stdout = stdout_capture
                sys.stderr = stderr_capture
                try:
                    exit_code = check_requires.main()
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr

                # Restore the patch.
                check_requires.load_resource_keys = original_load

                # Assertions.
                self.assertEqual(exit_code, 0)
                stdout_output = stdout_capture.getvalue().strip()
                # Expect the summary line.
                self.assertEqual(stdout_output, "Inspected 1 claude-all.json manifest(s)")
                # stderr should be empty.
                self.assertEqual(stderr_capture.getvalue(), "")
            finally:
                check_requires.REPO_ROOT = original_repo_root
                check_requires.SRC = original_src
                check_requires.INSTRUCTIONS_DIR = original_instructions_dir

    def test_zero_discovery_fails_with_message(self) -> None:
        """When no manifests are found, the script exits 1 with an error message."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            original_repo_root = check_requires.REPO_ROOT
            original_src = check_requires.SRC
            original_instructions_dir = check_requires.INSTRUCTIONS_DIR
            try:
                check_requires.REPO_ROOT = tmp_path  # type: ignore[attr-defined]
                check_requires.SRC = check_requires.REPO_ROOT / "src"  # type: ignore[attr-defined]
                check_requires.INSTRUCTIONS_DIR = check_requires.SRC / "claude_all" / "instructions"  # type: ignore[attr-defined]
                # We do not create any manifest files.

                # Monkey-patch load_resource_keys to avoid calling the actual discover (which would look in the real src).
                original_load = check_requires.load_resource_keys
                check_requires.load_resource_keys = lambda: set()

                # Capture stdout and stderr.
                stdout_capture = io.StringIO()
                stderr_capture = io.StringIO()
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                sys.stdout = stdout_capture
                sys.stderr = stderr_capture
                try:
                    exit_code = check_requires.main()
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr

                # Restore the patch.
                check_requires.load_resource_keys = original_load

                # Assertions.
                self.assertEqual(exit_code, 1)
                stdout_output = stdout_capture.getvalue().strip()
                # On zero-discovery, we expect no output to stdout (the summary line is only on success).
                self.assertEqual(stdout_output, "")
                stderr_output = stderr_capture.getvalue().strip()
                # Expect the error message about zero manifests.
                expected_error = (
                    f"Error: Zero manifests discovered (looked for 'claude-all.json' and '*.claude-all.json' "
                    f"under {check_requires.SRC / 'claude_all'})"
                )
                self.assertEqual(stderr_output, expected_error)
            finally:
                check_requires.REPO_ROOT = original_repo_root
                check_requires.SRC = original_src
                check_requires.INSTRUCTIONS_DIR = original_instructions_dir

    def test_existing_failure_still_fails(self) -> None:
        """When a manifest has a dangling require, the script exits 1 with the finding and error message."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            original_repo_root = check_requires.REPO_ROOT
            original_src = check_requires.SRC
            original_instructions_dir = check_requires.INSTRUCTIONS_DIR
            try:
                check_requires.REPO_ROOT = tmp_path  # type: ignore[attr-defined]
                check_requires.SRC = check_requires.REPO_ROOT / "src"  # type: ignore[attr-defined]
                check_requires.INSTRUCTIONS_DIR = check_requires.SRC / "claude_all" / "instructions"  # type: ignore[attr-defined]
                # Ensure the directories exist.
                check_requires.INSTRUCTIONS_DIR.mkdir(parents=True)
                (check_requires.SRC / "claude_all").mkdir(parents=True)

                # Create a manifest with a dangling require.
                manifest_dir = check_requires.SRC / "claude_all" / "skill"
                manifest_dir.mkdir(parents=True)
                manifest = manifest_dir / "claude-all.json"
                manifest.write_text('{"requires": ["skills/missing"]}', encoding="utf-8")

                # Monkey-patch load_resource_keys to return a known set that does
                # not include the missing require.
                original_load = check_requires.load_resource_keys
                check_requires.load_resource_keys = lambda: set()  # empty set

                # Capture stdout and stderr.
                stdout_capture = io.StringIO()
                stderr_capture = io.StringIO()
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                sys.stdout = stdout_capture
                sys.stderr = stderr_capture
                try:
                    exit_code = check_requires.main()
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr

                # Restore the patch.
                check_requires.load_resource_keys = original_load

                # Assertions.
                self.assertEqual(exit_code, 1)
                stdout_output = stdout_capture.getvalue().strip()
                # Expect the finding printed to stdout.
                # The finding should be about the missing require.
                # We know the manifest is at: src/claude_all/skill/claude-all.json
                # (relative to the tmp_path). The repo root is tmp_path, so the
                # relative path is: src/claude_all/skill/claude-all.json
                # The finding should be: "src/claude_all/skill/claude-all.json:
                # requires 'skills/missing' — no such resource (renamed/deleted? "
                #   "a built-in like /code-review does not belong in requires)"
                # We'll check for a substring.
                self.assertIn("requires 'skills/missing' — no such resource", stdout_output)
                # stderr should contain the error message about the findings.
                stderr_output = stderr_capture.getvalue()
                self.assertIn("1 requires finding(s)", stderr_output)
                # We do not expect the summary line because there were findings.
                self.assertNotIn("Inspected", stdout_output)
            finally:
                check_requires.REPO_ROOT = original_repo_root
                check_requires.SRC = original_src
                check_requires.INSTRUCTIONS_DIR = original_instructions_dir


if __name__ == "__main__":
    unittest.main()
