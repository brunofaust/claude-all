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

import pytest

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


def test_real_repo_reports_scanned_count(capsys: pytest.CaptureFixture[str]) -> None:
    """A clean run prints one greppable ``scanned=`` line and exits 0.

    Args:
        capsys: pytest fixture capturing stdout and stderr.
    """
    assert check_requires.main() == 0

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    line = out[0]
    assert line.startswith("scanned=")
    scanned = int(line.split()[0].removeprefix("scanned="))
    manifests = int(line.split("manifests=")[1].split(",")[0])
    snippets = int(line.split("snippets=")[1].split(",")[0])
    resource_keys = int(line.split("resource_keys=")[1].split(")")[0])
    assert manifests > 0
    assert resource_keys > 0
    assert scanned == manifests + snippets


def test_zero_discovery_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When every pattern matches nothing the gate exits 2 and names the patterns.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture for patching module attributes.
        capsys: pytest fixture capturing stdout and stderr.
    """
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert "matched zero units" in captured.err
    assert "claude-all.json" in captured.err
    assert "claude_md.md" in captured.err
    assert "scanned=" not in captured.out


def test_empty_installer_keys_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Manifests present but no installable resources is still a zero-discovery failure.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture for patching module attributes.
        capsys: pytest fixture capturing stdout and stderr.
    """
    manifest_dir = tmp_path / "src" / "claude_all" / "skills" / "demo"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "claude-all.json").write_text(
        json.dumps({"requires": ["skills/demo"]}), encoding="utf-8"
    )
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert "matched zero units" in captured.err
    assert "installer discover([]) resource keys" in captured.err
    assert "scanned=" not in captured.out


def test_single_empty_pattern_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Manifests and resource keys present but no instruction snippets still exits 2.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture for patching module attributes.
        capsys: pytest fixture capturing stdout and stderr.
    """
    manifest_dir = tmp_path / "src" / "claude_all" / "skills" / "demo"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "claude-all.json").write_text(
        json.dumps({"requires": ["skills/demo"]}), encoding="utf-8"
    )
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/demo"})

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert "instructions/*/claude_md.md" in captured.err
    assert "rglob 'claude-all.json'" not in captured.err
    assert "scanned=" not in captured.out


def test_dangling_requires_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A manifest pointing at a missing resource is still a finding with exit 1.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture for patching module attributes.
        capsys: pytest fixture capturing stdout and stderr.
    """
    manifest_dir = tmp_path / "src" / "claude_all" / "skills" / "demo"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "claude-all.json").write_text(
        json.dumps({"requires": ["skills/missing"]}), encoding="utf-8"
    )
    snippet(tmp_path / "instructions", "Plain text with no resource names.\n")
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/demo"})

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "requires 'skills/missing' — no such resource" in captured.out
    assert "requires finding(s)" in captured.err
    assert "scanned=" not in captured.out
