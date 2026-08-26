"""Codex artifacts generated from the Claude-authored resource source."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claude_all import cli


def agent_source(tmp_path: Path, model: str) -> Path:
    """Create a minimal Claude agent source with the requested model alias.

    Args:
        tmp_path: Isolated filesystem fixture.
        model: Claude model alias to write into front matter.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "agent.md"
    source.write_text(
        "---\n"
        "name: sample-agent\n"
        "description: Sample agent for conversion tests.\n"
        f"model: {model}\n"
        "tools:\n"
        "  - Bash\n"
        "---\n\n"
        "Do the narrow task and report evidence.\n",
        encoding="utf-8",
    )
    return source


@pytest.mark.parametrize(
    ("claude_model", "codex_model", "effort"),
    [
        ("claude-haiku-4-5", "gpt-5.6-luna", "medium"),
        ("claude-sonnet-5", "gpt-5.6-terra", "high"),
        ("claude-opus-5", "gpt-5.6-sol", "high"),
    ],
)
def test_render_codex_agent_maps_claude_models(
    tmp_path: Path, claude_model: str, codex_model: str, effort: str
) -> None:
    """Claude aliases compile into valid, appropriately configured Codex TOML.

    Args:
        tmp_path: Isolated filesystem fixture.
        claude_model: Authored Claude model alias.
        codex_model: Expected generated Codex model.
        effort: Expected Codex reasoning effort.
    """
    source = agent_source(tmp_path, claude_model)
    original = source.read_text(encoding="utf-8")

    rendered = cli.render_codex_agent(source)

    parsed = tomllib.loads(rendered)
    assert parsed["name"] == "sample-agent"
    assert parsed["description"] == "Sample agent for conversion tests."
    assert parsed["model"] == codex_model
    assert parsed["model_reasoning_effort"] == effort
    assert "Do the narrow task" in parsed["developer_instructions"]
    assert source.read_text(encoding="utf-8") == original


def test_render_codex_agent_rejects_unknown_claude_model(tmp_path: Path) -> None:
    """An unreviewed model alias never receives a silent arbitrary mapping.

    Args:
        tmp_path: Isolated filesystem fixture.
    """
    source = agent_source(tmp_path, "claude-unknown-1")

    with pytest.raises(ValueError, match=r"claude-unknown-1.*agent\.md"):
        cli.render_codex_agent(source)


def test_render_codex_agent_emits_toml_safe_non_bmp_unicode(tmp_path: Path) -> None:
    """Agent instructions containing emoji remain valid TOML, not JSON surrogates.

    Args:
        tmp_path: Isolated filesystem fixture.
    """
    source = agent_source(tmp_path, "claude-haiku-4-5")
    source.write_text(
        source.read_text(encoding="utf-8") + "Keep calm 😁\n",
        encoding="utf-8",
    )

    rendered = cli.render_codex_agent(source)

    assert "\\ud83d" not in rendered
    assert tomllib.loads(rendered)["developer_instructions"].endswith("😁")


