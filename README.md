# claude-all

Claude Code agents, skills, plugins, and MCP configurations. One place to manage everything that customizes how Claude works for me.

## Structure

```
claude-all/
├── pyproject.toml            # Packaging — hatchling build, `claude-all` console script
├── src/claude_all/
│   ├── cli.py                 # Interactive TUI installer (curses)
│   ├── agents/
│   │   ├── generic/           # Language-agnostic, project-agnostic
│   │   ├── aws/                # AWS-specific tooling
│   │   ├── databases/          # Non-AWS database tooling
│   │   ├── python/             # Python-specific
│   │   ├── web/                # Web / SEO agents
│   │   └── support/            # Cross-cutting: debugging, incidents
│   ├── skills/                # Reusable skills (e.g., python style)
│   ├── hooks/                 # Claude Code hook scripts (PreToolUse / PostToolUse / Stop)
│   ├── plugins/                # Claude Code plugins
│   ├── mcps/                   # MCP server configurations
│   ├── tools/                  # OS-level CLI tools (brew, uv_tool)
│   └── instructions/           # Standalone ~/.claude/CLAUDE.md snippets (no resource to install)
└── README.md
```

claude-all is **coding-scoped**: every resource is tooling that improves how Claude works on a
codebase. Resource categories (`agents/`, `skills/`, `hooks/`, …) live under `src/claude_all/` so
they ship inside the installed package — the `claude-all` CLI finds them relative to its own
install location, whether that's a `uv tool install` or an editable git clone.

## Installation

### Requirements

