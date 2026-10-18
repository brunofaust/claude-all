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


def fake_repo(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    manifest_requires: list[str],
    snippet_body: str | None,
    known: set[str],
) -> None:
    """Point the checker's discovery roots at a throwaway repo layout.

    Args:
        root: pytest's per-test temporary directory, used as the fake repo root.
        monkeypatch: pytest fixture used to redirect the module globals.
        manifest_requires: ``requires`` written into the fake resource manifest.
        snippet_body: body of the fake instruction snippet, or None for no snippet.
        known: resource keys the fake installer discovers.
    """
    src = root / "src"
    (src / "claude_all" / "skills" / "bar").mkdir(parents=True)
    (src / "claude_all" / "skills" / "bar" / "claude-all.json").write_text(
        json.dumps({"requires": manifest_requires}), encoding="utf-8"
    )
    instructions = src / "claude_all" / "instructions"
    if snippet_body is not None:
        (instructions / "demo").mkdir(parents=True)
        (instructions / "demo" / "claude_md.md").write_text(snippet_body, encoding="utf-8")
    monkeypatch.setattr(check_requires, "REPO_ROOT", root)
    monkeypatch.setattr(check_requires, "SRC", src)
    monkeypatch.setattr(check_requires, "INSTRUCTIONS_DIR", instructions)
    monkeypatch.setattr(check_requires, "load_resource_keys", lambda: known)


def test_main_success_prints_one_scanned_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A clean run exits 0, keeps stdout empty and prints one ``scanned=N`` line to stderr.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture used to redirect the discovery roots.
        capsys: pytest fixture capturing stdout and stderr.
    """
    fake_repo(
        tmp_path,
        monkeypatch,
        manifest_requires=["skills/foo-skill"],
        snippet_body="Load `foo-skill`.\n",
        known={"skills/foo-skill"},
    )
    # Declare the snippet's own requires so the instruction rule passes.
    (tmp_path / "src/claude_all/instructions/demo/claude-all.json").write_text(
        json.dumps({"requires": ["skills/foo-skill"]}), encoding="utf-8"
    )

    assert check_requires.main() == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    err_lines = captured.err.strip().splitlines()
    assert len(err_lines) == 1
    assert err_lines[0].startswith("scanned=3 ")


def test_main_zero_manifest_discovery_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A manifest pattern matching nothing exits 2 and names that pattern.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture used to redirect the discovery roots.
        capsys: pytest fixture capturing stdout and stderr.
    """
    fake_repo(
        tmp_path,
        monkeypatch,
        manifest_requires=[],
        snippet_body=None,
        known={"skills/foo-skill"},
    )
    # Remove the only manifest so the claude-all.json pattern matches nothing.
    (tmp_path / "src/claude_all/skills/bar/claude-all.json").unlink()

    assert check_requires.main() == 2

    captured = capsys.readouterr()
    assert "'claude-all.json'" in captured.err
    assert "scanned=" not in captured.err


def test_main_zero_snippet_discovery_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An instruction glob matching nothing exits 2 and names that pattern.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture used to redirect the discovery roots.
        capsys: pytest fixture capturing stdout and stderr.
    """
    fake_repo(
        tmp_path,
        monkeypatch,
        manifest_requires=["skills/foo-skill"],
        snippet_body=None,
        known={"skills/foo-skill"},
    )

    assert check_requires.main() == 2

    assert "'*/claude_md.md'" in capsys.readouterr().err


def test_main_zero_resource_keys_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An installer that discovers no resources exits 2 rather than passing vacuously.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture used to redirect the discovery roots.
        capsys: pytest fixture capturing stdout and stderr.
    """
    fake_repo(
        tmp_path,
        monkeypatch,
        manifest_requires=[],
        snippet_body="Plain text.\n",
        known=set(),
    )

    assert check_requires.main() == 2

    assert "discover([])" in capsys.readouterr().err


def test_main_dangling_requires_still_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A genuine dangling ``requires`` entry keeps the existing finding and exit 1.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture used to redirect the discovery roots.
        capsys: pytest fixture capturing stdout and stderr.
    """
    fake_repo(
        tmp_path,
        monkeypatch,
        manifest_requires=["skills/missing"],
        snippet_body="Plain text.\n",
        known={"skills/foo-skill"},
    )

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "requires 'skills/missing' — no such resource" in captured.out
    assert "1 requires finding(s)" in captured.err


def test_main_undeclared_instruction_ref_still_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An instruction naming an undeclared resource keeps the existing finding and exit 1.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture used to redirect the discovery roots.
        capsys: pytest fixture capturing stdout and stderr.
    """
    fake_repo(
        tmp_path,
        monkeypatch,
        manifest_requires=["skills/foo-skill"],
        snippet_body="Load `foo-skill`.\n",
        known={"skills/foo-skill"},
    )

    assert check_requires.main() == 1

    captured = capsys.readouterr()
    assert "names `foo-skill` but its claude-all.json does not require" in captured.out
    assert "scanned=" in captured.err


def test_main_allows_zero_optional_suffix_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero ``*.claude-all.json`` matches is a valid state; the required manifest still counts.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture used to redirect the discovery roots.
        capsys: pytest fixture capturing stdout and stderr.
    """
    fake_repo(
        tmp_path,
        monkeypatch,
        manifest_requires=["skills/foo-skill"],
        snippet_body="Plain text.\n",
        known={"skills/foo-skill"},
    )

    assert check_requires.main() == 0

    err_lines = capsys.readouterr().err.strip().splitlines()
    assert err_lines == ["scanned=2 requires unit(s) (1 manifest(s), 1 instruction snippet(s))"]


def test_main_counts_optional_suffix_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``*.claude-all.json`` manifest is inspected and counted in the summary.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest fixture used to redirect the discovery roots.
        capsys: pytest fixture capturing stdout and stderr.
    """
    fake_repo(
        tmp_path,
        monkeypatch,
        manifest_requires=["skills/foo-skill"],
        snippet_body="Plain text.\n",
        known={"skills/foo-skill"},
    )
    (tmp_path / "src/claude_all/skills/bar/extra.claude-all.json").write_text(
        json.dumps({"requires": ["skills/foo-skill"]}), encoding="utf-8"
    )

    assert check_requires.main() == 0

    err_lines = capsys.readouterr().err.strip().splitlines()
    assert err_lines == ["scanned=3 requires unit(s) (2 manifest(s), 1 instruction snippet(s))"]
