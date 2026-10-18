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
from unittest.mock import patch

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


def test_success(capsys) -> None:
    """Successful run prints summary line and exits 0."""
    with (
        patch.object(check_requires, "load_resource_keys", return_value={"a/b", "c/d"}),
        patch.object(check_requires, "find_violations", return_value=[]),
        patch.object(check_requires, "find_undeclared_instruction_refs", return_value=[]),
    ):
        exit_code = check_requires.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Inspected 2 resources" in captured.out
        assert captured.err == ""


def test_zero_discovery(capsys) -> None:
    """Zero-discovery run prints error message and exits 1."""
    expected_msg = (
        "Pattern 'the installer's discovery (agents, skills, plugins, mcps, "
        "tools, instructions, hooks)' matched no resources"
    )
    with patch.object(check_requires, "load_resource_keys", return_value=set()):
        exit_code = check_requires.main()
        assert exit_code == 1
        captured = capsys.readouterr()
        assert expected_msg in captured.out
        assert captured.err == ""


def test_failure(capsys) -> None:
    """Run with findings prints findings and exits 1 (no summary line)."""
    with (
        patch.object(check_requires, "load_resource_keys", return_value={"a/b"}),
        patch.object(check_requires, "find_violations", return_value=["some finding"]),
        patch.object(check_requires, "find_undeclared_instruction_refs", return_value=[]),
    ):
        exit_code = check_requires.main()
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "some finding" in captured.out
        assert "Inspected" not in captured.out
