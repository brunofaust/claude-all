"""Tests for scripts/check_requires.py gate behavior."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_requires import find_violations, main


class TestFindViolations:
    def test_normal_success_no_violations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Create a temporary src/claude_all tree with a manifest that requires nothing
        src = tmp_path / "src" / "claude_all"
        src.mkdir(parents=True)
        manifest = src / "claude-all.json"
        manifest.write_text(json.dumps({"requires": []}), encoding="utf-8")

        # Patch global paths
        import check_requires

        monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
        monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

        findings = find_violations(known=set())
        assert findings == []

    def test_genuine_failure_dangling_requires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        src = tmp_path / "src" / "claude_all"
        src.mkdir(parents=True)
        manifest = src / "claude-all.json"
        manifest.write_text(json.dumps({"requires": ["skills/missing"]}), encoding="utf-8")

        import check_requires

        monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
        monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)

        findings = find_violations(known=set())
        assert len(findings) == 1
        assert "requires 'skills/missing'" in findings[0]
        assert "claude-all.json" in findings[0]


class TestMainZeroDiscovery:
    def test_zero_discovery_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        # Point SRC to an empty tree so manifests list is empty
        empty_src = tmp_path / "empty_src" / "claude_all"
        empty_src.mkdir(parents=True)

        import check_requires

        monkeypatch.setattr(check_requires, "SRC", tmp_path / "empty_src")
        monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
        # Avoid real discover call
        monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

        exit_code = main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "0 manifests matched" in captured.err
        assert "claude-all.json" in captured.err

    def test_success_prints_summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
        src = tmp_path / "src" / "claude_all"
        src.mkdir(parents=True)
        (src / "claude-all.json").write_text(json.dumps({"requires": []}), encoding="utf-8")

        import check_requires

        monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
        monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

        exit_code = main()
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "inspected 1 manifests" in captured.out

    def test_existing_failure_still_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        src = tmp_path / "src" / "claude_all"
        src.mkdir(parents=True)
        (src / "claude-all.json").write_text(
            json.dumps({"requires": ["bad/resource"]}), encoding="utf-8"
        )

        import check_requires

        monkeypatch.setattr(check_requires, "SRC", tmp_path / "src")
        monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())

        exit_code = main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "1 dangling/invalid requires entry" in captured.err
