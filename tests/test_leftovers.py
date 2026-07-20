"""Tests for leftover-artifact detection (what `claude-all --prune` cleans up).

A check that can only ever report "clean" is worthless — the vacuous-pass failure
this repo keeps hunting. Every test asserts the check actually BITES on a specific
defect, plus explicit no-false-positive cases.

Findings are dicts: ``label`` for display, ``artifact`` carrying the reversal
(``None`` when only a reinstall or a hand-edit can fix it).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claude_all.cli import (
    check_claude_md,
    check_links,
    check_settings_hooks,
    install_root_of,
    remove_leftovers,
    scan_leftovers,
)


def write_settings(root: Path, hooks: dict) -> None:
    """Write a `.claude/settings.json` with the given hooks mapping.

    Args:
        root: The `.claude` directory.
        hooks: The `hooks` mapping to serialise.
    """
    (root / "settings.json").write_text(json.dumps({"hooks": hooks}))


class TestInstallRootOf:
    """Extracting the owning claude-all install from a symlink target."""

    def test_extracts_root(self) -> None:
        """A path through `claude_all/` yields everything before it."""
        got = install_root_of(Path("/opt/site-packages/claude_all/skills/x/SKILL.md"))
        assert got == "/opt/site-packages"

    def test_non_claude_all_path_yields_empty(self) -> None:
        """A target that is not a claude-all resource yields no root."""
        assert install_root_of(Path("/somewhere/else/file.md")) == ""


class TestCheckLinks:
    """Dangling links, and the mixed-install signal."""

    def test_dangling_link_is_reported(self, tmp_path: Path, monkeypatch) -> None:
        """A symlink whose target is gone is a finding.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: pytest fixture used to point the project scope at tmp_path.
        """
        claude = tmp_path / ".claude"
        (claude / "skills").mkdir(parents=True)
        (claude / "skills" / "ghost").symlink_to(tmp_path / "gone")
        monkeypatch.chdir(tmp_path)
        findings = check_links("project")
        assert any("dangling link" in f["label"] and "ghost" in f["label"] for f in findings)

    def test_mixed_install_is_reported(self, tmp_path: Path, monkeypatch) -> None:
        """Links pointing at two different claude-all roots flag a partial install.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: pytest fixture used to point the project scope at tmp_path.
        """
        claude = tmp_path / ".claude"
        (claude / "skills").mkdir(parents=True)
        for root, names in (("rootA", ["a1", "a2"]), ("rootB", ["b1"])):
            target = tmp_path / root / "claude_all" / "skills" / "s"
            target.mkdir(parents=True)
            for name in names:
                (claude / "skills" / name).symlink_to(target)
        monkeypatch.chdir(tmp_path)
        findings = check_links("project")
        assert any("mixed install" in f["label"] for f in findings)

    def test_consistent_install_is_quiet(self, tmp_path: Path, monkeypatch) -> None:
        """Links all pointing at ONE root produce no finding — no false positives.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: pytest fixture used to point the project scope at tmp_path.
        """
        claude = tmp_path / ".claude"
        (claude / "skills").mkdir(parents=True)
        target = tmp_path / "root" / "claude_all" / "skills" / "s"
        target.mkdir(parents=True)
        for name in ("a", "b", "c"):
            (claude / "skills" / name).symlink_to(target)
        monkeypatch.chdir(tmp_path)
        assert check_links("project") == []


class TestCheckSettingsHooks:
    """Broken and double-wired settings.json hook entries."""

    def test_orphan_hook_entry_is_reported(self, tmp_path: Path, monkeypatch) -> None:
        """A hook command pointing at a missing script is a finding.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: pytest fixture used to point the project scope at tmp_path.
        """
        claude = tmp_path / ".claude"
        claude.mkdir(parents=True)
        missing = tmp_path / "nope" / "gone-hook.py"
        write_settings(
            claude,
            {"PreToolUse": [{"matcher": "Edit", "hooks": [{"command": str(missing)}]}]},
        )
        monkeypatch.chdir(tmp_path)
        findings = check_settings_hooks("project")
        assert any("orphan hook" in f["label"] and "gone-hook.py" in f["label"] for f in findings)

    def test_double_wired_hook_is_reported(self, tmp_path: Path, monkeypatch) -> None:
        """The same script wired under two events may fire twice — a finding.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: pytest fixture used to point the project scope at tmp_path.
        """
        claude = tmp_path / ".claude"
        claude.mkdir(parents=True)
        script = tmp_path / "dup.py"
        script.write_text("")
        write_settings(
            claude,
            {
                "PreToolUse": [{"matcher": "Edit", "hooks": [{"command": str(script)}]}],
                "PostToolUse": [{"matcher": "", "hooks": [{"command": str(script)}]}],
            },
        )
        monkeypatch.chdir(tmp_path)
        findings = check_settings_hooks("project")
        assert any("double-wired" in f["label"] and "dup.py" in f["label"] for f in findings)


class TestCheckClaudeMd:
    """Orphaned, unclosed and duplicated tagged blocks."""

    def test_orphan_and_unclosed_and_duplicate(self, tmp_path: Path, monkeypatch) -> None:
        """Each malformed/unowned block shape produces its own finding.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: pytest fixture used to point the project scope at tmp_path.
        """
        (tmp_path / "CLAUDE.md").write_text(
            "<!-- claude-all:skills/orphan:start -->\nx\n<!-- claude-all:skills/orphan:end -->\n"
            "<!-- claude-all:skills/unclosed:start -->\ny\n"
            "<!-- claude-all:skills/dup:start -->\nz\n<!-- claude-all:skills/dup:end -->\n"
            "<!-- claude-all:skills/dup:start -->\nz\n<!-- claude-all:skills/dup:end -->\n"
        )
        monkeypatch.chdir(tmp_path)
        findings = check_claude_md("project")
        assert any("orphan block" in f["label"] and "orphan" in f["label"] for f in findings)
        assert any("unclosed block" in f["label"] for f in findings)
        assert any("duplicate block" in f["label"] for f in findings)

    def test_missing_claude_md_is_quiet(self, tmp_path: Path, monkeypatch) -> None:
        """No CLAUDE.md at all is not a defect.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: pytest fixture used to point the project scope at tmp_path.
        """
        monkeypatch.chdir(tmp_path)
        assert check_claude_md("project") == []


class TestRemoveLeftovers:
    """`--prune` reverses the removable findings and leaves advisory ones alone."""

    def test_removable_are_reversed_advisory_untouched(self, tmp_path: Path, monkeypatch) -> None:
        """A dangling link is deleted; an unclosed CLAUDE.md block is only reported.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: pytest fixture used to point the project scope at tmp_path.
        """
        claude = tmp_path / ".claude"
        (claude / "skills").mkdir(parents=True)
        link = claude / "skills" / "ghost"
        link.symlink_to(tmp_path / "gone")
        (tmp_path / "CLAUDE.md").write_text("<!-- claude-all:skills/x:start -->\nno end tag\n")
        monkeypatch.chdir(tmp_path)

        removable, advisory = scan_leftovers("project")
        cleaned = remove_leftovers(removable)

        assert not link.is_symlink(), "dangling link should have been removed"
        assert any("dangling link" in line for line in cleaned)
        assert any("unclosed block" in f["label"] for f in advisory)
        assert "no end tag" in (tmp_path / "CLAUDE.md").read_text(), "advisory file was modified"
