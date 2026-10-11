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


def test_success_normal_case(tmp_path: Path, capsys) -> None:
    """A normal success case should exit 0 and print inspected count."""
    # Create a simple valid resource
    # We need to set up the temporary directory to have:
    #   tmp_path/src/claude_all/skills/test/test-skill/{SKILL.md, claude-all.json}
    skill_dir = tmp_path / "src" / "claude_all" / "skills" / "test" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("# Test skill\n", encoding="utf-8")
    # Also create an empty __init__.py to make claude_all a package
    (tmp_path / "src" / "claude_all" / "__init__.py").touch()

    # Temporarily adjust the REPO_ROOT for this test
    with (
        patch.object(check_requires, "REPO_ROOT", tmp_path),
        patch.object(check_requires, "SRC", tmp_path / "src"),
    ):
        exit_code = check_requires.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "inspected=1 resources" in captured.out


def test_zero_discovery_fails(tmp_path, capsys) -> None:
    """A zero-discovery run should exit 2 with an error message."""
    # Create an empty src directory but with an empty claude_all package
    # so that the import succeeds but discover finds nothing.
    empty_src = tmp_path / "src"
    empty_src.mkdir()
    # Create an empty claude_all directory so that the package can be imported
    (empty_src / "claude_all").mkdir()
    (empty_src / "claude_all" / "__init__.py").touch()

    # Temporarily adjust the paths for this test
    with (
        patch.object(check_requires, "REPO_ROOT", tmp_path),
        patch.object(check_requires, "SRC", empty_src),
    ):
        exit_code = check_requires.main()

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "error: no resources discovered" in captured.err
    # Should not print the inspected line on failure
    assert "inspected=" not in captured.out


def test_existing_failure_still_fails(tmp_path, capsys) -> None:
    """An existing genuine failure should still exit 1 with findings."""
    # Create a resource with a bad requires entry
    skill_dir = tmp_path / "src" / "claude_all" / "skills" / "test" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "claude-all.json").write_text(
        '{"requires": ["nonexistent/resource"]}', encoding="utf-8"
    )

    # Temporarily adjust the REPO_SRC for this test
    with (
        patch.object(check_requires, "REPO_ROOT", tmp_path),
        patch.object(check_requires, "SRC", tmp_path / "src"),
    ):
        exit_code = check_requires.main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "requires 'nonexistent/resource' — no such resource" in captured.out
    # Should not print the inspected line when there are findings
    assert "inspected=" not in captured.out
