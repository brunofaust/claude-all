"""Codex artifacts generated from the Claude-authored resource source."""

from __future__ import annotations

import json
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claude_all import cli

# Migration contract from e94af8e: shrinking instructions must not delete their owners.
PRE_COMPACTION_INSTRUCTION_IDENTITIES = {
    "agents/aws-events-scheduler",
    "agents/aws-lambda-deployer",
    "agents/bug-hunter",
    "agents/cloudformation-deployer",
    "agents/cloudformation-reviewer",
    "agents/cloudwatch-inspector",
    "agents/code-quality",
    "agents/cost-audit-runner",
    "agents/cost-explorer",
    "agents/docker-log-inspector",
    "agents/docker-runner",
    "agents/dynamodb-inspector",
    "agents/dynamodb-mutator",
    "agents/e2e-scenario-runner",
    "agents/ecr-manager",
    "agents/ecs-inspector",
    "agents/email-inspector",
    "agents/friction-analyzer",
    "agents/frontend-builder",
    "agents/gh-runner",
    "agents/git-audit",
    "agents/git-cleanup",
    "agents/git-committer",
    "agents/git-runner",
    "agents/http-runner",
    "agents/iam-auditor",
    "agents/incident-responder",
    "agents/lint-fixer",
    "agents/migration-reviewer",
    "agents/postgres-query",
    "agents/python-deps",
    "agents/python-module-migrator",
    "agents/rds-postgres-query",
    "agents/repo-cleaner",
    "agents/s3-inspector",
    "agents/secrets-fetcher",
    "agents/seo-reviewer",
    "agents/seo-runner",
    "agents/sqs-monitor",
    "agents/step-functions-tracer",
    "agents/terraform-deployer",
    "agents/terraform-reviewer",
    "agents/test-author",
    "agents/test-runner",
    "instructions/agent-era-rules",
    "instructions/bash-safety",
    "instructions/commit-cadence",
    "instructions/delegate_search",
    "instructions/response-style",
    "instructions/secrets-in-shell",
    "instructions/tool-dispatch",
    "instructions/worktree-isolation",
    "skills/adversarial-verification",
    "skills/alembic-migration",
    "skills/aws-architecture",
    "skills/aws-cost-optimization",
    "skills/brunofaust-frontend-style",
    "skills/brunofaust-python-style",
    "skills/code-review-discipline",
    "skills/merge-main",
    "skills/prek",
    "skills/research-before-build",
    "skills/self-rationalization-guard",
    "skills/seo",
    "skills/ship-pr",
    "skills/subagent-prompting",
    "skills/verification-loop",
    "tools/rtk",
}

INVALID_HOOK_DOCUMENTS = [
    pytest.param({"hooks": []}, id="hooks-is-not-an-object"),
    pytest.param(
        {"hooks": {"PreToolUse": {}}},
        id="event-blocks-is-not-a-list",
    ),
    pytest.param(
        {"hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": {}}]}},
        id="hook-entries-is-not-a-list",
    ),
    pytest.param(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Edit",
                        "hooks": [{"type": "command", "command": ["foreign"]}],
                    }
                ]
            }
        },
        id="hook-command-is-not-a-string",
    ),
]


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


