"""Tests for the TUI "update all" action.

Update must refresh every recorded install at the scope it was installed in,
through the same guarded install path a fresh install uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claude_all import cli


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run inside a repository nested in a temp HOME with only Claude on PATH.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: fixture used to repoint HOME, cwd and module constants.

    Returns:
        The repository directory used as the working directory.
    """
    home_dir = tmp_path / "home"
    repo_dir = home_dir / "repo"
    repo_dir.mkdir(parents=True)
    state_dir = home_dir / ".claude-all"
    state_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.chdir(repo_dir)
    monkeypatch.setattr(cli, "USER_CLAUDE_DIR", home_dir / ".claude")
    monkeypatch.setattr(cli, "STATE_DIR", state_dir)
    monkeypatch.setattr(cli, "STATE_FILE", state_dir / "state.json")
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )
    return repo_dir


def agent_item(tmp_path: Path) -> cli.Item:
    """Build a minimal flat agent resource.

    Args:
        tmp_path: Directory that holds the agent source.

    Returns:
        The agent item.
    """
    source = tmp_path / "src" / "demo.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\nname: demo\ndescription: Demo agent.\nmodel: claude-haiku-5-5\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return cli.Item("agents", "test", "demo", source)


def test_update_refreshes_project_install_in_project_scope(
    tmp_path: Path,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A project install is refreshed in place, not reported as missing.

    Args:
        tmp_path: pytest's per-test temporary directory.
        repo: Working repository nested in HOME.
        monkeypatch: fixture used to stub repository discovery.
        capsys: fixture capturing the update report.
    """
    item = agent_item(tmp_path)
    cli.install_item(item, repo / ".claude")
    link = repo / ".claude" / "agents" / "demo.md"
    link.unlink()
    monkeypatch.setattr(cli, "discover", lambda filters: [item])

    cli.run_update_all()

    output = capsys.readouterr().out
    assert "missing target" not in output
    assert link.is_symlink()
    assert link.resolve() == item.src.resolve()
    entry = cli.load_state()["installs"][cli.state_key("agents", "demo")]
    assert set(entry["scopes"]) == {"project"}
    assert not (Path.home() / ".claude" / "agents" / "demo.md").exists()


def test_update_never_replaces_a_user_owned_file(
    tmp_path: Path,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real file at the recorded target survives an update.

    Args:
        tmp_path: pytest's per-test temporary directory.
        repo: Working repository nested in HOME.
        monkeypatch: fixture used to stub repository discovery.
    """
    item = agent_item(tmp_path)
    cli.install_item(item, repo / ".claude")
    link = repo / ".claude" / "agents" / "demo.md"
    link.unlink()
    link.write_text("mine\n", encoding="utf-8")
    monkeypatch.setattr(cli, "discover", lambda filters: [item])

    cli.run_update_all()

    assert not link.is_symlink()
    assert link.read_text(encoding="utf-8") == "mine\n"
