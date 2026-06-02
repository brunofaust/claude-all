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
│   │   ├── web/              # Web / SEO agents
│   │   └── support/          # Cross-cutting: debugging, incidents
│   ├── skills/               # Reusable skills (e.g., python style)
│   ├── hooks/                # Claude Code hook scripts (PreToolUse / PostToolUse / Stop)
│   ├── plugins/              # Claude Code plugins
│   ├── mcps/                 # MCP server configurations
│   └── tools/                # OS-level CLI tools (brew)
└── README.md
```

Future categories (travel, writing, research, etc.) live as siblings to `coding/`.

## Installation

### Requirements

- macOS or Linux
- Python 3.11+ (stdlib only — no pip installs)
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

### CLAUDE.md auto-injection

Any resource directory may ship a `claude_md.md` snippet:

- Agents (single file): `coding/agents/<cat>/<name>.claude_md.md`
- Skills / plugins / mcps (dir): `<resource-dir>/claude_md.md`

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
1. `.claude/settings.json` is merged (idempotent, deduped by command path)

Schema `hook.json`:

```json
{"event": "PreToolUse", "matcher": "Edit|Write", "timeout": 2000}
```

Shipped skill hooks are **non-blocking reminders** (exit code 1 — emits stderr, doesn't stop the tool). They fire only when the file being edited matches the skill's domain (e.g. `*.py` for python style, `*.tsx` with `<ViewTransition>` for view-transitions skill). Sonnet reads the stderr message and adjusts.

Target settings file:

- `--user` → `~/.claude/settings.json` + `~/.claude/hooks/`
- `--project` → `./.claude/settings.json` + `./.claude/hooks/`

## Coding

### 1. Agents

All agents follow the same pattern: a detailed `description` so Claude Code's auto-router picks the right one, a strict `model` (Haiku for mechanical work, Sonnet for judgment-heavy work), and a focused tool list.

#### 1.1 Generic (language-agnostic)

| Agent                 | Model      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code-quality`        | haiku-4-5  | Runs all available quality gates (prek, pre-commit, ruff, mypy, pytest, eslint, prettier, tsc, vitest). Reports failures only. Never auto-fixes.                                                                                                                                                                                                                                                                                                                                                                                                     |
| `lint-fixer`          | sonnet-4-6 | FIXES quality-gate findings (ruff, mypy, eslint, tsc, codecongruence). Clears the mechanical tier with `ruff --fix`/`ruff format`, then fixes judgment findings (types, complexity, semantic dedup) at the ROOT CAUSE — no `# type: ignore`/`# noqa`/config-loosening/`--no-verify`. Verifies with the gate + tests after each category. Pairs with `code-quality` (finds) + `test-runner` (confirms).                                                                                                                                               |
| `git-committer`       | haiku-4-5  | Stages changes, generates a Conventional Commits message, commits to current branch (optionally pushes). Never branches, merges, or rebases.                                                                                                                                                                                                                                                                                                                                                                                                         |
| `git-runner`          | haiku-4-5  | Read-only git inspection (log, diff, status, blame, show, branch, stash list). Returns tight summaries — author/file counts, not raw multi-page output. Prefers `rtk` wrapper if installed. Refuses any write/destructive git command.                                                                                                                                                                                                                                                                                                               |
| `log-filter`          | haiku-4-5  | Filters, summarizes, formats raw logs from any source (structlog JSON, CloudWatch output, stdout). Works on logs already in hand.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `docs-updater`        | sonnet-4-6 | Updates README, CLAUDE.md, ARCHITECTURE.md, CHANGELOG.md after code changes. Detects which doc needs the update; proposes diffs.                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `docker-runner`       | haiku-4-5  | Executes docker / docker compose commands (build, run, exec, logs, ps, compose up/down/restart/logs). Returns concise summary — image tag/size for builds, container state for ps, error chain for failures. Refuses destructive ops (rm/rmi/volume rm/prune/push/down -v) without explicit confirmation.                                                                                                                                                                                                                                            |
| `frontend-builder`    | haiku-4-5  | Builds frontend / web apps — npm/pnpm/yarn build, vite/next/astro/nuxt/tsc -b. Returns success + bundle size + top chunks; or tight error chain for failures. Never runs dev server, never modifies config.                                                                                                                                                                                                                                                                                                                                          |
| `gh-runner`           | haiku-4-5  | Read-only GitHub CLI (`gh`) inspection — PRs, issues, repos, releases, workflow runs, checks, comments, search. Returns tight summaries (PR table, issue header + body, failed CI step + error chain). Refuses any mutation (`gh pr create/merge/close`, `gh issue create`, `gh workflow run`, `gh secret set`, POST/PATCH/DELETE API calls).                                                                                                                                                                                                        |
| `email-inspector`     | haiku-4-5  | Read-only email triage via Gmail / Outlook / IMAP MCPs — filter inbox (Gmail-style operators: `from:`, `subject:`, `label:`, `is:unread`, `newer_than:`), summarize results, returns VERBATIM error/alarm text for CloudWatch / PagerDuty / Sentry / GitHub notification bodies. Refuses send / archive / delete / label changes. Pairs with `incident-responder` (hands off the verbatim alarm reason for live investigation).                                                                                                                      |
| `e2e-scenario-runner` | haiku-4-5  | Executes generic multi-step end-to-end scenarios — setup via MCPs (Atlassian / Slack / etc.), trigger Lambdas / HTTP endpoints, poll DDB / Postgres / SQS / Step Functions for downstream effects, scan CloudWatch logs for errors. Returns structured BLOCK/HIGH/MEDIUM/INFO report per step with evidence (status, latency, log excerpt, file:line root-cause hint). Stops on first BLOCK by default. **Never attempts fixes** — that's the main session's job after reading the report. No hardcoded service names — user describes the scenario. |
| `git-audit`           | haiku-4-5  | Audits git repo branch + worktree state. Categorizes every branch as MERGED / OPEN-PR / ACTIVE-WORKTREE / UNMERGED-WORK / STALE-REMOTE-GONE with ahead/behind counts. Presents the full picture, then (with explicit confirmation) executes safe deletions. Use for repo housekeeping — do NOT use for single inspection commands (`git-runner`) or creating commits (`git-committer`).                                                                                                                                                              |
| `git-cleanup`         | haiku-4-5  | End-of-session cleanup. Safety-scan first: blocks on uncommitted files, unpushed commits, and active Claude sessions in worktrees. Then presents a removal plan for merged/stale branches and orphaned worktrees — executes only after one explicit confirmation. Finishes by pulling latest main. Designed to be called once at the end of every session to prevent worktree explosion, branch accumulation, and lost work.                                                                                                                         |
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

