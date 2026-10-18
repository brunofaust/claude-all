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


def lay_out_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    manifest: bool = True,
    with_snippet: bool = True,
    snippet_requires: list[str] | None = None,
) -> Path:
    """Point the gate at a fake repo under ``tmp_path``.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's monkeypatch fixture.
        manifest: whether a skill manifest exists under ``src/claude_all``.
        with_snippet: whether an instruction snippet exists under the instructions dir.
        snippet_requires: ``requires`` written beside the snippet, if any.

    Returns:
        The instructions directory the gate will scan.
    """
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    src = tmp_path / "src"
    monkeypatch.setattr(check_requires, "SRC", src)
    instructions = src / "claude_all" / "instructions"
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions)
    (src / "claude_all").mkdir(parents=True)
    if manifest:
        skill = src / "claude_all" / "skills" / "bar"
        skill.mkdir(parents=True)
        (skill / "claude-all.json").write_text(json.dumps({"requires": ["skills/foo-skill"]}))
    if with_snippet:
        snippet_root = snippet(instructions, "Plain text only.\n", snippet_requires)
        assert snippet_root == instructions
    else:
        instructions.mkdir(parents=True, exist_ok=True)
    return instructions


def test_successful_run_prints_one_summary_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A clean run exits 0 and reports how many units it inspected on stderr.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's monkeypatch fixture.
        capsys: pytest's captured-output fixture.
    """
    lay_out_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: KNOWN)

    assert check_requires.main() == 0

    captured = capsys.readouterr()
    summary = [line for line in captured.err.splitlines() if "check_requires: inspected" in line]
    assert summary == [
        "check_requires: inspected 2 unit(s) (1 manifest(s), 1 instruction snippet(s))"
    ]
    assert captured.out == ""


def test_zero_manifests_exits_2_and_names_the_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero manifests is a hard failure, not a silent pass.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's monkeypatch fixture.
        capsys: pytest's captured-output fixture.
    """
    lay_out_repo(tmp_path, monkeypatch, manifest=False)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: KNOWN)

    assert check_requires.main() == 2

    err = capsys.readouterr().err
    assert "CANNOT CHECK" in err
    assert "claude-all.json" in err
    assert "inspected" not in err


def test_zero_instruction_snippets_exits_2_and_names_the_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero instruction snippets is a hard failure even when manifests exist.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's monkeypatch fixture.
        capsys: pytest's captured-output fixture.
    """
    lay_out_repo(tmp_path, monkeypatch, with_snippet=False)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: KNOWN)

    assert check_requires.main() == 2

    err = capsys.readouterr().err
    assert "CANNOT CHECK" in err
    assert "*/claude_md.md" in err


def test_empty_discover_exits_2_and_names_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty ``discover([])`` result is a hard failure, not a list of dangling findings.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's monkeypatch fixture.
        capsys: pytest's captured-output fixture.
    """
    lay_out_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    assert check_requires.main() == 2

    err = capsys.readouterr().err
    assert "discover([])" in err
    assert "requires '" not in err


def test_genuine_dangling_requires_still_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real dangling ``requires`` entry keeps its exit 1 and message.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's monkeypatch fixture.
        capsys: pytest's captured-output fixture.
    """
    lay_out_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"agents/bar-agent"})

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "requires 'skills/foo-skill' — no such resource" in captured.out
    assert "requires finding(s)" in captured.err
    assert "CANNOT CHECK" not in captured.err
    assert "inspected" not in captured.err


def test_undeclared_instruction_reference_still_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An instruction naming an undeclared resource keeps its exit 1 and message.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's monkeypatch fixture.
        capsys: pytest's captured-output fixture.
    """
    instructions = lay_out_repo(tmp_path, monkeypatch)
    (instructions / "demo" / "claude_md.md").write_text("Load `foo-skill`.\n", encoding="utf-8")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: KNOWN)

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "names `foo-skill` but its claude-all.json does not require skills/foo-skill" in (
        captured.out
    )
    assert "requires finding(s)" in captured.err
    assert "inspected" not in captured.err
