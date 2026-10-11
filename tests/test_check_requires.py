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


def test_success_prints_summary(tmp_path: Path, monkeypatch) -> None:
    """In a successful run, a summary line with the inspected count is printed."""
    # Set up a temporary directory structure
    src_dir = tmp_path / "src"
    claude_all_dir = src_dir / "claude_all"
    instructions_dir = claude_all_dir / "instructions"
    claude_all_dir.mkdir(parents=True)
    instructions_dir.mkdir(parents=True)

    # Create a valid manifest file
    manifest = claude_all_dir / "claude-all.json"
    manifest.write_text('{"requires": []}', encoding="utf-8")

    # Create a valid instruction snippet
    snippet_dir = instructions_dir / "demo"
    snippet_dir.mkdir()
    (snippet_dir / "claude_md.md").write_text("No references.", encoding="utf-8")
    (snippet_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")

    # Monkeypatch the constants in the check_requires module
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)

    # Mock load_resource_keys to return a known set (empty is fine because we have no requires)
    known: set[str] = set()
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known)
    # Run the main function and capture exit code, stdout, stderr
    import io
    import sys

    old_stderr = sys.stderr
    old_stdout = sys.stdout
    sys.stderr = io.StringIO()
    sys.stdout = io.StringIO()
    try:
        exit_code = check_requires.main()
        stderr_output = sys.stderr.getvalue()
        stdout_output = sys.stdout.getvalue()
    finally:
        sys.stderr = old_stderr
        sys.stdout = old_stdout
    assert exit_code == 0
    # Check that the summary line is printed to stdout
    assert stdout_output.strip() == "Inspected 2 units"
    # No findings should be printed to stdout (so the summary line is the only output)
    # stderr should be empty
    assert stderr_output == ""


def test_zero_discovery_fails(tmp_path: Path, monkeypatch) -> None:
    """When no files are found to check, the checker fails with a zero-discovery message."""
    # Set up a temporary directory structure but with no manifest or instruction files
    src_dir = tmp_path / "src"
    claude_all_dir = src_dir / "claude_all"
    instructions_dir = claude_all_dir / "instructions"
    claude_all_dir.mkdir(parents=True)
    instructions_dir.mkdir(parents=True)
    # Intentionally leave them empty

    # Monkeypatch the constants
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)

    # Mock load_resource_keys to return a known set (irrelevant)
    known: set[str] = set()
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known)

    # Run the main function
    import io
    import sys

    old_stderr = sys.stderr
    old_stdout = sys.stdout
    sys.stderr = io.StringIO()
    sys.stdout = io.StringIO()
    try:
        exit_code = check_requires.main()
        stderr_output = sys.stderr.getvalue()
        stdout_output = sys.stdout.getvalue()
    finally:
        sys.stderr = old_stderr
        sys.stdout = old_stdout

    # Check exit code and output
    assert exit_code == 1
    # stderr should contain the zero-discovery message
    expected_msg = (
        "Zero-discovery: manifest patterns ['**/claude-all.json', '**/*.claude-all.json'] "
        "and instruction snippet pattern '*/claude_md.md' matched no files."
    )
    assert expected_msg in stderr_output
    # stdout should be empty (no findings)
    assert stdout_output == ""


def test_existing_failure_still_fails(tmp_path: Path, monkeypatch) -> None:
    """A genuine failure (dangling requires) still fails and does not print the summary line."""
    # Set up a temporary directory structure
    src_dir = tmp_path / "src"
    claude_all_dir = src_dir / "claude_all"
    instructions_dir = claude_all_dir / "instructions"
    claude_all_dir.mkdir(parents=True)
    instructions_dir.mkdir(parents=True)

    # Create a manifest file with a dangling requires
    manifest = claude_all_dir / "claude-all.json"
    manifest.write_text('{"requires": ["dangling/resource"]}', encoding="utf-8")

    # No instruction snippets for simplicity

    # Monkeypatch the constants
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)

    # Mock load_resource_keys to return a known set that does not include the dangling resource
    known: set[str] = set()  # empty set, so the dangling resource is not known
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known)

    # Run the main function
    import io
    import sys

    old_stderr = sys.stderr
    old_stdout = sys.stdout
    sys.stderr = io.StringIO()
    sys.stdout = io.StringIO()
    try:
        exit_code = check_requires.main()
        stderr_output = sys.stderr.getvalue()
        stdout_output = sys.stdout.getvalue()
    finally:
        sys.stderr = old_stderr
        sys.stdout = old_stdout

    # Check exit code and output
    assert exit_code == 1
    # stdout should contain the finding about the dangling resource
    assert "requires 'dangling/resource' — no such resource" in stdout_output
    # stderr should contain the usual error message about the findings
    assert "\n1 requires finding(s) — a dependency manifest points at a " in stderr_output
    # The summary line should not be printed because there were findings
    assert "Inspected" not in stdout_output
    # Also, the summary line should not be in stderr
    assert "Inspected" not in stderr_output
