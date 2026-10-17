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


def test_main_reports_inspected_unit_count(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "src" / "claude_all"
    root.mkdir(parents=True)
    (root / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    (root / "demo.claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    instructions = root / "instructions"
    snippet(instructions, "No resource refs.\n", [])
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/foo-skill"})

    assert check_requires.main() == 0
    assert capsys.readouterr().out == "check_requires: inspected 5 units\n"


def test_main_fails_when_discovery_patterns_match_nothing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    root = tmp_path / "src" / "claude_all"
    root.mkdir(parents=True)
    instructions = root / "instructions"
    instructions.mkdir()
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/foo-skill"})

    assert check_requires.main() == 2
    captured = capsys.readouterr()
    assert "claude-all.json" in captured.err
    assert "*.claude-all.json" in captured.err
    assert "*/claude_md.md" in captured.err
    assert captured.out == ""


def test_main_fails_when_resource_discovery_is_empty(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "src" / "claude_all"
    root.mkdir(parents=True)
    (root / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    (root / "demo.claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    instructions = root / "instructions"
    snippet(instructions, "No resource refs.\n", [])
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    assert check_requires.main() == 2
    captured = capsys.readouterr()
    assert "discovery pattern matched zero units: discover([])" in captured.err
    assert captured.out == ""


def test_main_preserves_validation_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "src" / "claude_all"
    root.mkdir(parents=True)
    (root / "claude-all.json").write_text('{"requires": ["skills/missing"]}', encoding="utf-8")
    (root / "demo.claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    instructions = root / "instructions"
    snippet(instructions, "No resource refs.\n", [])
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/foo-skill"})

    assert check_requires.main() == 1
    captured = capsys.readouterr()
    assert "requires 'skills/missing'" in captured.out
    assert "1 requires finding(s)" in captured.err
    assert "inspected" not in captured.out


def test_shipped_instructions_declare_every_reference() -> None:
    """Every shipped instruction requires each resource it names."""
    known = check_requires.load_resource_keys()

    assert check_requires.find_undeclared_instruction_refs(known) == []
