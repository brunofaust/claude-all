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


def test_main_success(tmp_path: Path) -> None:
    """A successful run prints the inspected count and exits 0."""
    # Set up a temporary directory structure
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instructions_dir = src_dir / "instructions"
    instructions_dir.mkdir()

    # Create one manifest file
    manifest = src_dir / "claude-all.json"
    manifest.write_text('{"requires": ["skills/foo-skill"]}', encoding="utf-8")

    # Create one instruction snippet file
    instr_dir = instructions_dir / "demo"
    instr_dir.mkdir()
    (instr_dir / "claude_md.md").write_text("See `skills/foo-skill`", encoding="utf-8")
    (instr_dir / "claude-all.json").write_text(
        '{"requires": ["skills/foo-skill"]}', encoding="utf-8"
    )

    # Mock load_resource_keys to return our known set
    with (
        patch("scripts.check_requires.load_resource_keys", return_value=KNOWN),
        patch("scripts.check_requires.SRC", src_dir),
        patch("scripts.check_requires.INSTRUCTIONS_DIR", instructions_dir),
    ):
        # Capture stdout and stderr
        import io
        from contextlib import redirect_stderr, redirect_stdout

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = check_requires.main()
        # Check exit code
        assert exit_code == 0
        # Check stdout for the summary line
        assert stdout.getvalue().strip() == "Inspected 2 units"


def test_main_zero_discovery_manifest(tmp_path: Path) -> None:
    """Zero manifest files causes a failure with a clear message."""
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instructions_dir = src_dir / "instructions"
    instructions_dir.mkdir()

    # Create one instruction snippet file (but no manifest files)
    instr_dir = instructions_dir / "demo"
    instr_dir.mkdir()
    (instr_dir / "claude_md.md").write_text("See `skills/foo-skill`", encoding="utf-8")
    (instr_dir / "claude-all.json").write_text(
        '{"requires": ["skills/foo-skill"]}', encoding="utf-8"
    )

    with (
        patch("scripts.check_requires.load_resource_keys", return_value=KNOWN),
        patch("scripts.check_requires.SRC", src_dir),
        patch("scripts.check_requires.INSTRUCTIONS_DIR", instructions_dir),
    ):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = check_requires.main()
        assert exit_code == 1
        # Check stderr for the error message about manifest files
        stderr_output = stderr.getvalue()
        assert "requires check: no claude-all.json files found" in stderr_output
        assert "(patterns: '**/claude-all.json' and '**/*.claude-all.json')" in stderr_output
        # stdout should be empty
        assert stdout.getvalue() == ""


def test_main_zero_discovery_instruction(tmp_path: Path) -> None:
    """Zero instruction files causes a failure with a clear message."""
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instructions_dir = src_dir / "instructions"
    instructions_dir.mkdir(parents=True)  # create the directory but leave it empty

    # Create one manifest file
    manifest = src_dir / "claude-all.json"
    manifest.write_text('{"requires": ["skills/foo-skill"]}', encoding="utf-8")

    with (
        patch("scripts.check_requires.load_resource_keys", return_value=KNOWN),
        patch("scripts.check_requires.SRC", src_dir),
        patch("scripts.check_requires.INSTRUCTIONS_DIR", instructions_dir),
    ):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = check_requires.main()
        assert exit_code == 1
        stderr_output = stderr.getvalue()
        assert "instruction-ref check: no instruction snippet files found" in stderr_output
        assert "(pattern: '*/claude_md.md')" in stderr_output
        assert stdout.getvalue() == ""


def test_main_failure(tmp_path: Path) -> None:
    """A genuine failure (dangling reference) still fails and prints the finding."""
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    instructions_dir = src_dir / "instructions"
    instructions_dir.mkdir()

    # Create a manifest that requires a non-existent resource
    manifest = src_dir / "claude-all.json"
    manifest.write_text('{"requires": ["non/existent"]}', encoding="utf-8")

    # Create an instruction snippet (to have at least one instruction file)
    instr_dir = instructions_dir / "demo"
    instr_dir.mkdir()
    (instr_dir / "claude_md.md").write_text("See `skills/foo-skill`", encoding="utf-8")
    (instr_dir / "claude-all.json").write_text(
        '{"requires": ["skills/foo-skill"]}', encoding="utf-8"
    )

    with (
        patch("scripts.check_requires.load_resource_keys", return_value=KNOWN),
        patch("scripts.check_requires.SRC", src_dir),
        patch("scripts.check_requires.INSTRUCTIONS_DIR", instructions_dir),
    ):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = check_requires.main()
        assert exit_code == 1
        # Check that the finding is printed to stdout
        stdout_output = stdout.getvalue()
        assert "requires 'non/existent' — no such resource" in stdout_output
        # Check that the summary line is printed to stderr (as per existing behavior)
        stderr_output = stderr.getvalue()
        assert "1 requires finding(s)" in stderr_output
