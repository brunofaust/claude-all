# claude-all

Claude Code agents, skills, plugins, and MCP configurations. One place to manage everything that customizes how Claude works for me.

## Structure

```
claude-all/
├── claude-all                # Bash wrapper → dispatches to claude-all.py
├── claude-all.py             # Interactive TUI installer (curses)
├── coding/
│   ├── agents/
│   │   ├── generic/          # Language-agnostic, project-agnostic
│   │   ├── aws/              # AWS-specific tooling
│   │   ├── databases/        # Non-AWS database tooling
│   │   ├── python/           # Python-specific
│   │   └── support/          # Cross-cutting: debugging, incidents
│   ├── skills/               # Reusable skills (e.g., python style)
│   ├── plugins/              # Claude Code plugins
│   └── mcps/                 # MCP server configurations
└── README.md
```

Future categories (travel, writing, research, etc.) live as siblings to `coding/`.

## Installation

### Requirements

- macOS or Linux
- `python3` (stdlib only — no pip installs)
- `claude` CLI in PATH (for plugins with `type: claude-marketplace`)
- `pipx` in PATH (for plugins with `type: pip`)

Install `pipx` (only if you want pip-based plugins):

```bash
# macOS (Homebrew)
brew install pipx
pipx ensurepath

# Or via pip
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

After `pipx ensurepath`, restart your shell so `pipx` is on PATH.

### Setup

```bash
# 1. Clone the repository (anywhere — pick your own path)
git clone https://github.com/brunofaust/claude-all.git
cd claude-all

# 2. Make the wrapper executable
chmod +x claude-all claude-all.py

# 3. Add the cloned directory to your PATH
#    $(pwd) expands to the current directory at setup time.
echo "export PATH=\"$(pwd):\$PATH\"" >> ~/.zshrc
source ~/.zshrc
```

### Usage

Interactive TUI. Select items, pick user-level (`~/.claude/`) or project-level (`./.claude/`).

```bash
# Full TUI — everything available
claude-all

# Filtered to a category
claude-all coding aws       # only AWS agents
claude-all coding agents    # all agents
claude-all coding skills    # all skills

# Non-interactive listing
claude-all --list           # show everything
claude-all --list aws       # show AWS items only

# Non-interactive install
claude-all --all --user coding aws       # all AWS agents → ~/.claude/
claude-all --all --project coding skills # all skills → ./.claude/

