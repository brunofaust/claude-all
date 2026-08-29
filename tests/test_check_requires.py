"""Tests for the requires-gate's fail-loud discovery (scripts/check_requires.py).

A glob-discovered checker fails OPEN when a directory is renamed: the scan
matches nothing, nothing is validated, and the gate exits 0 while guarding
nothing. These tests pin the opposite — a zero-manifest scan is a hard failure
naming the pattern, a healthy run prints how many manifests it inspected, and
genuine failures (dangling `requires`, malformed manifest) still fail exactly
as before.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_requires import find_manifests, find_violations, main

CHECK_REQUIRES_MODULE = "check_requires"


def make_manifest(root: Path, name: str, requires: list[str]) -> Path:
    """Write one folder resource's ``claude-all.json`` under *root*.

    Args:
        root: Directory to create the resource in.
        name: Resource directory name.
        requires: The ``requires`` list to record.

    Returns:
        The manifest path.
    """
    resource = root / name
    resource.mkdir()
    manifest = resource / "claude-all.json"
    manifest.write_text(json.dumps({"requires": requires}), encoding="utf-8")
    return manifest


@pytest.fixture
def sandboxed_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the gate against a synthetic repo rooted at ``tmp_path``.

    ``find_violations`` renders finding paths relative to ``REPO_ROOT``, so the
    sandbox must redirect it — tmp manifests are otherwise outside the root and
    the relative-path computation would raise.
    """
    monkeypatch.setattr(f"{CHECK_REQUIRES_MODULE}.REPO_ROOT", tmp_path)
    return tmp_path


class TestZeroDiscovery:
    """A scan that discovers nothing is a hard failure, never a green run."""

    def test_zero_manifests_exits_non_zero_naming_the_pattern(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Zero manifest hits exits non-zero and names BOTH glob patterns."""
        monkeypatch.setattr(f"{CHECK_REQUIRES_MODULE}.find_manifests", list)

        assert main() == 2

        captured = capsys.readouterr()
        assert captured.out == "", "no success summary when nothing was inspected"
        assert "`claude-all.json`" in captured.err
        assert "`*.claude-all.json`" in captured.err

    def test_empty_resource_discovery_also_fails(
        self,
        sandboxed_gate: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An empty installer ``discover([])`` means no key can ever resolve."""
        manifest = make_manifest(tmp_path, "a", [])
        monkeypatch.setattr(f"{CHECK_REQUIRES_MODULE}.find_manifests", lambda: [manifest])
        monkeypatch.setattr(f"{CHECK_REQUIRES_MODULE}.load_resource_keys", set)

        assert main() == 2

        assert "discover([])" in capsys.readouterr().err


class TestSummaryLine:
    """A healthy run reports what it actually inspected."""

    def test_success_prints_inspected_count(
        self,
        sandboxed_gate: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Two manifests, all entries resolvable → exit 0 + one count line."""
        manifests = [
            make_manifest(tmp_path, "a", ["skills/b"]),
            make_manifest(tmp_path, "b", []),
        ]
        monkeypatch.setattr(f"{CHECK_REQUIRES_MODULE}.find_manifests", lambda: manifests)
        monkeypatch.setattr(
            f"{CHECK_REQUIRES_MODULE}.load_resource_keys", lambda: {"skills/a", "skills/b"}
        )

        assert main() == 0

        captured = capsys.readouterr()
        assert (
            "check_requires: 2 manifest(s) inspected — every `requires` entry resolves."
            in captured.out
        )
        assert captured.err == ""


class TestGenuineFailuresStillFail:
    """The new bookkeeping must not soften any existing failure."""

    def test_dangling_requires_still_exits_1(
        self,
        sandboxed_gate: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A renamed dependency target is reported verbatim and fails as before."""
        manifest = make_manifest(tmp_path, "a", ["skills/ghost"])
        monkeypatch.setattr(f"{CHECK_REQUIRES_MODULE}.find_manifests", lambda: [manifest])
        monkeypatch.setattr(
            f"{CHECK_REQUIRES_MODULE}.load_resource_keys", lambda: {"skills/a"}
        )

        assert main() == 1

        captured = capsys.readouterr()
        assert "requires 'skills/ghost' — no such resource" in captured.out
        assert "1 dangling/invalid requires entry(ies)" in captured.err
        assert "inspected" not in captured.out, "no success summary on a failing run"

    def test_malformed_manifest_still_reported(
        self, sandboxed_gate: Path, tmp_path: Path
    ) -> None:
        """Unparseable JSON yields the existing `not valid JSON` finding."""
        bad = tmp_path / "broken"
        bad.mkdir()
        manifest = bad / "claude-all.json"
        manifest.write_text("{not json", encoding="utf-8")

        findings = find_violations({"skills/a"}, [manifest])

        assert len(findings) == 1
        assert findings[0].startswith("broken/claude-all.json: not valid JSON")


class TestRealRepo:
    """The shipped tree itself: discovery must see manifests, and the gate is green."""

    def test_this_repo_discovers_manifests(self) -> None:
        """``find_manifests`` finds the manifests this repo actually ships."""
        manifests = find_manifests()

        assert manifests, (
            "this repo ships claude-all.json manifests — zero hits means discovery broke"
        )
        for manifest in manifests:
            assert manifest.name == "claude-all.json" or manifest.name.endswith(
                ".claude-all.json"
            )

    def test_this_repo_gate_passes_with_summary(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Against the real tree: exit 0 and the greppable inspected-count line."""
        assert main() == 0

        assert (
            "manifest(s) inspected — every `requires` entry resolves."
            in capsys.readouterr().out
        )
