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

import pytest

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


def test_success_normal_case_prints_scanned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Successful run prints scanned count and exits 0."""
    # Create a minimal claude-all.json to make load_resource_keys work
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").parent.mkdir(parents=True)
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").write_text(
        '{"requires": []}'
    )

    # Create an instruction snippet
    instructions_dir = tmp_path / "src" / "claude_all" / "instructions" / "test"
    instructions_dir.mkdir(parents=True)
    (instructions_dir / "claude_md.md").write_text("See `test-skill`\n")
    (instructions_dir / "claude-all.json").write_text('{"requires": ["skills/test-skill"]}')

    # Run the check
    result = check_requires.main()

    # Should succeed (exit 0) and print scanned count
    assert result == 0
    captured = capsys.readouterr()
    assert "scanned=" in captured.err


def test_zero_discovery_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Zero discovery should fail with error message."""
    # Create a temporary empty directory structure
    empty_src = tmp_path / "src" / "claude_all"
    empty_src.mkdir(parents=True)

    # Point REPO_ROOT to our empty directory for this test
    original_repo_root = check_requires.REPO_ROOT
    check_requires.REPO_ROOT = tmp_path  # type: ignore[attr-defined]
    check_requires.SRC = tmp_path / "src"  # type: ignore[attr-defined]
    check_requires.INSTRUCTIONS_DIR = tmp_path / "src" / "claude_all" / "instructions"  # type: ignore[attr-defined]

    try:
        result = check_requires.main()

        # Should fail (exit 2) and print zero discovery error
        assert result == 2
        captured = capsys.readouterr()
        assert "ERROR: Zero discovery" in captured.err
        assert "claude-all.json" in captured.err
        assert "claude_md.md" in captured.err
    finally:
        # Restore original values
        check_requires.REPO_ROOT = original_repo_root  # type: ignore[attr-defined]
        check_requires.SRC = original_repo_root / "src"  # type: ignore[attr-defined]
        check_requires.INSTRUCTIONS_DIR = original_repo_root / "src" / "claude_all" / "instructions"  # type: ignore[attr-defined]


def test_zero_discovery_manifests_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Zero discovery of manifests only should fail with specific message."""
    # Create instruction snippets but no manifests
    instructions_dir = tmp_path / "src" / "claude_all" / "instructions" / "test"
    instructions_dir.mkdir(parents=True)
    (instructions_dir / "claude_md.md").write_text("See `test-skill`\n")
    (instructions_dir / "claude-all.json").write_text('{"requires": ["skills/test-skill"]}')

    # Point to our test directory
    original_repo_root = check_requires.REPO_ROOT
    check_requires.REPO_ROOT = tmp_path  # type: ignore[attr-defined]
    check_requires.SRC = tmp_path / "src"  # type: ignore[attr-defined]
    check_requires.INSTRUCTIONS_DIR = tmp_path / "src" / "claude_all" / "instructions"  # type: ignore[attr-defined]

    try:
        result = check_requires.main()

        # Should fail (exit 2) and print zero discovery error for manifests only
        assert result == 2
        captured = capsys.readouterr()
        assert "ERROR: Zero discovery" in captured.err
        assert "claude-all.json" in captured.err
        assert "manifests" in captured.err
    finally:
        # Restore original values
        check_requires.REPO_ROOT = original_repo_root  # type: ignore[attr-defined]
        check_requires.SRC = original_repo_root / "src"  # type: ignore[attr-defined]
        check_requires.INSTRUCTIONS_DIR = original_repo_root / "src" / "claude_all" / "instructions"  # type: ignore[attr-defined]


def test_zero_discovery_snippets_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Zero discovery of snippets only should fail with specific message."""
    # Create manifests but no instruction snippets
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").parent.mkdir(parents=True)
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").write_text(
        '{"requires": []}'
    )

    # Point to our test directory
    original_repo_root = check_requires.REPO_ROOT
    check_requires.REPO_ROOT = tmp_path  # type: ignore[attr-defined]
    check_requires.SRC = tmp_path / "src"  # type: ignore[attr-defined]
    check_requires.INSTRUCTIONS_DIR = tmp_path / "src" / "claude_all" / "instructions"  # type: ignore[attr-defined]

    try:
        result = check_requires.main()

        # Should fail (exit 2) and print zero discovery error for snippets only
        assert result == 2
        captured = capsys.readouterr()
        assert "ERROR: Zero discovery" in captured.err
        assert "claude_md.md" in captured.err
        assert "instruction snippets" in captured.err
    finally:
        # Restore original values
        check_requires.REPO_ROOT = original_repo_root  # type: ignore[attr-defined]
        check_requires.SRC = original_repo_root / "src"  # type: ignore[attr-defined]
        check_requires.INSTRUCTIONS_DIR = original_repo_root / "src" / "claude_all" / "instructions"  # type: ignore[attr-defined]


def test_existing_failure_still_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An existing genuine failure should still fail."""
    # Create a manifest with a bad requirement
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").parent.mkdir(parents=True)
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").write_text(
        '{"requires": ["skills/nonexistent"]}'
    )

    # Point to our test directory
    original_repo_root = check_requires.REPO_ROOT
    check_requires.REPO_ROOT = tmp_path  # type: ignore[attr-defined]
    check_requires.SRC = tmp_path / "src"  # type: ignore[attr-defined]
    check_requires.INSTRUCTIONS_DIR = tmp_path / "src" / "claude_all" / "instructions"  # type: ignore[attr-defined]

    try:
        result = check_requires.main()

        # Should fail (exit 1) due to the bad requirement
        assert result == 1
        captured = capsys.readouterr()
        assert "requires 'skills/nonexistent'" in captured.out
        assert "scanned=1" in captured.err  # Should have discovered 1 manifest
    finally:
        # Restore original values
        check_requires.REPO_ROOT = original_repo_root  # type: ignore[attr-defined]
        check_requires.SRC = original_repo_root / "src"  # type: ignore[attr-defined]
        check_requires.INSTRUCTIONS_DIR = original_repo_root / "src" / "claude_all" / "instructions"  # type: ignore[attr-defined]
