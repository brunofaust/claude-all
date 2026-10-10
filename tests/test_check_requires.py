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


def test_zero_discovery_fails(tmp_path: Path, monkeypatch) -> None:
    """When no manifests or instruction snippets are found, exit with code 2."""
    # Create a temporary directory with no claude-all.json or *.claude-all.json under src/claude_all
    # and no instruction snippets.
    # We'll monkeypatch the paths used by the script to point to temporary directories.
    src_tmp = tmp_path / "src" / "claude_all"
    src_tmp.mkdir(parents=True)
    instructions_tmp = src_tmp / "instructions"
    instructions_tmp.mkdir()

    # Monkeypatch the constants in the module
    monkeypatch.setattr(check_requires, "SRC", src_tmp)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_tmp)
    # We also need to monkeypatch REPO_ROOT because load_resource_keys uses SRC which is derived from REPO_ROOT.
    # But note: load_resource_keys uses SRC to add to sys.path and to call discover.
    # We don't want to break the loading of known resources. We'll skip this test for now?
    # Alternatively, we can create a minimal src/claude_all/cli.py? That's too heavy.
    # Instead, we can test the zero discovery by mocking the glob results?
    # Since we are changing the functions to return counts, we can test the main function with mocked globals.
    # However, for simplicity, we'll test the zero discovery by creating a temporary repo structure.
    # We'll create a minimal src/claude_all/cli.py that just returns an empty list for discover.
    # But note: the ticket says no new dependencies, and we are allowed to write tests.
    # We'll create a temporary src directory with a minimal cli.py.
    src_claude_all = tmp_path / "src" / "claude_all"
    src_claude_all.mkdir(parents=True)
    (src_claude_all / "cli.py").write_text("""
def discover(_):
    return []

def state_key(kind, name):
    return f"{kind}/{name}"
""")
    # Set up the instructions directory
    instructions_dir = src_claude_all / "instructions"
    instructions_dir.mkdir()

    # Now, we need to set the module's SRC and INSTRUCTIONS_DIR to our temporary directories.
    # We'll do it by monkeypatching.
    monkeypatch.setattr(check_requires, "SRC", src_claude_all)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)
    # Also, REPO_ROOT is used for manifest paths. We'll set it to tmp_path.
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

    # Now run main and expect exit code 2.
    assert check_requires.main() == 2


def test_success_summary(tmp_path: Path, monkeypatch) -> None:
    """When there are files and no findings, print summary and exit 0."""
    # Create a temporary directory with one manifest and one instruction snippet.
    src_claude_all = tmp_path / "src" / "claude_all"
    src_claude_all.mkdir(parents=True)
    instructions_dir = src_claude_all / "instructions"
    instructions_dir.mkdir()

    # Create a manifest
    manifest = src_claude_all / "claude-all.json"
    manifest.write_text('{"requires": []}')

    # Create an instruction snippet
    instr_dir = instructions_dir / "test"
    instr_dir.mkdir()
    (instr_dir / "claude_md.md").write_text("See `demo`.")
    (instr_dir / "claude-all.json").write_text('{"requires": ["instructions/demo"]}')

    # We need to have a known resource for "instructions/demo"
    # We'll monkeypatch load_resource_keys to return a set that includes it.
    def mock_load_resource_keys():
        return {"instructions/demo"}

    monkeypatch.setattr(check_requires, "load_resource_keys", mock_load_resource_keys)

    # Also, we need to set the SRC and INSTRUCTIONS_DIR in the module.
    monkeypatch.setattr(check_requires, "SRC", src_claude_all)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions_dir)
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

    # We'll capture stdout and stderr to check the summary line.
    import sys
    from io import StringIO

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = StringIO()
    sys.stderr = StringIO()
    try:
        exit_code = check_requires.main()
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    assert exit_code == 0
    # Check that the summary line is printed to stdout
    assert "Inspected 1 manifest file(s) and 1 instruction snippet(s)." in stdout
    # No findings should be printed
    assert stdout.strip() == "Inspected 1 manifest file(s) and 1 instruction snippet(s)."
    assert stderr == ""