| Agent                | Model      | Description                                                                                                                                                                                                                                                                 |
| -------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `debugger`           | sonnet-4-6 | Root-cause analysis on bugs, test failures, distributed system issues. Forms hypotheses, verifies cheaply, proposes minimum fix.                                                                                                                                            |
| `incident-responder` | sonnet-4-6 | Coordinates active-incident investigation across AWS services. Builds a unified timeline. Produces postmortem-ready summary.                                                                                                                                                |
| `test-runner`        | haiku-4-5  | Runs tests (pytest, vitest, jest, mocha, playwright, go test, cargo test). Returns pass/fail counts + failed test IDs + first error per failure — no full tracebacks. Never modifies test files. Use for any "run tests" request to keep pytest output out of main context. |

### 2. Skills

#### 2.1 Python

| Skill                   | Description                                                                                                                                                                                                                                                                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| brunofaust-python-style | Modern Python 3.14+ coding standards for async-first, type-safe production code.                                                                                                                                                                                                                                                 |
| alembic-migration       | Generate Alembic migrations following myapp patterns — naming, backfill safety, merge resolution, ENUM handling, asyncpg query syntax. Anti-patterns table for common mistakes.                                                                                                                                                  |
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
| research-before-build       | Step-0 reuse discipline before writing net-new code — walk the hierarchy (internal codebase → Context7/vendor docs → `gh search` for an 80%-solution → package registries → web), then adopt/fork/wrap/build with explicit license/maintenance/supply-chain criteria + a short research note. Reuse beats generation on tokens + reliability.                               |
| security-audit              | Holistic whole-system security audit + threat modeling — OWASP Top 10 + STRIDE, six layers (app / secrets / dependency supply-chain / CI-CD / LLM-AI / cloud-infra), daily zero-noise gate vs deep periodic mode + a "build safe action-taking tools" section (dry-run default, bounded params, rollback). Complements `web-security` (frontend) + `iam-auditor` (AWS IAM). |
| claude-hooks                | Authoring + debugging Claude Code hooks — events/matchers, the stdin/stderr/exit-code contract, the two archetypes (guard blocks with exit 2 vs utility never breaks a turn → exit 0), resilient-shim pattern, exit-code capture, `settings.json` wiring, and payload testing. References the repo's `coding/hooks/` examples.                                              |

