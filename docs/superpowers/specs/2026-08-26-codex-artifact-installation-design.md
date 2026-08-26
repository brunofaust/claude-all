# Codex Artifact Installation Design

## Goal

Extend the existing `claude-all` command so every selected resource produces
both its current Claude Code installation and its equivalent Codex artifact,
without changing the Claude resource source or adding a second user-facing
command or target selector.

## User experience

`claude-all` remains the only command. Its existing interactive and
non-interactive selection flows keep their current arguments. For each selected
resource, it detects the locally installed `claude` and `codex` CLIs and
installs the Claude artifact, the Codex artifact, or both. When both are
available, dual-host installation is automatic and requires no selector or
second command. Status output identifies each host action and a missing CLI is
reported as a skipped host rather than an installer failure.

Existing recorded installs are Claude installs. New records identify their host
so update, prune, and uninstall only reverse the artifact they own.

## Resource compilation

The source tree stays Claude-first and is the only authored representation.

| Source resource | Claude output | Codex output |
| --- | --- | --- |
| Skill directory | `.claude/skills/<name>` symlink | `.agents/skills/<name>` symlink |
| Agent Markdown | `.claude/agents/<name>.md` symlink | `.codex/agents/<name>.toml` generated from front matter and body |
| `claude_md.md` companion | tagged `CLAUDE.md` block | tagged `AGENTS.md` block |
| Hook script + metadata | `.claude/hooks` symlink and `settings.json` entry | `.codex/hooks` symlink and `hooks.json` entry |
| MCP JSON | `claude mcp add` registration | Codex MCP registration/configuration |
| Tool JSON | one global tool installation | same global tool installation |

No Claude agent Markdown is modified. Codex agent TOML is regenerated on every
install/update and is never used as an input source.

## Agent transformation

The transformer reads the existing YAML front matter and Markdown body. It
requires a name and description; the body becomes `developer_instructions`.
Claude model aliases map to Codex model and effort as follows:

| Claude model | Codex model | Reasoning effort |
| --- | --- | --- |
| `claude-haiku-4-5` | `gpt-5.6-luna` | `medium` |
| `claude-sonnet-5` | `gpt-5.6-terra` | `high` |
| an Opus alias | `gpt-5.6-sol` | `high` |

An unknown Claude model is an install error with the source path and value; it
must not silently receive an arbitrary Codex model. The existing `tools` front
matter is retained in the instruction text as behavioral context, because
Codex custom-agent files do not use Claude's tool-list schema; actual tool and
permission availability continues to inherit from the parent Codex session.

## Hooks

Hook policy code remains shared where possible. The installer creates a Codex
registration from the existing `hook.json` metadata, translating timeout
milliseconds to whole seconds with a non-zero minimum. Events already shared by
both products (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`,
`PreCompact`, and `PostCompact`) retain their names.

The hook runtime receives a small host adapter. It normalizes input fields used
by existing hooks and emits Claude's structured output when invoked by Claude,
or Codex's supported structured output when invoked by Codex. It does not
weaken a guard's blocking decision. The generated Codex entry goes into
`.codex/hooks.json`; installer-owned commands can be replaced and removed
without changing any hand-authored hook block. Users must review the hook in
Codex's `/hooks` UI before Codex will run it.

## MCPs, tools, and plugins

MCP JSON stays shared metadata. Codex supports `codex mcp add` and persists
MCPs in its `config.toml`, so the installer uses the Codex CLI with the same
command, environment, argument, keychain, and scope rules currently used for
Claude. Tools are global and run their existing installation path only once.

The repository currently contains no `src/claude_all/plugins/*/plugin.json`
files. The plugin implementation nonetheless extends the plugin JSON schema
with explicit `claude` and `codex` installation objects. A future plugin must
declare its native catalog identifier and installation method for each host.
When both local CLIs are present, the installer runs both declared native
installations automatically. The installer does not infer that a Claude
marketplace entry exists in Codex; an undeclared host is reported as unsupported
for that plugin rather than pretending it installed successfully.

## Compatibility and verification

- Existing Claude command syntax, files, model aliases, settings entries, and
  state records remain compatible.
- Generated Codex agent TOML is parsed in tests and includes the approved model
  mapping.
- Tests cover user and project destinations, tagged `AGENTS.md` injection,
  hook JSON merge/removal and timeout conversion, MCP command construction,
  host-aware install state, and safe uninstall/prune behavior.
- README and architecture documentation describe the transparent dual-host
  installation and Codex hook-trust step.
