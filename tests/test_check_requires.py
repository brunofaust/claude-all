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
from pathlib import Path
from unittest.mock import patch

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
    instruction_files = {root / "demo" / "claude_md.md"}
    findings = check_requires.find_undeclared_instruction_refs(KNOWN, instruction_files, root)

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
    instruction_files = {root / "demo" / "claude_md.md"}
    findings = check_requires.find_undeclared_instruction_refs(KNOWN, instruction_files, root)
    assert findings == []


def test_shipped_instructions_declare_every_reference() -> None:
    """Every shipped instruction requires each resource it names."""
    known = check_requires.load_resource_keys()

    assert check_requires.find_undeclared_instruction_refs(known) == []


def test_normal_success(tmp_path: Path) -> None:
    """A run with files and no violations exits 0 and prints inspection count."""
    # Set up a minimal repo structure
    src = tmp_path / "src"
    claude_all = src / "claude_all"
    skill_dir = claude_all / "skill"
    skill_dir.mkdir(parents=True)
    # Manifest with no requires
    (skill_dir / "claude-all.json").write_text("{}", encoding="utf-8")
    # Instruction snippet with no backticks (so no references)
    instr_dir = claude_all / "instructions" / "instr"
    instr_dir.mkdir(parents=True)
    (instr_dir / "claude_md.md").write_text("Just text.", encoding="utf-8")
    # Mock load_resource_keys to return a set that includes any resources we might reference
    # (none in this case, but we return something to avoid KeyError)
    with (
        patch.object(check_requires, "load_resource_keys", return_value=KNOWN),
        patch.object(check_requires, "REPO_ROOT", tmp_path),
        patch.object(check_requires, "SRC", tmp_path / "src"),
        patch.object(
            check_requires,
            "INSTRUCTIONS_DIR",
            tmp_path / "src" / "claude_all" / "instructions",
        ),
    ):
        # Capture stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_io = io.StringIO()
        stderr_io = io.StringIO()
        sys.stdout = stdout_io
        sys.stderr = stderr_io
        try:
            exit_code = check_requires.main()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        stdout = stdout_io.getvalue()
        stderr = stderr_io.getvalue()
        assert exit_code == 0
        # Should print exactly one line: "Inspected N files"
        assert stdout.strip().startswith("Inspected ")
        assert stdout.strip().endswith(" files")
        # Extract number
        import re

        match = re.search(r"Inspected (\d+) files", stdout.strip())
        assert match is not None
        count = int(match.group(1))
        # We expect: 1 manifest + 1 instruction snippet = 2
        assert count == 2
        assert stderr == ""


def test_zero_discovery_failure(tmp_path: Path) -> None:
    """A run with zero discovered files exits non-zero with error message."""
    # Set up an empty repo structure (src/claude_all exists but empty)
    src = tmp_path / "src"
    claude_all = src / "claude_all"
    claude_all.mkdir(parents=True)
    # No manifest files, no instruction snippet files
    with (
        patch.object(check_requires, "load_resource_keys", return_value=KNOWN),
        patch.object(check_requires, "REPO_ROOT", tmp_path),
        patch.object(check_requires, "SRC", tmp_path / "src"),
        patch.object(
            check_requires,
            "INSTRUCTIONS_DIR",
            tmp_path / "src" / "claude_all" / "instructions",
        ),
    ):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_io = io.StringIO()
        stderr_io = io.StringIO()
        sys.stdout = stdout_io
        sys.stderr = stderr_io
        try:
            exit_code = check_requires.main()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        stdout = stdout_io.getvalue()
        stderr = stderr_io.getvalue()
        assert exit_code == 1
        # Should print nothing to stdout (or maybe nothing)
        assert stdout == ""
        # Stderr should contain the error message about patterns
        assert "ERROR: No files matched the patterns:" in stderr
        # Check that the patterns mentioned include the expected ones
        assert "claude-all.json" in stderr
        assert "*.claude-all.json" in stderr
        assert "*/claude_md.md" in stderr