#### 2.2 Frontend

All four kept under one `frontend/` folder — React-specific items are a subset of frontend work. Filter with `claude-all coding skills react` if you only want the React-named ones.

| Skill                         | Description                                                                                                                                                                                                                                                                                     |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| vercel-react-best-practices   | React + Next.js performance patterns from Vercel Engineering — bundle optimization, data fetching, render performance.                                                                                                                                                                          |
| vercel-composition-patterns   | React composition patterns that scale — replace boolean prop sprawl, build flexible component libraries.                                                                                                                                                                                        |
| vercel-react-view-transitions | React View Transition API — `<ViewTransition>`, `addTransitionType`, route/list/shared-element animations.                                                                                                                                                                                      |
| web-design-guidelines         | UI/UX/accessibility review checklist — design audits, "review my UI", "check accessibility".                                                                                                                                                                                                    |
| web-security                  | Frontend/web-app security — XSS (`dangerouslySetInnerHTML`, `safeUrl()` scheme allowlist), per-framework env-var leak table, Server-Actions-as-public-API validation, httpOnly cookie sessions (never localStorage), CSP + nonces, prototype pollution, source maps. Pairs with `seo-reviewer`. |
| react-correctness             | React component/hook *correctness* (vs the Vercel *perf* skill) — useEffect when-NOT-to-use, state-location decision tree, derived-state-not-effects, stale closures, keys for dynamic lists, default-don't-memoize, React 19 hooks (`use`/`useOptimistic`/`useActionState`/ref-as-prop).       |
| react-testing                 | Frontend testing (RTL/Vitest/Jest/Playwright-CT) — query priority (role→testid last), `userEvent`>`fireEvent`, MSW at the network layer, anti-snapshot stance, per-layer coverage table, a11y/axe, anti-patterns. The frontend counterpart to `test-author`.                                    |

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

Standalone hook scripts in `coding/hooks/`, installed as a first-class kind — `claude-all --user coding hooks` (or `--project`) symlinks each `<name>.py` into `.claude/hooks/` and wires it into `.claude/settings.json` per the `coding/hooks/hooks.json` manifest (`event` + `matcher` + `timeout`). Re-install **dedups by command basename**, so it cleanly replaces any prior entry (including a hand-wired one) — no double-firing. Most hooks are **non-blocking** reminders (`stderr`, exit 1); the two guards (`config-protection`, `destructive-command-guard`) **hard-block** (exit 2).

