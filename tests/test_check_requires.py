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


def test_main_reports_inspected_count(monkeypatch, capsys) -> None:
    """A clean run reports the manifests and snippets actually inspected."""
    manifest = REPO_ROOT / "src/claude_all/test/claude-all.json"
    snippet_path = REPO_ROOT / "src/claude_all/instructions/test/claude_md.md"
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: KNOWN)
    monkeypatch.setattr(check_requires, "discover_manifests", lambda: [manifest])
    monkeypatch.setattr(check_requires, "discover_instruction_snippets", lambda: [snippet_path])
    monkeypatch.setattr(check_requires, "find_violations", lambda known, manifests=None: [])
    monkeypatch.setattr(
        check_requires, "find_undeclared_instruction_refs", lambda known, snippets=None: []
    )

    assert check_requires.main() == 0
    assert capsys.readouterr().out.strip() == (
        "check_requires: inspected 5 units "
        "(1 manifests, 1 instruction snippets, 3 installer resources)"
    )


def test_main_zero_manifest_discovery_fails_with_pattern(monkeypatch, capsys) -> None:
    """An empty manifest discovery set fails closed and identifies its pattern."""
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: KNOWN)
    monkeypatch.setattr(check_requires, "discover_manifests", lambda: [])
    monkeypatch.setattr(check_requires, "discover_instruction_snippets", lambda: [Path("snippet")])

    assert check_requires.main() == 2
    captured = capsys.readouterr()
    assert "zero files/resources matched pattern" in captured.err
    assert "claude-all.json" in captured.err
    assert "matched pattern" in captured.err


def test_main_zero_instruction_discovery_fails_with_pattern(monkeypatch, capsys) -> None:
    """An empty instruction discovery set fails closed and identifies its pattern."""
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: KNOWN)
    monkeypatch.setattr(check_requires, "discover_manifests", lambda: [Path("manifest")])
    monkeypatch.setattr(check_requires, "discover_instruction_snippets", lambda: [])

    assert check_requires.main() == 2
    assert "instructions/*/claude_md.md" in capsys.readouterr().err


def test_main_zero_installer_resources_fails_with_pattern(monkeypatch, capsys) -> None:
    """An empty installer resource discovery set fails closed."""
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())
    monkeypatch.setattr(check_requires, "discover_manifests", lambda: [Path("manifest")])
    monkeypatch.setattr(check_requires, "discover_instruction_snippets", lambda: [Path("snippet")])

    assert check_requires.main() == 2
    assert "discover([]) installer resources" in capsys.readouterr().err


def test_main_preserves_genuine_validation_failure(monkeypatch, capsys, tmp_path: Path) -> None:
    """A real dangling dependency continues to fail with exit code 1."""
    manifest = tmp_path / "claude-all.json"
    manifest.write_text(json.dumps({"requires": ["skills/missing"]}), encoding="utf-8")
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: KNOWN)
    monkeypatch.setattr(check_requires, "discover_manifests", lambda: [manifest])
    monkeypatch.setattr(check_requires, "discover_instruction_snippets", lambda: [Path("snippet")])
    monkeypatch.setattr(
        check_requires, "find_undeclared_instruction_refs", lambda known, snippets=None: []
    )

    assert check_requires.main() == 1
    captured = capsys.readouterr()
    assert "requires 'skills/missing'" in captured.out
    assert "1 requires finding(s)" in captured.err
