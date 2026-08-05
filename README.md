# claude-all

Agents, skills, and hooks that customize how Claude Code works — install them into any project with one command.

## Requirements

Python 3.11+, [uv](https://docs.astral.sh/uv/), and the `claude` CLI.

## Install

```bash
uv tool install git+https://github.com/brunofaust/claude-all.git
```

Then, inside any project:

```bash
claude-all
```

This opens an interactive picker — choose items, then install them user-wide (`~/.claude/`) or just for this project (`./.claude/`).

Prefer scripting it? Skip the picker:

```bash
claude-all --list                      # see everything available
claude-all --all --user agents aws     # install all AWS agents, user-wide
claude-all --all --project skills      # install all skills, this project only
```

Update anytime with `uv tool upgrade claude-all`.

### Removing things

```bash
claude-all --prune                     # drop installs the repo no longer ships
claude-all --uninstall                 # reverse EVERY recorded install
claude-all --uninstall agents aws      # or just the ones matching a filter
```

`--uninstall` prints the full plan and asks before it removes anything (`--yes` skips the
prompt; a non-TTY run answers *no* by default, so a piped invocation can't wipe a setup by
accident). It removes the resource symlinks, the `CLAUDE.md` blocks this tool injected, and its
`settings.json` hook entries — **hand-written `CLAUDE.md` content outside those markers is left
alone**, and a `tools`/`plugins` record is forgotten without touching the real binary.

It does not remove the CLI itself; finish with `uv tool uninstall claude-all`.

**Developing on this repo?**

```bash
git clone https://github.com/brunofaust/claude-all.git
cd claude-all
uv sync --dev
uv run claude-all   # picks up local edits immediately
```

## Agents

Subagents Claude Code delegates to for specific jobs. Haiku for mechanical work, Sonnet for judgment calls.

### Generic

| Agent | Model | What it does |
| --- | --- | --- |
| [`code-quality`](src/claude_all/agents/generic/code-quality/agent.md) | haiku | Runs all available linters and reports the results. |
| [`bug-hunter`](src/claude_all/agents/generic/bug-hunter/agent.md) | sonnet | Hunts for real bugs in a given part of the code — not style. |
| [`lint-fixer`](src/claude_all/agents/generic/lint-fixer/agent.md) | sonnet | Fixes lint/type errors that `code-quality` found. |
| [`git-committer`](src/claude_all/agents/generic/git-committer/agent.md) | haiku | Stages, commits, and optionally pushes your changes. |
| [`git-runner`](src/claude_all/agents/generic/git-runner/agent.md) | haiku | Reads git log, diff, status, blame. |
| [`log-filter`](src/claude_all/agents/generic/log-filter.md) | haiku | Filters and summarizes logs you already have. |
| [`docs-updater`](src/claude_all/agents/generic/docs-updater.md) | sonnet | Updates README/CLAUDE.md after a code change. |
| [`docker-runner`](src/claude_all/agents/generic/docker-runner/agent.md) | haiku | Builds, runs, and inspects Docker containers. |
| [`docker-log-inspector`](src/claude_all/agents/generic/docker-log-inspector/agent.md) | haiku | Reads container logs and diagnoses a crash. |
| [`frontend-builder`](src/claude_all/agents/generic/frontend-builder/agent.md) | haiku | Runs your frontend build and reports the result. |
| [`gh-runner`](src/claude_all/agents/generic/gh-runner/agent.md) | haiku | Reads PRs, issues, and CI runs from GitHub. |
| [`http-runner`](src/claude_all/agents/generic/http-runner/agent.md) | haiku | Makes HTTP requests and checks the response. |
| [`email-inspector`](src/claude_all/agents/generic/email-inspector/agent.md) | haiku | Searches and summarizes your email. |
| [`e2e-scenario-runner`](src/claude_all/agents/generic/e2e-scenario-runner/agent.md) | haiku | Runs a multi-step scenario across services and reports pass/fail. |
| [`git-audit`](src/claude_all/agents/generic/git-audit/agent.md) | haiku | Reports which branches and worktrees are safe to remove. |
| [`git-cleanup`](src/claude_all/agents/generic/git-cleanup/agent.md) | haiku | Cleans up branches and worktrees at the end of a session. |
| [`repo-cleaner`](src/claude_all/agents/generic/repo-cleaner/agent.md) | haiku | Removes build artifacts, caches, and empty folders. |
| [`env-audit`](src/claude_all/agents/generic/env-audit.md) | haiku | Checks whether a deployed environment is behind the code. |
| [`env-sync`](src/claude_all/agents/generic/env-sync.md) | sonnet | Brings a dev/staging environment up to date, with your approval. |
| [`code-review-graph-analyst`](src/claude_all/agents/generic/code-review-graph-analyst/agent.md) | haiku | Risk-scores diffs, finds dead code, hub/bridge nodes, surprise-scoring, knowledge gaps via the code-review-graph MCP server. |

### AWS

| Agent | Model | What it does |
| --- | --- | --- |
| [`cloudwatch-inspector`](src/claude_all/agents/aws/cloudwatch-inspector/agent.md) | haiku | Reads CloudWatch logs and metrics. |
| [`s3-inspector`](src/claude_all/agents/aws/s3-inspector/agent.md) | haiku | Inspects S3 buckets and objects. |
| [`iam-auditor`](src/claude_all/agents/aws/iam-auditor/agent.md) | haiku | Reviews IAM roles and policies. |
| [`sqs-monitor`](src/claude_all/agents/aws/sqs-monitor/agent.md) | haiku | Checks SQS queue depth and DLQs. |
| [`dynamodb-inspector`](src/claude_all/agents/aws/dynamodb-inspector/agent.md) | haiku | Reads DynamoDB tables. |
| [`step-functions-tracer`](src/claude_all/agents/aws/step-functions-tracer/agent.md) | haiku | Traces a Step Functions run and finds what failed. |
| [`ecr-manager`](src/claude_all/agents/aws/ecr-manager/agent.md) | haiku | Lists and prunes ECR images. |
| [`cost-explorer`](src/claude_all/agents/aws/cost-explorer/agent.md) | haiku | Reports AWS spend by service, tag, or time. |
| [`cost-audit-runner`](src/claude_all/agents/aws/cost-audit-runner/agent.md) | sonnet | Finds idle or wasted AWS resources. |
| [`rds-postgres-query`](src/claude_all/agents/aws/rds-postgres-query/agent.md) | haiku | Runs read-only SQL against RDS/Aurora Postgres. |
| [`terraform-deployer`](src/claude_all/agents/aws/terraform-deployer/agent.md) | haiku | Runs `terraform plan`/`apply` with your approval. |
| [`terraform-reviewer`](src/claude_all/agents/aws/terraform-reviewer/agent.md) | sonnet | Reviews Terraform for security and cost issues. |
| [`cloudformation-deployer`](src/claude_all/agents/aws/cloudformation-deployer/agent.md) | haiku | Deploys CloudFormation stacks with your approval. |
| [`cloudformation-reviewer`](src/claude_all/agents/aws/cloudformation-reviewer/agent.md) | sonnet | Reviews CloudFormation templates for risk. |
| [`aws-events-scheduler`](src/claude_all/agents/aws/aws-events-scheduler/agent.md) | haiku | Manages EventBridge rules and Scheduler schedules. |
| [`dynamodb-mutator`](src/claude_all/agents/aws/dynamodb-mutator/agent.md) | sonnet | Writes to DynamoDB — only with your confirmation. |
| [`secrets-fetcher`](src/claude_all/agents/aws/secrets-fetcher/agent.md) | haiku | Looks up a secret in Secrets Manager — never prints the value. |
| [`aws-lambda-deployer`](src/claude_all/agents/aws/aws-lambda-deployer/agent.md) | haiku | Deploys and invokes Lambda functions. |
| [`ecs-inspector`](src/claude_all/agents/aws/ecs-inspector/agent.md) | haiku | Reads ECS task and service state. |

### Databases

| Agent | Model | What it does |
| --- | --- | --- |
| [`postgres-query`](src/claude_all/agents/databases/postgres-query/agent.md) | haiku | Runs read-only SQL against local/non-AWS Postgres. |

### Python

| Agent | Model | What it does |
| --- | --- | --- |
| [`python-refactorer`](src/claude_all/agents/python/python-refactorer.md) | sonnet | Proposes modern-Python refactors — doesn't apply them. |
| [`python-deps`](src/claude_all/agents/python/python-deps/agent.md) | haiku | Installs, updates, and locks Python dependencies. |
| [`migration-reviewer`](src/claude_all/agents/python/migration-reviewer/agent.md) | sonnet | Reviews an Alembic migration for safety. |
| [`python-module-migrator`](src/claude_all/agents/python/python-module-migrator/agent.md) | haiku | Moves a Python module and fixes every import. |
| [`test-author`](src/claude_all/agents/python/test-author/agent.md) | sonnet | Writes unit tests to close a coverage gap. |

### Web

| Agent | Model | What it does |
| --- | --- | --- |
| [`seo-runner`](src/claude_all/agents/web/seo-runner/agent.md) | haiku | Runs a live SEO audit against a URL. |
| [`seo-reviewer`](src/claude_all/agents/web/seo-reviewer/agent.md) | sonnet | Reviews SEO in your page source before deploy. |

### Support

| Agent | Model | What it does |
| --- | --- | --- |
| [`debugger`](src/claude_all/agents/support/debugger.md) | sonnet | Finds the root cause of a bug or failing test. |
| [`incident-responder`](src/claude_all/agents/support/incident-responder/agent.md) | sonnet | Investigates a production incident across services. |
| [`test-runner`](src/claude_all/agents/support/test-runner/agent.md) | haiku | Runs your test suite and reports results. |
| [`friction-analyzer`](src/claude_all/agents/support/friction-analyzer/agent.md) | sonnet | Reads a session transcript and proposes a fix for what went wrong. |
| [`lessons-extractor`](src/claude_all/agents/support/lessons-extractor.md) | sonnet | Reads merged PRs and proposes guardrails for recurring bugs. |

## Skills

Reusable know-how Claude loads on demand — a checklist, a workflow, or a style guide.

### Python

| Skill | What it does |
| --- | --- |
| [brunofaust-python-style](src/claude_all/skills/python/brunofaust-python-style/SKILL.md) | Modern Python style rules Claude follows when writing your code. |
| [alembic-migration](src/claude_all/skills/python/alembic-migration/SKILL.md) | Rules and patterns for writing Alembic migrations. |
| [python-module-migration](src/claude_all/skills/python/python-module-migration/SKILL.md) | How to safely move a Python module and fix imports. |

### Frontend

`brunofaust-frontend-style` is the entry point — it pulls in the four vendored skills below automatically.

| Skill | What it does |
| --- | --- |
| [brunofaust-frontend-style](src/claude_all/skills/frontend/brunofaust-frontend-style/SKILL.md) | Modern React/frontend rules Claude follows when writing your code. |
| [react-best-practices](src/claude_all/skills/frontend/react-best-practices/SKILL.md) *(vendored)* | React/Next.js performance patterns. |
| [composition-patterns](src/claude_all/skills/frontend/composition-patterns/SKILL.md) *(vendored)* | Cleaner ways to compose React components. |
| [react-view-transitions](src/claude_all/skills/frontend/react-view-transitions/SKILL.md) *(vendored)* | Animate route and state changes with the View Transition API. |
| [web-design-guidelines](src/claude_all/skills/frontend/web-design-guidelines/SKILL.md) *(vendored)* | UI/UX/accessibility review checklist. |

### AWS

| Skill | What it does |
| --- | --- |
| [aws-architecture](src/claude_all/skills/aws/aws-architecture/SKILL.md) | Patterns for Lambda, SQS/SNS/EventBridge, DynamoDB, Step Functions. |
| [aws-debug-loop](src/claude_all/skills/aws/aws-debug-loop/SKILL.md) | How to debug a failing AWS dev environment step by step. |
| [aws-cost-optimization](src/claude_all/skills/aws/aws-cost-optimization/SKILL.md) | Playbook for cutting AWS spend. |

### Web

| Skill | What it does |
| --- | --- |
| [seo](src/claude_all/skills/web/seo/SKILL.md) | SEO, GEO, and AEO checklist for pages and content. |

### Generic

| Skill | What it does |
| --- | --- |
| [adversarial-verification](src/claude_all/skills/generic/adversarial-verification/SKILL.md) | Don't say "it works" without running it and showing the output. |
| [code-review-discipline](src/claude_all/skills/generic/code-review-discipline/SKILL.md) | Shared format and verdict rules for any review task. |
| [prek](src/claude_all/skills/generic/prek/SKILL.md) | Setup and troubleshooting for the prek/pre-commit lint gate. |
| [self-rationalization-guard](src/claude_all/skills/generic/self-rationalization-guard/SKILL.md) | Catches Claude stalling or avoiding a task and redirects it to act. |
| [subagent-prompting](src/claude_all/skills/generic/subagent-prompting/SKILL.md) | Checklist for writing prompts for subagents. |
| [verification-loop](src/claude_all/skills/generic/verification-loop/SKILL.md) | Six-gate pre-PR checklist: lint, types, tests, coverage, security, diff. |
| [architecture-decision-guard](src/claude_all/skills/generic/architecture-decision-guard/SKILL.md) | Don't add a new layer or abstraction without a real need. |
| [regression-gates](src/claude_all/skills/generic/regression-gates/SKILL.md) | Add a new lint rule to an old codebase without breaking every commit. |
| [mock-drift-sweep](src/claude_all/skills/generic/mock-drift-sweep/SKILL.md) | Update every mock after a function's signature changes. |
| [execution-trace-audit](src/claude_all/skills/generic/execution-trace-audit/SKILL.md) | Trace a service's entrypoints to find dead code and bugs. |
| [diff-retrospective](src/claude_all/skills/generic/diff-retrospective/SKILL.md) | Turn recently merged PRs into new guardrails. |
| [research-before-build](src/claude_all/skills/generic/research-before-build/SKILL.md) | Check nothing like this already exists before building it. |
| [security-audit](src/claude_all/skills/generic/security-audit/SKILL.md) | Whole-stack security review — app, secrets, dependencies, CI/CD, cloud. |
| [claude-hooks](src/claude_all/skills/generic/claude-hooks/SKILL.md) | How to write and debug Claude Code hooks. |
| [wait-for-ready](src/claude_all/skills/generic/wait-for-ready/SKILL.md) | Poll until a service is ready instead of a fixed sleep. |
| [humanink](src/claude_all/skills/generic/humanink/SKILL.md) | Detects AI-sounding writing and rewrites it to sound human. |
| [repo-audit](src/claude_all/skills/generic/repo-audit/SKILL.md) | Full repo quality scorecard and improvement roadmap. |
| [session-harvest](src/claude_all/skills/generic/session-harvest/SKILL.md) | Mines your Claude Code history for what to automate next. |
| [ship](src/claude_all/skills/generic/ship/SKILL.md) | `/ship` — lint, test, and commit. No review, no PR. |
| [merge-main](src/claude_all/skills/generic/merge-main/SKILL.md) | `/merge-main` — merges `origin/main` in and resolves real conflicts, not just text ones. |
| [ship-pr](src/claude_all/skills/generic/ship-pr/SKILL.md) | `/ship-pr` — lint, test, review, docs, then opens the PR. |
| [resource-scaffolder](src/claude_all/skills/generic/resource-scaffolder/SKILL.md) | Turns an approved idea into a real skill, agent, or hook. |
| [implement-loop](src/claude_all/skills/generic/implement-loop/SKILL.md) | `/implement-loop` — implements an approved backlog one story at a time. |
| [retro](src/claude_all/skills/generic/retro/SKILL.md) | `/retro` — turns recent history and code into a prioritized backlog of fixes. |
| [requirements-ears](src/claude_all/skills/generic/requirements-ears/SKILL.md) | Turns a feature idea into precise, testable requirements. |

## Hooks

Scripts Claude Code runs automatically around tool calls — mostly quiet reminders, a few hard blocks.

| Hook | Event | What it does |
| --- | --- | --- |
| [`config-protection.py`](src/claude_all/hooks/config-protection.py) | PreToolUse | Asks before editing lint config or hook settings. |
| [`worktree-isolation-guard.py`](src/claude_all/hooks/worktree-isolation-guard.py) | PreToolUse | Asks before editing files directly on `main`. |
| [`mock-spec-guard.py`](src/claude_all/hooks/mock-spec-guard.py) | PreToolUse | Reminds you to spec a mock instead of leaving it bare. |
| [`test-data-isolation-guard.py`](src/claude_all/hooks/test-data-isolation-guard.py) | PreToolUse | Reminds you not to hardcode tenant IDs in tests. |
| [`python-orjson-guard.py`](src/claude_all/hooks/python-orjson-guard.py) | PreToolUse | Blocks stdlib `json` in favor of `orjson`. |
| [`python-structlog-guard.py`](src/claude_all/hooks/python-structlog-guard.py) | PreToolUse | Blocks stdlib `logging` in favor of `structlog`. |
| [`python-settings-env-guard.py`](src/claude_all/hooks/python-settings-env-guard.py) | PreToolUse | Blocks raw `os.environ` reads in favor of typed settings. |
| [`python-thread-subprocess-guard.py`](src/claude_all/hooks/python-thread-subprocess-guard.py) | PreToolUse | Blocks raw threads/subprocess in favor of the project's wrappers. |
| [`destructive-command-guard.py`](src/claude_all/hooks/destructive-command-guard.py) | PreToolUse | Blocks catastrophic commands — `rm -rf /`, force pushes, `DROP TABLE`. |
| [`secret-leak-guard.py`](src/claude_all/hooks/secret-leak-guard.py) | PreToolUse | Blocks a commit that would leak a credential. |
| [`supply-chain-guard.py`](src/claude_all/hooks/supply-chain-guard.py) | PreToolUse | Flags risky package installs before they run. |
| [`dev-server-tmux.py`](src/claude_all/hooks/dev-server-tmux.py) | PreToolUse | Blocks starting a dev server outside tmux. |
| [`edited-files-accumulator.py`](src/claude_all/hooks/edited-files-accumulator.py) | PostToolUse | Tracks which files changed this turn. |
| [`prek-stop-runner.py`](src/claude_all/hooks/prek-stop-runner.py) | Stop | Runs prek once per response instead of once per edit. |
| [`suggest-compact.py`](src/claude_all/hooks/suggest-compact.py) | PreToolUse | Reminds you to run `/compact` when context is getting full. |
| [`python-style-skill-loader.py`](src/claude_all/hooks/python-style-skill-loader.py) | SessionStart | Reminds Claude to load the Python style skill in a Python repo. |

## Plugins

A plugin is a third-party tool installed via `claude plugin install` (Claude Code marketplace) or `pipx` (a plain pip package). Each lives at `src/claude_all/plugins/<name>/plugin.json` with a `type` field of `claude-marketplace` or `pip`. None are currently installed — `code-review-graph` moved to Tools below.

## MCPs

MCP servers Claude Code can connect to. Each lives at `src/claude_all/mcps/<name>/mcp.json` and installs via `claude mcp add`.

| MCP | What it's for |
| --- | --- |
| [`terraform`](src/claude_all/mcps/terraform/mcp.json) | Terraform Registry lookups, provider docs, module discovery. |
| [`context7`](src/claude_all/mcps/context7/mcp.json) | Fresh library docs on demand. |
| [`playwright`](src/claude_all/mcps/playwright/mcp.json) | Browser automation — navigate, click, fill, screenshot. |
| [`postgres`](src/claude_all/mcps/postgres/mcp.json) | Read-only SQL against a Postgres DB (set the connection URL after install). |
| [`code-review-graph`](src/claude_all/mcps/code-review-graph/mcp.json) | Codebase knowledge graph — risk-scored diff review, hub/bridge detection, surprise-scoring, knowledge gaps, dead code. Run `code-review-graph build` in each target repo after install. |

**Secrets:** an MCP config value prefixed `keychain:NAME` is resolved from the macOS keychain at launch time — nothing is ever stored in plaintext. Store one once:

```bash
security add-generic-password -a "$USER" -s "CONTEXT7_API_KEY" -w "ctx7sk-XXXXXX"
```

Re-run the same command with a new value to rotate it — no MCP re-install needed.

## Tools

CLI tools installed at the OS level, not into `~/.claude/`. Each lives at `src/claude_all/tools/<name>/tool.json`.

| Tool | What it's for |
| --- | --- |
| [`rtk`](src/claude_all/tools/rtk/tool.json) | Cuts token cost on common CLI output (git, grep, aws, pytest, …) by 60-90%. |
| [`code-review-graph`](src/claude_all/tools/code-review-graph/tool.json) | A code knowledge graph for faster, cheaper code review. |

## Instructions

Standalone rules injected into `~/.claude/CLAUDE.md` — no agent or skill attached, just a rule.

| Instruction | What it does |
| --- | --- |
| [`delegate_search`](src/claude_all/instructions/delegate_search/claude_md.md) | Routes broad codebase search to the `Explore` agent instead of grep loops. |
| [`agent-era-rules`](src/claude_all/instructions/agent-era-rules/claude_md.md) | Standing rules learned from running AI agents on a real codebase. |
| [`tool-dispatch`](src/claude_all/instructions/tool-dispatch/claude_md.md) | Prefer built-in tools and agents over raw bash for common commands. |
| [`bash-safety`](src/claude_all/instructions/bash-safety/claude_md.md) | Avoid credential leaks and destructive writes in shell commands. |
| [`response-style`](src/claude_all/instructions/response-style/claude_md.md) | Keep replies short and checkpointed. |
| [`worktree-isolation`](src/claude_all/instructions/worktree-isolation/claude_md.md) | Branch before editing a shared repo; never wipe another session's work. |
| [`secrets-in-shell`](src/claude_all/instructions/secrets-in-shell/claude_md.md) | Fetch secrets at point of use; never print them to the transcript. |
| [`commit-cadence`](src/claude_all/instructions/commit-cadence/claude_md.md) | Commit early and often, WIP commits included. |

## Model strategy

- **Haiku** — mechanical work: read, run, report.
- **Sonnet** — judgment work: review, refactor, debug.
- **Opus** — reserved for the main session, not delegated to agents.

## Contributing back

Found something reusable in your own project — a skill, agent, or hook that isn't project-specific? Open a PR:

1. Add it under the right category in `src/claude_all/agents/`, `skills/`, `hooks/`, or `instructions/` (see `CLAUDE.md`).
2. Strip project-specific names — use the placeholders in `CLAUDE.md` (`myapp`, `acme`, `example.com`, …).
3. Run `prek run --all-files`.
4. Open a PR at <https://github.com/brunofaust/claude-all>.