@pytest.mark.parametrize("claude_model", ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"])
def test_render_codex_agent_omits_model_configuration(tmp_path: Path, claude_model: str) -> None:
    """Claude model aliases do not constrain the generated Codex TOML.

    Args:
        tmp_path: Isolated filesystem fixture.
        claude_model: Authored Claude model alias.
    """
    source = agent_source(tmp_path, claude_model)
    original = source.read_text(encoding="utf-8")

    rendered = cli.render_codex_agent(source)

    parsed = tomllib.loads(rendered)
    assert parsed["name"] == "sample-agent"
    assert parsed["description"] == "Sample agent for conversion tests."
    assert "model" not in parsed
    assert "model_reasoning_effort" not in parsed
    assert "Do the narrow task" in parsed["developer_instructions"]
    assert source.read_text(encoding="utf-8") == original


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


@pytest.fixture
def shipped_instruction_snippets() -> list[tuple[cli.Item, Path]]:
    """Discover the real instruction catalog, rejecting empty companion content."""
    items = cli.discover([])
    assert items, "Resource discovery returned an empty catalog"
    snippets = []
    for item in items:
        snippet = cli.claude_md_snippet_path(item)
        if snippet is not None:
            assert snippet.read_text(encoding="utf-8").strip(), f"Empty snippet: {snippet}"
            snippets.append((item, snippet))
    assert snippets, "No shipped instruction companions were discovered"
    identities = {f"{item.kind}/{item.name}" for item, _ in snippets}
    missing = PRE_COMPACTION_INSTRUCTION_IDENTITIES - identities
    assert not missing, f"Instruction compaction dropped original owners: {sorted(missing)}"
    return snippets


def test_shipped_instruction_catalog_stays_within_root_context_budget(
    tmp_path: Path, shipped_instruction_snippets: list[tuple[cli.Item, Path]]
) -> None:
    """Bound rendered instructions including ownership markers, not just body text.

    Args:
        tmp_path: Isolated instruction destination.
        shipped_instruction_snippets: Nonempty real resource companions.
    """
    target = tmp_path / "CLAUDE.md"
    for item, snippet in shipped_instruction_snippets:
        cli.inject_tagged_block(target, item, snippet)

    # Leave room for personal rules within the approved 70% file-size reduction.
    rendered_bytes = len(target.read_bytes())
    assert rendered_bytes <= 14_500, f"Managed instruction catalog uses {rendered_bytes} bytes"


def test_both_hosts_share_symlinked_instructions_without_growth_or_content_loss(
    tmp_path: Path, shipped_instruction_snippets: list[tuple[cli.Item, Path]]
) -> None:
    """Reinstalling both hosts preserves shared-file ownership and unmanaged text.

    Args:
        tmp_path: Isolated user home and installer state.
        shipped_instruction_snippets: Nonempty real resource companions.
    """
    claude = tmp_path / ".claude" / "CLAUDE.md"
    agents = tmp_path / ".codex" / "AGENTS.md"
    claude.parent.mkdir()
    agents.parent.mkdir()
    personal = "# Personal rules\n\nKeep café names unchanged.\n"
    foreign = (
        "\n<!-- another-tool:rules:start -->\nKeep this too.\n<!-- another-tool:rules:end -->\n"
    )
    original = personal + foreign
    claude.write_text(original, encoding="utf-8")
    agents.symlink_to(Path("../.claude/CLAUDE.md"))
    original_link = agents.readlink()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        patch.setattr(cli, "STATE_DIR", tmp_path / ".claude-all")
        patch.setattr(cli, "STATE_FILE", tmp_path / ".claude-all" / "state.json")
        for item, _ in shipped_instruction_snippets:
            cli.inject_claude_md(item, "user")
            cli.inject_agents_md(item, "user")
        installed = claude.read_bytes()
        for item, _ in shipped_instruction_snippets:
            cli.inject_claude_md(item, "user")
            cli.inject_agents_md(item, "user")

    assert agents.is_symlink() and agents.readlink() == original_link
    assert agents.resolve() == claude
    assert agents.read_bytes() == claude.read_bytes() == installed
    rendered = installed.decode("utf-8")
    assert rendered.startswith(original)
    for item, snippet in shipped_instruction_snippets:
        start, end = cli.snippet_tags(item)
        assert rendered.count(start) == rendered.count(end) == 1
        assert f"{start}\n{snippet.read_text(encoding='utf-8').rstrip()}\n{end}" in rendered


def test_merge_codex_hook_preserves_foreign_entry_and_timeout_seconds(
    tmp_path: Path,
) -> None:
    """Managed wiring preserves foreign hooks and host-native timeout seconds.

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

    cli.merge_codex_hook(hooks_file, "PreToolUse", "Bash", "managed.py", 2)

    hooks = json.loads(hooks_file.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    commands = [hook["command"] for block in hooks for hook in block["hooks"]]
    managed = next(
        hook for block in hooks for hook in block["hooks"] if hook["command"] == "managed.py"
    )
    assert commands == ["foreign", "managed.py"]
    assert managed["timeout"] == 2


def test_merge_codex_hook_rejects_malformed_json_without_overwriting(tmp_path: Path) -> None:
    """A malformed foreign Codex config remains byte-for-byte untouched.

    Args:
        tmp_path: Isolated filesystem fixture.
    """
    hooks_file = tmp_path / "hooks.json"
    original = '{"hooks": '
    hooks_file.write_text(original, encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        cli.merge_codex_hook(hooks_file, "PreToolUse", "Bash", "managed.py", 2)

    assert hooks_file.read_text(encoding="utf-8") == original


def test_hook_metadata_uses_host_native_timeout_seconds() -> None:
    """Every Claude-authored hook timeout is a practical seconds value."""
    manifest = json.loads((cli.REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    metadata_paths = sorted(cli.REPO_ROOT.glob("skills/**/hook.json"))
    timeouts = [metadata["timeout"] for metadata in manifest.values() if isinstance(metadata, dict)]
    timeouts.extend(
        json.loads(path.read_text(encoding="utf-8"))["timeout"] for path in metadata_paths
    )

    assert timeouts
    assert all(1 <= timeout <= 600 for timeout in timeouts)


def test_install_codex_hook_preserves_malformed_config_before_linking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex hook installation aborts before mutation when hooks.json is malformed.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    hooks_file = tmp_path / ".codex" / "hooks.json"
    hooks_file.parent.mkdir(parents=True)
    original = '{"hooks": '
    hooks_file.write_text(original, encoding="utf-8")
    item = next(item for item in cli.discover(["mock-spec-guard"]) if item.kind == "hooks")

    message = cli.install_codex_hook(item, "project")

    assert message is not None and "invalid" in message
    assert hooks_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".codex" / "hooks" / "hooks-mock-spec-guard.py").exists()


@pytest.mark.parametrize("hook_name", ["config-protection", "worktree-isolation-guard"])
def test_codex_skips_claude_approval_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hook_name: str
) -> None:
    """Claude approval hooks are not installed where Codex cannot honor ``ask``.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path isolation.
        hook_name: Standalone approval hook under test.
    """
    monkeypatch.chdir(tmp_path)
    item = next(item for item in cli.discover([hook_name]) if item.kind == "hooks")

    message = cli.install_codex_hook(item, "project")

    assert message is not None and "Claude-only approval hook" in message
    assert not (tmp_path / ".codex" / "hooks" / f"hooks-{hook_name}.py").exists()
    assert not (tmp_path / ".codex" / "hooks.json").exists()


def test_codex_skip_removes_previously_installed_approval_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upgrade removes old fail-open Codex wiring while preserving foreign hooks.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    item = next(item for item in cli.discover(["config-protection"]) if item.kind == "hooks")
    destination = tmp_path / ".codex" / "hooks" / "hooks-config-protection.py"
    destination.parent.mkdir(parents=True)
    destination.symlink_to(item.src)
    hooks_file = tmp_path / ".codex" / "hooks.json"
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write|MultiEdit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(destination),
                                    "timeout": 2,
                                },
                                {"type": "command", "command": "foreign.py", "timeout": 2},
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    cli.record_install(item.kind, item.name, None, host="claude", scope="project")
    cli.record_install(item.kind, item.name, destination, host="codex", scope="project")
    cli.record_artifact(
        item.kind,
        item.name,
        {"type": "symlink", "path": str(destination)},
        host="codex",
        scope="project",
    )
    cli.record_artifact(
        item.kind,
        item.name,
        {"type": "codex_hook", "file": str(hooks_file), "command": str(destination)},
        host="codex",
        scope="project",
    )

    message = cli.install_codex_hook(item, "project")

    assert message is not None and "removed legacy Codex wiring" in message
    assert not destination.exists()
    document = json.loads(hooks_file.read_text(encoding="utf-8"))
    commands = [
        hook["command"] for block in document["hooks"]["PreToolUse"] for hook in block["hooks"]
    ]
    assert commands == ["foreign.py"]
    hosts = cli.load_state()["installs"]["hooks/config-protection"]["scopes"]["project"]["hosts"]
    assert set(hosts) == {"claude"}


def test_codex_skip_preserves_repointed_hook_while_removing_managed_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup forgets stale wiring without deleting a repointed hook link.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    item = next(item for item in cli.discover(["config-protection"]) if item.kind == "hooks")
    destination = tmp_path / ".codex" / "hooks" / "hooks-config-protection.py"
    destination.parent.mkdir(parents=True)
    foreign_source = tmp_path / "foreign-hook.py"
    foreign_source.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    destination.symlink_to(item.src)
    hooks_file = tmp_path / ".codex" / "hooks.json"
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write|MultiEdit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(destination),
                                    "timeout": 2,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    cli.record_install(item.kind, item.name, None, host="claude", scope="project")
    cli.record_install(item.kind, item.name, destination, host="codex", scope="project")
    cli.record_artifact(
        item.kind,
        item.name,
        {"type": "symlink", "path": str(destination)},
        host="codex",
        scope="project",
    )
    cli.record_artifact(
        item.kind,
        item.name,
        {"type": "codex_hook", "file": str(hooks_file), "command": str(destination)},
        host="codex",
        scope="project",
    )
    destination.unlink()
    destination.symlink_to(foreign_source)

    cli.install_codex_hook(item, "project")

    assert destination.is_symlink()
    assert destination.resolve() == foreign_source.resolve()
    assert str(destination) not in hooks_file.read_text(encoding="utf-8")
    hosts = cli.load_state()["installs"]["hooks/config-protection"]["scopes"]["project"]["hosts"]
    assert set(hosts) == {"claude"}


def test_agent_cleanup_preserves_repointed_generated_file_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent cleanup forgets stale state without deleting a repointed link.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    destination = tmp_path / ".codex" / "agents" / "demo.toml"
    destination.parent.mkdir(parents=True)
    managed_source = tmp_path / "managed-demo.toml"
    managed_source.write_text('name = "managed"\n', encoding="utf-8")
    destination.symlink_to(managed_source)
    cli.record_install("agents", "demo", destination, host="codex", scope="project")
    cli.record_artifact(
        "agents",
        "demo",
        {"type": "generated_file", "path": str(destination)},
        host="codex",
        scope="project",
    )
    foreign_source = tmp_path / "foreign-demo.toml"
    foreign_source.write_text('name = "foreign"\n', encoding="utf-8")
    destination.unlink()
    destination.symlink_to(foreign_source)

    cli.remove_install_host("agents", "demo", "project", "codex")

    assert destination.is_symlink()
    assert destination.resolve() == foreign_source.resolve()
    assert foreign_source.read_text(encoding="utf-8") == 'name = "foreign"\n'
    assert "agents/demo" not in cli.load_state()["installs"]


def test_agent_cleanup_removes_unchanged_installer_managed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent cleanup removes its unchanged direct TOML file.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    source = agent_source(tmp_path / "source", "claude-haiku-4-5")
    item = cli.Item("agents", "test", "demo", source)

    cli.install_codex_item(item, "project")
    destination = tmp_path / ".codex" / "agents" / "demo.toml"
    assert destination.is_file() and not destination.is_symlink()

    cli.remove_install_host("agents", "demo", "project", "codex")

    assert not destination.is_symlink()
    assert not destination.exists()
    assert "agents/demo" not in cli.load_state()["installs"]


def test_agent_cleanup_preserves_a_user_modified_installer_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uninstall retains a generated TOML after the user changes its content.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    item = cli.Item("agents", "test", "demo", agent_source(tmp_path / "source", "claude-haiku-4-5"))

    cli.install_codex_item(item, "project")
    destination = tmp_path / ".codex" / "agents" / "demo.toml"
    destination.write_text('name = "user-modified"\n', encoding="utf-8")

    cli.remove_install_host("agents", "demo", "project", "codex")

    assert destination.read_text(encoding="utf-8") == 'name = "user-modified"\n'


@pytest.mark.parametrize("document", INVALID_HOOK_DOCUMENTS)
def test_install_codex_hook_rejects_invalid_nested_shapes_before_linking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: object
) -> None:
    """Structurally invalid Codex hook configs remain untouched.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
        document: Invalid but syntactically valid hook configuration.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    hooks_file = tmp_path / ".codex" / "hooks.json"
    hooks_file.parent.mkdir(parents=True)
    original = json.dumps(document)
    hooks_file.write_text(original, encoding="utf-8")
    item = next(item for item in cli.discover(["mock-spec-guard"]) if item.kind == "hooks")

    message = cli.install_codex_hook(item, "project")

    assert message is not None and "invalid hooks.json" in message
    assert hooks_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".codex" / "hooks" / "hooks-mock-spec-guard.py").exists()


