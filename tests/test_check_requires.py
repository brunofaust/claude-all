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


def test_normal_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """When there are files to check and no findings, exits 0 and prints inspection count."""
    src = tmp_path / "src"
    claude_all = src / "claude_all"
    claude_all.mkdir(parents=True)
    (claude_all / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    # No instructions directory.

    monkeypatch.setattr("check_requires.SRC", src)
    monkeypatch.setattr("check_requires.INSTRUCTIONS_DIR", claude_all / "instructions")
    monkeypatch.setattr("check_requires.load_resource_keys", lambda: set())

    exit_code = check_requires.main()
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "Inspected 1 units" in captured.out


def test_zero_discovery_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """When there are no files to check, the script exits 2 and prints an error message."""
    src = tmp_path / "src"
    claude_all = src / "claude_all"
    claude_all.mkdir(parents=True)
    # Leave claude_all empty.
    instructions_dir = claude_all / "instructions"
    # We leave it non-existent.

    monkeypatch.setattr("check_requires.SRC", src)
    monkeypatch.setattr("check_requires.INSTRUCTIONS_DIR", instructions_dir)
    monkeypatch.setattr("check_requires.load_resource_keys", lambda: set())

    exit_code = check_requires.main()
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Error: no files found" in captured.err
    assert "**/claude-all.json" in captured.err
    assert "'*/claude_md.md'" in captured.err


def test_genuine_failure_still_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """When there is a genuine validation error, the script exits 1 and prints the error."""
    src = tmp_path / "src"
    claude_all = src / "claude_all"
    claude_all.mkdir(parents=True)
    # Create a manifest that requires a non-existent resource.
    (claude_all / "claude-all.json").write_text('{"requires": ["non/existent"]}', encoding="utf-8")
    # No instructions.

    monkeypatch.setattr("check_requires.SRC", src)
    monkeypatch.setattr("check_requires.INSTRUCTIONS_DIR", claude_all / "instructions")
    # We do not mock load_resource_keys because we want it to discover the resources.
    # However, we have not created any agents, skills, etc., so the known set will be empty.

    exit_code = check_requires.main()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "requires 'non/existent' — no such resource" in captured.out
    # The summary line should not be printed because there are findings.
    assert "Inspected" not in captured.out
