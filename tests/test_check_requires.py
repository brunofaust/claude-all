"""Tests for the manifest-requires gate (`scripts/check_requires.py`).

The gate lives or dies on its discovery: if the globs that find `claude-all.json`
manifests silently match nothing, the checker inspects zero files and reports
green — a vacuous pass. These tests pin down that a zero-discovery run is a hard
failure (never exit 0), that a clean run prints an inspected-count summary, and
that a genuine dangling `requires` still fails exactly as before.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_requires
from check_requires import find_violations, main


@pytest.fixture
def synthetic_src(tmp_path: Path) -> Path:
    """A throwaway manifests root under a synthetic ``src`` tree.

    Args:
        tmp_path: pytest's per-test temporary directory.

    Returns:
        The ``claude_all`` subdir to scan for manifests.
    """
    d = tmp_path / "src" / "claude_all"
    d.mkdir(parents=True)
    return d


class TestFindViolations:
    """Discovery and validation counts, independent of the CLI wrapper."""

    def test_clean_manifests_report_inspected_counts(
        self, synthetic_src: Path
    ) -> None:
        """A clean graph returns zero findings and truthful manifest/entry counts.

        Args:
            synthetic_src: The temporary manifests root.
        """
        (synthetic_src / "a").mkdir()
        (synthetic_src / "a" / "claude-all.json").write_text(
            json.dumps({"requires": ["skills/a", "skills/b"]})
        )
        manifests, requires, findings = find_violations(
            {"skills/a", "skills/b"}, src_dir=synthetic_src
        )
        assert manifests == 1
        assert requires == 2
        assert findings == []

    def test_dangling_requires_is_reported(self, synthetic_src: Path) -> None:
        """An unresolvable `requires` entry is flagged, with its path.

        Args:
            synthetic_src: The temporary manifests root.
        """
        (synthetic_src / "a").mkdir()
        (synthetic_src / "a" / "claude-all.json").write_text(
            json.dumps({"requires": ["skills/ghost"]})
        )
        manifests, requires, findings = find_violations(
            {"skills/a"}, src_dir=synthetic_src
        )
        assert manifests == 1
        assert requires == 1
        assert len(findings) == 1
        assert "no such resource" in findings[0]
        assert "a/claude-all.json" in findings[0]

    def test_zero_discovery_yields_zero_manifest_count(
        self, synthetic_src: Path
    ) -> None:
        """No matching manifests → count 0, no findings: the vacuous-pass trap.

        Args:
            synthetic_src: An empty manifests root.
        """
        manifests, requires, findings = find_violations(
            set(), src_dir=synthetic_src
        )
        assert manifests == 0
        assert requires == 0
        assert findings == []

    def test_malformed_manifest_is_flagged(self, synthetic_src: Path) -> None:
        """An invalid manifest counts as inspected and reports a finding.

        Args:
            synthetic_src: The temporary manifests root.
        """
        (synthetic_src / "b").mkdir()
        (synthetic_src / "b" / "claude-all.json").write_text("{not json")
        manifests, requires, findings = find_violations(
            set(), src_dir=synthetic_src
        )
        assert manifests == 1
        assert requires == 0
        assert len(findings) == 1
        assert "not valid JSON" in findings[0]


class TestMain:
    """The CLI exit-code contract: 0 only when something was inspected and is clean."""

    def test_clean_run_prints_inspected_summary_and_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """A successful run prints one greppable summary line with the count.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: Fixture for pointing the gate at the synthetic tree.
            capsys: Fixture for capturing stdout.
        """
        d = tmp_path / "src" / "claude_all"
        d.mkdir(parents=True)
        (d / "claude-all.json").write_text(json.dumps({"requires": ["skills/a"]}))
        monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
        monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/a"})

        assert main() == 0
        out = capsys.readouterr().out
        assert "inspected: 1 manifest(s), 1 requires entr(ies) checked — OK" in out

    def test_zero_discovery_hard_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """No matching manifests is a hard failure naming the pattern, never exit 0.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: Fixture for pointing the gate at an empty tree.
            capsys: Fixture for capturing stderr.
        """
        empty = tmp_path / "src" / "claude_all"
        empty.mkdir(parents=True)
        monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
        monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

        assert main() == 1
        err = capsys.readouterr().err
        assert "claude-all.json" in err
        assert "*.claude-all.json" in err
        assert "matched zero files" in err

    def test_genuine_failure_still_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """A dangling `requires` keeps failing, before any summary line.

        Args:
            tmp_path: pytest's per-test temporary directory.
            monkeypatch: Fixture for pointing the gate at the synthetic tree.
            capsys: Fixture for capturing stdout/stderr.
        """
        d = tmp_path / "src" / "claude_all"
        d.mkdir(parents=True)
        (d / "claude-all.json").write_text(json.dumps({"requires": ["skills/ghost"]}))
        monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
        monkeypatch.setattr(check_requires, "load_resource_keys", lambda: {"skills/a"})

        assert main() == 1
        captured = capsys.readouterr()
        assert "no such resource" in captured.out
        assert "refusing to pass green" not in captured.out
        assert "inspected:" not in captured.out
        assert "1 dangling/invalid requires entry(ies)" in captured.err
