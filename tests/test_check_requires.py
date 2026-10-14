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


def test_zero_discovery_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    """When no manifests are found, the script exits with code 2
    and prints an error."""
    # Set up a temporary repo root with no manifests
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(
        check_requires, "INSTRUCTIONS_DIR", tmp_path / "src" / "claude_all" / "instructions"
    )
    # Create the directories (they will be empty)
    (check_requires.SRC / "claude_all").mkdir(parents=True, exist_ok=True)
    (check_requires.INSTRUCTIONS_DIR).mkdir(parents=True, exist_ok=True)
    # Run the main function
    exit_code = check_requires.main()
    assert exit_code == 2
    captured = capsys.readouterr()
    # Expect the error message in stderr
    under_path = check_requires.SRC.relative_to(check_requires.REPO_ROOT)
    expected_msg = (
        f"No files matched patterns 'claude-all.json' and '*.claude-all.json' under {under_path}"
    )
    assert expected_msg in captured.err
    # We don't expect anything in stdout
    assert captured.out == ""


def test_success_no_findings(tmp_path: Path, monkeypatch, capsys) -> None:
    """When manifests are found and there are no violations,
    exit 0 and print scanned line."""
    # Set up a temporary repo root
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(
        check_requires, "INSTRUCTIONS_DIR", tmp_path / "src" / "claude_all" / "instructions"
    )
    # Create the directory structure
    src_claude_all = check_requires.SRC / "claude_all"
    src_claude_all.mkdir(parents=True)
    (check_requires.INSTRUCTIONS_DIR).mkdir(parents=True)
    # Create a manifest file
    manifest = src_claude_all / "claude-all.json"
    manifest.write_text('{"requires": []}', encoding="utf-8")
    # Mock load_resource_keys to return an empty set (so no violations)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())
    # Run the main function
    exit_code = check_requires.main()
    assert exit_code == 0
    captured = capsys.readouterr()
    # Expect the scanned line in stdout
    assert captured.out.strip() == "scanned=1"
    # Expect nothing in stderr
    assert captured.err == ""


def test_success_with_findings(tmp_path: Path, monkeypatch, capsys) -> None:
    """When manifests are found and there are violations,
    exit 1 and print scanned line and findings."""
    # Set up a temporary repo root
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(
        check_requires, "INSTRUCTIONS_DIR", tmp_path / "src" / "claude_all" / "instructions"
    )
    # Create the directory structure
    src_claude_all = check_requires.SRC / "claude_all"
    src_claude_all.mkdir(parents=True)
    (check_requires.INSTRUCTIONS_DIR).mkdir(parents=True)
    # Create a manifest file with a bad requires
    manifest = src_claude_all / "claude-all.json"
    manifest.write_text('{"requires": ["bad/resource"]}', encoding="utf-8")
    # Mock load_resource_keys to return an empty set (so the requires is bad)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())
    # Run the main function
    exit_code = check_requires.main()
    assert exit_code == 1
    captured = capsys.readouterr()
    # Expect the scanned line in stdout
    assert "scanned=1" in captured.out
    # Expect a finding line in stdout (the finding about the bad resource)
    assert "bad/resource" in captured.out
    # Expect the findings summary in stderr
    assert "1 requires finding(s)" in captured.err
