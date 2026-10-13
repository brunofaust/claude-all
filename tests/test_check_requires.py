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


def test_success_print_summary_and_exit_0(tmp_path: Path, monkeypatch, capsys) -> None:
    """When there are manifests and instructions and no findings, print summary and exit 0."""
    # Set up a temporary repository structure.
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instr_dir = src_dir / "instructions"
    instr_dir.mkdir()

    # Create a manifest file that requires a known resource.
    manifest = src_dir / "test.claude-all.json"
    manifest.write_text('{"requires": ["fake-kind/fake-name"]}', encoding="utf-8")

    # Create an instruction snippet that declares the resource and names it.
    instr_dir = instr_dir / "demo"
    instr_dir.mkdir()
    (instr_dir / "claude_md.md").write_text(
        "See `fake-kind/fake-name` for details.", encoding="utf-8"
    )
    (instr_dir / "claude-all.json").write_text(
        '{"requires": ["fake-kind/fake-name"]}', encoding="utf-8"
    )

    # Mock load_resource_keys to return a set containing the known resource.
    def mock_load_resource_keys() -> set[str]:
        return {"fake-kind/fake-name"}

    monkeypatch.setattr(check_requires, "load_resource_keys", mock_load_resource_keys)
    # Mock the SRC and INSTRUCTIONS_DIR constants to point to our temporary directories.
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(
        check_requires, "INSTRUCTIONS_DIR", instr_dir.parent.parent / "instructions"
    )
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

    # Run the main function.
    exit_code = check_requires.main()

    # Capture stdout and stderr.
    captured = capsys.readouterr()
    out = captured.out
    err = captured.err

    # Assertions.
    assert exit_code == 0
    # The summary line should be printed to stdout.
    assert out.strip() == "Inspected 2 units"
    assert err == ""


def test_zero_discovery_fails_exit_2(tmp_path: Path, monkeypatch, capsys) -> None:
    """When no manifests and no instructions are found, exit with code 2 and error message."""
    # Set up a temporary repository structure with no manifests or instructions.
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instr_dir = src_dir / "instructions"
    instr_dir.mkdir()

    # Mock load_resource_keys to return an empty set (or any set, since we won't have findings).
    def mock_load_resource_keys() -> set[str]:
        return set()

    monkeypatch.setattr(check_requires, "load_resource_keys", mock_load_resource_keys)
    # Mock the SRC and INSTRUCTIONS_DIR constants.
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instr_dir)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

    # Run the main function.
    exit_code = check_requires.main()

    # Capture stdout and stderr.
    captured = capsys.readouterr()
    out = captured.out
    err = captured.err

    # Assertions.
    assert exit_code == 2
    # No summary line should be printed to stdout.
    assert out == ""
    # The error message should be printed to stderr.
    assert "Error: No manifest files found" in err
    assert "using patterns 'claude-all.json' and '*.claude-all.json'" in err
    assert "and no instruction snippets found" in err


def test_genuine_failure_still_fails_exit_1(tmp_path: Path, monkeypatch, capsys) -> None:
    """When there is a genuine requires failure, still exit 1 with the findings."""
    # Set up a temporary repository structure with a manifest that has a bad requires.
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instr_dir = src_dir / "instructions"
    instr_dir.mkdir()

    # Create a manifest that requires an unknown resource.
    manifest = src_dir / "test.claude-all.json"
    manifest.write_text('{"requires": ["unknown-kind/unknown-name"]}', encoding="utf-8")

    # Create an instruction snippet that does not reference any resource (to avoid extra findings).
    instr_dir = instr_dir / "demo"
    instr_dir.mkdir()
    (instr_dir / "claude_md.md").write_text("Just a comment.", encoding="utf-8")
    (instr_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")

    # Mock load_resource_keys to return an empty set (so the unknown resource is indeed unknown).
    def mock_load_resource_keys() -> set[str]:
        return set()

    monkeypatch.setattr(check_requires, "load_resource_keys", mock_load_resource_keys)
    # Mock the SRC and INSTRUCTIONS_DIR constants.
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instr_dir)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

    # Run the main function.
    exit_code = check_requires.main()

    # Capture stdout and stderr.
    captured = capsys.readouterr()
    out = captured.out
    err = captured.err

    # Assertions.
    assert exit_code == 1
    # The finding should be printed to stdout.
    assert "requires 'unknown-kind/unknown-name' — no such resource" in out
    # The error message about findings should be printed to stderr.
    assert "1 requires finding(s)" in err
    # No summary line should be printed.
    assert "Inspected" not in out
