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


def test_check_requires_success(tmp_path: Path, monkeypatch, capsys) -> None:
    """A successful run prints the number of units inspected."""
    known: set[str] = {"skills/test-skill", "instructions/test-instruction"}
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known)

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    claude_all_dir = src_dir / "claude_all"
    claude_all_dir.mkdir()
    instructions_dir = claude_all_dir / "instructions"
    instructions_dir.mkdir()

    # Create skill resource
    skill_dir = claude_all_dir / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "claude-all.json").write_text('{"requires": []}')

    # Create instruction resource
    instr_dir = instructions_dir / "test-instruction"
    instr_dir.mkdir()
    (instr_dir / "claude-all.json").write_text('{"requires": []}')
    (instr_dir / "claude_md.md").write_text("")

    # Patch the paths
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)

    exit_code = check_requires.main()
    assert exit_code == 0

    captured = capsys.readouterr()
    # The summary line should be in stdout
    assert "Inspected 2 units" in captured.out
    # There should be no findings in stdout and no error message in stderr
    assert captured.err == ""


def test_check_requires_zero_discovery(tmp_path: Path, monkeypatch, capsys) -> None:
    """A run that discovers zero files fails with a message."""
    known: set[str] = set()
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known)

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    claude_all_dir = src_dir / "claude_all"
    claude_all_dir.mkdir()
    instructions_dir = claude_all_dir / "instructions"
    instructions_dir.mkdir()
    # We intentionally create no manifest files and no instruction snippet files.

    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)

    exit_code = check_requires.main()
    assert exit_code == 1

    captured = capsys.readouterr()
    # The error message should be in stderr
    assert "no resources discovered for inspection" in captured.err
    # We should not see the summary line in stdout
    assert "Inspected" not in captured.out


def test_check_requires_existing_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    """An existing genuine failure still fails and does not print the success summary."""
    known: set[str] = {"skills/test-skill"}
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known)

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    claude_all_dir = src_dir / "claude_all"
    claude_all_dir.mkdir()
    instructions_dir = claude_all_dir / "instructions"
    instructions_dir.mkdir()

    # Create a skill resource
    skill_dir = claude_all_dir / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "claude-all.json").write_text('{"requires": []}')

    # Create a manifest with a dangling dependency
    manifest_dir = claude_all_dir / "some-agent"
    manifest_dir.mkdir()
    (manifest_dir / "claude-all.json").write_text('{"requires": ["skills/nonexistent"]}')

    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)

    exit_code = check_requires.main()
    assert exit_code == 1

    captured = capsys.readouterr()
    # The finding should be in stdout
    assert "requires 'skills/nonexistent' — no such resource" in captured.out
    # The error message about the number of findings should be in stderr
    assert "1 requires finding(s)" in captured.err
    # The success summary line should not be in stdout
    assert "Inspected" not in captured.out
