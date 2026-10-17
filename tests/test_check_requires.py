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


def test_main_success(tmp_path: Path) -> None:
    """A successful run should print a summary line with the inspected count."""
    # Set up known resources: a skill and an agent
    known_resources: set[tuple[str, str]] = {("skills", "test-skill"), ("agents", "test-agent")}
    # Create a fake cli.py that returns these resources
    cli_content = f"""
class FakeItem:
    def __init__(self, kind, name):
        self.kind = kind
        self.name = name

def discover(_dirs):
    return [FakeItem(kind, name) for (kind, name) in {known_resources!r}]

def state_key(kind, name):
    return f"{{kind}}/{{name}}"
""".strip()
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "cli.py").write_text(cli_content, encoding="utf-8")
    # Debug: check that we can import the fake cli module
    print(f"DEBUG: src_dir = {src_dir}", file=sys.stderr)
    print(f"DEBUG: cli_content = {cli_content!r}", file=sys.stderr)
    sys.path.insert(0, str(src_dir.parent))  # src_dir.parent is tmp_path/src
    try:
        print("DEBUG: fake cli import succeeded in test", file=sys.stderr)
    except Exception as e:
        print(f"DEBUG: fake cli import failed in test: {e}", file=sys.stderr)

    # Create a manifest for an agent that requires the skill
    agent_dir = src_dir / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "claude-all.json").write_text(
        '{"requires": ["skills/test-skill"]}', encoding="utf-8"
    )

    # Create an instruction snippet that declares the skill
    instr_dir = src_dir / "instructions" / "test-instr"
    instr_dir.mkdir(parents=True)
    (instr_dir / "claude_md.md").write_text("Load `test-skill`\n", encoding="utf-8")
    (instr_dir / "claude-all.json").write_text(
        '{"requires": ["skills/test-skill"]}', encoding="utf-8"
    )

    # Copy the script to the temporary directory
    script_src = REPO_ROOT / "scripts" / "check_requires.py"
    script_dst = tmp_path / "check_requires.py"
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Run the script
    import subprocess

    result = subprocess.run(
        [sys.executable, "check_requires.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Expect success
    assert result.returncode == 0
    # Expect exactly one line of stdout: the summary
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("Inspected ") and lines[0].endswith(" units")
    import re

    match = re.search(r"Inspected (\d+) units", lines[0])
    assert match is not None
    count = int(match.group(1))
    # We expect to have inspected 2 units: one requires and one instruction token
    assert count == 2


def test_main_zero_discovery_failure(tmp_path: Path) -> None:
    """When discovery matches zero files, the script should fail with a clear message."""
    # Set up known resources to be empty
    known_resources: set[tuple[str, str]] = set()
    cli_content = f"""
class FakeItem:
    def __init__(self, kind, name):
        self.kind = kind
        self.name = name

def discover(_dirs):
    return [FakeItem(kind, name) for (kind, name) in {known_resources!r}]

def state_key(kind, name):
    return f"{{kind}}/{{name}}"
""".strip()
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "cli.py").write_text(cli_content, encoding="utf-8")
    # No manifests or instruction snippets created -> zero units inspected

    # Copy the script
    script_src = REPO_ROOT / "scripts" / "check_requires.py"
    script_dst = tmp_path / "check_requires.py"
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Run the script
    import subprocess

    result = subprocess.run(
        [sys.executable, "check_requires.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Expect failure due to zero discovery
    assert result.returncode == 1
    # Expect error message in stderr
    assert "Error: dependency scan matched zero files" in result.stderr
    # Expect no output in stdout (no findings)
    assert result.stdout.strip() == ""


def test_main_genuine_failure(tmp_path: Path) -> None:
    """A genuine failure (dangling requires) should still be reported as before."""
    # Set up known resources to be empty so any requires is dangling
    known_resources: set[tuple[str, str]] = set()
    cli_content = f"""
class FakeItem:
    def __init__(self, kind, name):
        self.kind = kind
        self.name = name

def discover(_dirs):
    return [FakeItem(kind, name) for (kind, name) in {known_resources!r}]

def state_key(kind, name):
    return f"{{kind}}/{{name}}"
""".strip()
    src_dir = tmp_path / "src" / "claude_all"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "cli.py").write_text(cli_content, encoding="utf-8")

    # Create a manifest with a dangling requires
    agent_dir = src_dir / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "claude-all.json").write_text(
        '{"requires": ["skills/nonexistent"]}', encoding="utf-8"
    )

    # Copy the script
    script_src = Path(__file__).parents[2] / "scripts" / "check_requires.py"
    script_dst = tmp_path / "check_requires.py"
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Run the script
    import subprocess

    result = subprocess.run(
        [sys.executable, "check_requires.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Expect failure
    assert result.returncode == 1
    # Expect the finding in stdout
    assert "requires 'skills/nonexistent' — no such resource" in result.stdout
    # Expect the summary line in stderr (with exactly one finding)
    expected_stderr = (
        "\n1 requires finding(s) — a dependency manifest points at a resource the installer cannot discover, "
        "or an instruction names one it does not require."
    )
    assert result.stderr == expected_stderr