def test_inject_hook_preserves_malformed_claude_settings_before_linking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion-hook installation leaves malformed Claude settings untouched.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    source = tmp_path / "source" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Demo\n", encoding="utf-8")
    (source.parent / "hook.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (source.parent / "hook.json").write_text(
        json.dumps({"event": "PreToolUse", "matcher": "Edit", "timeout": 2}),
        encoding="utf-8",
    )
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    original = '{"hooks": '
    settings_file.write_text(original, encoding="utf-8")
    item = cli.Item("skills", "test", "demo", source)

    message = cli.inject_hook(item, "project")

    assert message is not None and "invalid settings.json" in message
    assert settings_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".claude" / "hooks" / "skills-demo.py").exists()


def test_install_standalone_hook_preserves_malformed_claude_settings_before_linking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Standalone-hook installation leaves malformed Claude settings untouched.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    original = '{"hooks": '
    settings_file.write_text(original, encoding="utf-8")
    item = next(item for item in cli.discover(["mock-spec-guard"]) if item.kind == "hooks")

    message = cli.install_standalone_hook(item, "project")

    assert "invalid settings.json" in message
    assert settings_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".claude" / "hooks" / "mock-spec-guard.py").exists()


@pytest.mark.parametrize("document", INVALID_HOOK_DOCUMENTS)
def test_inject_hook_rejects_invalid_nested_shapes_before_linking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: object
) -> None:
    """Companion hooks reject invalid nested Claude settings before mutation.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
        document: Invalid but syntactically valid hook configuration.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    source = tmp_path / "source" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Demo\n", encoding="utf-8")
    (source.parent / "hook.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (source.parent / "hook.json").write_text(
        json.dumps({"event": "PreToolUse", "matcher": "Edit", "timeout": 2}),
        encoding="utf-8",
    )
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    original = json.dumps(document)
    settings_file.write_text(original, encoding="utf-8")
    item = cli.Item("skills", "test", "demo", source)

    message = cli.inject_hook(item, "project")

    assert message is not None and "invalid settings.json" in message
    assert settings_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".claude" / "hooks" / "skills-demo.py").exists()


@pytest.mark.parametrize("document", INVALID_HOOK_DOCUMENTS)
def test_install_standalone_hook_rejects_invalid_nested_shapes_before_linking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: object
) -> None:
    """Standalone hooks reject invalid nested Claude settings before mutation.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
        document: Invalid but syntactically valid hook configuration.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    original = json.dumps(document)
    settings_file.write_text(original, encoding="utf-8")
    item = next(item for item in cli.discover(["mock-spec-guard"]) if item.kind == "hooks")

    message = cli.install_standalone_hook(item, "project")

    assert "invalid settings.json" in message
    assert settings_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".claude" / "hooks" / "mock-spec-guard.py").exists()


