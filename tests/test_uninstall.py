"""Tests for `claude-all --uninstall`.

This command deletes a user's entire setup, so the tests that matter are the ones
proving it removes what it claims AND — more importantly — that it refuses to
touch anything else: a path outside the install scope, a real file recorded where
a symlink was expected, a companion sub-record selected on its own, or a
tool/plugin whose real binary must survive.

Every destructive case is paired with the no-false-positive case, and the
confirmation path is tested both ways: declining must remove nothing at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claude_all import cli


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every install root and the state file into a temp HOME.

    The module reads `Path.home()` once at import, so the constants — not the
    env var — are what must be redirected.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: fixture used to repoint the module constants.
    """
    claude = tmp_path / ".claude"
    (claude / "skills").mkdir(parents=True)
    (claude / "hooks").mkdir(parents=True)
    state_dir = tmp_path / ".claude-all"
    state_dir.mkdir()
    monkeypatch.setattr(cli, "USER_CLAUDE_DIR", claude)
    monkeypatch.setattr(cli, "STATE_DIR", state_dir)
    monkeypatch.setattr(cli, "STATE_FILE", state_dir / "state.json")
    monkeypatch.setattr(cli, "scan_leftovers", lambda scope: ([], []))
    return tmp_path


def claude_md(home_dir: Path, body: str) -> Path:
    """Write a user CLAUDE.md and return its path.

    Args:
        home_dir: The temp home.
        body: File content.
    """
    path = home_dir / ".claude" / "CLAUDE.md"
    path.write_text(body, encoding="utf-8")
    return path


def install_record(home_dir: Path, *, kind: str = "skills", name: str = "demo") -> Path:
    """Create a realistic install: a symlink, a CLAUDE.md block, a state record.

    Args:
        home_dir: The temp home.
        kind: Resource kind to record.
        name: Resource name to record.

    Returns:
        The resource symlink path.
    """
    source = home_dir / "pkg" / name
    source.mkdir(parents=True, exist_ok=True)
    link = home_dir / ".claude" / "skills" / name
    link.symlink_to(source)

    start, end = (
        f"<!-- claude-all:{kind}/{name}:start -->",
        f"<!-- claude-all:{kind}/{name}:end -->",
    )
    md = claude_md(home_dir, f"# mine\n\nkeep me\n\n{start}\ninjected\n{end}\n")

    cli.record_install(kind, name, link)
    cli.record_artifact(
        kind, name, {"type": "claude_md", "file": str(md), "start": start, "end": end}
    )
    return link


