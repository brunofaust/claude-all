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


def test_zero_discovery_fails_closed() -> None:
    """load_resource_keys returning empty set causes main to exit 1 with zero-discovery message."""
    original_load = check_requires.load_resource_keys

    def returning_empty() -> set[str]:
        return set()

    check_requires.load_resource_keys = returning_empty

    try:
        import io
        import sys

        captured_stderr = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = captured_stderr
        try:
            exit_code = check_requires.main()
            assert exit_code == 1, f"Expected exit 1, got {exit_code}"
            stderr_output = captured_stderr.getvalue()
            assert "0 resources matched the discovery pattern" in stderr_output, (
                f"Expected zero-discovery message in stderr, got: {stderr_output!r}"
            )
        finally:
            sys.stderr = original_stderr
    finally:
        check_requires.load_resource_keys = original_load


def test_inspected_line_on_success() -> None:
    """When load_resource_keys discovers real resources, main exits 0 with inspected N."""
    # Use the real discovery to get all known resources
    known = check_requires.load_resource_keys()
    assert len(known) > 0, "Expected discover to find resources"

    import io
    import sys

    captured_stdout = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = captured_stdout
    try:
        exit_code = check_requires.main()
        assert exit_code == 0, f"Expected exit 0, got {exit_code}"
        output = captured_stdout.getvalue()
        assert f"inspected {len(known)}" in output, (
            f"Expected 'inspected {len(known)}' in output, got: {output!r}"
        )
    finally:
        sys.stdout = original_stdout


def test_gentine_failure_still_fails() -> None:
    """When a subset of real-known keys is missing requires, main exits 1 with findings."""
    all_known = check_requires.load_resource_keys()
    # Remove one known resource to trigger a violation
    partial_known = all_known - {"skills/regression-gates"}

    import io
    import sys

    captured_stderr = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured_stderr
    try:
        original = check_requires.load_resource_keys
        check_requires.load_resource_keys = lambda: partial_known
        try:
            exit_code = check_requires.main()
            assert exit_code == 1, f"Expected exit 1, got {exit_code}"
            stderr_output = captured_stderr.getvalue()
            assert "requires finding" in stderr_output, (
                f"Expected 'requires finding' in stderr, got: {stderr_output!r}"
            )
        finally:
            check_requires.load_resource_keys = original
    finally:
        sys.stderr = original_stderr