def test_install_codex_postgres_mcp_resolves_keychain_at_launch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Codex registers Postgres with a runtime Keychain launcher and setup guidance.

    Args:
        monkeypatch: Pytest fixture for subprocess and state isolation.
        capsys: Pytest fixture for installer output inspection.
    """
    item = next(item for item in cli.discover(["postgres"]) if item.kind == "mcps")
    commands: list[list[str]] = []

    def run(command: list[str], *, check: bool) -> None:
        """Capture the MCP registration command without launching Codex.

        Args:
            command: Registration command that would be executed.
            check: Whether subprocess failures would raise.
        """
        assert check
        commands.append(command)

    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(cli, "record_install", lambda *args, **kwargs: None)

    cli.install_codex_mcp(item, "user")

    expected_shell = (
        "exec 'npx' '-y' '@modelcontextprotocol/server-postgres' "
        '"$(security find-generic-password -a "$USER" -s "POSTGRES_URL" -w)"'
    )
    assert commands == [
        [
            "codex",
            "mcp",
            "add",
            "postgres",
            "--",
            "sh",
            "-c",
            expected_shell,
        ]
    ]
    output = capsys.readouterr().out
    assert "Store the connection URL in macOS Keychain, then re-install this MCP" in output
    assert 'security add-generic-password -U -a "$USER" -s "POSTGRES_URL" -w' in output


@pytest.mark.parametrize(
    ("canonical_name", "legacy_directory"),
    [
        ("vercel-react-best-practices", "react-best-practices"),
        ("vercel-composition-patterns", "composition-patterns"),
        ("vercel-react-view-transitions", "react-view-transitions"),
    ],
)
def test_discover_selects_vendored_skills_by_claude_frontmatter_name(
    canonical_name: str, legacy_directory: str
) -> None:
    """Claude frontmatter names drive identity while legacy filters remain accepted.

    Args:
        canonical_name: Claude-authored skill name.
        legacy_directory: Historical resource directory and filter alias.
    """
    canonical = [item for item in cli.discover([canonical_name]) if item.kind == "skills"]
    legacy = [item for item in cli.discover([legacy_directory]) if item.kind == "skills"]

    assert [(item.name, item.src.parent.name) for item in canonical] == [
        (canonical_name, legacy_directory)
    ]
    assert [item.name for item in legacy] == [canonical_name]


def test_discover_rejects_invalid_skill_frontmatter_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude frontmatter cannot create an unsafe installer identity.

    Args:
        tmp_path: Isolated resource tree.
        monkeypatch: Pytest fixture for replacing the resource root.
    """
    source = tmp_path / "skills" / "test" / "demo" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\nname: ../../victim\n---\n# Demo\n", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError, match="invalid Claude skill name"):
        cli.discover([])


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize(
    "bad_name",
    [
        pytest.param(None, id="absolute-path"),
        pytest.param("../../victim", id="parent-traversal"),
        pytest.param("nested/name", id="forward-slash"),
        pytest.param(r"nested\name", id="backslash"),
        pytest.param("Bad_Name", id="invalid-characters"),
        pytest.param("a" * 65, id="over-64-characters"),
    ],
)
def test_skill_install_rejects_unsafe_name_before_both_host_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    bad_name: str | None,
) -> None:
    """Both installers fail closed before using an unsafe name as a path.

    Args:
        tmp_path: Isolated host roots.
        monkeypatch: Pytest fixture for path and state isolation.
        host: Installer host under test.
        bad_name: Unsafe canonical identity, or None for an absolute path.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    source = tmp_path / "source" / "SKILL.md"
    source.parent.mkdir()
    source.write_text("# Demo\n", encoding="utf-8")
    outside = tmp_path / "victim"
    name = str(outside) if bad_name is None else bad_name
    item = cli.Item("skills", "test", name, source)

    message = (
        cli.install_claude_item(item, tmp_path / ".claude")
        if host == "claude"
        else cli.install_codex_item(item, "project")
    )

    assert "invalid Claude skill name" in message
    assert not outside.exists()
    assert not cli.STATE_FILE.exists()


@pytest.mark.parametrize(
    ("host", "reserved_name"),
    [
        pytest.param("claude", "claude-hooks", id="claude-host-claude-reserved"),
        pytest.param("claude", "anthropic-tools", id="claude-host-anthropic-reserved"),
        pytest.param("codex", "claude-hooks", id="codex-host-claude-reserved"),
        pytest.param("codex", "anthropic-tools", id="codex-host-anthropic-reserved"),
    ],
)
def test_skill_install_rejects_reserved_name_before_host_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
    reserved_name: str,
) -> None:
    """Both installers reject Claude-reserved canonical-name substrings.

    Args:
        tmp_path: Isolated host roots.
        monkeypatch: Pytest fixture for path and state isolation.
        host: Installer host under test.
        reserved_name: Canonical identity containing a reserved substring.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    source = tmp_path / "source" / "SKILL.md"
    source.parent.mkdir()
    source.write_text("# Demo\n", encoding="utf-8")
    item = cli.Item("skills", "test", reserved_name, source)

    message = (
        cli.install_claude_item(item, tmp_path / ".claude")
        if host == "claude"
        else cli.install_codex_item(item, "project")
    )

    assert "invalid Claude skill name" in message
    assert not (tmp_path / ".claude" / "skills" / reserved_name).exists()
    assert not (tmp_path / ".agents" / "skills" / reserved_name).exists()
    assert not cli.STATE_FILE.exists()


