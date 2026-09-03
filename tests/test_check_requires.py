"""Tests for the ``check_requires.py`` prek gate.

Covers the gate contract: a clean run prints a single greppable summary line
with the inspected resource count, a zero-inspection run (discovery matched no
resources) fails hard instead of reporting green, and a genuine dangling
``requires`` entry still fails.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_requires


@pytest.fixture
def fake_src(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the gate at a synthetic resource tree; return the fake ``src`` root."""
    src = tmp_path / "src"
    monkeypatch.setattr(check_requires, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_requires, "SRC", src)
    return src


def write_manifest(src: Path, *rel_manifests: str, requires: list[str]) -> None:
    """Write a ``claude-all.json`` manifest under ``src`` with the given deps."""
    for rel in rel_manifests:
        parent = src / "claude_all" / Path(rel).parent
        parent.mkdir(parents=True, exist_ok=True)
        (parent / Path(rel).name).write_text(json.dumps({"requires": requires}))


class TestNormalSuccess:
    """A clean graph prints one greppable summary line with the inspected count."""

    def test_reports_inspected_count(self, fake_src: Path, capsys: pytest.CaptureFixture) -> None:
        """Two resources, one dependency, all resolving — summary counts 2."""
        write_manifest(
            fake_src,
            "skills/x/claude-all.json",
            "skills/y/claude-all.json",
            requires=[],
        )
        rc = check_requires.run({"skills/x", "skills/y"})
        assert rc == 0
        out = capsys.readouterr().out
        assert "inspected 2 resource(s)" in out
        assert out.count("\n") == 1, "expected exactly one summary line"

    def test_no_manifests_still_counts_known_resources(
        self, fake_src: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """No manifests on disk is fine as long as discovery found resources."""
        rc = check_requires.run({"skills/x"})
        assert rc == 0
        assert "inspected 1 resource(s)" in capsys.readouterr().out


class TestZeroDiscovery:
    """Discovery matching zero resources is a hard failure, never a green run."""

    def test_empty_known_set_exits_nonzero(
        self, fake_src: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """`run(set())` must return 1, name the scan, and print to stderr."""
        rc = check_requires.run(set())
        assert rc == 1
        err = capsys.readouterr().err
        assert "matched ZERO resources" in err
        assert "inspected" not in err

    def test_main_fails_when_discovery_finds_nothing(
        self, fake_src: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """`main()` routes an empty `load_resource_keys()` into a hard failure."""
        monkeypatch.setattr(check_requires, "load_resource_keys", lambda: set())
        assert check_requires.main() == 1
        assert "matched ZERO resources" in capsys.readouterr().err


class TestGenuineFailure:
    """A real dangling `requires` entry still fails with its original message."""

    def test_dangling_requires_fails(self, fake_src: Path, capsys: pytest.CaptureFixture) -> None:
        """A `requires` naming a missing resource fails and names the target."""
        write_manifest(fake_src, "skills/x/claude-all.json", requires=["skills/missing"])
        rc = check_requires.run({"skills/x"})
        assert rc == 1
        out = capsys.readouterr().out
        assert "skills/x" in out and "skills/missing" in out
        assert "inspected 1 resource(s)" not in out

    def test_malformed_manifest_fails(self, fake_src: Path, capsys: pytest.CaptureFixture) -> None:
        """A non-JSON manifest is still reported as invalid, not silently skipped."""
        parent = fake_src / "claude_all" / "skills" / "bad"
        parent.mkdir(parents=True)
        (parent / "claude-all.json").write_text("{not json")
        rc = check_requires.run({"skills/x"})
        assert rc == 1
        assert "not valid JSON" in capsys.readouterr().out
