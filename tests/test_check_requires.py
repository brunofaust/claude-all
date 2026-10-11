"""Tests for the `check_requires` gate's instruction-reference rule.

A standalone instruction snippet has no agent or skill of its own to carry a
dependency, so every resource it names must be declared in its `claude-all.json`
or installing the instruction ships a rule pointing at nothing.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
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


def test_main_success(tmp_path: Path) -> None:
    """Successful run prints summary and exits 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Copy the check_requires script into the repo
    (repo / "check_requires.py").write_text(
        (REPO_ROOT / "scripts" / "check_requires.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Create a minimal valid structure: one manifest and one instruction snippet
    src_dir = repo / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    # Manifest with empty requires
    (src_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    # Instruction snippet
    instr_dir = src_dir / "instructions" / "test"
    instr_dir.mkdir(parents=True)
    (instr_dir / "claude_md.md").write_text("No code spans.", encoding="utf-8")
    # Run the script
    result = subprocess.run(
        [sys.executable, "check_requires.py"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    # Success: exit code 0, summary line in stdout, no stderr
    assert result.returncode == 0
    assert "Inspected 2 units" in result.stdout
    assert result.stderr == ""


def test_main_zero_discovery(tmp_path: Path) -> None:
    """Zero-discovery fails with message and exits non-zero."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "check_requires.py").write_text(
        (REPO_ROOT / "scripts" / "check_requires.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Create src/claude_all directory but leave it empty (no manifests, no instrs)
    (repo / "src" / "claude_all").mkdir(parents=True)
    result = subprocess.run(
        [sys.executable, "check_requires.py"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    # Failure: exit code 1, error message in stderr
    assert result.returncode == 1
    assert "Error: No files to inspect" in result.stderr
    # Check that the searched patterns are mentioned
    assert "src/claude_all/**/claude-all.json" in result.stderr
    assert "src/claude_all/**/*.claude-all.json" in result.stderr
    assert "src/claude_all/instructions/*/claude_md.md" in result.stderr


def test_main_failure_still_works(tmp_path: Path) -> None:
    """A genuine failure still produces findings and exits 1."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "check_requires.py").write_text(
        (REPO_ROOT / "scripts" / "check_requires.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    src_dir = repo / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    # Manifest with a bad requires
    (src_dir / "claude-all.json").write_text('{"requires": ["bad/resource"]}', encoding="utf-8")
    # Also add an instruction snippet to avoid zero-discovery (not strictly necessary but safe)
    instr_dir = src_dir / "instructions" / "test"
    instr_dir.mkdir(parents=True)
    (instr_dir / "claude_md.md").write_text("", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "check_requires.py"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    # Failure due to findings: exit code 1
    assert result.returncode == 1
    # Finding should be in stdout
    assert "bad/resource" in result.stdout
    # Error summary in stderr
    assert "requires finding(s)" in result.stderr
    # Summary line should not be present (because there were findings)
    assert "Inspected" not in result.stdout
