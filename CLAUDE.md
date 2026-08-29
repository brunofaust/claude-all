# claude-all — contribution guidelines

`claude-all` is the single installer command for both Claude Code and Codex.
It detects the locally available host CLIs; it never installs either CLI.

## Commands

```bash
# Install an agent or skill into every available host (positional args are path filters)
claude-all --all --user <name>     # ~/.claude, ~/.codex, and ~/.agents/skills
claude-all --all --project <name>  # ./.claude, ./.codex, and ./.agents/skills
claude-all --rebuild               # regenerate installed Codex agent TOMLs

# Remove installs
claude-all --prune                 # only what the repo no longer ships
claude-all --uninstall             # EVERYTHING recorded — shows a plan, then asks
claude-all --uninstall <name>      # narrow it with the same path filters
claude-all --uninstall --yes       # skip the prompt (non-interactive)

# Dev setup (editable install + installs prek)
uv sync --dev
# then run the dev build with: uv run claude-all

# Lint (single entry point — runs ruff, mypy, typos)
prek run --all-files
```

### `--rebuild`

`claude-all --rebuild` regenerates the Codex agents that this installer already
records as installed, directly in `~/.codex/agents`. It has no project scope and
does not enable unselected agents.

### Codex agent discovery compatibility

**Tested 2026-08-29 with Codex CLI 0.151.0:** Codex discovers a regular
`~/.codex/agents/<name>.toml` file, but skips an individual TOML symlink even
when its target is readable (`0644`). Do not symlink generated agent files to
an installer cache. Generate regular files directly in the existing agents
directory, preserving any user-owned agents there. A directory-level symlink
also loaded in this version, but must not be used because it would hide or
replace unrelated user agents.

## Commits and releases

Commits must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

[optional body]

