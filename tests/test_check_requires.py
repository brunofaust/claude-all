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


def test_zero_discovery_fails(monkeypatch, tmp_path, capsys):
    """Zero-discovery run fails with a clear message."""
    # Set up empty directories for manifests and snippets
    tmp_src = tmp_path / "src"
    tmp_src_claude_all = tmp_src / "claude_all"
    tmp_src_claude_all.mkdir(parents=True)
    tmp_instructions = tmp_path / "src" / "claude_all" / "instructions"
    tmp_instructions.mkdir(parents=True)
    # Monkeypatch the module's constants
    monkeypatch.setattr(check_requires, "SRC", tmp_src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_instructions)
    # Monkeypatch load_resource_keys to avoid ImportError and provide known resources
    monkeypatch.setattr(
        check_requires,
        "load_resource_keys",
        lambda: {"skills/foo-skill", "agents/bar-agent", "instructions/demo"},
    )
    # Run main
    exit_code = check_requires.main()
    # Expect failure
    assert exit_code == 1
    # Check stderr for error message
    captured = capsys.readouterr()
    assert "Error: no resources discovered" in captured.err
    assert "**/claude-all.json" in captured.err
    assert "'*/*.claude-all.json'" in captured.err
    assert "*/claude_md.md" in captured.err


def test_success_prints_summary(monkeypatch, tmp_path, capsys):
    """Successful run prints inspected count summary."""
    # Set up temporary directory with one manifest and one snippet
    tmp_src = tmp_path / "src"
    tmp_src_claude_all = tmp_src / "claude_all"
    tmp_src_claude_all.mkdir(parents=True)
    # Create a manifest
    manifest = tmp_src_claude_all / "test.claude-all.json"
    manifest.write_text('{"requires": ["skills/foo-skill"]}', encoding="utf-8")
    # Create instructions directory and a snippet
    tmp_instructions = tmp_path / "src" / "claude_all" / "instructions"
    tmp_instructions.mkdir(parents=True)
    snippet_dir = tmp_instructions / "test"
    snippet_dir.mkdir()
    (snippet_dir / "claude_md.md").write_text("See `skills/foo-skill`\n", encoding="utf-8")
    # Monkeypatch
    monkeypatch.setattr(check_requires, "SRC", tmp_src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_instructions)
    # Provide load_resource_keys that includes the referenced skill
    monkeypatch.setattr(
        check_requires,
        "load_resource_keys",
        lambda: {"skills/foo-skill"},
    )
    # Run main
    exit_code = check_requires.main()
    # Expect success
    assert exit_code == 0
    captured = capsys.readouterr()
    # Check stdout for summary line
    assert "Inspected 2 units" in captured.out  # 1 manifest + 1 snippet
    # Ensure no findings output
    assert captured.err == ""
