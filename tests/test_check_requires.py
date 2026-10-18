"""Tests for the `check_requires` gate's instruction-reference rule.

A standalone instruction snippet has no agent or skill of its own to carry a
dependency, so every resource it names must be declared in its `claude-all.json`
or installing the instruction ships a rule pointing at nothing.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
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


def test_success_prints_summary(capsys) -> None:
    """On success, the script prints a summary line with inspected counts."""
    # Run the actual script
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_requires.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # Should succeed (exit code 0)
    assert result.returncode == 0
    # Should have printed the summary line to stdout
    assert "Inspected" in result.stdout
    assert "manifests" in result.stdout
    assert "instruction snippets" in result.stdout
    # Should not have error message
    assert "Error:" not in result.stderr


def test_zero_discovery_fails(capsys) -> None:
    """When zero files are discovered, the script fails with exit code 2 and clear message."""
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create minimal repository structure
        # We need to recreate the parts that the script depends on
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        claude_all_dir = src_dir / "claude_all"
        claude_all_dir.mkdir()

        # Create a minimal cli.py that the script can import
        cli_dir = claude_all_dir / "cli.py"
        cli_dir.write_text(
            "# Minimal cli module for testing\n"
            "def discover(args):\n"
            "    return []\n"
            "def state_key(kind, name):\n"
            "    return f'{kind}/{name}'\n"
        )

        # Create empty instructions directory
        instructions_dir = claude_all_dir / "instructions"
        instructions_dir.mkdir()

        # Copy the script to the temp directory
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        shutil.copy(REPO_ROOT / "scripts" / "check_requires.py", script_dir / "check_requires.py")

        # Run the script - it should find zero files since we created empty directories
        result = subprocess.run(
            [sys.executable, str(script_dir / "check_requires.py")],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        # Should fail with exit code 2
        assert result.returncode == 2
        # Should have error message about zero files
        assert "Error:" in result.stderr
        assert "zero files to inspect" in result.stderr


def test_genuine_failure_still_fails(tmp_path: Path) -> None:
    """A genuine validation failure still produces exit code 1 and the original error message."""
    import shutil

    # Set up the directory structure in the temp directory to mirror the repo
    src_base = tmp_path / "src" / "claude_all"
    src_base.mkdir(parents=True)

    # Create a minimal cli.py that the script can import
    cli_dir = src_base / "cli.py"
    cli_dir.write_text(
        "# Minimal cli module for testing\n"
        "def discover(args):\n"
        "    # Return a mock item with our test resource\n"
        "    class MockItem:\n"
        "        def __init__(self, kind, name):\n"
        "            self.kind = kind\n"
        "            self.name = name\n"
        "    return [MockItem('skills', 'test-skill')]\n"
        "def state_key(kind, name):\n"
        "    return f'{kind}/{name}'\n"
    )

    # Create a claude-all.json with a bad dependency
    manifest = src_base / "test-skill" / "claude-all.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"requires": ["non/existent-resource"]}', encoding="utf-8")

    # Create an instruction snippet that references nothing (to avoid the other check)
    snippet_dir = src_base / "instructions" / "test-instr"
    snippet_dir.mkdir(parents=True)
    (snippet_dir / "claude_md.md").write_text("Just some text.\n", encoding="utf-8")
    (snippet_dir / "claude-all.json").write_text('{"requires": []}', encoding="utf-8")

    # Copy the script to the temp directory
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "check_requires.py", script_dir / "check_requires.py")

    result = subprocess.run(
        [sys.executable, str(script_dir / "check_requires.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Should fail with exit code 1 (validation failure)
    assert result.returncode == 1
    # Should have the original error message in stdout
    assert "non/existent-resource" in result.stdout
    # Should have the summary about findings in stderr
    assert "requires finding(s)" in result.stderr
