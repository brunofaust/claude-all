# Codex Artifact Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `claude-all` install every selected resource into each locally
available Claude Code and Codex host without changing Claude-authored sources.

**Architecture:** Keep resource discovery and selection unchanged. Add a small
host abstraction that dispatches each install, update, prune, and uninstall
operation to Claude and/or Codex. Claude artifacts keep their present formats;
Codex artifacts are generated or registered from the same source metadata.

**Tech Stack:** Python 3.11 standard library, pytest, JSON, TOML generation by
the installer, Claude Code CLI, Codex CLI.

**Spec:** `docs/superpowers/specs/2026-08-26-codex-artifact-installation-design.md`

## Global Constraints

- Keep the existing `claude-all` executable and arguments; do not add a target
  selector or a `codex-all` command.
- Detect `claude` and `codex` with `shutil.which`; install to every available
  host and report unavailable hosts without failing the available one.
- Never modify the existing Claude agent Markdown or `model:` aliases.
- Generated Codex agents use `.codex/agents/<name>.toml` and map Haiku to
  `gpt-5.6-luna`/medium, Sonnet to `gpt-5.6-terra`/high, and Opus to
  `gpt-5.6-sol`/high.
- Preserve all user-authored `AGENTS.md`, `hooks.json`, and `config.toml`
  content. Remove only installer-recorded artifacts.
- Claude and Codex must have separate, host-aware install records; legacy
  records represent existing Claude installs.

**User decisions (already made):** Keep one transparent `claude-all` command;
install for Claude and Codex automatically; preserve the Claude agent model;
map Opus-class agents to Sol; define host-native plugin installation metadata;
do not install the CLIs themselves.

---

### Task 1: Add host and state primitives

**Goal:** Represent installed hosts and make the state file distinguish Claude
from Codex without invalidating existing records.

**Files:**
- Modify: `src/claude_all/cli.py`
- Test: `tests/test_dual_host_install.py`

**Acceptance Criteria:**
- [ ] `available_hosts()` returns Claude and/or Codex based on executable
  discovery.
- [ ] Existing state records load as Claude records.
- [ ] New state keys and footprints include their host, so same-named resource
  artifacts do not collide.

**Verify:** `uv run pytest tests/test_dual_host_install.py -q` → PASS.

**Steps:**

- [ ] Write failing tests that monkeypatch `shutil.which` and assert the exact
  detected host set for Claude-only, Codex-only, both, and neither; write a
  legacy state fixture and assert it normalizes to Claude.
- [ ] Run `uv run pytest tests/test_dual_host_install.py -q` and confirm the
  tests fail because the host APIs and migration behavior do not exist.
- [ ] Add the minimal `Host` representation, availability detection, and
  state-record normalization. Keep existing callers defaulted to Claude while
  subsequent tasks move them to explicit hosts.
- [ ] Re-run the targeted tests and commit the passing change with
  `feat(installer): add host-aware installation state`.

### Task 2: Generate and manage Codex agent and instruction artifacts

**Goal:** Convert a Claude agent source into a valid Codex TOML agent and inject
its instruction companions into `AGENTS.md`.

**Files:**
- Modify: `src/claude_all/cli.py`
- Test: `tests/test_codex_artifacts.py`

**Acceptance Criteria:**
- [ ] Generated TOML has `name`, `description`, `model`,
  `model_reasoning_effort`, and `developer_instructions`.
- [ ] All three model mappings work; an unknown model fails with its source
  path and value.
- [ ] Claude Markdown source is unchanged.
- [ ] Installation and uninstall replace/remove only its tagged `AGENTS.md`
  block.

**Verify:** `uv run pytest tests/test_codex_artifacts.py -q` → PASS.

**Steps:**

- [ ] Write failing tests using one temporary Haiku agent, one Sonnet agent,
  one Opus agent, and an unsupported agent; parse generated TOML with
  `tomllib.loads` and assert the mapping and unmodified source text.
- [ ] Add a failing instruction test that seeds hand-written `AGENTS.md` text,
  installs a companion, uninstalls it, and asserts only the tagged block went
  away.
- [ ] Run the focused test file and confirm each failure is from a missing
  renderer or Codex instruction target.
- [ ] Implement front-matter parsing, TOML string serialization, Codex agent
  destination selection, and host-specific tagged-document helpers.
- [ ] Re-run the focused tests and commit with
  `feat(installer): generate codex agents and instructions`.

### Task 3: Install Codex skills, hooks, and MCPs

**Goal:** Produce safe Codex equivalents for compatible resource artifacts.

**Files:**
- Modify: `src/claude_all/cli.py`
- Modify: `src/claude_all/hooks/*.py` only where a normalized host adapter is
  required
