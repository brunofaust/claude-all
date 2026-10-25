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


def test_success_prints_one_scanned_summary_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """A clean run on the shipped repo reports a non-zero inspected count on stderr only.

    Args:
        capsys: pytest's captured stdout/stderr.
    """
    assert check_requires.main() == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    summary = [line for line in captured.err.splitlines() if "scanned=" in line]
    assert len(summary) == 1
    assert summary[0].startswith("check_requires: scanned=")
    assert int(summary[0].split("scanned=")[1].split()[0]) > 0


def test_zero_discovery_exits_2_naming_the_patterns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Discovery that matches nothing is a hard failure that names the pattern.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's attribute patcher.
        capsys: pytest's captured stdout/stderr.
    """
    (tmp_path / "src" / "claude_all").mkdir(parents=True)
    (tmp_path / "instructions").mkdir()
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set(KNOWN))

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert 'rglob("claude-all.json")' in captured.err
    assert "matched 0 manifests" in captured.err
    assert 'instructions_dir glob "*/claude_md.md" matched 0 snippets' in captured.err
    assert "scanned=" not in captured.err


def test_zero_resource_keys_exit_2_naming_the_installer_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An installer that discovers no resources is a hard failure, even with files present.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's attribute patcher.
        capsys: pytest's captured stdout/stderr.
    """
    skill = tmp_path / "src" / "claude_all" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(json.dumps({"requires": []}))
    snippet(tmp_path / "instructions", "Plain text.\n")
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "installer discover([]) returned 0 resource keys" in captured.err
    assert "matched 0 manifests" not in captured.err
    assert "matched 0 snippets" not in captured.err


def test_zero_manifests_still_fail_when_snippets_are_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each input is checked on its own: zero manifests fails even with snippets found.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's attribute patcher.
        capsys: pytest's captured stdout/stderr.
    """
    (tmp_path / "src" / "claude_all").mkdir(parents=True)
    snippet(tmp_path / "instructions", "Plain text.\n")
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set(KNOWN))

    assert check_requires.main() == 2

    err = capsys.readouterr().err
    assert "matched 0 manifests" in err
    assert "matched 0 snippets" not in err


def test_dangling_requires_still_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A genuine dangling `requires` entry still fails with exit 1 and its finding text.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's attribute patcher.
        capsys: pytest's captured stdout/stderr.
    """
    skill = tmp_path / "src" / "claude_all" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(json.dumps({"requires": ["skills/missing"]}))
    snippet(tmp_path / "instructions", "Plain text.\n")
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set(KNOWN))

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "requires 'skills/missing' — no such resource" in captured.out
    assert "1 requires finding(s)" in captured.err
    assert "scanned=" not in captured.err


def test_summary_counts_manifests_requires_and_snippets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The success line reports each inspected unit and their total.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's attribute patcher.
        capsys: pytest's captured stdout/stderr.
    """
    skill = tmp_path / "src" / "claude_all" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(
        json.dumps({"requires": ["skills/foo-skill", "agents/bar-agent"]})
    )
    snippet(tmp_path / "instructions", "Plain text.\n")
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set(KNOWN))

    assert check_requires.main() == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "check_requires: scanned=4 (manifests=1 requires=2 snippets=1)\n"


def test_zero_snippets_still_fail_when_manifests_are_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each input is checked on its own: zero snippets fails even with manifests found.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's attribute patcher.
        capsys: pytest's captured stdout/stderr.
    """
    skill = tmp_path / "src" / "claude_all" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "claude-all.json").write_text(json.dumps({"requires": ["skills/foo-skill"]}))
    (tmp_path / "instructions").mkdir()
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", tmp_path / "instructions")
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set(KNOWN))

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert 'instructions_dir glob "*/claude_md.md" matched 0 snippets' in captured.err
    assert "matched 0 manifests" not in captured.err


def test_find_violations_messages_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dangling entry and a non-list `requires` keep their exact finding text.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's attribute patcher.
    """
    dangling = tmp_path / "src" / "claude_all" / "skills" / "dangling"
    dangling.mkdir(parents=True)
    (dangling / "claude-all.json").write_text(json.dumps({"requires": ["skills/missing"]}))
    malformed = tmp_path / "src" / "claude_all" / "skills" / "malformed"
    malformed.mkdir(parents=True)
    (malformed / "claude-all.json").write_text(json.dumps({"requires": "skills/foo-skill"}))
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")

    findings = check_requires.find_violations(set(KNOWN))

    assert findings == [
        "src/claude_all/skills/dangling/claude-all.json: requires 'skills/missing' — no such "
        "resource (renamed/deleted? a built-in like /code-review does not belong in requires)",
        "src/claude_all/skills/malformed/claude-all.json: `requires` must be a list of "
        "'kind/name' strings",
    ]