def test_no_records_is_a_clean_noop(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """With nothing recorded the command reports so and exits 0.

    Args:
        home: The temp home fixture.
        capsys: Captures stdout.
    """
    assert cli.cmd_uninstall(filters=[], scope="user", assume_yes=True) == 0
    assert "Nothing to uninstall" in capsys.readouterr().out


def test_removes_symlink_and_claude_md_block(home: Path) -> None:
    """The recorded symlink goes, the injected block goes, hand-written text stays.

    Args:
        home: The temp home fixture.
    """
    link = install_record(home)
    md = home / ".claude" / "CLAUDE.md"

    assert cli.cmd_uninstall(filters=[], scope="user", assume_yes=True) == 0

    assert not link.is_symlink(), "resource symlink survived the uninstall"
    text = md.read_text(encoding="utf-8")
    assert "injected" not in text, "injected block survived"
    assert "keep me" in text, "hand-written CLAUDE.md content was destroyed"
    assert cli.load_state().get("installs") == {}


def test_removes_recorded_codex_agents_md_block(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uninstall strips only the managed AGENTS.md block recorded for a Codex item.

    Args:
        home: Isolated project directory.
        monkeypatch: Changes the project root to the isolated directory.
    """
    monkeypatch.chdir(home)
    agents_md = home / "AGENTS.md"
    start = "<!-- claude-all:agents/demo:start -->"
    end = "<!-- claude-all:agents/demo:end -->"
    agents_md.write_text(f"# Local rules\n\n{start}\nmanaged\n{end}\n", encoding="utf-8")
    cli.record_install("agents", "demo", home / ".codex" / "agents" / "demo.toml")
    cli.record_artifact(
        "agents",
        "demo",
        {"type": "claude_md", "file": str(agents_md), "start": start, "end": end},
    )

    assert cli.cmd_uninstall(filters=[], scope="project", assume_yes=True) == 0
    assert agents_md.read_text(encoding="utf-8") == "# Local rules\n"


def test_uninstall_removes_the_managed_codex_cache_only_after_the_last_install(
    home: Path,
) -> None:
    """A narrowed uninstall preserves the shared cache until no installs remain.

    Args:
        home: Isolated installer state directory.
    """
    install_record(home, name="first")
    install_record(home, name="second")
    cache = cli.codex_cache_root()
    cache.mkdir(parents=True)
    (cache / "manifest.json").write_text("{}\n", encoding="utf-8")

    assert cli.cmd_uninstall(filters=["first"], scope="user", assume_yes=True) == 0
    assert cache.exists()

    assert cli.cmd_uninstall(filters=["second"], scope="user", assume_yes=True) == 0
    assert not cache.exists()


def test_declining_removes_nothing(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Answering no leaves every artifact and the state record intact.

    Args:
        home: The temp home fixture.
        monkeypatch: used to force the confirmation to False.
    """
    link = install_record(home)
    monkeypatch.setattr(cli, "confirm", lambda prompt: False)

    assert cli.cmd_uninstall(filters=[], scope="user", assume_yes=False) == 1

    assert link.is_symlink(), "declining still removed the symlink"
    assert "injected" in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert cli.load_state()["installs"], "declining still dropped the state record"


def test_confirm_is_false_when_not_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A piped / CI invocation gets the safe answer, never an accidental wipe.

    Args:
        monkeypatch: used to simulate a non-TTY stdin.
    """
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cli.confirm("Proceed?") is False


def test_path_outside_install_scope_is_untouched(home: Path) -> None:
    """A record pointing outside the install roots is never followed.

    This is the guard that stopped a real incident: a copied state.json whose
    absolute paths pointed into a DIFFERENT home.

    Args:
        home: The temp home fixture.
    """
    outsider = home / "elsewhere" / "precious"
    outsider.parent.mkdir(parents=True)
    outsider.symlink_to(home / "pkg")
    cli.record_install("skills", "stray", outsider)

    assert cli.cmd_uninstall(filters=[], scope="user", assume_yes=True) == 0
    assert outsider.is_symlink(), "uninstall followed a path outside its own scope"


def test_real_file_recorded_as_target_is_never_deleted(home: Path) -> None:
    """Only symlinks are unlinked — a recorded real file survives.

    Args:
        home: The temp home fixture.
    """
    real = home / ".claude" / "skills" / "not-a-link.md"
    real.write_text("real file", encoding="utf-8")
    cli.record_install("skills", "not-a-link", real)

    assert cli.cmd_uninstall(filters=[], scope="user", assume_yes=True) == 0
    assert real.is_file(), "a recorded REAL file was deleted"


def test_companion_record_is_not_selected_alone(home: Path) -> None:
    """Companion sub-records ride their primary and are never primaries themselves.

    Args:
        home: The temp home fixture.
    """
    cli.record_install("skills", f"demo{cli.COMPANION_SUFFIX}", None)
    assert cli.all_install_records([]) == []


def test_tool_records_are_forgotten_not_uninstalled(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tools/plugins record is dropped, but its real binary is left alone.

    Args:
        home: The temp home fixture.
        capsys: Captures stdout.
    """
    cli.record_install("tools", "some-binary", None)

    assert cli.cmd_uninstall(filters=[], scope="user", assume_yes=True) == 0
    out = capsys.readouterr().out
    assert "binary left in place" in out
    assert cli.load_state().get("installs") == {}


def test_filters_narrow_the_selection(home: Path) -> None:
    """Only matching records are removed; the rest stay installed.

    Args:
        home: The temp home fixture.
    """
    keep = install_record(home, name="keeper")
    drop = install_record(home, name="dropme")

    assert cli.cmd_uninstall(filters=["dropme"], scope="user", assume_yes=True) == 0

    assert not drop.is_symlink(), "the filtered-in record was not removed"
    assert keep.is_symlink(), "a record outside the filter was removed"
    assert "skills/keeper" in cli.load_state()["installs"]


def test_project_uninstall_preserves_user_state(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project uninstall does not erase the same resource at user scope.

    Args:
        home: Isolated home-directory fixture.
        monkeypatch: Pytest fixture for current-directory isolation.
    """
    monkeypatch.chdir(home)
    user_link = home / ".claude" / "skills" / "demo"
    user_source = home / "user-source"
    user_source.mkdir()
    user_link.symlink_to(user_source)
    project_link = home / ".codex" / "agents" / "demo.toml"
    project_source = home / "project-source"
    project_source.mkdir()
    project_link.parent.mkdir(parents=True)
    project_link.symlink_to(project_source)
    cli.record_install("skills", "demo", user_link, host="claude", scope="user")
    cli.record_install("skills", "demo", project_link, host="codex", scope="project")

    assert cli.cmd_uninstall(filters=[], scope="project", assume_yes=True) == 0

    state = cli.load_state()["installs"]["skills/demo"]
    assert user_link.is_symlink()
    assert "user" in state["scopes"]
    assert "project" not in state["scopes"]


def test_state_file_survives_a_partial_uninstall(home: Path) -> None:
    """State is only deleted when nothing is recorded any more.

    Args:
        home: The temp home fixture.
    """
    install_record(home, name="keeper")
    install_record(home, name="dropme")

    cli.cmd_uninstall(filters=["dropme"], scope="user", assume_yes=True)
    assert cli.STATE_FILE.exists(), "state file removed while records remained"

    cli.cmd_uninstall(filters=[], scope="user", assume_yes=True)
    assert not cli.STATE_FILE.exists(), "state file kept after everything was removed"


def test_settings_hook_entry_is_dropped(home: Path) -> None:
    """A recorded settings.json hook entry is removed from the file.

    Args:
        home: The temp home fixture.
    """
    settings = home / ".claude" / "settings.json"
    command = str(home / ".claude" / "hooks" / "demo.py")
    settings.write_text(
        json.dumps(
            {"hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"command": command}]}]}}
        ),
        encoding="utf-8",
    )
    cli.record_install("hooks", "demo", None)
    cli.record_artifact(
        "hooks", "demo", {"type": "settings_hook", "file": str(settings), "command": command}
    )

    assert cli.cmd_uninstall(filters=[], scope="user", assume_yes=True) == 0
    assert command not in settings.read_text(encoding="utf-8")