[optional footer(s)]
```

Common types and their version impact:

| Type                                               | Impact     | When to use             |
| --------------------------------------------------- | ---------- | ----------------------- |
| `feat`                                             | minor bump | new user-facing feature |
| `fix`                                              | patch bump | bug fix                 |
| `perf`                                             | patch bump | performance improvement |
| `feat!` / `BREAKING CHANGE`                        | major bump | breaking API change     |
| `chore`, `docs`, `refactor`, `test`, `build`, `ci` | no bump    | maintenance             |

The `commitizen` prek hook validates the format on every commit. If your
commit message is rejected, rewrite it with `git commit --amend`.

Releases are triggered by merging a `release/` branch into `main` (same setup as
`brunofaust/codecongruence`):

1. Merge feature PRs to `main` normally — no release is created.
1. When ready to release, create a branch named `release/x.y.z` off `main`
    (no content changes required) and open a PR to `main`.
1. Merging that PR triggers `python-semantic-release`, which reads all
    conventional commits since the last tag, bumps `pyproject.toml`,
    and creates a GitHub release + git tag with auto-generated notes.

**Do not bump the version manually** — the release process derives the version and
release notes entirely from Conventional Commits history, so there is no changelog
file to hand-edit.

There is no `CHANGELOG.md` — a hand-maintained changelog was a merge-conflict magnet
across every parallel PR. Release notes are generated from commit/PR history instead.

## Repo structure

| Path                                                     | Purpose                                                                                                                       |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `src/claude_all/cli.py`                                 | CLI installer — discovers and installs agents/skills/hooks; console script `claude-all`                                       |
| `src/claude_all/agents/<category>/<name>.md`           | Flat agent definition (no companions) — dispatched by the router                                                              |
| `src/claude_all/agents/<category>/<name>/agent.md`     | Folder agent (ships companions) — `agent.md` + `claude_md.md` and/or `hook.py`/`hook.json` grouped in one dir                  |
| `src/claude_all/agents/<category>/<name>.claude_md.md` | Companion snippet injected into Claude `CLAUDE.md` and Codex `AGENTS.md` on install (folder agents put it at `<name>/claude_md.md`) |
| `src/claude_all/skills/<category>/<name>/SKILL.md`     | Skill definitions (invoked via Skill tool)                                                                                    |
| `src/claude_all/instructions/<name>/claude_md.md`      | Standalone Claude `CLAUDE.md` and Codex `AGENTS.md` snippet (no agent/skill to install — e.g. dispatch rules for built-in agents like `Explore`) |
| `src/claude_all/hooks/`                                 | Standalone hook scripts — installable kind, wired per the `hooks/hooks.json` manifest                                          |
| `.claude/hooks/`                                         | Active hooks for this repo's Claude sessions                                                                                  |
| `.claude/agents/`                                        | Sub-agent definitions scoped to this repo                                                                                     |
| `.claude/skills/`                                        | Skills scoped to this repo (used when working ON claude-all, NOT shipped via the installer) — e.g. `vendored-sources`. `.claude/` is tracked in this repo (not git-ignored). |
| `.codex/agents/`                                         | Generated TOML sub-agent definitions scoped to this repo                                                                      |
| `.codex/hooks.json`                                      | Codex hook registrations scoped to this repo                                                                                  |
| `.agents/skills/`                                        | Codex-compatible skills scoped to this repo                                                                                   |

## Adding a new agent or skill

**Agent:**

1. Bare agent → flat file `src/claude_all/agents/<category>/<name>.md`. Agent that ships
   companions → folder `src/claude_all/agents/<category>/<name>/agent.md` (keep `agent.md` +
   its `claude_md.md` / `hook.*` together)
1. Optionally add a `claude_md.md` snippet — flat: `<name>.claude_md.md` beside the
   `.md`; folder: `<name>/claude_md.md` beside `agent.md`
1. Run `claude-all --all --user <name>` to activate
1. **Update `README.md`** — add a row to the relevant agent table (§ 1.x)

**Skill:**

1. Create `src/claude_all/skills/<category>/<name>/SKILL.md`
1. Optionally add a companion `hook.py` + `hook.json` (see § *Authoring companion hooks*) and/or a `claude_md.md` snippet beside `SKILL.md`
1. Run `claude-all --all --user <name>` to activate
1. **Update `README.md`** — add a row to the relevant skill table (§ 2.x)

## Authoring companion hooks (reminder vs guard)

A skill or agent may ship a `hook.py` + `hook.json` beside its main file
(`SKILL.md` / folder-agent `agent.md`; a flat agent uses prefixed siblings
`<name>.hook.{py,json}`). On install the script is symlinked into
`.claude/hooks/` for Claude and into Codex's hook configuration when supported.
The hosts have different hook input/output contracts, so a Codex hook must use an
adapter rather than assuming Claude hook output is portable. There are **two archetypes** —
pick ONE and obey its firing rule:

| Archetype          | Purpose                                                                                                          | Fires                                                              | Channel                                                                  |
| ------------------ | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **Reminder**       | Surface a skill's conventions when a relevant file/command appears (orientation, not enforcement)                | **Once per session** — dedup via a `/tmp` flag keyed by `session_id` | exit 0 + JSON `additionalContext` (addressed to **Claude**)             |
| **Guard / utility** | Safety check or bookkeeping that must evaluate *every* occurrence (`destructive-command-guard`, `supply-chain-guard`, `edited-files-accumulator`) | **Every matching call** — no dedup                                | exit 2 to BLOCK (PreToolUse), or `additionalContext` / stderr per intent |

### Reminder-hook rules (the common case)

1. **Fire once per session.** Flag at
   `tempfile.gettempdir()/claude-all-<slug>-<session_id>.flag`; if it exists,
   `return 0` silently. Write best-effort under `contextlib.suppress(OSError)`
   (unwritable FS → skip the dedup, never crash). Hooks can't share a session —
   the flag is the only state. (Want "once ever, across sessions"? Use a
   persistent path under `~/.claude-all/` instead of `tempfile` — but per-session
   is the default; reach for once-ever only when explicitly asked.)
2. **Address Claude, not the user.** Emit
   `{"hookSpecificOutput": {"hookEventName": "<event>", "additionalContext": "…"}}`
   to **stdout** and `return 0`. NEVER use exit-1 / stderr for a Claude-facing
   reminder — stderr is shown to the **USER** as a hook error, never to Claude.
3. **Never break a turn.** Malformed stdin, wrong file type, or any unexpected
   error → `return 0`. A reminder hook must be invisible when it has nothing to say.
4. **Match narrowly + bail early.** `Edit|Write` + a file-extension / path check,
   or `Bash` + a command regex. `return 0` early on `node_modules` / `dist` /
   vendored paths and on non-matching commands.
5. **Don't stack overlapping reminders.** Before adding a reminder whose matcher
   overlaps an existing one (e.g. a second `*.tsx` Edit hook), confirm it won't
   pile multiple reminders onto a single edit.

### Guard-hook rule

A guard fires on **every** matching call by design — deduping it would defeat the
safety / bookkeeping purpose. Reserve exit 2 (hard block) for genuinely
destructive or irreversible actions, and give an explicit override (env var or
`# guard:allow` comment) as an escape hatch.

### `hook.json` schema

```json
{"event": "PreToolUse", "matcher": "Edit|Write", "timeout": 2000}
```

`matcher` is a tool-name regex (`Bash` for command hooks, empty `""` for all
tools). `timeout` is milliseconds. Keep the script executable; the installer also
sets the bit.

