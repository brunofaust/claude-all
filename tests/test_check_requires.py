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


def test_main_zero_discovery_fails(tmp_path: Path, monkeypatch, capsys):
    """When no manifests and no snippets are found, exit with 2 and error message."""
    # Create a temporary directory structure that is empty for src/claude_all
    fake_src = tmp_path / "src"
    fake_src.mkdir()
    fake_claude_all = fake_src / "claude_all"
    fake_claude_all.mkdir()
    fake_instructions = fake_claude_all / "instructions"
    fake_instructions.mkdir()

    # Monkeypatch the constants
    monkeypatch.setattr(check_requires, "SRC", fake_src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", fake_instructions)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

    exit_code = check_requires.main()
    assert exit_code == 2

    captured = capsys.readouterr()
    # The error message should be printed to stderr
    assert "Error: No files found for manifest patterns" in captured.err
    assert "and for snippet pattern" in captured.err


def test_main_success_prints_summary(tmp_path: Path, monkeypatch, capsys):
    """When there are manifests and snippets and no findings, exit 0 and print summary."""
    import json

    # Create a temporary directory structure with one manifest and one snippet
    fake_src = tmp_path / "src"
    fake_src.mkdir()
    fake_claude_all = fake_src / "claude_all"
    fake_claude_all.mkdir()
    fake_instructions = fake_claude_all / "instructions"
    fake_instructions.mkdir()

    # Create a manifest
    manifest = fake_claude_all / "test.claude-all.json"
    manifest.write_text(json.dumps({"requires": []}), encoding="utf-8")

    # Create a snippet directory and files
    snippet_dir = fake_instructions / "demo"
    snippet_dir.mkdir()
    (snippet_dir / "claude_md.md").write_text("No references", encoding="utf-8")
    (snippet_dir / "claude-all.json").write_text(json.dumps({"requires": []}), encoding="utf-8")

    # Monkeypatch the constants
    monkeypatch.setattr(check_requires, "SRC", fake_src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", fake_instructions)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

    exit_code = check_requires.main()
    assert exit_code == 0

    captured = capsys.readouterr()
    # The summary line should be printed to stdout
    assert "Inspected 2 manifest(s) and 1 instruction snippet(s)" in captured.out


def test_main_failure_unchanged(tmp_path: Path, monkeypatch, capsys):
    """When there is a finding, exit 1 and print the finding and summary (existing behavior)."""
    import json

    # Create a temporary directory structure with one manifest that has a bad require
    fake_src = tmp_path / "src"
    fake_src.mkdir()
    fake_claude_all = fake_src / "claude_all"
    fake_claude_all.mkdir()
    fake_instructions = fake_claude_all / "instructions"
    fake_instructions.mkdir()

    # Create a manifest with a bad require
    manifest = fake_claude_all / "test.claude-all.json"
    manifest.write_text(json.dumps({"requires": ["bad/resource"]}), encoding="utf-8")

    # Monkeypatch the constants
    monkeypatch.setattr(check_requires, "SRC", fake_src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", fake_instructions)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

    exit_code = check_requires.main()
    assert exit_code == 1

    captured = capsys.readouterr()
    # The finding should be in stdout
    assert "requires 'bad/resource' — no such resource" in captured.out
    # The summary about findings should be in stderr
    assert "1 requires finding(s)" in captured.err