def test_inject_codex_agents_md_preserves_handwritten_content(tmp_path: Path, monkeypatch) -> None:
    """Uninstalling an owned Codex block does not disturb surrounding AGENTS.md text.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for current-directory isolation.
    """
    monkeypatch.chdir(tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Local rules\n\nKeep this.\n", encoding="utf-8")
    snippet = tmp_path / "claude_md.md"
    snippet.write_text("Use the installed resource.\n", encoding="utf-8")
    item = cli.Item("instructions", "test", "demo", snippet)

    cli.inject_agents_md(item, "project")
    assert cli.write_tagged_block(agents, item, None) == "removed"

    assert agents.read_text(encoding="utf-8") == "# Local rules\n\nKeep this.\n"


def test_merge_codex_hook_preserves_foreign_entry_and_converts_timeout(
    tmp_path: Path,
) -> None:
    """Managed wiring preserves foreign hooks and converts milliseconds to seconds.

    Args:
        tmp_path: Isolated filesystem fixture.
    """
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "foreign"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    cli.merge_codex_hook(hooks_file, "PreToolUse", "Bash", "managed.py", 2000)

    hooks = json.loads(hooks_file.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    commands = [hook["command"] for block in hooks for hook in block["hooks"]]
    managed = next(
        hook for block in hooks for hook in block["hooks"] if hook["command"] == "managed.py"
    )
    assert commands == ["foreign", "managed.py"]
    assert managed["timeout"] == 2


def test_install_item_creates_claude_and_codex_agent_artifacts(tmp_path: Path, monkeypatch) -> None:
    """One ordinary install produces host-native artifacts for both detected CLIs.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for global-path isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "USER_CLAUDE_DIR", tmp_path / "home" / ".claude")
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    monkeypatch.setattr(
        cli,
        "STATE_FILE",
        tmp_path / "home" / ".claude-all" / "state.json",
    )
    source = agent_source(tmp_path, "claude-haiku-4-5")
    item = cli.Item("agents", "test", "sample-agent", source)

    cli.install_item(item, tmp_path / ".claude")

    assert (tmp_path / ".claude" / "agents" / "sample-agent.md").is_symlink()
    generated = tmp_path / ".codex" / "agents" / "sample-agent.toml"
    assert generated.is_symlink()
    assert tomllib.loads(generated.read_text(encoding="utf-8"))["model"] == "gpt-5.6-luna"


def test_build_codex_cache_renders_all_agents_but_installs_only_selected_agent(
    tmp_path: Path, monkeypatch
) -> None:
    """The managed cache holds every render while Codex sees only selected resources.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for global-path isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    monkeypatch.setattr(
        cli,
        "STATE_FILE",
        tmp_path / "home" / ".claude-all" / "state.json",
    )
    first = cli.Item(
        "agents",
        "test",
        "first-agent",
        agent_source(tmp_path / "first", "claude-haiku-4-5"),
    )
    second = cli.Item(
        "agents",
        "test",
        "second-agent",
        agent_source(tmp_path / "second", "claude-sonnet-5"),
    )

    cli.build_codex_cache([first, second])
    cli.install_codex_item(first, "project")

    cache = tmp_path / "home" / ".claude-all" / "codex" / "agents"
    assert (
        tomllib.loads((cache / "first-agent.toml").read_text(encoding="utf-8"))["model"]
        == "gpt-5.6-luna"
    )
    assert (
        tomllib.loads((cache / "second-agent.toml").read_text(encoding="utf-8"))["model"]
        == "gpt-5.6-terra"
    )
    assert (tmp_path / ".codex" / "agents" / "first-agent.toml").is_symlink()
    assert not (tmp_path / ".codex" / "agents" / "second-agent.toml").exists()


def test_codex_cache_contains_only_generated_agents(tmp_path: Path, monkeypatch) -> None:
    """Instructions and compatible skills are installed directly, outside the cache.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for global-path isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    agent = cli.Item(
        "agents",
        "test",
        "sample-agent",
        agent_source(tmp_path / "agent", "claude-haiku-4-5"),
    )
    instruction = tmp_path / "instruction.md"
    instruction.write_text("Use local rules.\n", encoding="utf-8")

    cli.build_codex_cache([agent, cli.Item("instructions", "test", "demo", instruction)])

    cache = tmp_path / "home" / ".claude-all" / "codex"
    assert (cache / "agents" / "sample-agent.toml").is_file()
    assert not (cache / "instructions").exists()
    assert not (cache / "skills").exists()
    assert not (cache / "hooks").exists()


def test_codex_skill_links_directly_to_its_compatible_source(tmp_path: Path, monkeypatch) -> None:
    """A SKILL.md directory needs no generated cache artifact.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for current-directory isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    skill_source = tmp_path / "source" / "SKILL.md"
    skill_source.parent.mkdir(parents=True)
    skill_source.write_text("# Demo\n", encoding="utf-8")
    item = cli.Item("skills", "test", "demo", skill_source)

    cli.install_codex_item(item, "project")

    destination = tmp_path / ".agents" / "skills" / "demo"
    assert destination.is_symlink()
    assert destination.resolve() == skill_source.parent
    assert not (tmp_path / "home" / ".claude-all" / "codex" / "skills").exists()


def test_ensure_codex_cache_uses_a_source_fingerprint_to_skip_unchanged_builds(
    tmp_path: Path, monkeypatch
) -> None:
    """A content digest works for released and local editable installations alike.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for global-path isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    item = cli.Item(
        "agents",
        "test",
        "sample-agent",
        agent_source(tmp_path, "claude-haiku-4-5"),
    )

    assert cli.ensure_codex_cache([item]) is True
    assert cli.ensure_codex_cache([item]) is False

    item.src.write_text(
        item.src.read_text(encoding="utf-8") + "\nNew instruction.\n", encoding="utf-8"
    )

    assert cli.ensure_codex_cache([item]) is True


def test_rebuild_flag_rebuilds_only_the_managed_cache(tmp_path: Path, monkeypatch) -> None:
    """The explicit rebuild command creates no visible Codex artifacts.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for collaborators.
    """
    item = cli.Item(
        "agents",
        "test",
        "sample-agent",
        agent_source(tmp_path, "claude-haiku-4-5"),
    )
    seen: list[list[cli.Item]] = []
    monkeypatch.setattr(cli, "discover", lambda filters: [item])
    monkeypatch.setattr(
        cli,
        "ensure_codex_cache",
        lambda items: seen.append(items) or True,
    )

    assert cli.main(["--rebuild"]) == 0
    assert seen == [[item]]


def test_rebuild_rejects_scope_flags() -> None:
    """The one managed cache cannot be narrowed to an installation scope."""
    with pytest.raises(SystemExit, match="2"):
        cli.main(["--rebuild", "--user"])


def test_install_migrates_a_previous_generated_agent_to_a_cache_symlink(
    tmp_path: Path, monkeypatch
) -> None:
    """Installing the selected agent upgrades the previous generated layout safely.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for global-path isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    monkeypatch.setattr(
        cli,
        "STATE_FILE",
        tmp_path / "home" / ".claude-all" / "state.json",
    )
    item = cli.Item(
        "agents",
        "test",
        "sample-agent",
        agent_source(tmp_path, "claude-haiku-4-5"),
    )
    old_destination = tmp_path / ".codex" / "agents" / "sample-agent.toml"
    old_destination.parent.mkdir(parents=True)
    old_destination.write_text(
        cli.render_codex_agent(item.src, item.name),
        encoding="utf-8",
    )
    cli.ensure_codex_cache([item])
    cli.install_codex_item(item, "project")

    assert old_destination.is_symlink()