## Before raising a PR

Always update **`README.md`** to reflect any additions or changes:

- New agent → row in the correct § 1.x table
- New skill → row in the correct § 2.x table
- New hook → row in § 3
- New plugin → row in § 4
- New MCP → row in § 5
- New tool → row in § 6 "Installed tools" table
- Changed schema / installer behaviour → update the relevant schema block in § 4–6

The README is the single source of truth for what's in the repo. A PR without a README update is incomplete.

**This is gated, not just asked for.** The `check-md-links` prek hook fails when a discovered
resource has no README row, and when any relative markdown link doesn't resolve. Each row links the
resource name to its source file (`SKILL.md` / `agent.md` / hook script) — keep that shape when
adding one, since the link is what the coverage check looks for.

## Naming conventions — always use generic placeholders

All examples, agent prompts, skill documentation, and config snippets must use
fictional, generic names. Never embed real project names, company names, domain
names, or internal tool names from any specific codebase.

### Approved placeholder names

| Category            | Use these                                  |
| ------------------- | ------------------------------------------ |
| Project / app       | `myapp`, `my-service`, `my-project`        |
| Company / org       | `mycompany`, `Acme Inc`, `acme`            |
| Domain              | `example.com`, `acme.example.com`          |
| AWS resource prefix | `myapp-dev-`, `myapp-prod-`                |
| GitHub repo         | `myorg/myapp`, `brunofaust/myapp`          |
| Ticket prefix       | `TICK-`, `APP-`                            |
| DB / secret path    | `myapp/dev/db-credentials`                 |
| Lambda functions    | `myapp-dev-dispatcher`, `myapp-dev-worker` |
| DynamoDB tables     | `myapp-dev-tickets`, `myapp-dev-run-locks` |
| Docker images       | `myapp:latest`                             |
| Python modules      | `src/myapp/handlers/`                      |
| Secret values       | `••••••` or `<redacted>`                   |

### Never use

- Real project names from any client or employer codebase
- Real internal tool or hook names (e.g. private GitHub repos used as prek hooks)
    are fine in actual config files (`prek.toml`) but must not appear in skill
    documentation examples — use `myorg/myhook` instead.
    **Functional exception:** agent dispatch triggers and gate-output handling may
    name a real hook the user actually runs (e.g. `lint-fixer` matching
    "resolve codecongruence" and its finding codes) — dispatch must match real
    command output to work. Illustrative examples still use `myorg/myhook`.
- Real email addresses in examples — use `user@example.com`
- Real AWS account IDs — use `123456789012`
- Real ARNs — use `arn:aws:lambda:us-east-1:123456789012:function:myapp-dev-worker`

## Skills and agents — keep them generic

Skills and agents in this repo are shared tooling. They must work for any
project without exposing implementation details of any specific one.

- **No project-specific architecture** in skill/agent body copy (flows, table
    schemas, Lambda naming patterns specific to one app)
- **No project-specific ticket IDs** (use `TICK-1`, `TICK-2`)
- **No project-specific AWS resource names** in examples (use the placeholders above)
- If a skill was originally written for a specific project, strip all project
    specifics before committing it here

## prek.toml

Real hook repos (including private ones like `brunofaust/codecongruence`) are
allowed in `prek.toml` because that file is functional config, not documentation.
But their names must not appear in skill documentation examples — use
`myorg/myhook` as the placeholder in SKILL.md files.

The naming-conventions rule above is enforced mechanically by the
`banned-project-names` prek check: it pygreps `src/claude_all/agents/`,
`src/claude_all/skills/`, and `src/claude_all/instructions/` for known real
names/artifacts (vendored dirs excluded).

Note that check does **not** cover `src/claude_all/hooks/`, `tests/`, or
`README.md` — when a change adds files there, grep them for real project names
by hand before opening the PR.

### 🔴 A reference hook config MUST be named `prek.toml.example`, never `prek.toml`

prek treats **every** `prek.toml` under the repo root as a workspace *project*
(see `prek run [HOOK|PROJECT]`), not just the one at the root. So a file literally
named `prek.toml` shipped inside a skill directory as *documentation* gets loaded
and executed by this repo's own gate — and a single stale `rev` in it kills the
whole run with `Failed to init hooks` before one check executes. Ship reference
configs as `<skill>/prek.toml.example` and tell the user to rename on copy.

The `.example` suffix means `check-toml` no longer validates them (it matches
`*.toml`), so `tests/test_reference_prek_configs.py` buys that coverage back —
it parses each one with `tomllib` and asserts the suffix is still in place.

## Vendored (third-party) resources

