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

    findings, _ = check_requires.find_undeclared_instruction_refs(KNOWN, root)

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

    findings, _ = check_requires.find_undeclared_instruction_refs(KNOWN, root)
    assert findings == []


def test_shipped_instructions_declare_every_reference() -> None:
    """Every shipped instruction requires each resource it names."""
    known = check_requires.load_resource_keys()

    findings, _ = check_requires.find_undeclared_instruction_refs(known)
    assert findings == []


def test_main_success_case(capsys, tmp_path) -> None:
    """Main function prints summary on successful validation."""
    import scripts.check_requires as cr

    # Save original functions
    original_load = cr.load_resource_keys
    original_violations = cr.find_violations
    original_undeclared = cr.find_undeclared_instruction_refs

    try:
        # Mock to return known resources and no findings
        def mock_load_resource_keys() -> set[str]:
            return {"skills/foo-skill", "agents/bar-agent"}

        def mock_find_violations(known: set[str]) -> tuple[list[str], int]:
            return ([], 2)  # 2 manifests

        def mock_find_undeclared_instruction_refs(
            known: set[str], instructions_dir: Path = cr.INSTRUCTIONS_DIR
        ) -> tuple[list[str], int]:
            return ([], 3)  # 3 snippets

        cr.load_resource_keys = mock_load_resource_keys  # type: ignore
        cr.find_violations = mock_find_violations  # type: ignore
        cr.find_undeclared_instruction_refs = mock_find_undeclared_instruction_refs  # type: ignore

        exit_code = cr.main()
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out.strip() == "inspected 2 manifests and 3 instruction snippets"
    finally:
        # Restore original functions
        cr.load_resource_keys = original_load
        cr.find_violations = original_violations
        cr.find_undeclared_instruction_refs = original_undeclared


def test_main_zero_discovery_failure(capsys) -> None:
    """Main function fails when discovery returns zero resources."""
    import scripts.check_requires as cr

    original_load = cr.load_resource_keys

    def mock_load_resource_keys_empty() -> set[str]:
        return set()

    cr.load_resource_keys = mock_load_resource_keys  # type: ignore

    try:
        exit_code = cr.main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "error: installer discovery returned zero resources" in captured.err
    finally:
        cr.load_resource_keys = original_load


def test_main_existing_failure_case(capsys) -> None:
    """Main function still fails on genuine validation errors."""
    import scripts.check_requires as cr

    original_load = cr.load_resource_keys
    cr.load_resource_keys = lambda: {"skills/foo-skill"}  # Missing bar-agent

    try:
        exit_code = cr.main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "requires finding(s)" in captured.err
    finally:
        cr.load_resource_keys = original_load
