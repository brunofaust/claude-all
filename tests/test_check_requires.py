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


def point_gate_at(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    manifests: dict[str, list[str]],
    snippets: list[str],
    keys: set[str],
) -> None:
    """Build a fake repo tree and point the gate's module globals at it."""
    src = root / "src"
    for rel, requires in manifests.items():
        path = src / "claude_all" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"requires": requires}), encoding="utf-8")
    instructions = root / "instructions"
    for name in snippets:
        folder = instructions / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "claude_md.md").write_text("Plain text.\n", encoding="utf-8")
    monkeypatch.setattr(check_requires, "REPO_ROOT", root)
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: keys)


def test_success_prints_scanned_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A clean run exits 0 and prints the inspected count on stderr."""
    point_gate_at(
        monkeypatch,
        tmp_path,
        manifests={
            "skills/a/claude-all.json": ["skills/foo-skill"],
            "agents/b/x.claude-all.json": [],
        },
        snippets=["demo", "other"],
        keys=KNOWN,
    )

    assert check_requires.main() == 0
    captured = capsys.readouterr()
    assert "scanned=4 requires unit(s) (manifests=2, instruction snippets=2)" in captured.err
    assert captured.out == ""


def test_zero_manifests_fails_closed_naming_the_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero manifests is exit 2 and the message names the manifest glob."""
    point_gate_at(monkeypatch, tmp_path, manifests={}, snippets=["demo"], keys=KNOWN)

    assert check_requires.main() == 2
    err = capsys.readouterr().err
    assert "CANNOT CHECK" in err
    assert "claude-all.json" in err
    assert "*.claude-all.json" in err


def test_zero_instruction_snippets_fails_closed_naming_the_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero instruction snippets is exit 2 and the message names the snippet glob."""
    point_gate_at(
        monkeypatch,
        tmp_path,
        manifests={"skills/a/claude-all.json": []},
        snippets=[],
        keys=KNOWN,
    )

    assert check_requires.main() == 2
    err = capsys.readouterr().err
    assert "CANNOT CHECK" in err
    assert "*/claude_md.md" in err


def test_zero_resource_keys_fails_closed_naming_discover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero discovered resources is exit 2 and the message names discover()."""
    point_gate_at(
        monkeypatch,
        tmp_path,
        manifests={"skills/a/claude-all.json": []},
        snippets=["demo"],
        keys=set(),
    )

    assert check_requires.main() == 2
    err = capsys.readouterr().err
    assert "CANNOT CHECK" in err
    assert "discover()" in err


def test_dangling_requires_still_fails_with_exit_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dangling ``requires`` entry keeps exit 1 and its existing message."""
    point_gate_at(
        monkeypatch,
        tmp_path,
        manifests={"skills/a/claude-all.json": ["skills/missing-skill"]},
        snippets=["demo"],
        keys=KNOWN,
    )

    assert check_requires.main() == 1
    captured = capsys.readouterr()
    assert "requires 'skills/missing-skill' — no such resource" in captured.out
    assert "1 requires finding(s)" in captured.err


def test_undeclared_instruction_reference_still_fails_with_exit_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An undeclared instruction reference keeps exit 1 and its existing message."""
    point_gate_at(
        monkeypatch,
        tmp_path,
        manifests={"skills/a/claude-all.json": []},
        snippets=["demo"],
        keys=KNOWN,
    )
    (tmp_path / "instructions" / "demo" / "claude_md.md").write_text(
        "Load `foo-skill`.\n", encoding="utf-8"
    )

    assert check_requires.main() == 1
    captured = capsys.readouterr()
    assert "names `foo-skill` but its claude-all.json does not require skills/foo-skill" in (
        captured.out
    )
    assert "1 requires finding(s)" in captured.err