Some skills/agents are copied from upstream repos (e.g. Vercel `agent-skills`, `humanink`). They are
tracked in `vendored.json` (repo root) and refreshed with `python scripts/vendor_sync.py`. Rules (full
detail in the `vendored-sources` skill):

- Keep vendored files **byte-identical to upstream** — local additions go in `local_only` sidecars
  (`ATTRIBUTION.md`, `claude_md.md`, `hook.*`); the only in-file change is `frontmatter_inject`.
- Every vendored dir has an **`ATTRIBUTION.md`**; vendor the upstream **`LICENSE` verbatim** if it has
  one. Never fabricate a copyright notice. Only vendor permissive licenses (MIT/Apache/BSD/ISC).
- Add a `vendored.json` entry for anything imported so it's attributed and updatable.

## Agent error reporting — verbatim by default

Agents exist to absorb large output so the main session stays clean. But when
an error needs to be **fixed**, the main session needs the full error text — a
summary is not enough.

### Rule

**Return errors verbatim unless the main session cannot act on the detail.**

| Error type                                                 | Return                                             |
| ---------------------------------------------------------- | -------------------------------------------------- |
| Test failures (pytest, jest, vitest)                       | Verbatim — full traceback + assertion diff         |
| Linter / type-checker errors (ruff, mypy, eslint, tsc)     | Verbatim — file:line + message                     |
| Pre-commit / hook failures                                 | Verbatim — full hook output                        |
| Log entries with exceptions                                | Verbatim — timestamp + exception class + traceback |
| AWS errors (Lambda FunctionError, DDB ValidationException) | Verbatim — error code + message + request ID       |
| SQL errors                                                 | Verbatim — SQLSTATE + message                      |
| Simple bash failure the caller can't act on                | Summary OK — e.g. "exit 1: file not found"         |
| Infra/deploy success confirmation                          | Summary OK — e.g. "✓ deployed, ARN: ..."           |

### What "verbatim" means

Quote the exact output — do not paraphrase, truncate error messages, or replace
specifics with "looks like a permission issue" / "probably a type error". The
main session reads the raw text to locate the file, line, and cause.

Summaries are acceptable only when:

- The output is a success / no-op (counts, durations, resource names).
- The error is a system/infra issue the caller cannot fix from text alone
    (e.g., network timeout, missing AWS credentials) — in that case return the
    exact error code + message but skip surrounding noise.

### Never

- Paraphrase error messages ("the import failed" instead of the full
    `ImportError: cannot import name 'X' from 'Y (path)'`).
- Truncate stack traces to "top frame only" — return at least the 3 frames
    closest to the call site.
- Omit file paths and line numbers from lint/type errors.
- Summarise a failing test as "2 tests failed" without the failure bodies.

## Managed instruction injection — never edit the installed files directly

Write injected snippets for model execution: concise triggers, mandatory routing,
caller obligations and global safety constraints. Do not repeat resource descriptions
or procedures. Put selection criteria in frontmatter and details in the owning
agent/skill; preserve a reachable owner for every unique rule. Keep the complete
rendered catalog within the 14,500-byte test budget, including ownership markers.
Preserve personal content and existing `AGENTS.md` → `CLAUDE.md` symlinks on refresh.

`~/.claude/CLAUDE.md` (Claude) and `~/.codex/AGENTS.md` (Codex) are the user's
global instruction files. They are managed by the `claude-all` installer via
tagged snippet injection. **Do not edit injected blocks directly.**

### How dispatch instructions reach the host instruction files

When `claude-all --all --user <agent>` runs, it looks for a
`<agent>.claude_md.md` file next to the agent's `.md` file and injects its
content as a tagged block. Reinstalling is idempotent — the block is replaced.

Agent `claude_md.md` naming: flat `src/claude_all/agents/<category>/<name>.claude_md.md`, or folder `src/claude_all/agents/<category>/<name>/claude_md.md` (beside `agent.md`)
Skill/tool `claude_md.md` naming: inside the resource's directory.
Standalone snippet naming: `src/claude_all/instructions/<name>/claude_md.md` — a resource
whose ONLY effect is injecting that block (no agent/skill/hook to install). Use it
for main-session dispatch rules that target built-in agents (e.g. routing broad
searches to `Explore`). Install with `claude-all --all --user <name>`.

### Rules

- To add dispatch table rows or anti-patterns for an agent, create or update
    its `<name>.claude_md.md` — never edit injected blocks by hand.
- Only edit a host instruction file directly if the user explicitly asks to make
    a one-off personal change that does not belong in any agent or skill.
- Do not edit files outside this repo's tree (e.g. `~/.claude/`, `~/.codex/`, other project
    repos) unless the user explicitly requests it.
