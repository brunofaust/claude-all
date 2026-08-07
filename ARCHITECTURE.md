# ARCHITECTURE.md

This document describes how `claude-all` is put together: what the repo is,
how its resources are laid out on disk, and how the installer turns that
layout into files inside `~/.claude/` or a project's `.claude/`. See
`CLAUDE.md` for contribution rules and `README.md` for the full catalog of
what currently ships.

## What this repo is

`claude-all` is a Python CLI (`claude_all.cli`, console script `claude-all`)
that installs Claude Code customizations — agents, skills, hooks, MCP
servers, standalone CLI tools, plugins, and standing instructions — into a
target project or the user's global `~/.claude/`. The repo itself is the
source catalog: every resource claude-all can install lives under
`src/claude_all/` as a file or folder, and the CLI's `discover()` function
walks that tree to find them. There is no runtime service — install-time
only; once installed, the resources run as ordinary Claude Code
agents/hooks/skills inside whatever project adopted them.

## Top-level layout

| Path | What it holds |
| --- | --- |
| `src/claude_all/cli.py` | The entire installer: resource discovery (`discover`), dependency-closure resolution (`resolve_closure`/`load_requires`), per-kind install functions (`install_item`, `install_mcp`, `install_tool`, `install_plugin`, `install_standalone_hook`), `~/.claude/CLAUDE.md` snippet injection (`inject_claude_md`/`strip_claude_md_block`), hook wiring into `settings.json` (`inject_hook`/`purge_hook_entries`), an interactive curses TUI (`TuiState`, `tui_select`), and an `--uninstall` path that reverses every recorded install via a local state file. |
| `src/claude_all/agents/<category>/` | Agent definitions, one per subagent, grouped into `aws/`, `databases/`, `generic/`, `python/`, `support/`, `web/`. A bare agent is a flat `<name>.md`; an agent that ships companion files (a `claude_md.md` snippet and/or a `hook.py`/`hook.json`) is a folder `<name>/agent.md` with those companions alongside it. |
| `src/claude_all/skills/<category>/<name>/SKILL.md` | Skill definitions, invoked via the Skill tool, grouped into `aws/`, `frontend/`, `generic/`, `python/`, `web/`. |
| `src/claude_all/hooks/` | Standalone hook scripts not tied to a specific agent/skill — safety guards and reminders (destructive-command blocking, secret-leak blocking, style guards, worktree isolation, etc.), wired via the manifest at `src/claude_all/hooks/hooks.json`. |
| `src/claude_all/instructions/<name>/claude_md.md` | Standalone rules injected straight into `~/.claude/CLAUDE.md` with no agent/skill attached (e.g. routing broad search to the `Explore` agent, bash-safety rules, commit cadence). |
| `src/claude_all/mcps/<name>/mcp.json` | MCP server definitions installed via `claude mcp add`. |
| `src/claude_all/tools/<name>/tool.json` | OS-level CLI tools installed outside `~/.claude/` (e.g. `rtk`, `code-review-graph`). |
| `src/claude_all/plugins/<name>/plugin.json` | Third-party plugins installed via `claude plugin install` or `pipx`, each declaring a `type` of `claude-marketplace` or `pip`. |
| `scripts/` | Standalone Python scripts, most of them prek gates run against this repo's own source (see below). |
| `tests/` | Pytest suite (`test_dependency_resolution.py`, `test_leftovers.py`, `test_md_links.py`) covering the installer's dependency-closure logic, leftover/orphan detection, and the README-link gate. |
| `hooks/` (repo root) | Empty — not to be confused with `src/claude_all/hooks/`, which holds the actual installable hook scripts. |
| `.claude/` | This repo's own Claude Code configuration: `.claude/skills/` (repo-scoped skills used *while working on* claude-all, not shipped by the installer — e.g. `vendored-sources`), `.claude/settings.json`, and worktree bookkeeping. Tracked in git, not ignored. |
| `.github/workflows/ci.yml` | Runs `prek run --all-files` on every PR to `main` (`SKIP=no-commit-to-branch` so CI itself isn't blocked by the branch-protection hook). |
| `.github/workflows/release.yml` | Drives the `python-semantic-release` release flow (see below). |
| `prek.toml` | The full pre-commit/prek hook chain — the project's single lint/quality gate (see "Gates" below). |
| `codecongruence.toml` | Config for the `codecongruence` semantic-drift hook run via prek. |
| `pyproject.toml` | Package metadata, `ruff`/`vulture`/`typos`/`markdownlint`/`semantic-release`/`commitizen` config. No runtime dependencies (`dependencies = []`) — the installer only touches the standard library plus dev-only `prek`/`pytest`. |
| `vendored.json` + `vulture_whitelist.py` | Vendored-resource manifest (see "Vendored resources" below) and vulture's allowlist of intentionally-unused names. |

## How the pieces relate

**Discovery.** `discover()` in `cli.py` walks `src/claude_all/{agents,skills,hooks,instructions,mcps,tools,plugins}` and builds an `Item` per resource, inferring its kind from which subtree it's in and its shape (flat file vs. folder with a companion file). This is the single source of truth the CLI, the TUI, and the prek gates all read from — nothing is hand-registered elsewhere.

**Installing.** Running `claude-all` opens an interactive picker (or, non-interactively, `claude-all --all --user|--project <filters>`) that installs the chosen items either user-wide (`~/.claude/`) or into the current project's `./.claude/`. Each kind has its own install function: agents/skills are copied or symlinked into place, `claude_md.md` companions are injected into the target `CLAUDE.md` as a tagged, idempotent block (`inject_claude_md`), hook companions are symlinked into `.claude/hooks/` and merged into `settings.json` (`inject_hook`), MCPs run through `claude mcp add`, and tools/plugins run their own install path (`install_tool`/`install_plugin`). A `--uninstall` pass reverses every recorded install via a local install-state file, including stripping injected `CLAUDE.md` blocks and `settings.json` entries.

**Dependencies between resources.** A resource can declare `requires` entries (in its `claude-all.json`) naming other resources it needs; `load_requires`/`resolve_closure` pull in the full transitive closure before installing. The `check-requires` prek hook (`scripts/check_requires.py`) fails the build if a `requires` entry doesn't resolve to a real resource.

**Companion hooks.** A skill or agent may ship a `hook.py` + `hook.json` beside its main file. `CLAUDE.md` documents two archetypes contributors must pick between: a *reminder* hook (fires once per session, addresses Claude via `additionalContext`, never blocks) and a *guard* hook (fires on every matching call, may exit 2 to hard-block a destructive action). The root-level `src/claude_all/hooks/` scripts are the standalone examples of both — most are `PreToolUse` guards/reminders, one (`prek-stop-runner.py`) is a `Stop` hook, one (`python-style-skill-loader.py`) is `SessionStart`.

**Vendored resources.** Some skills/agents (e.g. from Vercel's `agent-skills`, `humanink`) are copied from upstream repos rather than authored here. `vendored.json` tracks their source and is refreshed by `scripts/vendor_sync.py`. Vendored files must stay byte-identical to upstream — local additions go in sidecar files (`ATTRIBUTION.md`, `claude_md.md`, `hook.*`) rather than edits to the vendored file itself, and several prek hooks (whitespace fixers, `typos`) exclude the vendored directories to avoid drifting them from upstream.

## Gates (`scripts/` + `prek.toml`)

`prek run --all-files` is the single lint/quality entry point (mirrored in `.github/workflows/ci.yml`, which runs the same command on every PR). It chains a standard `pre-commit-hooks` set (JSON/TOML/YAML validation, whitespace/EOL fixers, large-file and merge-conflict checks, `no-commit-to-branch`) with several checks specific to this repo:

- `ruff-check` / `ruff-format` (Python lint + format, target `py311`), `mypy` (scoped to `cli.py`, `scripts/`, `src/claude_all/hooks/`, `src/claude_all/tools/` — skill-embedded `hook.py` files all share the module name `hook`, which mypy can't batch-check, so ruff + vulture cover those instead), `pyupgrade`, `typos`, `gitleaks`, and `pygrep-hooks` (blanket `# type: ignore`, mock-method mistakes, deprecated `log.warn`, comment-style type annotations).
- `vulture` (dead-code detection at `min_confidence = 60`, scoped to `cli.py`, `src/claude_all/hooks/`, `src/claude_all/skills/`, `vulture_whitelist.py`).
- `banned-project-names` — a `pygrep` local hook that fails if any real project name, ticket-prefix artifact, or stray tool-call XML tag leaks into `src/claude_all/{agents,skills,instructions}/`. This is the mechanical enforcement of the "always use generic placeholders" rule in `CLAUDE.md` — skills and agents here are shared tooling and must not encode one specific project's names or architecture.
- `check-requires` (`scripts/check_requires.py`) — every `claude-all.json` `requires` entry must resolve to a real resource.
- `check-md-links` (`scripts/check_md_links.py`) — every relative markdown link in the repo must resolve, and every discovered resource (agent/skill/hook/tool/MCP/instruction) must have a row in `README.md`. This is what makes `README.md` the enforced single source of truth for the catalog rather than aspirational documentation.
- `self-module-private` / `self-junk-drawer` — this repo ships regression-gate *checkers* as a skill (`src/claude_all/skills/generic/regression-gates/checkers/`) but historically never ran them on its own source; these two local hooks now run those checkers against `cli.py`/`scripts/`/`src/claude_all/` to enforce the "no module-level `_name`s" and "no junk-drawer module" rules this repo itself publishes.
- `codecongruence` — a semantic-drift check (external hook, config in `codecongruence.toml`).
- `commitizen` (commit-msg stage) — enforces Conventional Commits on every commit message.
- `uv-lock` (pre-push stage) — keeps `uv.lock` in step with `pyproject.toml`; deferred to pre-push because it rewrites a file and a mutating hook shouldn't fail the commit it mutates.

## Conventions a contributor must respect

- **Where a new resource goes.** Bare agent → `src/claude_all/agents/<category>/<name>.md`. Agent with companions → folder `src/claude_all/agents/<category>/<name>/agent.md`. Skill → `src/claude_all/skills/<category>/<name>/SKILL.md`. Standalone `CLAUDE.md`-only rule with no agent/skill attached → `src/claude_all/instructions/<name>/claude_md.md`.
- **README is gated, not just requested.** `check-md-links` fails the build if a new resource has no matching README row — adding a resource without updating `README.md` does not pass CI.
- **Generic placeholders only** in skill/agent/instruction body copy — no real project, company, or ticket-prefix names (`CLAUDE.md` gives the approved placeholder table); enforced by `banned-project-names`.
- **Conventional Commits** on every commit (`commitizen`, commit-msg stage) — `type(scope): summary`, feeding `python-semantic-release`'s version bump.
- **No hand-maintained changelog.** Release notes are generated entirely from commit/PR history by `python-semantic-release` when a `release/x.y.z` branch merges to `main`; there is deliberately no `CHANGELOG.md` to hand-edit or merge-conflict over.
- **Vendored files stay byte-identical to upstream.** Local changes to a vendored resource go in a sidecar file, never a direct edit to the vendored content, and are tracked in `vendored.json`.
