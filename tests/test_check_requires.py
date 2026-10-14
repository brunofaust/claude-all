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


def test_zero_discovery_exits_2_and_prints_message(tmp_path: Path, monkeypatch, capsys) -> None:
    """When no manifest or snippet files are discovered, exit 2 with clear message."""
    # Set up empty directories
    src_dir = tmp_path / "src"
    claude_all_dir = src_dir / "claude_all"
    instructions_dir = claude_all_dir / "instructions"
    src_dir.mkdir()
    claude_all_dir.mkdir()
    instructions_dir.mkdir()
    # Monkeypatch the paths used by the script
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)
    # Load resource keys should still work; we can mock it to avoid filesystem dependence
    monkeypatch.setattr(
        check_requires, "load_resource_keys", lambda: {"skills/foo-skill", "agents/bar-agent"}
    )
    # Run the main function
    exit_code = check_requires.main()
    # Check exit code
    assert exit_code == 2
    # Check stderr for the expected message
    stderr = capsys.readouterr().err
    assert "No files discovered for inspection via patterns:" in stderr
    assert "src/claude_all/**/*.claude-all.json" in stderr
    assert "src/claude_all/instructions/*/claude_md.md" in stderr
    # Ensure no stdout output (findings)
    assert capsys.readouterr().out == ""


def test_success_exits_0_and_prints_inspected_count(tmp_path: Path, monkeypatch, capsys) -> None:
    """When files are discovered and no failures, exit 0 and print inspected count."""
    # Set up directories with one manifest and one snippet
    src_dir = tmp_path / "src"
    claude_all_dir = src_dir / "claude_all"
    instructions_dir = claude_all_dir / "instructions"
    src_dir.mkdir()
    claude_all_dir.mkdir()
    instructions_dir.mkdir()
    # Create a manifest file
    manifest = claude_all_dir / "test.claude-all.json"
    manifest.write_text('{"requires": []}', encoding="utf-8")
    # Create a snippet directory and file
    snippet_dir = instructions_dir / "demo"
    snippet_dir.mkdir()
    (snippet_dir / "claude_md.md").write_text("See `demo`.\n", encoding="utf-8")
    (snippet_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    # Monkeypatch the paths
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)
    # Mock load_resource_keys to return a known set (so validation passes)
    monkeypatch.setattr(
        check_requires,
        "load_resource_keys",
        lambda: {"skills/foo-skill", "agents/bar-agent", "instructions/demo"},
    )
    # Run the main function
    exit_code = check_requires.main()
    # Check exit code
    assert exit_code == 0
    # Check stderr for inspection count line
    stderr = capsys.readouterr().err
    # Expect exactly one line: inspected=1 manifests, 1 snippets
    # Note: there may be trailing newline, but we can check for the substring
    assert "inspected=1 manifests, 1 snippets" in stderr
    # Ensure no findings printed to stdout
    assert capsys.readouterr().out == ""
    # Ensure no error message printed to stderr (the validation failure message)
    assert "\n" not in stderr or stderr.strip() == "inspected=1 manifests, 1 snippets"


def test_failure_exits_1_and_prints_inspected_count_and_findings(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """When files are discovered and there are failures, exit 1 and print"""
    """ inspected count and findings."""
    # Set up directories with one manifest that has a dangling requirement
    src_dir = tmp_path / "src"
    claude_all_dir = src_dir / "claude_all"
    instructions_dir = claude_all_dir / "instructions"
    src_dir.mkdir()
    claude_all_dir.mkdir()
    instructions_dir.mkdir()
    # Create a manifest file with a dangling requirement
    manifest = claude_all_dir / "test.claude-all.json"
    manifest.write_text('{"requires": ["unknown/resource"]}', encoding="utf-8")
    # Create a snippet directory and file (with no references to keep it simple)
    snippet_dir = instructions_dir / "demo"
    snippet_dir.mkdir()
    (snippet_dir / "claude_md.md").write_text("No refs.\n", encoding="utf-8")
    (snippet_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    # Monkeypatch the paths
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)
    # Mock load_resource_keys to return a known set that does NOT include "unknown/resource"
    monkeypatch.setattr(
        check_requires,
        "load_resource_keys",
        lambda: {"skills/foo-skill", "agents/bar-agent", "instructions/demo"},
    )
    # Run the main function
    exit_code = check_requires.main()
    # Check exit code
    assert exit_code == 1
    # Check stderr for inspection count line
    stderr = capsys.readouterr().err
    assert "inspected=1 manifests, 1 snippets" in stderr
    # Check stdout for the finding
    stdout = capsys.readouterr().out
    assert "requires 'unknown/resource' — no such resource" in stdout
    # Check stderr for the final error message (after findings)
    assert "\n1 requires finding(s)" in stderr