| Hook                           | Event         | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------ | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config-protection.py`         | `PreToolUse`  | Requires explicit user confirmation before editing the quality/safety gate: lint configs (`prek.toml`, `.ruff.toml`, `.pre-commit-config.yaml`) **and** Claude Code hook/settings files (`.claude/hooks/**`, `.claude/settings.json`). Prevents accidental side-effect changes — and silent gate-neutering (e.g. disabling a lint hook to unblock a refactor).                                                                                                       |
| `destructive-command-guard.py` | `PreToolUse`  | **Hard-blocks** (exit 2) catastrophic/irreversible Bash — `rm -rf /`, disk wipes, `DROP`/`TRUNCATE`, `git push --force` / `reset --hard`, `docker`/`kubectl`/volume destruction, `terraform destroy`, `aws ...delete-*`, fork bombs — with a safe build-dir allowlist (`node_modules`, `dist`, `.venv`, …) and an explicit `GUARD_OK=1` / `# guard:allow` override. Warns on risky-but-routine ops. Mechanically enforces the prose "STOP — destructive" guardrails. |
| `dev-server-tmux.py`           | `PreToolUse`  | Blocks long-running dev server commands (e.g. `npm run dev`, `uvicorn`, `next dev`) unless the session is inside a tmux pane — prevents orphaned background processes that outlive the Claude session.                                                                                                                                                                                                                                                               |
| `edited-files-accumulator.py`  | `PostToolUse` | After every `Edit`/`Write`/`MultiEdit`, appends the edited file path to a per-session temp file. Pairs with `prek-stop-runner.py` to enable per-response prek batch execution.                                                                                                                                                                                                                                                                                       |
| `prek-stop-runner.py`          | `Stop`        | Reads the accumulator written by `edited-files-accumulator.py`, runs `prek run` for both `pre-commit` and `pre-push` stages against the batch, then clears the file. Result: prek fires once per Claude response, not once per file edit.                                                                                                                                                                                                                            |
| `suggest-compact.py`           | `PreToolUse`  | Counts edit-class tool calls per session. Every N calls emits a non-blocking `/compact` reminder before the context window fills and forces an abrupt compaction.                                                                                                                                                                                                                                                                                                    |

### 4. Plugins

Each plugin lives at `coding/plugins/<name>/plugin.json`. The installer dispatches on the `type` field:

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

    Example: `[{"type": "pip", "package": "igraph"}, {"type": "bash", "command": ["code-review-graph", "install"]}]`

- `post_install_message` — string printed after install, e.g. instructions the user must follow per-project.

Installed plugins:

| Plugin              | Type                  | Source                                                                        | Description                                                                                                                                                                     |
| ------------------- | --------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code-review-graph` | pip (`[communities]`) | [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph) | Persistent incremental knowledge graph for token-efficient, context-aware code reviews. `igraph` is pip-installed into the plugin's pipx venv via `pipx inject` during install. |

### 5. MCPs

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

| MCP          | Package                                 | Source                                                                                        | Description                                                                                              |
| ------------ | --------------------------------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `terraform`  | `@hashicorp/terraform-mcp-server`       | [hashicorp/terraform-mcp-server](https://github.com/hashicorp/terraform-mcp-server)           | Terraform Registry lookups, provider docs, module discovery, schema introspection.                       |
| `context7`   | `@upstash/context7-mcp`                 | [upstash/context7](https://github.com/upstash/context7)                                       | Fresh library docs on demand — resolves library IDs, returns current API/usage snippets.                 |
| `playwright` | `@playwright/mcp`                       | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)                       | Browser automation — navigate, click, fill, screenshot, evaluate JS.                                     |
| `postgres`   | `@modelcontextprotocol/server-postgres` | [mcp/server-postgres](https://github.com/modelcontextprotocol/servers/tree/main/src/postgres) | Read-only SQL against a Postgres DB. **Edit connection URL after install** (see `post_install_message`). |

### 6. Tools

CLI tools installed at the OS level (not into `~/.claude/`). Each tool lives at `coding/tools/<name>/tool.json`. Currently only `type: brew` (Homebrew) is supported.

Schema:

```json
{
  "name": "rtk",
  "github": "...",
  "type": "brew",
  "package": "rtk",
  "tap": "rtk-ai/rtk",
  "post_install": [["rtk", "init", "-g"]],
  "post_install_message": "..."
}
```

Installer:

- Checks `brew` on PATH (errors with `https://brew.sh/` link if missing)
- `brew tap <tap>` (only if not already tapped)
- `brew install <package>` (skipped if already installed)
- Runs each `post_install` command (e.g. `rtk init -g`)
- Injects optional `claude_md.md` into `~/.claude/CLAUDE.md` or `./CLAUDE.md` (per `--user` / `--project`)

Installed tools:

| Tool  | Source                                      | Install path                       | Purpose                                                                                                                                                                                                                                               |
| ----- | ------------------------------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rtk` | [rtk-ai/rtk](https://github.com/rtk-ai/rtk) | `brew install rtk` + `rtk init -g` | Rust Token Killer — wraps `git`, `grep`, `cat`, `find`, `ls`, `aws`, `make`, `terraform`, `pytest`, `gh`, `npm`, `eslint`, `playwright`, `psql`, `wc` to cut output token cost 60-90%. Ships `rtk discover --all --since 30` to find missed adoption. |

## Model strategy

- **Haiku (haiku-4-5)** — mechanical tasks: read + report, run + summarize, execute deterministic CLI operations. The agent should refuse anything requiring judgment.
- **Sonnet (sonnet-4-6)** — reasoning: code review, refactoring, debugging, incident response, doc updates. Tasks where the right answer depends on context.

Opus is intentionally absent — these agents are for routine work, and Opus is reserved for sessions where reasoning depth justifies the cost.

## Adding a new agent

1. Create the `.md` file in the right category folder.
1. Frontmatter must include `name`, `description` (detailed, with triggers), `model`, and `tools`.
1. Body describes capabilities, workflow, output format, and rules.
1. Test with `claude-all --list coding <category>` to verify discovery.
1. Update this README's table.

Description guidelines: be explicit about WHEN to trigger AND when NOT to trigger. List specific user phrasings. The router uses this text to pick agents — vague descriptions cause wrong delegation.
