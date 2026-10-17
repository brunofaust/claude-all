"""Tests for the `check_requires` gate's instruction-reference rule.

A standalone instruction snippet has no agent or skill of its own to carry a
dependency, so every resource it names must be declared in its `claude-all.json`
or installing the instruction ships a rule pointing at nothing.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest import mock

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


def _run_main(src: Path, instructions: Path, known: set[str]) -> tuple[int, str, str]:
    """Run ``main()`` against a fake source tree and return (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch.object(check_requires, "REPO_ROOT", src.parent),
        mock.patch.object(check_requires, "SRC", src),
        mock.patch.object(check_requires, "INSTRUCTIONS_DIR", instructions),
        mock.patch.object(check_requires, "load_resource_keys", return_value=known),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        code = check_requires.main()
    return code, out.getvalue(), err.getvalue()


def _tree(tmp_path: Path, manifest_requires: list[str] | None) -> tuple[Path, Path]:
    """Build a fake ``src`` tree (optional manifest) and one clean instruction snippet."""
    src = tmp_path / "src"
    (src / "claude_all" / "skills" / "bar").mkdir(parents=True)
    if manifest_requires is not None:
        (src / "claude_all" / "skills" / "bar" / "claude-all.json").write_text(
            json.dumps({"requires": manifest_requires})
        )
    instructions = src / "claude_all" / "instructions"
    (instructions / "demo").mkdir(parents=True)
    (instructions / "demo" / "claude_md.md").write_text("Plain rule, no names.\n")
    return src, instructions


def test_success_prints_scanned_count_and_exits_zero(tmp_path: Path) -> None:
    """A clean run exits 0 and prints one greppable ``scanned=N`` line on stderr.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    src, instructions = _tree(tmp_path, ["skills/foo-skill"])

    code, out, err = _run_main(src, instructions, {"skills/foo-skill"})

    assert code == 0
    assert out == ""
    assert "scanned=2 " in err
    assert "manifests=1" in err
    assert "instruction_snippets=1" in err


def test_zero_manifests_is_cannot_check(tmp_path: Path) -> None:
    """No manifest matched ``claude-all.json`` → exit 2 naming that pattern.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    src, instructions = _tree(tmp_path, None)

    code, _out, err = _run_main(src, instructions, {"skills/foo-skill"})

    assert code == 2
    assert "CANNOT CHECK" in err
    assert "claude-all.json" in err
    assert "scanned=" not in err


def test_zero_instruction_snippets_is_cannot_check(tmp_path: Path) -> None:
    """No instruction snippet matched ``*/claude_md.md`` → exit 2 naming that pattern.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    src, instructions = _tree(tmp_path, ["skills/foo-skill"])
    (instructions / "demo" / "claude_md.md").unlink()

    code, _out, err = _run_main(src, instructions, {"skills/foo-skill"})

    assert code == 2
    assert "CANNOT CHECK" in err
    assert "*/claude_md.md" in err
    assert "scanned=" not in err


def test_dangling_requires_still_fails_with_exit_one(tmp_path: Path) -> None:
    """A genuine dangling ``requires`` entry still exits 1 with the unchanged finding.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    src, instructions = _tree(tmp_path, ["skills/missing"])

    code, out, err = _run_main(src, instructions, {"skills/foo-skill"})

    assert code == 1
    assert "requires 'skills/missing' — no such resource" in out
    assert "scanned=" not in err


def test_empty_installer_discovery_is_cannot_check(tmp_path: Path) -> None:
    """An installer that discovers no resources cannot resolve anything → exit 2.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    src, instructions = _tree(tmp_path, [])

    code, _out, err = _run_main(src, instructions, set())

    assert code == 2
    assert "CANNOT CHECK" in err
    assert "discover([])" in err
    assert "scanned=" not in err


def test_dangling_requires_with_empty_installer_still_exits_one(tmp_path: Path) -> None:
    """A dangling entry keeps exit 1 even when the installer discovers nothing.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    src, instructions = _tree(tmp_path, ["skills/missing"])

    code, out, err = _run_main(src, instructions, set())

    assert code == 1
    assert "requires 'skills/missing' — no such resource" in out
    assert "CANNOT CHECK" not in err


def test_undeclared_instruction_reference_still_fails_with_exit_one(tmp_path: Path) -> None:
    """An instruction naming an undeclared resource still exits 1 with its finding.

    Args:
        tmp_path: pytest's per-test temporary directory.
    """
    src, instructions = _tree(tmp_path, ["skills/foo-skill"])
    (instructions / "demo" / "claude_md.md").write_text("Delegate to `bar-agent`.\n")

    code, out, err = _run_main(src, instructions, {"agents/bar-agent", "skills/foo-skill"})

    assert code == 1
    assert "names `bar-agent` but its claude-all.json does not require agents/bar-agent" in out
    assert "scanned=" not in err