- Test: `tests/test_codex_artifacts.py`

**Acceptance Criteria:**
- [ ] Skills symlink into `.agents/skills` for Codex.
- [ ] Hooks symlink into `.codex/hooks`, merge their command into
  `.codex/hooks.json`, and convert milliseconds to positive seconds.
- [ ] Reinstall replaces only the managed Codex hook command; uninstall removes
  only its own command and symlink.
- [ ] Codex MCP installation invokes `codex mcp add` using the current shared
  command/env/keychain behavior and requested scope.

**Verify:** `uv run pytest tests/test_codex_artifacts.py tests/test_leftovers.py -q` → PASS.

**Steps:**

- [ ] Write failing tests for a skill symlink target, a preserved foreign hook
  entry plus a managed hook entry, timeout conversion of `2000` milliseconds to
  `2` seconds, and a mocked `codex mcp add` command.
- [ ] Run the focused tests and confirm failures identify missing Codex paths,
  hook merging, and MCP dispatch.
- [ ] Implement Codex hook-file merge/purge/remove helpers, reusing the
  installer footprint model. Adapt only normalized hook input/output helpers;
  do not duplicate policy logic.
- [ ] Extend MCP dispatch so the existing metadata produces a Claude command
  and a Codex command for each available host.
- [ ] Re-run the focused tests and commit with
  `feat(installer): install codex skills hooks and mcps`.

### Task 4: Add dual-host plugins and wire full installation lifecycle

**Goal:** Make normal selection, update, prune, and uninstall drive all
available hosts and support explicit host-native plugin configurations.

**Files:**
- Modify: `src/claude_all/cli.py`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Test: `tests/test_dual_host_install.py`

**Acceptance Criteria:**
- [ ] One selected item installs into both available hosts without new CLI
  arguments.
- [ ] A plugin JSON may contain explicit `claude` and `codex` configuration;
  the correct native install operation runs for each declared available host.
- [ ] A host absent from a plugin declaration is reported unsupported, not
  falsely recorded installed.
- [ ] Update, prune, and uninstall only reverse artifacts owned by their host.
- [ ] Documentation states Codex hook trust and the Codex plugin-browser
  limitation where a plugin cannot be non-interactively installed.

**Verify:** `uv run pytest tests/test_dual_host_install.py tests/test_uninstall.py tests/test_dependency_resolution.py -q` → PASS.

**Steps:**

- [ ] Write failing lifecycle tests with mocked Claude/Codex executables and
  subprocess calls, including a plugin with two declared host configurations
  and a plugin unsupported on Codex.
- [ ] Run the tests and confirm they fail because the existing single-host
  dispatcher and plugin schema cannot satisfy them.
- [ ] Implement the top-level dual-host dispatcher and explicit plugin schema.
  Use documented non-interactive commands only where Codex supports them;
  otherwise return an actionable `/plugins` message and do not create state.
- [ ] Update README and architecture documentation with the one-command flow,
  generated artifacts, plugin metadata, and Codex hook review requirement.
- [ ] Re-run targeted tests and commit with
  `feat(installer): install resources for codex automatically`.

### Task 5: Verify source compatibility and full repository gates

**Goal:** Prove the implementation adds Codex output without regressing the
existing Claude package.

**Files:**
- Modify only files required to resolve verified failures.

**Acceptance Criteria:**
- [ ] The full pytest suite passes.
- [ ] `prek run --all-files` passes.
- [ ] A dry, isolated installation with both executable paths mocked produces
  both Claude and Codex artifacts and leaves hand-authored content intact.
- [ ] No unrelated untracked workspace content is included in changes.

**Verify:** `uv run pytest -q && prek run --all-files` → PASS.

**Steps:**

- [ ] Run `uv run pytest -q` and fix only failures caused by the dual-host
  implementation.
- [ ] Run `prek run --all-files`; address each reported issue and repeat until
  it passes.
- [ ] Inspect `git diff --check`, `git diff -- docs src tests README.md
  ARCHITECTURE.md pyproject.toml`, and `git status --short`; verify untracked
  `.agents/`, `.claude/`, `.codex/`, and root `AGENTS.md` are not staged.
- [ ] Commit verified fixes, if any, with a Conventional Commit message.

## Self-review

- Spec coverage: Tasks 1–4 cover host detection/state, agents/instructions,
  skills/hooks/MCPs, plugins/full lifecycle, and documentation. Task 5 covers
  regression gates and workspace isolation.
- Placeholder scan: no deferred implementation placeholders remain; the plan
  names the exact commands, files, artifacts, mappings, and error behavior.
- Type consistency: all tasks use the same host-aware installer model and do
  not introduce a second command or target selector.
