"""Tests for the `check_requires` gate's instruction-reference rule.

A standalone instruction snippet has no agent or skill of its own to carry a
dependency, so every resource it names must be declared in its `claude-all.json`
or installing the instruction ships a rule pointing at nothing.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest.mock
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


def test_undeclared_reference_is_reported() -> None:
    """A named resource missing from ``requires`` is a finding."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        root = snippet(
            tmp_path, "Load `foo-skill`; delegate to `bar-agent`.\n", ["agents/bar-agent"]
        )

        findings = check_requires.find_undeclared_instruction_refs(KNOWN, root)

        assert len(findings) == 1
        assert "`foo-skill`" in findings[0]
        assert "skills/foo-skill" in findings[0]


def test_declared_and_non_resource_tokens_pass() -> None:
    """Declared resources, the snippet itself and plain code spans are fine."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
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


def test_main_success() -> None:
    """Normal success: manifests and snippets found, no findings."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Set up a temporary repo structure
        src = tmp_path / "src"
        claude_all = src / "claude_all"
        instructions_dir = claude_all / "instructions"
        instructions_dir.mkdir(parents=True)
        # Create a manifest
        manifest = claude_all / "foo.claude-all.json"
        manifest.write_text('{"requires": []}')
        # Create an instruction snippet
        demo_dir = instructions_dir / "demo"
        demo_dir.mkdir()
        (demo_dir / "claude_md.md").write_text("See `foo`")
        (demo_dir / "claude-all.json").write_text('{"requires": ["skills/foo"]}')

        # Mock load_resource_keys to return a set that includes "skills/foo"
        known = {"skills/foo"}

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with (
            unittest.mock.patch.object(check_requires, "load_resource_keys", return_value=known),
            unittest.mock.patch("sys.stdout", stdout_capture),
            unittest.mock.patch("sys.stderr", stderr_capture),
        ):
            # Run the script
            ret = check_requires.main()
            assert ret == 0

        # Get the captured output
        out = stdout_capture.getvalue()
        err = stderr_capture.getvalue()

        # We expect the inspection summary on stdout
        assert "inspected=1 manifests and 1 instruction snippets" in out
        # No findings, so nothing else on stdout
        assert out.strip() == "inspected=1 manifests and 1 instruction snippets"
        # No stderr output
        assert err == ""


def test_main_zero_discovery() -> None:
    """Zero-discovery: no manifests and no snippets found."""
    with tempfile.TemporaryDirectory() as _:
        # We do not create any manifests or the instructions directory

        # Mock load_resource_keys to return an empty set (or any set, but we don't have any
        # files to check)
        known: set[str] = set()

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with (
            unittest.mock.patch.object(check_requires, "load_resource_keys", return_value=known),
            unittest.mock.patch("sys.stdout", stdout_capture),
            unittest.mock.patch("sys.stderr", stderr_capture),
        ):
            # Run the script
            ret = check_requires.main()
            assert ret == 2

        # Get the captured output
        out = stdout_capture.getvalue()
        err = stderr_capture.getvalue()

        # No stdout output (because we failed before printing the summary)
        assert out == ""
        # Check stderr for the error message
        assert (
            "No manifests found via rglob('claude-all.json') or rglob('*.claude-all.json')" in err
        )
        assert "and no instruction snippets found via glob('*/claude_md.md')" in err


def test_main_failure() -> None:
    """Existing genuine failure: a manifest has a bad requires entry."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Set up a temporary repo structure
        src = tmp_path / "src"
        claude_all = src / "claude_all"
        instructions_dir = claude_all / "instructions"
        instructions_dir.mkdir(parents=True)
        # Create a manifest with a bad requires entry
        manifest = claude_all / "foo.claude-all.json"
        manifest.write_text('{"requires": ["nonexistent"]}')
        # Create an instruction snippet (to have at least one snippet,
        # so we don't trigger zero-discovery)
        demo_dir = instructions_dir / "demo"
        demo_dir.mkdir()
        (demo_dir / "claude_md.md").write_text("See `foo`")
        (demo_dir / "claude-all.json").write_text('{"requires": ["skills/foo"]}')

        # Mock load_resource_keys to return a set that includes "skills/foo" but not "nonexistent"
        known = {"skills/foo"}

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with (
            unittest.mock.patch.object(check_requires, "load_resource_keys", return_value=known),
            unittest.mock.patch("sys.stdout", stdout_capture),
            unittest.mock.patch("sys.stderr", stderr_capture),
        ):
            # Run the script
            ret = check_requires.main()
            assert ret == 1

        # Get the captured output
        out = stdout_capture.getvalue()
        err = stderr_capture.getvalue()

        # We expect the inspection summary on stdout
        assert "inspected=1 manifests and 1 instruction snippets" in out
        # We expect the finding on stdout
        assert "requires 'nonexistent' — no such resource" in out
        # We expect the error summary on stderr
        assert "1 requires finding(s)" in err