@pytest.mark.parametrize("occupant", ["directory", "file", "foreign-symlink"])
def test_install_claude_skill_preserves_unowned_canonical_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, occupant: str
) -> None:
    """Claude installation never replaces an unowned canonical destination.

    Args:
        tmp_path: Isolated host root.
        monkeypatch: Pytest fixture for path and state isolation.
        occupant: Existing user-owned destination shape.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    source = tmp_path / "source" / "SKILL.md"
    source.parent.mkdir()
    source.write_text("# Demo\n", encoding="utf-8")
    item = cli.Item("skills", "test", "safe-demo", source)
    destination = tmp_path / ".claude" / "skills" / item.name
    destination.parent.mkdir(parents=True)
    foreign_source = tmp_path / "foreign-skill"
    if occupant == "directory":
        destination.mkdir()
        (destination / "sentinel.txt").write_text("user-owned\n", encoding="utf-8")
    elif occupant == "file":
        destination.write_text("user-owned\n", encoding="utf-8")
    else:
        foreign_source.mkdir()
        destination.symlink_to(foreign_source)

    message = cli.install_claude_item(item, tmp_path / ".claude")

    assert "destination is user-owned" in message
    if occupant == "directory":
        assert not destination.is_symlink()
        assert (destination / "sentinel.txt").read_text(encoding="utf-8") == "user-owned\n"
    elif occupant == "file":
        assert not destination.is_symlink()
        assert destination.read_text(encoding="utf-8") == "user-owned\n"
    else:
        assert destination.is_symlink()
        assert destination.resolve() == foreign_source.resolve()
    assert not cli.STATE_FILE.exists()


def test_canonical_skill_install_migrates_legacy_host_records_and_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reinstalling a renamed skill replaces both hosts' legacy footprints safely.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path, executable, and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    item = next(
        item for item in cli.discover(["vercel-composition-patterns"]) if item.kind == "skills"
    )
    legacy_name = "composition-patterns"
    old_claude = tmp_path / ".claude" / "skills" / legacy_name
    old_codex = tmp_path / ".agents" / "skills" / legacy_name
    old_claude.parent.mkdir(parents=True)
    old_codex.parent.mkdir(parents=True)
    old_claude.symlink_to(item.src.parent)
    old_codex.symlink_to(item.src.parent)
    cli.record_install("skills", legacy_name, old_claude, host="claude", scope="project")
    cli.record_install("skills", legacy_name, old_codex, host="codex", scope="project")

    cli.install_claude_item(item, tmp_path / ".claude")
    cli.install_codex_item(item, "project")

    assert not old_claude.exists()
    assert not old_codex.exists()
    assert (tmp_path / ".claude" / "skills" / item.name).is_symlink()
    assert (tmp_path / ".agents" / "skills" / item.name).is_symlink()
    installs = cli.load_state()["installs"]
    assert "skills/composition-patterns" not in installs
    assert set(installs[f"skills/{item.name}"]["scopes"]["project"]["hosts"]) == {
        "claude",
        "codex",
    }


def test_legacy_skill_migration_preserves_repointed_link_while_removing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy cleanup forgets stale state without deleting a repointed link.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    item = next(
        item for item in cli.discover(["vercel-composition-patterns"]) if item.kind == "skills"
    )
    skill_root = tmp_path / ".agents" / "skills"
    legacy_destination = skill_root / "composition-patterns"
    legacy_destination.parent.mkdir(parents=True)
    foreign_source = tmp_path / "foreign-skill"
    foreign_source.mkdir()
    legacy_destination.symlink_to(item.src.parent)
    cli.record_install(
        "skills",
        "composition-patterns",
        legacy_destination,
        host="codex",
        scope="project",
    )
    legacy_destination.unlink()
    legacy_destination.symlink_to(foreign_source)

    cli.migrate_legacy_skill_host(item, "project", "codex", skill_root)

    assert legacy_destination.is_symlink()
    assert legacy_destination.resolve() == foreign_source.resolve()
    assert "skills/composition-patterns" not in cli.load_state()["installs"]


def test_full_claude_skill_install_preserves_legacy_footprint_on_invalid_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed hook preflight leaves the complete legacy Claude install unchanged.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    item = next(
        item for item in cli.discover(["vercel-react-best-practices"]) if item.kind == "skills"
    )
    legacy_name = "react-best-practices"
    legacy_skill = tmp_path / ".claude" / "skills" / legacy_name
    legacy_hook = tmp_path / ".claude" / "hooks" / f"skills-{legacy_name}.py"
    legacy_skill.parent.mkdir(parents=True)
    legacy_hook.parent.mkdir(parents=True)
    legacy_skill.symlink_to(item.src.parent)
    legacy_hook.symlink_to(item.src.parent / "hook.py")
    settings_file = tmp_path / ".claude" / "settings.json"
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {"type": "command", "command": str(legacy_hook), "timeout": 2},
                        {"type": "command", "command": ["foreign"]},
                    ],
                }
            ]
        }
    }
    settings_file.write_text(json.dumps(settings), encoding="utf-8")
    cli.record_install("skills", legacy_name, legacy_skill, host="claude", scope="project")
    cli.record_artifact(
        "skills",
        legacy_name,
        {"type": "symlink", "path": str(legacy_hook)},
        host="claude",
        scope="project",
    )
    cli.record_artifact(
        "skills",
        legacy_name,
        {"type": "settings_hook", "file": str(settings_file), "command": str(legacy_hook)},
        host="claude",
        scope="project",
    )
    original_state = cli.STATE_FILE.read_text(encoding="utf-8")
    original_settings = settings_file.read_text(encoding="utf-8")

    message = cli.install_claude_item(item, tmp_path / ".claude")

    assert "invalid settings.json" in message
    assert legacy_skill.is_symlink()
    assert legacy_hook.is_symlink()
    assert not (tmp_path / ".claude" / "skills" / item.name).exists()
    assert settings_file.read_text(encoding="utf-8") == original_settings
    assert cli.STATE_FILE.read_text(encoding="utf-8") == original_state


def test_full_codex_skill_install_preserves_legacy_footprint_on_invalid_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed hook preflight leaves the complete legacy Codex install unchanged.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "state" / "state.json")
    item = next(
        item for item in cli.discover(["vercel-react-best-practices"]) if item.kind == "skills"
    )
    legacy_name = "react-best-practices"
    legacy_skill = tmp_path / ".agents" / "skills" / legacy_name
    legacy_hook = tmp_path / ".codex" / "hooks" / f"skills-{legacy_name}.py"
    legacy_skill.parent.mkdir(parents=True)
    legacy_hook.parent.mkdir(parents=True)
    legacy_skill.symlink_to(item.src.parent)
    legacy_hook.symlink_to(item.src.parent / "hook.py")
    hooks_file = tmp_path / ".codex" / "hooks.json"
    hooks = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {"type": "command", "command": str(legacy_hook), "timeout": 2},
                        {"type": "command", "command": ["foreign"]},
                    ],
                }
            ]
        }
    }
    hooks_file.write_text(json.dumps(hooks), encoding="utf-8")
    cli.record_install("skills", legacy_name, legacy_skill, host="codex", scope="project")
    cli.record_artifact(
        "skills",
        legacy_name,
        {"type": "symlink", "path": str(legacy_hook)},
        host="codex",
        scope="project",
    )
    cli.record_artifact(
        "skills",
        legacy_name,
        {"type": "codex_hook", "file": str(hooks_file), "command": str(legacy_hook)},
        host="codex",
        scope="project",
    )
    original_state = cli.STATE_FILE.read_text(encoding="utf-8")
    original_hooks = hooks_file.read_text(encoding="utf-8")

    message = cli.install_codex_item(item, "project")

    assert "invalid hooks.json" in message
    assert legacy_skill.is_symlink()
    assert legacy_hook.is_symlink()
    assert not (tmp_path / ".agents" / "skills" / item.name).exists()
    assert hooks_file.read_text(encoding="utf-8") == original_hooks
    assert cli.STATE_FILE.read_text(encoding="utf-8") == original_state


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

    with pytest.MonkeyPatch.context() as hosts:
        hosts.setattr(
            cli.shutil,
            "which",
            {"claude": "/test-bin/claude", "codex": "/test-bin/codex"}.get,
        )
        cli.install_item(item, tmp_path / ".claude")

    assert (tmp_path / ".claude" / "agents" / "sample-agent.md").is_symlink()
    generated = tmp_path / ".codex" / "agents" / "sample-agent.toml"
    assert generated.is_file() and not generated.is_symlink()
    assert "model" not in tomllib.loads(generated.read_text(encoding="utf-8"))


def test_rebuild_codex_agents_renders_only_installed_agents_directly(
    tmp_path: Path, monkeypatch
) -> None:
    """A rebuild writes only already-installed agents into Codex's directory.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for global-path isolation.
    """
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path / "home")
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

    cli.record_install(
        "agents",
        "first-agent",
        tmp_path / "home" / ".codex" / "agents" / "first-agent.toml",
        host="codex",
        scope="user",
    )
    legacy_cache = tmp_path / "home" / ".claude-all" / "codex"
    legacy_cache.mkdir(parents=True)
    (legacy_cache / "manifest.json").write_text("{}\n", encoding="utf-8")
    agents = tmp_path / "home" / ".codex" / "agents"
    personal_agent = agents / "personal-agent.toml"
    personal_agent.parent.mkdir(parents=True, exist_ok=True)
    personal_agent.write_text('name = "personal-agent"\n', encoding="utf-8")
    assert cli.rebuild_codex_agents([first, second]) == 1
    assert (agents / "first-agent.toml").is_file()
    assert not (agents / "second-agent.toml").exists()
    assert not (agents / "first-agent.toml").is_symlink()
    assert personal_agent.read_text(encoding="utf-8") == 'name = "personal-agent"\n'
    assert not legacy_cache.exists()


def test_codex_skill_links_directly_to_its_compatible_source(tmp_path: Path, monkeypatch) -> None:
    """A SKILL.md directory needs no generated cache artifact.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for current-directory isolation.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    monkeypatch.setattr(cli, "STATE_FILE", tmp_path / "home" / ".claude-all" / "state.json")
    skill_source = tmp_path / "source" / "SKILL.md"
    skill_source.parent.mkdir(parents=True)
    skill_source.write_text("# Demo\n", encoding="utf-8")
    item = cli.Item("skills", "test", "demo", skill_source)

    cli.install_codex_item(item, "project")

    destination = tmp_path / ".agents" / "skills" / "demo"
    assert destination.is_symlink()
    assert destination.resolve() == skill_source.parent


