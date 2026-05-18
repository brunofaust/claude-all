# claude-all

Claude Code agents, skills, plugins, and MCP configurations. One place to manage everything that customizes how Claude works for me.

## Structure

```
claude-all/
├── install.sh                # Interactive installer
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

The installer presents an interactive menu, lets you select what to install, and chooses between user-level (`~/.claude/`) or project-level (`./.claude/`).

```bash
# Clone the repository
git clone https://github.com/brunofaust/claude-all.git

# Permission to install.sh to execute
chmod +x install.sh

# Full menu — everything available
./install.sh

# Filtered to a category
./install.sh coding aws       # only AWS agents
./install.sh coding agents    # all agents
./install.sh coding skills    # all skills

# Non-interactive listing
./install.sh --list           # show everything
./install.sh --list aws       # show AWS items only

# Help
./install.sh --help
```

### Menu controls

- `↑`/`↓` or `j`/`k` — move cursor
- `SPACE` — toggle selection
- `A` — select all visible
- `N` — clear selection
- `ENTER` — proceed to install level choice
- `q` — quit

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
| `log-filter` | haiku-4-5 | Filters, summarizes, formats raw logs from any source (structlog JSON, CloudWatch output, stdout). Works on logs already in hand. |
| `docs-updater` | sonnet-4-6 | Updates README, CLAUDE.md, ARCHITECTURE.md, CHANGELOG.md after code changes. Detects which doc needs the update; proposes diffs. |

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

#### 1.5 Support (cross-cutting)

| Agent | Model | Description |
|---|---|---|
| `debugger` | sonnet-4-6 | Root-cause analysis on bugs, test failures, distributed system issues. Forms hypotheses, verifies cheaply, proposes minimum fix. |
| `incident-responder` | sonnet-4-6 | Coordinates active-incident investigation across AWS services. Builds a unified timeline. Produces postmortem-ready summary. |

### 2. Skills

#### 2.1 Python

| Skill | Description |
|---|---|
| brunofaust-python-style | Modern Python 3.14+ coding standards for async-first, type-safe production code. |

### 3. Plugins

| Plugin | Description |
|---|---|
| _(none yet)_ | |

### 4. MCPs

| MCP | Description |
|---|---|
| _(none yet)_ | |

## Model strategy

- **Haiku (haiku-4-5)** — mechanical tasks: read + report, run + summarize, execute deterministic CLI operations. The agent should refuse anything requiring judgment.
- **Sonnet (sonnet-4-6)** — reasoning: code review, refactoring, debugging, incident response, doc updates. Tasks where the right answer depends on context.

Opus is intentionally absent — these agents are for routine work, and Opus is reserved for sessions where reasoning depth justifies the cost.

## Adding a new agent

1. Create the `.md` file in the right category folder.
2. Frontmatter must include `name`, `description` (detailed, with triggers), `model`, and `tools`.
3. Body describes capabilities, workflow, output format, and rules.
4. Test with `./install.sh --list <category>` to verify discovery.
5. Update this README's table.

Description guidelines: be explicit about WHEN to trigger AND when NOT to trigger. List specific user phrasings. The router uses this text to pick agents — vague descriptions cause wrong delegation.
