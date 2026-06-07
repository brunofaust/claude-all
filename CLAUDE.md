# claude-all — contribution guidelines

## Commands

```bash
# Install an agent or skill into Claude Code
./claude-all install <agent-name> --level user    # global
./claude-all install <agent-name> --level project # repo-local

# Dev setup (installs prek)
uv sync --dev

# Lint (single entry point — runs ruff, mypy, typos)
prek run --all-files
```

## Repo structure

| Path                                           | Purpose                                                                                                                       |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `claude-all` / `claude-all.py`                 | CLI installer — discovers and installs agents/skills/hooks                                                                    |
| `agents/<category>/<name>.md`           | Flat agent definition (no companions) — dispatched by the router                                                              |
| `agents/<category>/<name>/agent.md`     | Folder agent (ships companions) — `agent.md` + `claude_md.md` and/or `hook.py`/`hook.json` grouped in one dir                  |
| `agents/<category>/<name>.claude_md.md` | Companion snippet injected into `~/.claude/CLAUDE.md` on install (folder agents put it at `<name>/claude_md.md`)               |
| `skills/<category>/<name>/SKILL.md`     | Skill definitions (invoked via Skill tool)                                                                                    |
| `instructions/<name>/claude_md.md`      | Standalone `~/.claude/CLAUDE.md` snippet (no agent/skill to install — e.g. dispatch rules for built-in agents like `Explore`) |
| `hooks/`                                | Hook scripts (source — not yet active)                                                                                        |
| `.claude/hooks/`                               | Active hooks for this repo's Claude sessions                                                                                  |
| `.claude/agents/`                              | Sub-agent definitions scoped to this repo                                                                                     |

## Adding a new agent or skill

**Agent:**

1. Bare agent → flat file `agents/<category>/<name>.md`. Agent that ships
   companions → folder `agents/<category>/<name>/agent.md` (keep `agent.md` +
   its `claude_md.md` / `hook.*` together)
1. Optionally add a `claude_md.md` snippet — flat: `<name>.claude_md.md` beside the
   `.md`; folder: `<name>/claude_md.md` beside `agent.md`
1. Run `./claude-all install <name> --level user` to activate
1. **Update `README.md`** — add a row to the relevant agent table (§ 1.x)

**Skill:**

1. Create `skills/<category>/<name>/SKILL.md`
1. Run `./claude-all install <name> --level user` to activate
1. **Update `README.md`** — add a row to the relevant skill table (§ 2.x)

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
    documentation examples — use `myorg/myhook` instead
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

## CLAUDE.md injection — never edit `~/.claude/CLAUDE.md` directly

`~/.claude/CLAUDE.md` is the user's global Claude config. It is managed by
`claude-all install` via tagged snippet injection. **Do not edit it directly.**

### How dispatch instructions reach `~/.claude/CLAUDE.md`

When `claude-all install <agent> --level user` runs, it looks for a
`<agent>.claude_md.md` file next to the agent's `.md` file and injects its
content as a tagged block. Reinstalling is idempotent — the block is replaced.

Agent `claude_md.md` naming: flat `agents/<category>/<name>.claude_md.md`, or folder `agents/<category>/<name>/claude_md.md` (beside `agent.md`)
Skill/tool `claude_md.md` naming: inside the resource's directory.
Standalone snippet naming: `instructions/<name>/claude_md.md` — a resource
whose ONLY effect is injecting that block (no agent/skill/hook to install). Use it
for main-session dispatch rules that target built-in agents (e.g. routing broad
searches to `Explore`). Install with `./claude-all install <name> --level user`.

### Rules

- To add dispatch table rows or anti-patterns for an agent, create or update
    its `<name>.claude_md.md` — never edit `~/.claude/CLAUDE.md` by hand.
- Only edit `~/.claude/CLAUDE.md` directly if the user explicitly asks to make
    a one-off personal change that does not belong in any agent or skill.
- Do not edit files outside this repo's tree (e.g. `~/.claude/`, other project
    repos) unless the user explicitly requests it.
