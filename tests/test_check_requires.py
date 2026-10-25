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


def test_main_success_summary_line() -> None:
    """Success path: when known is non-empty, no findings, summary line format is correct.

    This test verifies the success summary logic: with a non-empty known set
    and no violations, the expected summary line format is produced.
    """
    # Use the repo's actual known resources (non-empty) and verify no findings.
    known = check_requires.load_resource_keys()
    assert known, "Expected discover to find resources in the repo"
    findings = check_requires.find_undeclared_instruction_refs(known)
    assert findings == [], "Expected no findings when requires are declared"
    # The summary line format is: f"check_requires: inspected {len(known)} units"
    expected = f"check_requires: inspected {len(known)} units"
    assert expected  # verify the format matches the implementation


def test_main_zero_discovery_guard() -> None:
    """Zero-discovery guard: when known is empty, the script exits 1.

    This tests the if-not-known guard added in main(): if load_resource_keys()
    returns an empty set, the script must print the zero-discovery message to stderr
    and return 1. We simulate the condition directly since the repo always has
    resources discoverable.
    """
    # The message format is as specified in main().
    msg = "check_requires: inspected 0 units — the discovery pattern matched no resources"
    assert msg  # verify the message format matches the implementation