def test_rebuild_preserves_legacy_cache_for_an_unmigrated_agent_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebuild never strands an agent source that is no longer shipped.

    Args:
        tmp_path: Isolated filesystem fixture.
        monkeypatch: Pytest fixture for path and state isolation.
    """
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    monkeypatch.setattr(
        cli,
        "STATE_FILE",
        tmp_path / "home" / ".claude-all" / "state.json",
    )
    legacy_cache = tmp_path / "home" / ".claude-all" / "codex"
    legacy_source = legacy_cache / "agents" / "retired-agent.toml"
    legacy_source.parent.mkdir(parents=True)
    legacy_source.write_text('name = "retired-agent"\n', encoding="utf-8")
    visible = tmp_path / "home" / ".codex" / "agents" / "retired-agent.toml"
    visible.parent.mkdir(parents=True)
    visible.symlink_to(legacy_source)

    assert cli.rebuild_codex_agents([]) == 0

    assert legacy_source.is_file()
    assert visible.is_symlink()
    assert visible.resolve() == legacy_source.resolve()


def test_rebuild_flag_generates_global_codex_agents(tmp_path: Path, monkeypatch) -> None:
    """The explicit rebuild command writes visible global Codex artifacts.

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
    monkeypatch.setattr(cli, "discover", lambda filters: [item])
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "home" / ".claude-all")
    monkeypatch.setattr(
        cli,
        "STATE_FILE",
        tmp_path / "home" / ".claude-all" / "state.json",
    )
    cli.record_install(
        "agents",
        "sample-agent",
        tmp_path / "home" / ".codex" / "agents" / "sample-agent.toml",
        host="codex",
        scope="user",
    )

    assert cli.main(["--rebuild"]) == 0
    destination = tmp_path / "home" / ".codex" / "agents" / "sample-agent.toml"
    assert destination.is_file() and not destination.is_symlink()


def test_rebuild_rejects_scope_flags() -> None:
    """The one managed cache cannot be narrowed to an installation scope."""
    with pytest.raises(SystemExit, match="2"):
        cli.main(["--rebuild", "--user"])


def test_version_flag_reports_installed_distribution_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI reports the version supplied by installed package metadata.

    Args:
        capsys: Captures the CLI's version output.
    """
    with pytest.raises(SystemExit) as exited:
        cli.main(["--version"])

    assert exited.value.code == 0
    assert capsys.readouterr().out == f"claude-all {version('claude-all')}\n"


def test_install_migrates_a_legacy_cache_symlink_to_a_direct_file(
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
    cache = tmp_path / "home" / ".claude-all" / "codex" / "agents"
    cache.mkdir(parents=True)
    legacy_source = cache / "sample-agent.toml"
    legacy_source.write_text(old_destination.read_text(encoding="utf-8"), encoding="utf-8")
    old_destination.unlink()
    old_destination.symlink_to(legacy_source)
    cli.install_codex_item(item, "project")

    assert old_destination.is_file() and not old_destination.is_symlink()
