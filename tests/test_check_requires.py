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


def test_zero_discovery_exits_with_error_and_message(monkeypatch):
    """When discovery returns no resources, the gate exits with code 2 and an error message."""
    import check_requires

    # Patch load_resource_keys to return an empty set
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    # Run the main function and capture exit code and stderr
    import sys
    from io import StringIO

    old_stderr = sys.stderr
    sys.stderr = StringIO()
    try:
        exit_code = check_requires.main()
        stderr_output = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    assert exit_code == 2
    assert "Error: discovery pattern" in stderr_output
    assert "matched zero resources" in stderr_output


def test_normal_success_prints_summary_line(monkeypatch, capsys):
    """When discovery returns resources and no violations, the gate prints a summary line and exits 0."""
    import check_requires

    # Patch load_resource_keys to return a non-empty set
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"agents/foo", "skills/bar"})
    # Patch the two find functions to return empty lists
    monkeypatch.setattr(check_requires, "find_violations", lambda known: [])
    monkeypatch.setattr(check_requires, "find_undeclared_instruction_refs", lambda known, _: [])

    # Run the main function
    exit_code = check_requires.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Inspected 2 resources" in captured.out
    # Ensure no error output
    assert captured.err == ""


def test_existing_genuine_failure_still_fails(monkeypatch, capsys):
    """When there is a genuine violation, the gate still exits 1 and prints the findings and error message."""
    import check_requires

    # Patch load_resource_keys to return a non-empty set
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"agents/foo"})
    # Patch find_violations to return a finding
    monkeypatch.setattr(
        check_requires,
        "find_violations",
        lambda known: ["some/path/claude-all.json: requires 'missing' — no such resource"],
    )
    # Patch find_undeclared_instruction_refs to return empty
    monkeypatch.setattr(
        check_requires,
        "find_undeclared_instruction_refs",
        lambda known, _: [],
    )

    # Run the main function
    exit_code = check_requires.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    # Check that the finding is printed to stdout
    assert "some/path/claude-all.json: requires 'missing' — no such resource" in captured.out
    # Check that the error message is printed to stderr
    assert "requires finding(s)" in captured.err
    assert "dependency manifest points at a resource" in captured.err
    # Ensure no summary line
    assert "Inspected" not in captured.out
