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


def make_repo(
    tmp_path: Path,
    *,
    manifest_requires: list[str] | None = None,
    snippet_body: str | None = None,
    snippet_requires: list[str] | None = None,
    suffixed_manifest: bool = True,
) -> tuple[Path, Path]:
    """Build a fake ``src/claude_all`` tree; returns ``(src, instructions)``."""
    src = tmp_path / "src"
    instructions = src / "claude_all" / "instructions"
    instructions.mkdir(parents=True)
    if manifest_requires is not None:
        skill = src / "claude_all" / "skills" / "foo"
        skill.mkdir(parents=True)
        (skill / "claude-all.json").write_text(json.dumps({"requires": manifest_requires}))
        if suffixed_manifest:
            (skill / "extra.claude-all.json").write_text(json.dumps({"requires": []}))
    if snippet_body is not None:
        folder = instructions / "demo"
        folder.mkdir()
        (folder / "claude_md.md").write_text(snippet_body, encoding="utf-8")
        if snippet_requires is not None:
            (folder / "claude-all.json").write_text(json.dumps({"requires": snippet_requires}))
    return src, instructions


def point_gate_at(monkeypatch: pytest.MonkeyPatch, src: Path, instructions: Path) -> None:
    """Aim the gate's ``main`` at a fake tree with a fixed resource set."""
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set(KNOWN))


def test_clean_run_prints_one_scanned_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A clean run exits 0 with one ``scanned=N`` line on stderr only."""
    src, instructions = make_repo(
        tmp_path,
        manifest_requires=["skills/foo-skill"],
        snippet_body="Load `foo-skill`.\n",
        snippet_requires=["skills/foo-skill"],
    )
    point_gate_at(monkeypatch, src, instructions)

    assert check_requires.main() == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    summary = [line for line in captured.err.splitlines() if line.startswith("scanned=")]
    # Three manifests: the skill's claude-all.json, its suffixed sibling and the snippet's.
    assert summary == ["scanned=4 manifests=3 snippets=1 resources=3"]


def test_empty_instructions_glob_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty snippet glob exits 2 and names that pattern."""
    src, instructions = make_repo(tmp_path, manifest_requires=["skills/foo-skill"])
    point_gate_at(monkeypatch, src, instructions)

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "CANNOT CHECK" in captured.err
    assert "instructions/*/claude_md.md" in captured.err
    assert "scanned=" not in captured.err


def test_no_manifests_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No ``claude-all.json`` manifest exits 2 and names that pattern."""
    src, instructions = make_repo(tmp_path, snippet_body="Plain text.\n")
    point_gate_at(monkeypatch, src, instructions)

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "CANNOT CHECK" in captured.err
    assert "claude-all.json" in captured.err


def test_plain_manifest_glob_fails_closed_even_when_suffixed_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty plain manifest glob fails even when the suffixed glob matches."""
    src, instructions = make_repo(tmp_path, snippet_body="Plain text.\n")
    skill = src / "claude_all" / "skills" / "foo"
    skill.mkdir(parents=True)
    (skill / "extra.claude-all.json").write_text(json.dumps({"requires": []}))
    point_gate_at(monkeypatch, src, instructions)

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "claude_all/**/claude-all.json" in captured.err
    assert "*.claude-all.json" not in captured.err


def test_shipped_tree_passes_zero_discovery_rule(capsys: pytest.CaptureFixture[str]) -> None:
    """The shipped tree passes the zero-discovery rule."""
    assert check_requires.main() == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "CANNOT CHECK" not in captured.err
    assert "scanned=" in captured.err


def test_zero_resources_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No discovered resources exits 2 and names that pattern."""
    src, instructions = make_repo(
        tmp_path,
        manifest_requires=["skills/foo-skill"],
        snippet_body="Plain text.\n",
        snippet_requires=[],
    )
    point_gate_at(monkeypatch, src, instructions)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "CANNOT CHECK" in captured.err
    assert "installer discover([]) resources" in captured.err


def test_dangling_requires_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dangling ``requires`` entry still exits 1 with its finding."""
    src, instructions = make_repo(
        tmp_path,
        manifest_requires=["skills/missing-skill"],
        snippet_body="Plain text.\n",
        snippet_requires=[],
    )
    point_gate_at(monkeypatch, src, instructions)

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "requires 'skills/missing-skill' — no such resource" in captured.out
    assert "scanned=" not in captured.err


def test_undeclared_instruction_ref_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An undeclared instruction reference still exits 1 with its finding."""
    src, instructions = make_repo(
        tmp_path,
        manifest_requires=["skills/foo-skill"],
        snippet_body="Load `foo-skill`.\n",
        snippet_requires=[],
    )
    point_gate_at(monkeypatch, src, instructions)

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert (
        "names `foo-skill` but its claude-all.json does not require skills/foo-skill"
        in captured.out
    )
