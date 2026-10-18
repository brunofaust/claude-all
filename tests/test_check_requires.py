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


def test_real_repo_run_succeeds_with_one_summary_line(capsys: pytest.CaptureFixture[str]) -> None:
    """Shipped repo run exits 0 and prints one non-zero inspected summary."""
    assert check_requires.main() == 0

    lines = capsys.readouterr().out.splitlines()
    summaries = [line for line in lines if line.startswith("requires-check: inspected ")]
    assert len(summaries) == 1
    assert int(summaries[0].split()[2]) > 0


def test_zero_discovery_exits_two_and_names_the_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empty tree matches nothing, so the gate fails closed with exit 2."""
    src = tmp_path / "src"
    (src / "claude_all").mkdir(parents=True)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", src / "claude_all" / "instructions")

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert "CANNOT CHECK:" in captured.err
    assert "claude-all.json" in captured.err
    assert "*/claude_md.md" in captured.err
    assert "requires-check: inspected" not in captured.out


def test_missing_instructions_dir_fails_even_with_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matching manifests must not mask an empty snippet discovery point."""
    src = tmp_path / "src"
    skill = src / "claude_all" / "skills" / "generic" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(json.dumps({"requires": []}))
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", src / "claude_all" / "instructions")

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert "CANNOT CHECK:" in captured.err
    assert "*/claude_md.md" in captured.err
    assert "claude-all.json" not in captured.err
    assert "requires-check: inspected" not in captured.out


def test_genuine_dangling_requires_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A manifest requiring a missing resource still yields exit 1 and a finding."""
    src = tmp_path / "src"
    skill = src / "claude_all" / "skills" / "generic" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(json.dumps({"requires": ["skills/ghost"]}))
    instructions = src / "claude_all" / "instructions" / "demo"
    instructions.mkdir(parents=True)
    (instructions / "claude_md.md").write_text("Plain snippet.\n", encoding="utf-8")
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", src / "claude_all" / "instructions")

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "requires 'skills/ghost' — no such resource" in captured.out
    assert "1 requires finding(s)" in captured.err
    assert "requires-check: inspected" not in captured.out


def test_undeclared_instruction_reference_still_fails_through_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A snippet naming an undeclared shipped resource still yields exit 1."""
    src = tmp_path / "src"
    skill = src / "claude_all" / "skills" / "generic" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(json.dumps({"requires": []}))
    instructions = src / "claude_all" / "instructions" / "demo"
    instructions.mkdir(parents=True)
    (instructions / "claude_md.md").write_text("Delegate to `retro`.\n", encoding="utf-8")
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", src / "claude_all" / "instructions")

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "names `retro` but its claude-all.json does not require" in captured.out
    assert "1 requires finding(s)" in captured.err
    assert "requires-check: inspected" not in captured.out


def test_clean_tree_prints_exact_inspected_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A clean tree exits 0 and reports manifests + snippets + requires entries."""
    src = tmp_path / "src"
    skill = src / "claude_all" / "skills" / "generic" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(json.dumps({"requires": ["skills/demo"]}))
    instructions = src / "claude_all" / "instructions" / "demo"
    instructions.mkdir(parents=True)
    (instructions / "claude_md.md").write_text("Plain snippet.\n", encoding="utf-8")
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", src / "claude_all" / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/demo"})

    assert check_requires.main() == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "requires-check: inspected 3 unit(s) — manifests=1 snippets=1 requires=1 resources=1"
    ]
    assert captured.err == ""


def test_empty_installer_discovery_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero installer-discovered resources exits 2 even when both globs match."""
    src = tmp_path / "src"
    skill = src / "claude_all" / "skills" / "generic" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(json.dumps({"requires": []}))
    instructions = src / "claude_all" / "instructions" / "demo"
    instructions.mkdir(parents=True)
    (instructions / "claude_md.md").write_text("Plain snippet.\n", encoding="utf-8")
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", src / "claude_all" / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert "CANNOT CHECK: installer discover([]) matched no resources" in captured.err
    assert "requires-check: inspected" not in captured.out