# Help
claude-all --help
```

Install into a project:

```bash
cd ~/repos/my_project
claude-all
```

### TUI controls

- `↑`/`↓` or `j`/`k` — move cursor
- `PgUp`/`PgDn`, `Home`/`End` — jump
- `SPACE` — toggle item under cursor
- `a` — select all visible (respects active filter)
- `n` — clear selection of visible
- `/` — incremental filter (type to narrow, `ENTER` to confirm, `ESC` to clear)
- `ENTER` — proceed to install-level choice
- `q` or `ESC` — quit

### Installation method

Symlinks. Edits in this repo propagate to every project where the items are installed. To "update", just `git pull` here.

## Coding

### 1. Agents

All agents follow the same pattern: a detailed `description` so Claude Code's auto-router picks the right one, a strict `model` (Haiku for mechanical work, Sonnet for judgment-heavy work), and a focused tool list.

#### 1.1 Generic (language-agnostic)

| Agent | Model | Description |
|---|---|---|
| `code-quality` | haiku-4-5 | Runs all available quality gates (prek, pre-commit, ruff, mypy, pytest, eslint, prettier, tsc, vitest). Reports failures only. Never auto-fixes. |
| `git-committer` | haiku-4-5 | Stages changes, generates a Conventional Commits message, commits to current branch (optionally pushes). Never branches, merges, or rebases. |
| `git-runner` | haiku-4-5 | Read-only git inspection (log, diff, status, blame, show, branch, stash list). Returns tight summaries — author/file counts, not raw multi-page output. Prefers `rtk` wrapper if installed. Refuses any write/destructive git command. |
| `log-filter` | haiku-4-5 | Filters, summarizes, formats raw logs from any source (structlog JSON, CloudWatch output, stdout). Works on logs already in hand. |
| `docs-updater` | sonnet-4-6 | Updates README, CLAUDE.md, ARCHITECTURE.md, CHANGELOG.md after code changes. Detects which doc needs the update; proposes diffs. |
| `docker-runner` | haiku-4-5 | Executes docker / docker compose commands (build, run, exec, logs, ps, compose up/down/restart/logs). Returns concise summary — image tag/size for builds, container state for ps, error chain for failures. Refuses destructive ops (rm/rmi/volume rm/prune/push/down -v) without explicit confirmation. |

#### 1.2 AWS

| Agent | Model | Description |
|---|---|---|
| `cloudwatch-inspector` | haiku-4-5 | Queries CloudWatch Logs and Metrics. Runs Logs Insights queries, filters by pattern/severity/time. Read-only. |
| `s3-inspector` | haiku-4-5 | Inspects S3 buckets, prefixes, lifecycle, encryption, versioning. Read-only. |
| `iam-auditor` | haiku-4-5 | Audits IAM roles, users, policies, trust relationships. Flags wildcard permissions and stale credentials. Read-only. |
| `sqs-monitor` | haiku-4-5 | Monitors SQS queue depths, DLQs, oldest message age, in-flight counts. Read-only. |
| `dynamodb-inspector` | haiku-4-5 | Inspects DynamoDB tables: schema, GSI status, item count, capacity mode. Limited scans. Read-only. |
| `step-functions-tracer` | haiku-4-5 | Traces Step Functions executions, identifies failed states, extracts error chains. Read-only. |
| `ecr-manager` | haiku-4-5 | Lists ECR repos, images, tags. Can prune old images with explicit confirmation. |
| `cost-explorer` | haiku-4-5 | Queries Cost Explorer for spend by service/tag, forecasts, anomalies. Read-only. |
| `rds-postgres-query` | haiku-4-5 | Read-only SQL on AWS RDS/Aurora Postgres. Handles IAM auth and RDS Proxy. Only SELECT/EXPLAIN/SHOW. |
| `terraform-deployer` | haiku-4-5 | Executes terraform init/plan/apply/destroy. Always shows plan; never applies/destroys without explicit confirmation. |
| `terraform-reviewer` | sonnet-4-6 | Reviews Terraform code and plan output for security, cost, IAM scope, operational risks. Read-only. |
| `cloudformation-deployer` | haiku-4-5 | Executes CloudFormation via change sets. Validates, describes, deploys after confirmation. |
| `cloudformation-reviewer` | sonnet-4-6 | Reviews CloudFormation templates and change sets for security and operational risks. Read-only. |

#### 1.3 Databases (non-AWS)

| Agent | Model | Description |
|---|---|---|
| `postgres-query` | haiku-4-5 | Read-only SQL on generic Postgres (local, Docker, Supabase, Neon). Only SELECT/EXPLAIN/SHOW. Use `rds-postgres-query` for AWS RDS. |

#### 1.4 Python

| Agent | Model | Description |
|---|---|---|
| `python-refactorer` | sonnet-4-6 | Refactors Python code to brunofaust-python-style conventions: PEP 695 generics, asyncio.TaskGroup, structlog, strict typing. Proposes diffs; never auto-applies. |
| `python-deps` | haiku-4-5 | Executes Python dep-manager commands (uv/pip/poetry/pipx) and returns a concise summary — success, key changes, useful error chain, well-known fix suggestion when obvious. Never edits lockfiles or pyproject. |
| `migration-reviewer` | sonnet-4-6 | Reviews Alembic migrations for safety, asyncpg correctness, ENUM patterns, lock contention, backfill docs, downgrade reversibility, and ORM consistency. Returns a BLOCK/WARN/INFO scored report with line refs. Read-only — never applies migrations. Pairs with the `alembic-migration` skill. |

#### 1.5 Support (cross-cutting)

| Agent | Model | Description |
|---|---|---|
| `debugger` | sonnet-4-6 | Root-cause analysis on bugs, test failures, distributed system issues. Forms hypotheses, verifies cheaply, proposes minimum fix. |
| `incident-responder` | sonnet-4-6 | Coordinates active-incident investigation across AWS services. Builds a unified timeline. Produces postmortem-ready summary. |
| `test-runner` | haiku-4-5 | Runs tests (pytest, vitest, jest, mocha, playwright, go test, cargo test). Returns pass/fail counts + failed test IDs + first error per failure — no full tracebacks. Never modifies test files. Use for any "run tests" request to keep pytest output out of main context. |

### 2. Skills

#### 2.1 Python

| Skill | Description |
|---|---|
| brunofaust-python-style | Modern Python 3.14+ coding standards for async-first, type-safe production code. |
| alembic-migration | Generate Alembic migrations following busydone patterns — naming, backfill safety, merge resolution, ENUM handling, asyncpg query syntax. Anti-patterns table for common mistakes. |

### 3. Plugins

Each plugin lives at `coding/plugins/<name>/plugin.json`. The installer dispatches on the `type` field:

| Type | Installer | Required fields |
|---|---|---|
| `claude-marketplace` | `claude plugin marketplace add` + `claude plugin install` | `marketplace`, `plugin` |
| `pip` | `pipx install <package>[extras]` | `package` (optional: `extras`, `pin`, `command`) |

Optional fields:

- `post_install` — list of argv lists, run after the main install, e.g. `[["code-review-graph", "install"]]` for one-time setup commands.
- `post_install_message` — string printed after install, e.g. instructions the user must follow per-project.

Installed plugins:

| Plugin | Type | Source | Description |
|---|---|---|---|
| `caveman` | claude-marketplace | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) | Ultra-compressed communication mode. Cuts token usage from Claude responses. |
| `claude-mem` | claude-marketplace | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | Persistent cross-session memory for Claude Code. |
| `code-review-graph` | pip (`[communities]`) | [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph) | Persistent incremental knowledge graph for token-efficient, context-aware code reviews. Includes `igraph` via the `communities` extra. |

### 4. MCPs

Each MCP lives at `coding/mcps/<name>/mcp.json`. Installer runs `claude mcp add` at the chosen scope (`--user` → user scope, `--project` → writes `.mcp.json` in cwd).

Schema:
```json
{
  "name": "terraform",
  "github": "...",
  "command": "npx",
  "args": ["-y", "@hashicorp/terraform-mcp-server"],
  "env": {},
  "transport": "stdio",
  "description": "...",
  "post_install_message": "optional — shown after install"
}
```

**Secrets via macOS keychain (runtime expansion)** — env values or args prefixed `keychain:NAME` are wrapped in a `sh -c '... $(security find-generic-password ...) ...'` invocation, so the secret is resolved on every MCP launch and **never** stored plaintext in `.claude.json` / `.mcp.json`. The keychain entry stays the single source of truth.

Store the secret once:

```bash
security add-generic-password -a "$USER" -s "CONTEXT7_API_KEY" -w "ctx7sk-XXXXXX"
security add-generic-password -a "$USER" -s "POSTGRES_URL" -w "postgresql://user:pass@host:5432/dbname"
```

Rotate by re-running `security add-generic-password` with the new value (it overwrites). No MCP re-install needed — next launch picks up the new secret.

Generated example (context7):
```bash
claude mcp add context7 --scope user -- \
  sh -c 'CONTEXT7_API_KEY=$(security find-generic-password -a "$USER" -s "CONTEXT7_API_KEY" -w) exec npx -y @upstash/context7-mcp'
