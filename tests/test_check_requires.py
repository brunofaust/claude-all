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


def test_main_zero_discovery_manifests(tmp_path, monkeypatch, capsys):
    """When no manifest files are discovered, main exits 1 with a clear message."""
    # Set up an empty src/claude_all directory
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    claude_all_dir = src_dir / "claude_all"
    claude_all_dir.mkdir()
    # Instructions directory exists but may be empty
    instructions_dir = claude_all_dir / "instructions"
    instructions_dir.mkdir()

    # Monkeypatch the module's paths
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    # Mock load_resource_keys to return an empty set (or any set; it doesn't affect file discovery)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    # Run the main function
    exit_code = check_requires.main()
    assert exit_code == 1

    # Check stderr for the zero-discovery message
    captured = capsys.readouterr()
    assert "No files discovered:" in captured.err
    assert "'claude-all.json' and '*.claude-all.json' under" in captured.err
    # Ensure no findings were printed to stdout (since there are no files)
    assert captured.out == ""


def test_main_zero_discovery_snippets(tmp_path, monkeypatch, capsys):
    """When no instruction snippet files are discovered, main exits 1 with a clear message."""
    # Set up src/claude_all with a manifest file but no instructions
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    claude_all_dir = src_dir / "claude_all"
    claude_all_dir.mkdir()
    # Create a manifest to avoid manifest zero-discovery; we want to test snippet zero-discovery.
    # We'll create a manifest so manifest count > 0; we want snippet count == 0.
    # Actually, we want snippet count == 0; we can leave instructions dir empty.
    # Also avoid manifest zero-discovery by creating one manifest.
    manifest_dir = claude_all_dir / "test-skill"
    manifest_dir.mkdir()
    (manifest_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    # Instructions directory exists but is empty
    instructions_dir = claude_all_dir / "instructions"
    instructions_dir.mkdir()

    # Monkeypatch the module's paths
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    # Mock load_resource_keys to return the resource we created
    known_set = {"skills/test-skill"}
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known_set)

    # Run the main function
    exit_code = check_requires.main()
    assert exit_code == 1

    # Check stderr for the zero-discovery message
    captured = capsys.readouterr()
    assert "No files discovered:" in captured.err
    assert "'*/claude_md.md' under" in captured.err
    # We should have printed the manifest findings? There are none because the manifest is valid.
    # So stdout should be empty (no findings and no summary because we failed)
    assert captured.out == ""


def test_main_success(tmp_path, monkeypatch, capsys):
    """When files are discovered and no violations, main prints summary and exits 0."""
    # Set up src/claude_all with one manifest and one instruction snippet
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    claude_all_dir = src_dir / "claude_all"
    claude_all_dir.mkdir()

    # Create a manifest under src/claude_all
    manifest_dir = claude_all_dir / "test-skill"
    manifest_dir.mkdir()
    (manifest_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")

    # Create an instructions directory and a snippet
    instructions_dir = claude_all_dir / "instructions"
    instructions_dir.mkdir()
    snippet_dir = instructions_dir / "test-snippet"
    snippet_dir.mkdir()
    (snippet_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")
    (snippet_dir / "claude_md.md").write_text("Some text without backticks.", encoding="utf-8")

    # Monkeypatch the module's paths
    monkeypatch.setattr(check_requires, "SRC", src_dir)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    # Mock load_resource_keys to return the resources we created
    known_set = {"skills/test-skill", "instructions/test-snippet"}
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known_set)

    # Run the main function
    exit_code = check_requires.main()
    assert exit_code == 0

    # Check stdout for the summary line
    captured = capsys.readouterr()
    assert "inspected 2 units" in captured.out
    # Ensure no error output
    assert captured.err == ""
    # Ensure no findings were printed (so the only stdout is the summary line)
    # We can check that the stdout is exactly the summary line (ignoring trailing newline)
    # Note: print adds newline; expect "inspected 2 units\\n"
    # We'll check the string is in out and there's no other output.
    # Since we print nothing else, out should be summary line plus newline.
    # To be safe, check summary line present and no other stdout output.
    # We'll split the out by newline and expect one non-empty line.
    out_lines = [line for line in captured.out.splitlines() if line]
    assert len(out_lines) == 1
    assert out_lines[0] == "inspected 2 units"