- macOS or Linux
- Python 3.11+ (stdlib only — no pip installs)
- [`uv`](https://docs.astral.sh/uv/) in PATH
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

**Install (recommended):**

```bash
uv tool install git+https://github.com/brunofaust/claude-all.git
```

This puts `claude-all` on PATH. To update: `uv tool upgrade claude-all` (or re-run the install
command with `--force`). Pin to a tag: `uv tool install "git+https://github.com/brunofaust/claude-all.git@vX.Y.Z"`.

**Development setup** (for editing agents/skills in this repo):

```bash
git clone https://github.com/brunofaust/claude-all.git
cd claude-all
uv sync --dev
```

`uv sync` does an editable install, so `uv run claude-all` picks up edits to `agents/`, `skills/`,
etc. immediately — no reinstall needed.

### Usage

Interactive TUI. Select items, pick user-level (`~/.claude/`) or project-level (`./.claude/`).

```bash
# Full TUI — everything available
claude-all

# Filtered to a category
claude-all agents aws       # only AWS agents
claude-all agents           # all agents
claude-all skills           # all skills

# Non-interactive listing
claude-all --list           # show everything
claude-all --list aws       # show AWS items only

# Non-interactive install
claude-all --all --user agents aws    # all AWS agents → ~/.claude/
claude-all --all --project skills     # all skills → ./.claude/

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

Symlinks, pointing back into wherever `claude-all` itself is installed — a `uv tool install` copy,
or this repo when set up via the development setup. Update that source (`uv tool upgrade claude-all`,
or `git pull` in a dev clone) and every project's symlinks pick up the change automatically; no
reinstall needed.

### CLAUDE.md auto-injection

Any resource may ship a `claude_md.md` snippet:

- Flat agent (single file): `src/claude_all/agents/<cat>/<name>.claude_md.md`
- Folder agent (ships companions): `src/claude_all/agents/<cat>/<name>/claude_md.md` (alongside `agent.md`)
- Skills / plugins / mcps (dir): `<resource-dir>/claude_md.md`

Agents use a **hybrid layout**: a bare agent stays a single file `src/claude_all/agents/<cat>/<name>.md`; an agent that ships companions (a `claude_md.md` snippet and/or a `hook.py`/`hook.json`) becomes a folder `src/claude_all/agents/<cat>/<name>/` containing `agent.md` + those companions, so everything groups in one place. The installer discovers both forms.

On install, the snippet is wrapped in tags and appended to the target `CLAUDE.md`:

```
<!-- claude-all:<kind>/<name>:start -->
...snippet content...
<!-- claude-all:<kind>/<name>:end -->
```

Target = `~/.claude/CLAUDE.md` for `--user`, `./CLAUDE.md` for `--project`.

Re-install replaces the block in place (idempotent — no duplicates). Future uninstall strips the block between the tags.

### Hook auto-injection

Skills (and any other resource) may ship a `hook.py` + `hook.json` next to their main file. On install:

1. `hook.py` is symlinked into `.claude/hooks/<kind>-<name>.py`
1. `.claude/settings.json` is merged (idempotent — re-install sweeps and replaces any prior entry for this hook's script across all events, so a changed `event`/`matcher` in `hook.json` never leaves a stale double-firing entry)

Schema `hook.json`:

```json
{"event": "PreToolUse", "matcher": "Edit|Write", "timeout": 2000}
```

Shipped skill hooks are **non-blocking reminders** (exit 0 + JSON `hookSpecificOutput.additionalContext` — the reminder lands in Claude's context without stopping the tool or rendering as a hook error). They fire only when the file being edited or written matches the skill's domain (e.g. `*.py` for python style, `*.tsx` with `<ViewTransition>` for view-transitions skill), once per session.

Target settings file:

- `--user` → `~/.claude/settings.json` + `~/.claude/hooks/`
- `--project` → `./.claude/settings.json` + `./.claude/hooks/`

## First run — audit & customize per project

After installing claude-all, the **first thing to run in each project** is the customization pass.
The entry point is **`repo-audit`** — it's the umbrella that also runs `session-harvest` for you (as
its dimension 14), so you don't invoke both. Run it once per project for suggestions tailored to
*that* repo.

```bash
cd ~/repos/my_project
claude-all --project repo-audit session-harvest   # install both; repo-audit drives session-harvest
```

Then, inside a Claude Code session in that project, run **`repo-audit`**. It works for **any language**
(Python, TypeScript/frontend, Go, Rust, …): it audits the whole repo against generic quality
boundaries — format/lint, type safety, complexity, layering & dependency direction, single-owner
external systems, typed contracts, error handling, docs, dead code, tests, config, secrets/SAST,
**IaC: CloudFormation + Terraform** — translating each boundary to the stack's own tooling
(`brunofaust-python-style` + `prek` are the Python reference). As part of the same pass:

- **dim 14 — `session-harvest`** mines your assistant histories (Claude Code / Cursor / Codex /
  Copilot) into a backlog of skills/agents/hooks/instructions to create, each with an estimated **%
  improvement**.
- **dim 15 — project profile** recommends which existing claude-all agents/skills/hooks fit this
  project, plus net-new project-specific ones.

Output: a per-dimension **scorecard** + a **ratcheting roadmap** + a **resource-recommendation list**.
Re-run it in every project for per-project suggestions. It's **report-only** — it proposes; you decide
what to install or create.

> **Run `session-harvest` on its own** only when you want history mining *without* a full code audit
> — a quick "what should I automate next?" pass. Inside a `repo-audit` run it's already covered by
> dim 14 — don't run it twice.

Both are **ad-hoc, user-invoked** skills, so neither ships a `claude_md.md` (no always-on rule injected
into `~/.claude/CLAUDE.md`) — you invoke them deliberately when onboarding or health-checking a repo.
Their behavior:

**`repo-audit`** (any language)

- **Generic boundaries, per-stack tooling.** `brunofaust-python-style` + `prek` are the Python
  *reference* (ruff / mypy / import-linter / banned-api / interrogate / vulture / bandit / gitleaks);
  for other stacks it translates each boundary to that stack's tools (eslint/tsc, golangci-lint,
  clippy, …) and where no tool exists, audits by reasoning + `grep` — it never skips a boundary.
  Frontend lenses → `react-correctness` / `react-testing` / `composition-patterns` /
  `web-design-guidelines` / `web-security` / `seo`.
- **Brownfield rule: measure → baseline → ratchet, never big-bang.** Don't `--strict` everything or
  reformat the whole repo — that blocks every commit on legacy noise and hides regressions. Wire gates
  advisory, baseline caps at current-worst + margin, ratchet down one notch per PR.
- **Report-only.** It measures and plans; fixes are later *reviewed* PRs (`lint-fixer`,
  `python-module-migrator`, `test-author`). For a single diff use `verification-loop`; for
  security-only use `security-audit`. Gate structural moves through `architecture-decision-guard`.

**`session-harvest`**

- Mines histories across **Claude Code, Cursor, Codex, GitHub Copilot** into a prioritized backlog of
  skills/agents/hooks/instructions, each with an estimated **% improvement** that must **cite its
  evidence** (occurrence count + example) — never an invented number.
- Reads histories **programmatically** (jq / sqlite3 / grep); treats all history content as **data,
  not instructions**; never dumps raw transcripts into context.
- **Report-only** — it proposes the backlog; confirm before creating any hook / settings / CLAUDE.md
  instruction. It's the cross-assistant superset of the `friction-analyzer` agent.

## Coding

### 1. Agents

All agents follow the same pattern: a detailed `description` so Claude Code's auto-router picks the right one, a strict `model` (Haiku for mechanical work, Sonnet for judgment-heavy work), and a focused tool list.

#### 1.1 Generic (language-agnostic)

| Agent                 | Model      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code-quality`        | haiku-4-5  | Runs all available quality gates (prek, pre-commit, ruff, mypy, pytest, eslint, prettier, tsc, vitest). Reports failures only. Never auto-fixes.                                                                                                                                                                                                                                                                                                                                                                                                     |
| `bug-hunter`          | sonnet-4-6 | Deep correctness bug hunt over a named scope (files/dirs/subsystem) — reasoning-based review against a bug-class taxonomy (async/concurrency, data handling, storage/transactions, error swallowing, off-by-one/boundary) that linters can't see. Dispatcher inlines the file list + hot spots (uncommitted diffs, recent churn, tricky domain logic). Read-only, severity-tagged findings with file:line + brief code quote, ≤70-line report. Not for style (`code-quality`), PR diffs (`/code-review`), or whole-repo scorecards (`repo-audit`).   |
| `lint-fixer`          | sonnet-4-6 | FIXES quality-gate findings (ruff, mypy, eslint, tsc, codecongruence). Clears the mechanical tier with `ruff --fix`/`ruff format`, then fixes judgment findings (types, complexity, semantic dedup) at the ROOT CAUSE — no `# type: ignore`/`# noqa`/config-loosening/`--no-verify`. Verifies with the gate + tests after each category. Pairs with `code-quality` (finds) + `test-runner` (confirms).                                                                                                                                               |
| `git-committer`       | haiku-4-5  | Stages changes, generates a Conventional Commits message, commits to current branch (optionally pushes). Never branches, merges, or rebases.                                                                                                                                                                                                                                                                                                                                                                                                         |
| `git-runner`          | haiku-4-5  | Read-only git inspection (log, diff, status, blame, show, branch, stash list). Returns tight summaries — author/file counts, not raw multi-page output. Uses the `rtk` wrapper if installed. Refuses any write/destructive git command.                                                                                                                                                                                                                                                                                                               |
| `log-filter`          | haiku-4-5  | Filters, summarizes, formats raw logs from any source (structlog JSON, CloudWatch output, stdout). Works on logs already in hand.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `docs-updater`        | sonnet-4-6 | Updates README, CLAUDE.md, ARCHITECTURE.md, CHANGELOG.md after code changes. Detects which doc needs the update; proposes diffs.                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `docker-runner`       | haiku-4-5  | Executes docker / docker compose commands (build, run, exec, logs, ps, compose up/down/restart/logs). Returns concise summary — image tag/size for builds, container state for ps, error chain for failures. Refuses destructive ops (rm/rmi/volume rm/prune/push/down -v) without explicit confirmation.                                                                                                                                                                                                                                            |
| `docker-log-inspector` | haiku-4-5 | Read-only Docker container log reader + bug hunter — the `cloudwatch-inspector` pattern for local containers. Pulls logs (`docker logs` / `docker compose logs`, bounded `--tail`/`--since`, never `-f`) from running OR exited containers, filters for errors/exceptions, returns VERBATIM error blocks (timestamp, exception class, top-3 traceback frames) + crash diagnosis via `docker inspect` (exit code, OOMKilled, restart-count/crash-loop). Correlates failures across compose services by timestamp. Never build/run/up/down/restart/exec — refuses + points at `docker-runner`. For logs already in context use `log-filter`. |
| `frontend-builder`    | haiku-4-5  | Builds frontend / web apps — npm/pnpm/yarn build, vite/next/astro/nuxt/tsc -b. Returns success + bundle size + top chunks; or tight error chain for failures. Never runs dev server, never modifies config.                                                                                                                                                                                                                                                                                                                                          |
| `gh-runner`           | haiku-4-5  | Read-only GitHub CLI (`gh`) inspection — PRs, issues, repos, releases, workflow runs, checks, comments, search. Returns tight summaries (PR table, issue header + body, failed CI step + error chain). Refuses any mutation (`gh pr create/merge/close`, `gh issue create`, `gh workflow run`, `gh secret set`, POST/PATCH/DELETE API calls).                                                                                                                                                                                                        |
| `http-runner`         | haiku-4-5  | Read-only HTTP requests — runs curl/wget against an endpoint and returns status + key headers + a trimmed/jq-extracted body (not the full payload). Masks credentials; one line for health checks. Not for `curl \| sh` installs or large downloads. Pairs with the `wait-for-ready` skill.                                                                                                                                                                                                                                                          |
| `email-inspector`     | haiku-4-5  | Read-only email triage via Gmail / Outlook / IMAP MCPs — filter inbox (Gmail-style operators: `from:`, `subject:`, `label:`, `is:unread`, `newer_than:`), summarize results, returns VERBATIM error/alarm text for CloudWatch / PagerDuty / Sentry / GitHub notification bodies. Refuses send / archive / delete / label changes. Pairs with `incident-responder` (hands off the verbatim alarm reason for live investigation).                                                                                                                      |
| `e2e-scenario-runner` | haiku-4-5  | Executes generic multi-step end-to-end scenarios — setup via MCPs (Atlassian / Slack / etc.), trigger Lambdas / HTTP endpoints, poll DDB / Postgres / SQS / Step Functions for downstream effects, scan CloudWatch logs for errors. Returns structured BLOCK/HIGH/MEDIUM/INFO report per step with evidence (status, latency, log excerpt, file:line root-cause hint). Stops on first BLOCK by default. **Never attempts fixes** — that's the main session's job after reading the report. No hardcoded service names — user describes the scenario. |
| `git-audit`           | haiku-4-5  | Audits git repo branch + worktree state. Categorizes every branch as MERGED / OPEN-PR / ACTIVE-WORKTREE / UNMERGED-WORK / STALE-REMOTE-GONE with ahead/behind counts. Presents the full picture, then (with explicit confirmation) executes safe deletions. Use to understand branch/worktree state — do NOT use for single inspection commands (`git-runner`), creating commits (`git-committer`), or the end-of-session batch cleanup ritual (`git-cleanup`).                                                                                                                                                              |
| `git-cleanup`         | haiku-4-5  | End-of-session cleanup. Safety-scan first: blocks on uncommitted files, unpushed commits, and active Claude sessions in worktrees. Then presents a removal plan for merged/stale branches and orphaned worktrees — executes only after one explicit confirmation. Finishes by pulling latest main. Designed to be called once at the end of every session to prevent worktree explosion, branch accumulation, and lost work.                                                                                                                         |
| `repo-cleaner`        | haiku-4-5  | Filesystem cruft remover — empty folders, build artifacts, `__pycache__`, `node_modules`. Detects repo language and applies matching safe-to-delete patterns. Runs `git ls-files` before touching anything — never removes committed assets or lockfiles.                                                                                                                                                                                                                                                                                            |
| `env-audit`           | haiku-4-5  | Read-only deployment-state diff for any environment. Compares Lambda last-modified timestamps vs recent git commits, checks Terraform drift, detects pending Alembic/Flyway migrations. Returns a structured "needs update" report — never writes anything.                                                                                                                                                                                                                                                                                          |
| `env-sync`            | sonnet-4-6 | Brings a **non-prod** environment up to date: audit → tf-plan → confirm with user → tf-apply → Lambda deploy → migrations → smoke test. Hard-blocks on any environment name containing `prod`/`production`/`prd`. Never applies changes without showing the full plan and getting explicit confirmation.                                                                                                                                                                                                                                             |

#### 1.2 AWS

| Agent                     | Model      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cloudwatch-inspector`    | haiku-4-5  | Queries CloudWatch Logs and Metrics. Runs Logs Insights queries, filters by pattern/severity/time. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `s3-inspector`            | haiku-4-5  | Inspects S3 buckets, prefixes, lifecycle, encryption, versioning. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `iam-auditor`             | haiku-4-5  | Audits IAM roles, users, policies, trust relationships. Flags wildcard permissions and stale credentials. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                            |
| `sqs-monitor`             | haiku-4-5  | Monitors SQS queue depths, DLQs, oldest message age, in-flight counts. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `dynamodb-inspector`      | haiku-4-5  | Inspects DynamoDB tables: schema, GSI status, item count, capacity mode. Limited scans. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `step-functions-tracer`   | haiku-4-5  | Traces Step Functions executions, identifies failed states, extracts error chains. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `ecr-manager`             | haiku-4-5  | Lists ECR repos, images, tags. Can prune old images with explicit confirmation.                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `cost-explorer`           | haiku-4-5  | Queries Cost Explorer for spend by service/tag, forecasts, anomalies. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `cost-audit-runner`       | sonnet-4-6 | Multi-service read-only WASTE hunt (idle/orphaned Lambda versions, EIPs, EBS, NAT, log groups, RDS, S3, DynamoDB, Secrets). Emits prioritized findings with rough $/mo estimates + NON-EXECUTED `fix_commands` for the user to review. Never mutates, never `get-secret-value`. Complements `cost-explorer` (which only does CE-API spend totals).                                                                                                                                                                              |
| `rds-postgres-query`      | haiku-4-5  | Read-only SQL on AWS RDS/Aurora Postgres. Handles IAM auth and RDS Proxy. Only SELECT/EXPLAIN/SHOW.                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `terraform-deployer`      | haiku-4-5  | Executes terraform init/plan/apply/destroy. Always shows plan; never applies/destroys without explicit confirmation.                                                                                                                                                                                                                                                                                                                                                                                                            |
| `terraform-reviewer`      | sonnet-4-6 | Reviews Terraform code and plan output for security, cost, IAM scope, operational risks. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `cloudformation-deployer` | haiku-4-5  | Executes CloudFormation via change sets. Validates, describes, deploys after confirmation.                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `cloudformation-reviewer` | sonnet-4-6 | Reviews CloudFormation templates and change sets for security and operational risks. Read-only.                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `aws-events-scheduler`    | haiku-4-5  | Inspects + (with confirmation) modifies EventBridge rules + Scheduler schedules — list, describe, put-rule, put-targets, create-schedule. Refuses writes without explicit "yes update/delete/disable" confirmation. Flags Terraform-managed rules and recommends IaC change.                                                                                                                                                                                                                                                    |
| `dynamodb-mutator`        | sonnet-4-6 | DynamoDB WRITES (put-item, update-item, delete-item, batch-write, transact-write). Confirmation gate enforced — refuses without explicit "yes delete/write" in the prompt. Captures BEFORE-snapshot, returns ALL_OLD for rollback. Prod-pattern tables (`*-prod-*`) need extra "prod confirmed". Closes the `subprocess.run([... 'dynamodb', 'delete-item' ...])` heredoc-bypass loophole.                                                                                                                                      |
| `secrets-fetcher`         | haiku-4-5  | AWS Secrets Manager READ — returns metadata only (ARN, last-rotated, KMS key, JSON top-level keys), NEVER the secret value. Refuses writes (create/update/delete/rotate). If caller needs the value to execute something, emits a copy-paste shell snippet for the user's own terminal rather than executing it.                                                                                                                                                                                                                |
| `aws-lambda-deployer`     | haiku-4-5  | Executes Lambda code-deploys, invokes, and smoke tests (`aws lambda update-function-code`, `aws lambda invoke`, `make deploy-lambda*`, `make test-lambdas`). Returns per-function status + S3 upload + ARN updates; groups identical failures across N functions; surfaces well-known causes (KMS/Decrypt, ResourceConflict Pending, RequestEntityTooLarge, ImportError after build). Refuses config changes (`update-function-configuration`, `publish-version`, `put-concurrency`) and deletes without explicit confirmation. |
| `ecs-inspector`           | haiku-4-5  | Read-only ECS inspection — `describe-task-definition`, `describe-service`, `describe-tasks`. Redacts all env var values and secret ARNs (names only). Never modifies cluster state (`register-task-definition`, `update-service`, `run-task`, `stop-task`). Note: `list-*` calls have short output and are fine in the main session.                                                                                                                                                                                            |

#### 1.3 Databases (non-AWS)

| Agent            | Model     | Description                                                                                                                        |
| ---------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `postgres-query` | haiku-4-5 | Read-only SQL on generic Postgres (local, Docker, Supabase, Neon). Only SELECT/EXPLAIN/SHOW. Use `rds-postgres-query` for AWS RDS. |

#### 1.4 Python

| Agent                    | Model      | Description                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------ | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python-refactorer`      | sonnet-4-6 | Refactors Python code to brunofaust-python-style conventions: PEP 695 generics, asyncio.TaskGroup, structlog, strict typing. Proposes diffs; never auto-applies.                                                                                                                                                                                                                                                                          |
| `python-deps`            | haiku-4-5  | Executes Python dep-manager commands (uv/pip/poetry/pipx) and returns a concise summary — success, key changes, useful error chain, well-known fix suggestion when obvious. Never edits lockfiles or pyproject.                                                                                                                                                                                                                           |
| `migration-reviewer`     | sonnet-4-6 | Reviews Alembic migrations for safety, asyncpg correctness, ENUM patterns, lock contention, backfill docs, downgrade reversibility, and ORM consistency. Returns a BLOCK/WARN/INFO scored report with line refs. Read-only — never applies migrations. Pairs with the `alembic-migration` skill.                                                                                                                                          |
| `python-module-migrator` | haiku-4-5  | Mechanically executes a Python module move plan — `git mv` + repoint every importer (perl look-around, no double-nesting) + repoint test `patch()` targets + verify `pytest --collect-only` with zero residual refs. Has finish discipline (never leaves the tree half-moved). Never commits. Executes the plan; does NOT design layout (Sonnet) or refactor logic (`python-refactorer`). Pairs with the `python-module-migration` skill. |
| `test-author`            | sonnet-4-6 | WRITES unit tests to close a coverage gap (e.g. file ≥ 85% / total ≥ 90%). Measures gaps via `pytest --cov`, writes behavior-asserting tests following the `brunofaust-python-style` conventions (factories, DI not module-patching, tests mirror src/). No coverage-gaming, never edits source to fudge the number. Pairs with `test-runner` (author writes → runner verifies).                                                          |

#### 1.5 Web

| Agent          | Model      | Description                                                                                                                                                                                                                                                                                                                                                                                                       |
| -------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `seo-runner`   | haiku-4-5  | Executes live SEO / GEO / AEO audits via curl — Google PageSpeed Insights, Mozilla HTTP Observatory v2, W3C Markup Validator, on-page meta scrape, robots.txt + sitemap.xml + llms.txt fetch, security headers, AI-bot policy analysis. Returns severity-scored report (BLOCK / HIGH / MEDIUM / GOOD) with actionable priority fixes. Read-only. Pairs with the `seo` skill for the rule knowledge.               |
| `seo-reviewer` | sonnet-4-6 | Static code review for SEO / GEO / AEO — reads HTML, JSX/TSX, Next.js (App + Pages router), Astro, Remix, Gatsby, MDX, plus `robots.txt` / `sitemap.xml` / `llms.txt`. Framework-aware (knows `metadata` / `generateMetadata` / `<Head>` / Astro frontmatter). Returns BLOCK/HIGH/MEDIUM/INFO findings with file:line refs and code-block fix snippets. Read-only. Use BEFORE deploy. Pairs with the `seo` skill. |

#### 1.6 Support (cross-cutting)

| Agent                | Model      | Description                                                                                                                                                                                                                                                                                                                                                                                                                  |
| -------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `debugger`           | sonnet-4-6 | Root-cause analysis on bugs, test failures, distributed system issues. Forms hypotheses, verifies cheaply, proposes minimum fix.                                                                                                                                                                                                                                                                                             |
| `incident-responder` | sonnet-4-6 | Coordinates active-incident investigation across AWS services. Builds a unified timeline. Produces postmortem-ready summary.                                                                                                                                                                                                                                                                                                 |
| `test-runner`        | haiku-4-5  | Runs tests (pytest, vitest, jest, mocha, playwright, go test, cargo test). Returns pass/fail counts + failed test IDs + first error per failure — no full tracebacks. Never modifies test files. Use for any "run tests" request to keep pytest output out of main context.                                                                                                                                                  |
| `friction-analyzer`  | sonnet-4-6 | Mines a session transcript (JSONL, via jq — never dumps it) for FRICTION — reverts, repeated corrections, command thrash, a guard firing repeatedly, raw-command dispatch leaks, re-derived gotchas — and proposes a preventative rule per pattern (guard hook / CLAUDE.md rule / agent-or-skill improvement) with verbatim evidence. Read-only — proposes, never edits hooks/settings/CLAUDE.md. Pairs with `claude-hooks`. |
| `lessons-extractor`  | sonnet-4-6 | Diff-retrospective extractor. Reads the DIFFS in an assigned PR/commit RANGE (not just descriptions), clusters recurring root causes (mock drift, real-dep gaps, config/wiring, distributed correctness, security, ownership, LLM seams), and proposes guardrails — checking each candidate against the repo's EXISTING enforcement (prek/CI/CLAUDE.md/skills) so it proposes only NEW gates. Read-only. Caller partitions a large range and fans out several in parallel, then merges. Mines shipped code (vs `friction-analyzer`/`session-harvest`, which mine chat histories). Pairs with the `diff-retrospective` skill. |

### 2. Skills

#### 2.1 Python

| Skill                   | Description                                                                                                                                                                                                                                                                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| brunofaust-python-style | Modern Python 3.14+ coding standards for async-first, type-safe production code. Pydantic validation at every boundary (Lambda events, ECS env vars), flaky-test prevention via test data isolation (dynamic DB ids, per-test ownership, no cross-tenant FK, mandatory `pytest-xdist`), and scoped global processes (run-for-one parameter + scope-aware DynamoDB idempotency where a global run supersedes a customer run). Optional Postgres tenant-isolation hardening (RLS enforcement + non-blocking audit table, no-code-change e2e for real lambdas). Reference files per topic (type-hints, error-handling, async-patterns, config, testing, data-modeling, scoped-processes, tenant-isolation, …).                                                                                                                                                                                                                                                 |
| alembic-migration       | Generate Alembic migrations following myapp patterns — naming, backfill safety, merge resolution, ENUM handling, asyncpg query syntax. Anti-patterns table for common mistakes. Ships a `PreToolUse`/`Edit\|Write` companion hook that fires a once-per-session reminder when you edit an Alembic migration (a `versions/`/`alembic/` path, or a `migrations/` file whose content carries an Alembic signal — so it stays quiet on Django et al.).                                                                                                                                                  |
| python-module-migration | Safely relocate Python modules + repoint imports. The git mv + perl-repoint + collect-only verify recipe and the foot-guns (negative-lookbehind to avoid double-nesting, zsh word-split, BSD-grep false-positives, ruff-hook ordering, untracked-dest check, patch-target drift). Pairs with the `python-module-migrator` agent. |

#### 2.5 Generic (cross-cutting)

| Skill                       | Description                                                                                                                                                                                                                                                                                                                                                                 |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| adversarial-verification    | Evidence-first verification discipline. 5-step gate (IDENTIFY/RUN/READ/VERIFY/CLAIM) before claiming work complete. Forbids hedging language until evidence is quoted. Includes revert-and-rerun regression check + try-to-break failure probes.                                                                                                                            |
| code-review-discipline      | Discipline for any review-style task (code review, security review, SEO review, migration review, architecture review). Enforces uniform output format, mechanical Approve/Warning/Block verdict rule, PR merge-readiness pre-check, and "report-only" rule. Pair with domain-specific review skills — this one defines the output shape.                                   |
| prek                        | Prek setup, config reference, and gotchas. Use when adding new hooks to `prek.toml`, debugging hook failures, or understanding the `final_check.py` Claude Code hook pattern. Covers `stages = ["pre-commit"]` requirement, `SKIP=` env var, `prek autoupdate`, and the 2-failure stop rule.                                                                                |
| self-rationalization-guard  | Behavioral guard — detects 7 execution-avoidance patterns (explaining instead of executing, restating constraints, pre-emptive surrender, spirit-vs-letter dodge, retroactive scope shrink, false-equivalence substitution, authority deflection) and forces redirect to action.                                                                                            |
| subagent-prompting          | 10-point dispatch-prompt checklist for high-quality Agent/Task tool calls. Subagent has zero memory of parent session — inline every input. Includes return-status enum (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED / OVER_BUDGET) + parallel-dispatch independence test.                                                                                          |
| verification-loop           | Structured pre-PR verification with explicit PASS/FAIL per gate. Six phases (lint/format → types → tests → coverage → security/secrets → diff review) culminating in a READY / NOT READY verdict. Complements `adversarial-verification` (claim verification) by enforcing a uniform gate format before any PR opens.                                                       |
| architecture-decision-guard | Guardrails before adding structural boundaries — don't add a layer/tier/abstraction without a concrete present need; prefer containment (single-owner + banned-api) over speculative layering. Smell tests, revert-the-split guidance, gate-rollout-without-backlog. Pairs with `brunofaust-python-style` + `python-module-migration`.                                      |
| regression-gates            | Introduce a NEW lint/quality/correctness gate to a brownfield repo WITHOUT a big-bang cleanup — the regression-only baseline harness + the three-step warn→error rollout. Ships a runnable `baseline_gate.py` (new findings fail, baselined pass, **stale baseline entries also fail** so the file only shrinks, keyed by stable identity, fail-closed) + example checkers (`migration_head`, `ci_env_guard`, `junk_drawer`, `module_private`). Encodes "a rule in prose gets violated; a rule encoded as a checker holds". Pairs with `architecture-decision-guard` + `prek` + `repo-audit`. |
| mock-drift-sweep            | Sweep and update every mock/fake/stub after a signature/return/exception/import change — so green tests don't hide a broken production seam (the #1 silent failure). Locate all forms (patch-strings, autospec, hand fakes, mock servers, recorded fixtures), prefer spec'd mocks, build config mocks from the real model, and keep one real-dependency test per contract. Notes the "`--collect-only` doesn't catch renamed patch attributes" trap. Pairs with `adversarial-verification` + `test-author`.                |
| diff-retrospective          | Turn a range of merged PRs/commits into durable guardrails — read the DIFFS (not descriptions), cluster recurring root causes, and emit per cluster (a) a CLAUDE.md rule and (b) where possible an executable checker. Complements `session-harvest` / `friction-analyzer` (chat histories) by mining the SHIPPED CODE. Pairs with the `lessons-extractor` agent for parallel fan-out.                |
| research-before-build       | Step-0 reuse discipline before writing net-new code — walk the hierarchy (internal codebase → Context7/vendor docs → `gh search` for an 80%-solution → package registries → web), then adopt/fork/wrap/build with explicit license/maintenance/supply-chain criteria + a short research note. Reuse beats generation on tokens + reliability.                               |
| security-audit              | Whole-system security audit + threat modeling — OWASP Top 10 + STRIDE, six layers (app / secrets / dependency supply-chain / CI-CD / LLM-AI / cloud-infra), daily zero-noise gate vs deep periodic mode + a "build safe action-taking tools" section (dry-run default, bounded params, rollback). Complements `web-security` (frontend) + `iam-auditor` (AWS IAM). |
| claude-hooks                | Authoring + debugging Claude Code hooks — events/matchers, the stdin/stderr/exit-code contract, the two archetypes (guard blocks with exit 2 vs utility never breaks a turn → exit 0), resilient-shim pattern, exit-code capture, `settings.json` wiring, and payload testing. References the repo's `src/claude_all/hooks/` examples.                                              |
| wait-for-ready              | Poll a service / container / port / DB until healthy (timeout + interval) instead of a fixed `sleep N` — a generic `wait_until` poller plus ready-made probes (HTTP health, TCP port, `pg_isready`, docker healthy, compose up). Ships a PreToolUse hook that catches `sleep && curl` poll-by-delay loops and points here.                                                  |
| humanink                    | Detect + rewrite AI writing patterns so text reads human — 35 patterns, AI-probability score (0–100), context modes (academic/casual/corporate/creative) + severity levels, style fingerprinting. Multilingual: English / Brazilian Portuguese / Spanish (also French, German, Japanese, Italian); force a language with `--pt` / `--es`. Vendored from [sirambrosio/humanink](https://github.com/sirambrosio/humanink) (MIT). |
| repo-audit                  | Whole-repo, point-in-time code-quality audit for an existing/brownfield codebase in ANY language. Audits against generic boundaries (format/lint, type safety, complexity, layering) and also drives `session-harvest`. For bug hunts, fans out parallel deep-dive lanes (`bug-hunter` for hot code, bespoke one-off prompts for infra configs). See "First run — audit & customize per project" above.                                                                                                                                                                                                                                                |
| session-harvest             | Mines AI coding-assistant session histories (Claude Code, Cursor, Codex, GitHub Copilot) for recurring friction, re-derived knowledge, and repeated workflows — returns a prioritized backlog of reusable resources to create (skills / agents / hooks / instructions). Run standalone for a quick "what should I automate next?" pass; `repo-audit` already includes it.                                                                                                                                                     |
| ship                        | Workflow orchestrator (`/ship`) — lightweight pre-commit pipeline: `test-coverage gate` → `lint-fixer` → `test-runner` → `verification-loop` → (confirm) → `git-committer`. The test-coverage gate runs first (before lint/test): it confirms the change ships unit tests for its new/changed code AND — where an e2e/integration suite exists — e2e/integration tests validating each **business requirement** of the feature (user-observable behaviour, not the implementation); a feature with no business-requirement coverage is a hard stop. Stops on first hard failure, PASS/FAIL per step. No review/PR (use `ship-pr` for those). User-invoke only. Sequences existing agents/skills; never re-implements them.                                                                                                                                                          |
| merge-main                  | Workflow orchestrator (`/merge-main`) — merge `origin/main` into the current branch and resolve **both** textual and **semantic** conflicts, for parallel sessions syncing a freshly-landed main. Calling the skill IS the decision to merge — it doesn't re-ask. A clean `git merge` (0 textual conflicts) can still be broken: main touched a file this branch deleted, changed a contract this branch still calls, or removed a symbol it references. Sequence: check incoming changes + textual conflicts via `git merge-tree` (working tree untouched) → semantic check (delete/modify ∩, rename/move, dangling-reference via `git grep` of the would-be merged tree, contradicting-logic — delegated to a subagent) → merge `--no-commit` → resolve textual conflicts → resolve semantic conflicts, validated by gates (`lint-fixer` → `test-runner` → `verification-loop`) → finalize + summarize. Checks semantics **before** merging so resolution is informed; **only stops to ask** on huge differences / high-risk impact (security contracts, schema/migration, ambiguous either-side resolution). Includes an older-git fallback (throwaway `git worktree`). Local merge only — never pushes / opens a PR (use `ship-pr`). Model-invocable and ships a `claude_md.md` rule, so merging origin/main routes through it automatically. Also ships a `PreToolUse`/`Bash` companion hook that, on the first `git merge`/`git pull` of `origin/main` in a session, fires a non-blocking nudge to route through `/merge-main` (deduped once per session, so it stays quiet during merge-main's own merge).                                                                                                                                                   |
| ship-pr                     | Workflow orchestrator (`/ship-pr`) — heavyweight pre-PR pipeline: optional `/simplify` → the `/ship` gates (`test-coverage gate` → `lint-fixer` → `test-runner` → `verification-loop`) **plus** `/code-review` (gate on Block) → conditional `security-review` → `docs-updater` (revise CLAUDE.md + docs from the diff) → (confirm) `git-committer` → open a DRAFT PR (confirm). The test-coverage gate runs before lint/test and hard-stops on a feature that lacks unit tests for its code or e2e/integration tests for its business requirements. Review runs once here, not per commit. Optional tail: `review <pr#>` for an already-open PR. Model-invocable and ships a `claude_md.md` rule, so opening a PR routes through it automatically (best practice). Also ships a `PreToolUse`/`Bash` companion hook that, on the first `git commit`/`git push` of a session, fires a non-blocking nudge to route the change through `/ship-pr` (deduped once per session, so it stays quiet during ship-pr's own commit/push).                                                                                                                                                   |
| resource-scaffolder         | Generation engine — turns an APPROVED proposal (from `session-harvest` / `repo-audit` / `diff-retrospective` / `friction-analyzer` / `lessons-extractor`) into a correctly-scaffolded skill / subagent / hook / instruction, for a project's `.claude/` or a claude-all contribution. The build step those propose-only resources lack. Verifies discovery + lint before done. Pairs with `claude-hooks` + `subagent-prompting` + `regression-gates`.                                  |
| implement-loop              | Workflow orchestrator (`/implement-loop`) — implement an approved backlog/PRD one story at a time, each in a FRESH subagent context, in dependency order, committed with an acceptance-criteria trace (`ac_trace: bN`), reviewed diff-only (ideally cross-model), progress fed forward via a progress file. The structured "story-by-story" form of the Ralph loop — prevents context drift on multi-story features. Pairs with `requirements-ears` (stories + `[bN]` ids), `subagent-prompting`, `adversarial-verification`, `code-review-discipline`, and `/ship-pr`. User-invoke only. Inspired by dotclaude's `ralph-adversarial`.                       |
| retro                       | Workflow orchestrator (`/retro`) — unified "learn & harden": gathers from THREE sources (`session-harvest` history + `diff-retrospective`/`lessons-extractor` PR diffs + `repo-audit` code), synthesizes ONE deduped ranked backlog, and after confirm generates resources via `resource-scaffolder` / wires gates via `regression-gates`. Report-only until the confirmed build phase. Merges the history-mining and PR-retrospective passes into one synthesis. **Tip: schedule it ~weekly** (a cron/CI job, a Claude Code routine via `/schedule`, or the `/loop` skill) to keep the repo and its Claude resources continuously updated; it suggests contributing any generic generated resources back to claude-all.                       |
| requirements-ears           | Convert a business idea, feature request, or change into precise, testable acceptance criteria using EARS notation. Use BEFORE implementing when the requester specifies behavior at the business level. Pairs with brainstorming (decides WHAT to build) by pinning HOW each behavior must work; output feeds directly into tests.                                                                                                                                                                                           |

#### 2.2 Frontend

All four kept under one `frontend/` folder — React-specific items are a subset of frontend work. Filter with `claude-all skills react` if you only want the React-named ones. These three skills and `web-design-guidelines` are **vendored from Vercel** ([agent-skills](https://github.com/vercel-labs/agent-skills), [web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines)) — see `vendored.json` + each skill's `ATTRIBUTION.md`, and update via `scripts/vendor_sync.py`. The registry also carries `watch` entries for skills *derived* from upstream repos (synthesized, not copied — e.g. `adversarial-verification`): the sync never touches their files, it just reports upstream commits since the last review (`--ack <id>` after reviewing).

| Skill                         | Description                                                                                                                                                                                                                                                                                     |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| react-best-practices          | React + Next.js performance patterns from Vercel Engineering — bundle optimization, data fetching, render performance.                                                                                                                                                                          |
| composition-patterns          | React composition patterns that scale — replace boolean prop sprawl, build flexible component libraries.                                                                                                                                                                                        |
| react-view-transitions        | React View Transition API — `<ViewTransition>`, `addTransitionType`, route/list/shared-element animations.                                                                                                                                                                                      |
| web-design-guidelines         | UI/UX/accessibility review checklist — design audits, "review my UI", "check accessibility".                                                                                                                                                                                                    |
| web-security                  | Frontend/web-app security — XSS (`dangerouslySetInnerHTML`, `safeUrl()` scheme allowlist), per-framework env-var leak table, Server-Actions-as-public-API validation, httpOnly cookie sessions (never localStorage), CSP + nonces, prototype pollution, source maps. Pairs with `seo-reviewer`. |
| react-correctness             | React component/hook *correctness* (vs the Vercel *perf* skill) — useEffect when-NOT-to-use, state-location decision tree, derived-state-not-effects, stale closures, keys for dynamic lists, default-don't-memoize, React 19 hooks (`use`/`useOptimistic`/`useActionState`/ref-as-prop).       |
| react-testing                 | Frontend testing (RTL/Vitest/Jest/Playwright-CT) — query priority (role→testid last), `userEvent`>`fireEvent`, MSW at the network layer, anti-snapshot stance, per-layer coverage table, a11y/axe, anti-patterns. The frontend counterpart to `test-author`. Ships a `PreToolUse`/`Edit\|Write` companion hook that fires a once-per-session reminder when you edit a test file (`*.test.*`/`*.spec.*` or `__tests__/`).                                    |

#### 2.3 AWS

| Skill                 | Description                                                                                                                                                                                                                                                                                                                                                                 |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| aws-architecture      | Serverless + event-driven AWS patterns — Lambda idempotency / VPC / cold starts, SQS visibility + DLQ, SNS vs EventBridge vs SQS decision matrix, DynamoDB partition design + single-table, Step Functions Express vs Standard, API Gateway HTTP vs REST, cost gotchas (NAT, CW Logs, cross-AZ). Anchored to AWS Well-Architected + Serverless Application Lens.            |
| aws-debug-loop        | Structured debug loop for AWS dev environments. Covers e2e and integration test failures — how to split a full test into isolated pieces, hotfix the dev environment directly (env vars, timeouts, image versions) before deploying, validate each fix in isolation, run independent pieces in parallel, and know when to declare a piece fixed vs redeploy.                |
| aws-cost-optimization | AWS cost / FinOps playbook. "AWS recommendation engines first" hierarchy (Cost Optimization Hub → Compute Optimizer → Trusted Advisor → Cost Explorer → CUR/Athena), Well-Architected 5 areas, waste catalog + idle criteria, RI/SP/Spot/Graviton/right-sizing/lifecycle levers, Infracost/Cloud Custodian, FOCUS. Pairs with `cost-audit-runner` + `cost-explorer` agents. |

#### 2.4 Web

| Skill | Description                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| seo   | SEO + GEO + AEO — classic search ranking, generative-engine citation (Perplexity / ChatGPT / Gemini / AI Overviews), and answer-engine optimization (featured snippets, PAA, voice). Covers on-page, JSON-LD (with deprecation warnings for HowTo / non-authority FAQPage), Core Web Vitals (LCP / INP / CLS with current thresholds), robots/sitemap/hreflang, AI-bot access (GPTBot, ClaudeBot, PerplexityBot), `llms.txt`, programmatic-page caps. |

### 3. Hooks

Standalone hook scripts in `src/claude_all/hooks/`, installed as a first-class kind — `claude-all --user hooks` (or `--project`) symlinks each `<name>.py` into `.claude/hooks/` and wires it into `.claude/settings.json` per the `hooks/hooks.json` manifest (`event` + `matcher` + `timeout`). Re-install sweeps and replaces any prior entry for the hook's script across all events (scoped to `.claude/hooks/` paths, so a same-named script living elsewhere is left untouched) — no double-firing. Most hooks are **non-blocking** reminders — exit 0 + JSON `hookSpecificOutput.additionalContext` (not `stderr`/exit 1, which the harness renders as a hook error). `destructive-command-guard` and `prek-stop-runner` (on a real prek failure) **hard-block** (exit 2); `config-protection` pauses the tool call for approval via `permissionDecision: "ask"`.

| Hook                           | Event         | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------ | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config-protection.py`         | `PreToolUse`  | Requires explicit user confirmation before editing the quality/safety gate: lint configs (`prek.toml`, `.ruff.toml`, `.pre-commit-config.yaml`) **and** Claude Code hook/settings files (`.claude/hooks/**`, `.claude/settings.json`). Prevents accidental side-effect changes — and silent gate-neutering (e.g. disabling a lint hook to unblock a refactor).                                                                                                       |
| `destructive-command-guard.py` | `PreToolUse`  | **Hard-blocks** (exit 2) catastrophic/irreversible Bash — `rm -rf /`, disk wipes, `DROP`/`TRUNCATE`, `git push --force` / `reset --hard`, `docker`/`kubectl`/volume destruction, `terraform destroy`, `aws ...delete-*`, fork bombs — with a safe build-dir allowlist (`node_modules`, `dist`, `.venv`, …) and an explicit `GUARD_OK=1` / `# guard:allow` override. Warns on risky-but-routine ops. Mechanically enforces the prose "STOP — destructive" guardrails. |
| `supply-chain-guard.py`        | `PreToolUse`  | Non-blocking reminder on package-install commands (`npm`/`pnpm`/`yarn`/`bun install\|add\|ci`, `pip`/`pipx install`, `uv add`/`uv pip install`, `poetry add`). Static checks: git/URL sources (bypass registry review), missing `--ignore-scripts` (npm lifecycle hooks run arbitrary code), a bare `install` with a lockfile present (use `npm ci` / `--frozen-lockfile`), Python alternate indexes (`--index-url`/`--extra-index-url` dependency-confusion, `--trusted-host` TLS-off). **Release-date cooldown:** alerts if a package being installed was published within the window (default 7d). Reads `upload-time` straight from `uv.lock` (so `uv sync` is checked **offline** — no network, no cache); for named installs / dateless lockfiles it does a small uncached live npm/PyPI lookup under a time budget that **fails open** (an unreachable registry never blocks). Reinforces `research-before-build` + `security-audit`. Env: `CC_SUPPLY_CHAIN_OK=1` (silence), `CC_SUPPLY_CHAIN_NO_NETWORK=1` (skip live lookups; uv.lock dates still checked), `CC_SUPPLY_CHAIN_COOLDOWN_DAYS`. |
| `dev-server-tmux.py`           | `PreToolUse`  | Blocks long-running dev server commands (e.g. `npm run dev`, `uvicorn`, `next dev`) unless the session is inside a tmux pane — prevents orphaned background processes that outlive the Claude session.                                                                                                                                                                                                                                                               |
| `edited-files-accumulator.py`  | `PostToolUse` | After every `Edit`/`Write`/`MultiEdit`, appends the edited file path to a per-session temp file. Pairs with `prek-stop-runner.py` to enable per-response prek batch execution.                                                                                                                                                                                                                                                                                       |
| `prek-stop-runner.py`          | `Stop`        | Reads the accumulator written by `edited-files-accumulator.py`, runs `prek run` for both `pre-commit` and `pre-push` stages against the batch, then clears the file. Result: prek fires once per Claude response, not once per file edit. **Hard-blocks** (exit 2) on a real prek failure; if prek itself can't run (missing `uv`, timeout, or the shared 50s budget exhausted) it prints a short notice and exits 1 instead of crashing the turn. Bails immediately if already inside a stop-hook continuation (`stop_hook_active`), to avoid looping.                                                                                                                                                                                                                                                                                                                            |
| `suggest-compact.py`           | `PreToolUse`  | **Token-aware** /compact reminder (matcher `""`). Reads the latest `message.usage` from the session transcript to estimate real context occupancy (`input + cache_read + cache_creation` tokens) and suggests `/compact` once it crosses a threshold (default 160K, env `CC_COMPACT_TOKEN_THRESHOLD`), re-suggesting as it climbs and resetting after a compaction. The transcript read is amortized (every Nth call); falls back to a tool-call cadence when no token signal is available. |
| `python-style-skill-loader.py` | `SessionStart` | Non-blocking reminder (matcher `""`) to invoke the `brunofaust-python-style` skill when the session's cwd looks like a Python project (`pyproject.toml`/`setup.py`/`setup.cfg`/a top-level or `src/` `*.py`). Silent in non-Python sessions. The proactive bookend to the skill's own edit-time reminder hook — it writes the **same** per-session dedup flag, so the two never stack a reminder. Install separately from the skill (`claude-all --user hooks python-style-skill-loader`). |

### 4. Plugins

Each plugin lives at `src/claude_all/plugins/<name>/plugin.json`. The installer dispatches on the `type` field:

| Type                 | Installer                                                 | Required fields                                  |
| -------------------- | --------------------------------------------------------- | ------------------------------------------------ |
| `claude-marketplace` | `claude plugin marketplace add` + `claude plugin install` | `marketplace`, `plugin`                          |
| `pip`                | `pipx install <package>[extras]`                          | `package` (optional: `extras`, `pin`, `command`) |

Optional fields:

- `post_install` — list of **typed steps** run after the main install. Each step is one of:

  - `{"type": "pip", "package": "<pkg>"}` — pip-install `<pkg>` into the plugin's pipx venv via
        `pipx inject` (optional: `"extras": ["x"]`, `"pin": "==1.2"`, `"target": "<other-app>"` to
        inject into a different venv than the plugin's own `package`).
  - `{"type": "bash", "command": ["foo", "install"]}` — run a command (optional: `"pwd": "sub/dir"`).
  - A bare argv list (e.g. `["foo", "install"]`) is still accepted as a legacy `bash` step.

    Example: `[{"type": "bash", "command": ["foo", "install"]}]`

- `post_install_message` — string printed after install, e.g. instructions the user must follow per-project.

No plugins currently installed — `code-review-graph` moved to § 6 Tools (installed via `uv tool install` from git, not pipx).

### 5. MCPs

Each MCP lives at `src/claude_all/mcps/<name>/mcp.json`. Installer runs `claude mcp add` at the chosen scope (`--user` → user scope, `--project` → writes `.mcp.json` in cwd).

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

| MCP          | Package                                 | Source                                                                                        | Description                                                                                              |
| ------------ | --------------------------------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `terraform`  | `@hashicorp/terraform-mcp-server`       | [hashicorp/terraform-mcp-server](https://github.com/hashicorp/terraform-mcp-server)           | Terraform Registry lookups, provider docs, module discovery, schema introspection.                       |
| `context7`   | `@upstash/context7-mcp`                 | [upstash/context7](https://github.com/upstash/context7)                                       | Fresh library docs on demand — resolves library IDs, returns current API/usage snippets.                 |
| `playwright` | `@playwright/mcp`                       | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)                       | Browser automation — navigate, click, fill, screenshot, evaluate JS.                                     |
| `postgres`   | `@modelcontextprotocol/server-postgres` | [mcp/server-postgres](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres) | Read-only SQL against a Postgres DB. **Edit connection URL after install** (see `post_install_message`). |

### 6. Tools

CLI tools installed at the OS level (not into `~/.claude/`). Each tool lives at `src/claude_all/tools/<name>/tool.json`. Two types are supported: `brew` (Homebrew) and `uv_tool` (`uv tool install` from a git URL).

Schema (`brew`):

```json
{
  "name": "mytool",
  "github": "https://github.com/org/mytool",
  "type": "brew",
  "tap": "org/mytool",
  "package": "mytool",
  "post_install": [
    {"type": "bash", "command": ["mytool", "init", "--global"]}
  ],
  "post_install_message": "Restart your shell so the hook activates."
}
```

Schema (`uv_tool`):

```json
{
  "name": "mytool",
  "github": "https://github.com/org/mytool",
  "type": "uv_tool",
  "git": "https://github.com/org/mytool",
  "package": "mytool",
  "extras": ["extra-a", "extra-b"],
  "post_install": [
    {"type": "bash", "command": ["mytool", "install"]}
  ],
  "post_install_message": "Run 'mytool build' inside each project where you want to use it."
}
```

A tool may also ship a `config_append.toml` companion — a TOML fragment appended to the tool's own config file during install. Reference it from a `post_install` bash step:

```json
{"type": "bash", "command": ["sh", "-c", "cat tools/mytool/config_append.toml >> \"$HOME/.config/mytool/config.toml\""]}
```

Installer:

- `brew`: checks `brew` on PATH (errors with `https://brew.sh/` link if missing) → `brew tap <tap>` (only if not already tapped) → `brew install <package>` (skipped if already installed)
- `uv_tool`: checks `uv` on PATH (errors with the astral.sh install link if missing) → builds `<package>[<extras>] @ git+<git>` → `uv tool install --force <spec>` (re-run is idempotent and picks up upstream changes)
- Either type then runs each `post_install` step in order, and injects the optional `claude_md.md` into `~/.claude/CLAUDE.md` or `./CLAUDE.md` (per `--user` / `--project`)

Installed tools:

| Tool                | Type      | Source                                                                        | Install                                                                                    | Purpose                                                                                                                                                                                                                                    |
| ------------------- | --------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rtk`               | `brew`    | [rtk-ai/rtk](https://github.com/rtk-ai/rtk)                                   | `brew install rtk` + `rtk init -g`                                                          | Rust Token Killer — explicit prefix model (`rtk git log`, `rtk aws …`). Wraps `git`, `grep`, `cat`, `find`, `ls`, `aws`, `make`, `terraform`, `pytest`, `gh`, `npm`, `eslint`, `playwright`, `psql`, `wc` to cut output token cost 60-90%. |
| `code-review-graph` | `uv_tool` | [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph) | `uv tool install "code-review-graph[communities,enrichment] @ git+..."` + `... install`     | Persistent incremental knowledge graph for token-efficient, context-aware code reviews. `communities` pulls in `igraph`, `enrichment` pulls in `jedi`.                                                                                   |

### 7. Instructions (standalone CLAUDE.md snippets)

A resource whose **only** effect is injecting a tagged block into `~/.claude/CLAUDE.md` — no
agent/skill/hook/tool to install. Each lives at `src/claude_all/instructions/<name>/claude_md.md` and is installed
with `claude-all --all --user <name>`. Use for main-session dispatch rules that target built-in
agents or cut across many agents (so they don't belong to any single agent's companion).

| Snippet           | Purpose                                                                                                       |
| ----------------- | ------------------------------------------------------------------------------------------------------------- |
| `delegate_search` | Routes broad/iterative codebase search to the built-in `Explore` agent instead of grep loops in main session. |
| `agent-era-rules` | Distilled standing rules from running AI agents on a production codebase (mock drift, gates, ownership, …).    |
| `tool-dispatch`   | Token-efficiency dispatch: built-in tools over Bash for filesystem; RAG over Grep; self-check before raw `aws`/`psql`/`terraform`. |
| `bash-safety`     | Credential-leak + destructive-write anti-patterns (`PGPASSWORD=`, `Bearer` tokens, secret echoes, raw DDB/SQL writes, heredoc bypass). |

## Model strategy

- **Haiku (haiku-4-5)** — mechanical tasks: read + report, run + summarize, execute deterministic CLI operations. The agent should refuse anything requiring judgment.
- **Sonnet (sonnet-4-6)** — reasoning: code review, refactoring, debugging, incident response, doc updates. Tasks where the right answer depends on context.

Opus is intentionally absent — these agents are for routine work, and Opus is reserved for sessions where reasoning depth justifies the cost.

## Analyzing your session history

The agents and dispatch rules here come from real usage — spotting commands that ran inline in the main (Opus) session when they should have been delegated. You can mine your own Claude Code history the same way.

Claude Code stores one JSONL transcript per session under `~/.claude/projects/<sanitized-cwd>/<session-id>.jsonl`. The command below extracts a compact, shareable view — your prompts, assistant replies, and every tool call with its key input — while dropping the bulky tool *outputs* (file dumps, command stdout, tracebacks) where size and secrets live:

```bash
find ~/.claude/projects -name '*.jsonl' -mtime -60 -print0 \
| xargs -0 cat \
| jq -rc 'def render: if .type=="tool_use" then "«"+.name+": "+(( .input.command // .input.file_path // .input.pattern // .input.query // .input.description // (.input|tostring) )|tostring|gsub("\n";" ")|.[0:800])+"»" elif .type=="thinking" then "«thinking»" else (.text // "") end; select(.isSidechain != true) | select(.toolUseResult == null) | {t:.timestamp, role:.type, text:(.message.content | if type=="string" then . elif type=="array" then [.[]|render]|join(" ") else "" end)|.[0:3000]} | select(.text != "")' \
> ~/claude-insights-60d.jsonl
```

- `-mtime -60` keeps the last 60 days (Claude Code's default retention is 30 — raise `cleanupPeriodDays` in settings to keep more).
- Stripping outputs turns a multi-hundred-MB history into a few MB. Still **review it before sharing** — prompts themselves can contain proprietary detail.

For the delegation question specifically, a frequency-ranked list of every distinct `Bash` command is the highest-signal artifact:

```bash
find ~/.claude/projects -name '*.jsonl' -mtime -60 -print0 \
| xargs -0 cat \
| jq -rc 'select(.toolUseResult==null) | .message.content // [] | (if type=="array" then .[] else empty end) | select(.type=="tool_use" and .name=="Bash") | .input.command' \
| sort | uniq -c | sort -rn > ~/claude-bash-60d.txt
```

Then hand the extract to Claude with a prompt like:

> Analyze this Claude Code session history (prompts + tool calls; outputs were stripped). Identify (1) **delegation gaps** — Bash/search/test/lint commands that ran inline in the main session but should route to a sub-agent; (2) **repeated manual sequences** worth turning into a skill or hook; (3) **agent-coverage holes**. Rank findings by token impact and propose concrete agent or dispatch-rule changes.

The `test-runner` / `lint-fixer` routing and the rules in `src/claude_all/instructions/` came directly from runs of this analysis.

The **`session-harvest`** skill automates and generalizes this recipe: it mines histories across **Claude Code, Cursor, Codex, and GitHub Copilot** and returns a prioritized backlog of resources to create (skills / agents / hooks / instructions), each with an estimated % improvement. Run it instead of doing the `jq` extraction by hand.

## Adding a new agent

1. Create the `.md` file in the right category folder.
1. Frontmatter must include `name`, `description` (detailed, with triggers), `model`, and `tools`.
1. Body describes capabilities, workflow, output format, and rules.
1. Test with `claude-all --list <category>` to verify discovery.
1. Update this README's table.

Description guidelines: be explicit about WHEN to trigger AND when NOT to trigger. List specific user phrasings. The router uses this text to pick agents — vague descriptions cause wrong delegation.

## Contributing back — share your findings

claude-all gets better the more projects it sees. When `repo-audit` or `session-harvest` surfaces a
reusable skill, agent, hook, or instruction in your project — something generic enough to help others,
not project-specific — **open a PR back into this repo** so the whole team benefits.

1. Branch and add the resource under the right category (`src/claude_all/agents/` · `src/claude_all/skills/` · `src/claude_all/hooks/` ·
   `src/claude_all/instructions/`), following "Adding a new agent" / "Adding a new agent or skill" in `CLAUDE.md`.
1. **Strip all project specifics** — use the generic placeholders in `CLAUDE.md` (`myapp`, `acme`,
   `example.com`, `TICK-`, …). No real project, company, domain, ARN, or internal tool names.
1. Run the gate: `prek run --all-files` (ruff + mypy + typos + the rest).
1. Open a PR at <https://github.com/brunofaust/claude-all> describing the pattern it captures and the
   evidence (which projects/sessions it came from). Where it fits, cite the estimated % improvement
   from `session-harvest`.

That's the loop: audit a project, harvest what worked, contribute the generic version back — and the
next project starts a step ahead.