```

Installed MCPs:

| MCP | Package | Source | Description |
|---|---|---|---|
| `terraform` | `@hashicorp/terraform-mcp-server` | [hashicorp/terraform-mcp-server](https://github.com/hashicorp/terraform-mcp-server) | Terraform Registry lookups, provider docs, module discovery, schema introspection. |
| `context7` | `@upstash/context7-mcp` | [upstash/context7](https://github.com/upstash/context7) | Fresh library docs on demand — resolves library IDs, returns current API/usage snippets. |
| `playwright` | `@playwright/mcp` | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | Browser automation — navigate, click, fill, screenshot, evaluate JS. |
| `postgres` | `@modelcontextprotocol/server-postgres` | [mcp/server-postgres](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres) | Read-only SQL against a Postgres DB. **Edit connection URL after install** (see `post_install_message`). |

## Model strategy

- **Haiku (haiku-4-5)** — mechanical tasks: read + report, run + summarize, execute deterministic CLI operations. The agent should refuse anything requiring judgment.
- **Sonnet (sonnet-4-6)** — reasoning: code review, refactoring, debugging, incident response, doc updates. Tasks where the right answer depends on context.

Opus is intentionally absent — these agents are for routine work, and Opus is reserved for sessions where reasoning depth justifies the cost.

## Adding a new agent

1. Create the `.md` file in the right category folder.
2. Frontmatter must include `name`, `description` (detailed, with triggers), `model`, and `tools`.
3. Body describes capabilities, workflow, output format, and rules.
4. Test with `claude-all --list coding <category>` to verify discovery.
5. Update this README's table.

Description guidelines: be explicit about WHEN to trigger AND when NOT to trigger. List specific user phrasings. The router uses this text to pick agents — vague descriptions cause wrong delegation.
