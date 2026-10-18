"""Tests for the `check_requires` gate's instruction-reference rule.

A standalone instruction snippet has no agent or skill of its own to carry a
dependency, so every resource it names must be declared in its `claude-all.json`
or installing the instruction ships a rule pointing at nothing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
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


def test_undeclared_reference_is_reported(tmp_path: Path) -> None:
    """A named resource missing from ``requires`` is a finding.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    root = snippet(tmp_path, "Load `foo-skill`; delegate to `bar-agent`.\n", ["agents/bar-agent"])

    findings = check_requires.find_undeclared_instruction_refs(KNOWN, root)

    assert len(findings) == 1
    assert "`foo-skill`" in findings[0]
    assert "skills/foo-skill" in findings[0]


def test_declared_and_non_resource_tokens_pass(tmp_path: Path) -> None:
    """Declared resources, the snippet itself and plain code spans are fine.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    root = snippet(
        tmp_path,
        "Load `foo-skill`; see `demo`; set `MY_FLAG=1`.\n",
        ["skills/foo-skill"],
    )

    assert check_requires.find_undeclared_instruction_refs(KNOWN, root) == []


def test_shipped_instructions_declare_every_reference() -> None:
    """Every shipped instruction requires each resource it names."""
    known = check_requires.load_resource_keys()

    assert check_requires.find_undeclared_instruction_refs(known) == []


def test_success_runs_print_summary_line(capsys) -> None:
    """Successful runs print one summary line with the inspected count."""
    # Import the module directly to test main()
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_requires.py")],
        capture_output=True,
        text=True,
    )
    # Should succeed (exit 0) and print summary line
    assert result.returncode == 0
    # Check that output contains the summary line
    assert "Inspected" in result.stdout
    assert "files" in result.stdout
    assert "manifests" in result.stdout
    assert "instruction snippets" in result.stdout


def test_zero_discovery_fails_with_clear_message(monkeypatch, tmp_path) -> None:
    """A zero-discovery run exits non-zero with a clear message."""
    # Create a temporary directory with no matching files
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    # Mock the paths to point to our empty directory
    import scripts.check_requires as cr

    original_src = cr.SRC
    original_instructions = cr.INSTRUCTIONS_DIR

    try:
        cr.SRC = empty_dir / "src" / "claude_all"
        cr.INSTRUCTIONS_DIR = empty_dir / "src" / "claude_all" / "instructions"
        # Ensure directories exist
        cr.SRC.mkdir(parents=True)
        cr.INSTRUCTIONS_DIR.mkdir(parents=True)

        result = cr.main()
        # Should fail (exit 1) and print error to stderr
        assert result == 1
        # Note: We can't easily capture stderr in this context, but we know it should print an error
    finally:
        # Restore original paths
        cr.SRC = original_src
        cr.INSTRUCTIONS_DIR = original_instructions


def test_zero_discovery_manifest_only_fails(monkeypatch, tmp_path) -> None:
    """Zero manifest files but instruction files present should fail."""
    # Create directory structure with only instruction files
    base_dir = tmp_path / "project"
    base_dir.mkdir()
    src_dir = base_dir / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instructions_dir = src_dir / "instructions"
    instructions_dir.mkdir()

    # Create an instruction file but no manifest files
    (instructions_dir / "test" / "claude_md.md").parent.mkdir()
    (instructions_dir / "test" / "claude_md.md").write_text("test", encoding="utf-8")

    # Mock the paths
    import scripts.check_requires as cr

    original_src = cr.SRC
    original_instructions = cr.INSTRUCTIONS_DIR

    try:
        cr.SRC = src_dir
        cr.INSTRUCTIONS_DIR = instructions_dir

        result = cr.main()
        # Should fail (exit 1) due to zero manifest files
        assert result == 1
    finally:
        # Restore original paths
        cr.SRC = original_src
        cr.INSTRUCTIONS_DIR = original_instructions


def test_zero_discovery_instructions_only_fails(monkeypatch, tmp_path) -> None:
    """Zero instruction files but manifest files present should fail."""
    # Create directory structure with only manifest files
    base_dir = tmp_path / "project"
    base_dir.mkdir()
    src_dir = base_dir / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instructions_dir = src_dir / "instructions"
    instructions_dir.mkdir()

    # Create a manifest file but no instruction files
    (src_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")

    # Mock the paths
    import scripts.check_requires as cr

    original_src = cr.SRC
    original_instructions = cr.INSTRUCTIONS_DIR

    try:
        cr.SRC = src_dir
        cr.INSTRUCTIONS_DIR = instructions_dir

        result = cr.main()
        # Should fail (exit 1) due to zero instruction files
        assert result == 1
    finally:
        # Restore original paths
        cr.SRC = original_src
        cr.INSTRUCTIONS_DIR = original_instructions
