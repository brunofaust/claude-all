---
name: repo-audit
description: >-
  Whole-repo, point-in-time quality audit for an existing / brownfield Python codebase against the
  brunofaust-python-style standard and its enforcement stack (ruff, mypy strict, import-linter,
  banned-api, interrogate, vulture, bandit, gitleaks, skill_enforcer), plus an Infrastructure-as-Code
  pass (CloudFormation + Terraform: cfn-lint / tflint / checkov / tfsec) and a process-tooling pass
  that mines assistant histories for missing skills/agents/hooks (session-harvest). Also profiles the
  project (stack / frameworks / cloud / DB) and recommends which claude-all agents/skills/hooks to
  install for THIS repo plus net-new project-specific ones — run it per-project for tailored
  suggestions. Use when: onboarding a new
  colleague or inherited repo to the standard, running a first-time congruence audit on an existing
  product, establishing a quality baseline before adopting the gates, deciding what to fix first in a
  messy codebase, or doing a recurring (quarterly) health check. Produces a per-dimension scorecard
  plus a RATCHETING remediation roadmap that improves quality without a commit-blocking big-bang.
  Report-only — it measures and plans; fixes happen in later reviewed PRs (lint-fixer /
  python-module-migrator). Distinct from verification-loop (gates ONE diff before a PR),
  code-review-discipline (defines review output shape), and security-audit (security layers only —
  this delegates to it). Two modes: baseline (first run) and recurring (trend vs last baseline).
disable-model-invocation: false
user-invocable: true
---

# Repo Audit

A whole-repo congruence audit for an **existing / brownfield** Python codebase. It answers one
question — *"how far is this repo from the brunofaust-python-style standard, and what is the safe
order to close the gap?"* — and produces two artifacts: a **scorecard** and a **ratcheting
remediation roadmap**.

This is **not** a diff review. `verification-loop` gates one PR; `code-review-discipline` defines the
shape of a review; this audits the *whole repo* at a point in time and plans the cleanup.

______________________________________________________________________

## The brownfield thesis — measure, baseline, ratchet (never big-bang)

The instinct on inheriting a messy repo is to turn every gate to `--strict` and reformat everything.
That is the one thing you must not do. Enabling a strict hook on a legacy codebase lights up
**hundreds** of pre-existing findings, **blocks every commit**, and buries the *new* signal you care
about under legacy noise — a 400-file reformat PR also hides real regressions in the churn.

The audit's job is the opposite:

1. **Measure** every dimension in *count-only* mode — never fix during the audit.
1. **Baseline** the gates at *current-worst + a small margin* so nothing passing today breaks.
1. **Ratchet** the caps down one notch per PR/sprint, so the gate blocks *new* debt from day one
   while legacy debt is paid on a schedule.

See the `prek` skill, *"Rolling out a new hook or complexity cap without a backlog"*, and
`architecture-decision-guard`, *"Rolling out enforcement gates without a backlog"* — this skill is the
repo-wide application of that discipline.

______________________________________________________________________

## When to invoke / when not

**Invoke when:**

- A colleague joins or you inherit an existing product / brownfield Python repo.
- Before adopting `brunofaust-python-style` + the gate stack on a repo that never had them.
- You need to decide *what to fix first* in a large codebase (triage, not a blind sweep).
- Recurring health check (quarterly / before a big launch) — track the trend.

**Do not invoke for:** a single PR or diff (→ `verification-loop`), a security-only pass
(→ `security-audit`), or to *fix* findings (→ `lint-fixer` / `python-module-migrator` — this skill
only measures and plans).

______________________________________________________________________

## Two modes

- **Baseline (first run)** — full inventory across every dimension, establish the scorecard, write
  the roadmap. Goal is the *map*, not the fix. Lower confidence bar — surface everything, then
  prioritise.
- **Recurring (health check)** — re-run, diff against the last baseline scorecard, report the trend
  per dimension (**new / fixed / regressed**) and whether the ratchet schedule is on track. Higher
  bar — only flag movement and new high-severity debt.

______________________________________________________________________

## The audit process — six phases

Run in order. Each phase delegates heavy output to a subagent so the main session stays clean (see
*Delegate the heavy lifting* below).

### Phase 0 — Detect & inventory the gates

You cannot enforce what isn't wired. Before counting violations, inventory what enforcement *exists*:

```bash
ls prek.toml .pre-commit-config.yaml pyproject.toml 2>/dev/null
# Which commit-time gates are configured?
grep -E "ruff|mypy|interrogate|vulture|bandit|gitleaks|import|skill_enforcer" prek.toml pyproject.toml 2>/dev/null
# Which session-time guards / dev-loop hooks exist?
ls .claude/hooks/ .claude/settings.json 2>/dev/null
```

Record, per gate: **wired & blocking / wired but advisory / absent**. Cover both tiers — *commit-time*
gates (prek hooks: ruff, mypy, import-linter, interrogate, vulture, gitleaks, the `skill_enforcer`
AST rules) and *session-time* guards (the `.claude/hooks/` stack: `config-protection`,
`destructive-command-guard`, `prek-stop-runner`, `edited-files-accumulator` — see the `claude-hooks`
skill). A dimension with no gate is the highest-leverage fix — wiring it (in measure mode) is cheaper
than hand-auditing it.

### Phase 1 — Measure each dimension (count-only, NEVER fix)

For every dimension in the table below, run its measure command in **statistics / count mode**.
Capture the number, not the fix. Use `--statistics`, `--count`, `| wc -l`, `interrogate` percentages,
`pytest --cov` totals — anything that yields a *number* and an example, not a 400-line dump.

### Phase 2 — Score

Grade each dimension from the counts (grading rubric below). Assemble the **scorecard**.

### Phase 3 — Prioritise (severity × effort)

Sort findings into four buckets:

| Bucket | Definition | Example |
| --- | --- | --- |
| **Quick win** | deterministic, auto-fixable, zero behaviour change | `ruff --fix`, `ruff format`, EOF/whitespace, typos |
| **Gate-it** | wire the gate in measure mode + baseline the cap | turn on `interrogate`, `PLR` caps, `import-linter` |
| **Scheduled debt** | judgment refactor, one category per PR, ratchet | remove `dict[str, Any]`, extract owner classes, layering |
| **Out of scope** | legacy that's stable & isolated — leave, per-file-ignore | a frozen module nobody touches |

### Phase 4 — Roadmap (ratchet plan)

Turn the buckets into a phased plan (template below). The plan is the deliverable, not a pile of edits.

### Phase 5 — Report

Emit the scorecard + roadmap. **Report-only** — do not edit source. Fixes are separate, reviewed PRs.

______________________________________________________________________

## Audit dimensions

Each maps to a `brunofaust-python-style` reference and a measurable gate. Run the measure command
count-only. (`<src>` = the package root, e.g. `src/myapp`.)

| # | Dimension | Measure (count-only) | Standard reference |
| --- | --- | --- | --- |
| 0 | **Gate inventory** | inspect `prek.toml` / `pyproject.toml` / importlinter config (Phase 0) | `references/enforcement.md` |
| 1 | **Lint & format** | `ruff check --statistics .` · `ruff format --check .` | `references/pyproject-toml.md` |
| 2 | **Type safety** | `mypy <src> 2>&1 \| tail -1` (strict — error count) | `references/type-hints.md` |
| 3 | **Complexity & size** | `ruff check --select PLR0911,PLR0912,PLR0913,PLR0915 --statistics .` + files > 800 lines / funcs > 50 | `references/architecture.md`, `code-review-discipline` size gates |
| 4 | **Structure & layering** | folder layout vs the template; `lint-imports` (contract violations) | `references/project-structure.md` |
| 5 | **External-system ownership** | raw `boto3`/`httpx`/SDK imports outside owner folders (ruff `TID251` / grep) | `references/external-system-ownership.md` |
| 6 | **Boundary data modeling** | `dict[str, Any]` in signatures between modules (`skill_enforcer` / grep) | `references/data-modeling.md` |
| 7 | **Error handling** | ruff `BLE001`; `grep -rn "suppress(Exception)"`; `log.debug` inside `except` | `references/error-handling.md` |
| 8 | **Docstrings & docs** | `interrogate -v <src>` (%); mandatory files present (README/CHANGELOG/CLAUDE.md/ARCHITECTURE) | `references/docstrings.md`, `references/project-docs.md` |
| 9 | **Dead code & visibility** | `vulture <src>`; module-level `_`-prefixed names (use `__all__`) | `references/visibility.md` |
| 10 | **Tests** | `pytest --cov --cov-report=term-missing` (%); tests mirror `src/`; `@pytest.mark.asyncio` / module-global mocks | `references/testing.md` |
| 11 | **Config discipline** | `grep -rn "os.getenv" <src>` outside `settings.py`; hardcoded model names / timeouts / resource names at module level | `references/config.md` |
| 12 | **Security & secrets** | delegate to **`security-audit`** (deep mode): `gitleaks detect` (full history), `bandit -r <src>` | `security-audit` skill |
| 13 | **Infrastructure-as-Code** | CFN: `cfn-lint <templates>` + `checkov -d . --framework cloudformation`. Terraform: `terraform fmt -check -recursive`, `terraform validate`, `tflint`, `checkov`/`tfsec`, `terraform plan -detailed-exitcode` (drift = exit 2) | `aws-architecture`, `aws-cost-optimization`, `iam-auditor` + `cloudformation-reviewer` agents |
| 14 | **Assistant leverage / process tooling** | delegate to **`session-harvest`** — mine Claude Code / Cursor / Codex / Copilot histories → backlog of skills/agents/hooks/instructions (each with est. % improvement) | `session-harvest` skill |
| 15 | **Project profile & resource fit** | profile the stack/frameworks/cloud/domain, then recommend which claude-all agents/skills/hooks to install + propose net-new project-specific ones (see section below) | `claude-all --list`, `research-before-build` |

> Dimension 13 covers IaC *correctness, drift, and cost*; IaC *security* (open SGs, public buckets,
> over-broad IAM) is shared with dimension 12 — run `checkov`/`tfsec` once and split findings by lens.
> Dimensions 14 & 15 audit the *development setup*, not the code — their fix is new tooling, not a
> code change. Dim 14 is *history-driven* (what you keep redoing); dim 15 is *project-driven* (what
> this stack needs). Run them together for the full customization picture.

> Per-layer coverage targets (dimension 10): utils/pure ≥ 90%, domain services ≥ 85%, handlers ≥ 80%,
> orchestration ≥ 70%. Project gate default 80%. (From `code-review-discipline`.)

______________________________________________________________________

## Project profiling & resource recommendations (dimension 15)

Beyond grading the code, the audit profiles **what this project is** and recommends the claude-all
resources that fit it — so a colleague can run repo-audit in *any* project and get tailored
suggestions. Repeatable per-project: each repo gets its own recommendation list.

### Step A — profile the project

Detect the stack from the files present (read manifests/configs, don't guess):

| Profile axis | Detect from | Example signals |
| --- | --- | --- |
| Language / runtime | `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml` | Python 3.x, Node, Go |
| Web framework | imports / deps | FastAPI, Django, Flask, Next.js, React |
| Cloud / infra | `*.tf`, `*.yaml` (CFN/SAM/CDK), `serverless.yml` | AWS (which services), GCP |
| Data / DB | deps, ORM models, migrations | SQLAlchemy + Alembic, Postgres, DynamoDB, Polars |
| Async / messaging | imports | asyncio, SQS/SNS, Kafka |
| Tests / CI | `tests/`, `.github/workflows`, `prek.toml` | pytest, jest, GH Actions |
| AI / LLM | deps, prompt code | Anthropic/Claude, agents, RAG |

### Step B — map the profile to claude-all resources

Recommend installing what matches (catalog via `claude-all --list`), e.g.:

| If the project has… | Recommend installing |
| --- | --- |
| Python (any) | `brunofaust-python-style`, `prek`, `verification-loop`, `code-review-discipline`, `lint-fixer`, `test-runner` |
| FastAPI / API surface | `web-security`, `security-audit` |
| React / frontend | `react-correctness`, `react-testing`, `web-design-guidelines`, `web-security`, `seo` |
| AWS resources | `aws-architecture`, `aws-cost-optimization`, `iam-auditor`, `cloudformation-reviewer`, relevant `*-inspector` agents |
| Terraform / CloudFormation | `cloudformation-reviewer` / `terraform-reviewer` agents, `aws-architecture` |
| SQLAlchemy + Alembic | `alembic-migration` |
| Postgres | `postgres-query` agent, `postgres` MCP |
| LLM / agent code | `security-audit` (LLM trust-boundary lens), `subagent-prompting` |
| Layered architecture / big refactor | `architecture-decision-guard`, `python-module-migration` |

### Step C — propose net-new, project-specific resources

Where no existing resource fits, propose creating one — scoped to this project (a project `CLAUDE.md`
with conventions, a guard hook for a project footgun, a domain skill for a recurring workflow). Use
the `session-harvest` resource-type rubric to pick skill vs agent vs hook vs instruction. Always
`research-before-build` first — don't recommend installing or creating something that already exists.

### Output — recommendation list

```
PROJECT PROFILE & RECOMMENDATIONS
=================================
Profile: Python 3.13 · FastAPI · AWS (S3/SQS/Lambda) · Postgres+Alembic · pytest · no IaC linting

Install now (existing claude-all resources):
  ✓ brunofaust-python-style, prek, verification-loop   — Python baseline
  ✓ web-security, security-audit                        — FastAPI public surface
  ✓ iam-auditor, aws-architecture                       — AWS footprint
  ✓ alembic-migration, postgres-query                   — DB layer

Create (project-specific, no existing fit):
  + hook · protect-applied-migrations   block edits to already-applied Alembic revisions   (S)
  + instruction · sqs-event-shape       document the SQS event contract for this service   (S)

Out of scope: react-* (no frontend), terraform-reviewer (no Terraform)
```

Report-only: it recommends; the user runs `claude-all install <name>` for the picks and creates the
proposals. Re-run per project — recommendations are specific to each repo's profile.

______________________________________________________________________

## Grading rubric (per dimension)

Mechanical, from the measured count — not opinion:

| Grade | Meaning |
| --- | --- |
| **A** | Gate wired & blocking, zero findings (or above target %). |
| **B** | Gate wired; a handful of findings, all per-file-ignored with a TODO. |
| **C** | Gate not wired but code is mostly clean (low finding density). |
| **D** | No gate; significant finding density — needs a ratchet plan. |
| **F** | No gate AND pervasive violations, or a CRITICAL (leaked secret, no auth boundary). |

Individual findings inside a dimension still use the `code-review-discipline` severity model
(CRITICAL/HIGH/MEDIUM/LOW/INFO) so the roadmap can sort them.

______________________________________________________________________

## Scorecard format (output)

```
REPO AUDIT SCORECARD
====================
Repo: <name>   Mode: <baseline | recurring>   Commit: <sha>   Date: <date>

Dim  Dimension                 Gate          Findings   Grade   Δ vs last
 0   Gate inventory            partial       6/13 wired   C      —
 1   Lint & format             advisory      214          D      ▲ new
 2   Type safety               absent        87 errors    D      —
 3   Complexity & size         absent        12 funcs     C      ▼ -4
 …
12   Security & secrets        wired         0            A      =

Overall grade: C-      Gates wired: 6/13
Single most important next step: <one concrete action>
```

Rules: numbers are **counts**, not adjectives ("214 findings", not "lots"). Recurring mode fills the
`Δ vs last` column (new / fixed=▼ / regressed=▲ / =). A dimension that can't be measured records
`SKIP` + a one-line reason — never a silent blank.

______________________________________________________________________

## Remediation roadmap format (output)

Phased so quality climbs without ever blocking the team on legacy debt:

```
REMEDIATION ROADMAP
===================
Phase 0 — Wire the gates (advisory/measure mode)         [~0.5 day, 1 PR]
  Add the missing hooks to prek.toml in NON-blocking mode; record baselines.
  → prek skill. No source changes.

Phase 1 — Quick wins (deterministic, zero behaviour change)   [1 PR, lint-fixer]
  ruff --fix · ruff format · end-of-file/whitespace · typos. One reviewed PR.
  Safe because the transforms are deterministic — review the diff, not each line.

Phase 2 — Baseline + ratchet the caps                         [1 PR + recurring]
  Set PLR / interrogate / complexity caps at current-worst + margin → gate NEW
  code; per-file-ignore legacy hotspots with a TODO. Ratchet one notch per sprint.

Phase 3 — Scheduled structural debt (one category / PR)       [N PRs, on a schedule]
  - dict[str, Any] on boundaries → Pydantic/dataclass   (data-modeling)
  - raw SDK imports → owner classes + banned-api          (external-system-ownership)
  - layering violations → import-linter contracts         (python-module-migration)
  Each category is its own reviewed PR; never one mega-refactor.

Phase 4 — Recurring health check                              [quarterly]
  Re-run this skill; track the scorecard trend; lower the ratchet caps.
```

Pair the roadmap with `architecture-decision-guard` before any *structural* phase-3 move — don't add a
layer/boundary without a concrete present need; prefer containment (single-owner + banned-api) over
layering.

______________________________________________________________________

## Delegate the heavy lifting

The audit reads a lot; keep the main session clean by delegating:

| Task | Delegate to | Why |
| --- | --- | --- |
| Inventory layout, naming, where SDK calls live | `Explore` agent | broad fan-out search, returns conclusions not dumps |
| Run lint/type/test count commands | `test-runner` / `code-quality` agents | absorb large output, return counts + verbatim errors |
| The security dimension (12) | `security-audit` skill | full six-layer + secrets-history pass |
| The IaC dimension (13) | `cloudformation-reviewer` + `iam-auditor` agents, `aws-architecture` skill | CFN/Terraform correctness, IAM, cost |
| The process-tooling dimension (14) | `session-harvest` skill | assistant histories → resource backlog with est. % improvement |
| The project-profile dimension (15) | `Explore` agent + `claude-all --list` | profile the stack → recommend matching resources; `research-before-build` before proposing net-new |
| Fixing findings (Phases 1, 3) — *after* the audit | `lint-fixer`, `python-module-migrator` | root-cause fixes, never during the audit |
| Mining a single Claude transcript for one guard rule | `friction-analyzer` agent | narrower than `session-harvest` — one rule from one session |

Return errors **verbatim** (file:line + message) per the repo's agent error-reporting rule — the
roadmap needs the specifics, not "looks like some type errors".

______________________________________________________________________

## Integration with other skills

| Skill / agent | Relationship |
| --- | --- |
| `brunofaust-python-style` | the standard being audited against (every dimension cites a reference) |
| `prek` | how to wire gates + baseline-and-ratchet without a backlog (Phase 0/2) |
| `code-review-discipline` | severity model, size/complexity gates, report-only rule |
| `verification-loop` | the per-PR gate the roadmap leads toward — repo-audit is the macro, one-time map |
| `security-audit` | owns dimension 12 (delegate, don't reimplement) |
| `aws-architecture` / `aws-cost-optimization` / `iam-auditor` / `cloudformation-reviewer` | own dimension 13 (CloudFormation + Terraform correctness, cost, IAM) |
| `session-harvest` | owns dimension 14 — mines assistant histories into a skills/agents/hooks/instructions backlog |
| `claude-all --list` catalog | dimension 15 — the menu of installable resources to match against the project profile |
| `research-before-build` | dimension 15 — confirm a recommended/net-new resource isn't a duplicate |
| `architecture-decision-guard` | gate every structural phase-3 move (containment > layering) |
| `python-module-migration` | executes layering / move-by-subject fixes safely |
| `lint-fixer` / `test-author` | execute Phase 1/3 fixes + close coverage gaps (later PRs) |

______________________________________________________________________

## Anti-patterns

| Anti-pattern | Why | Instead |
| --- | --- | --- |
| Big-bang reformat / `--strict` everything on day one | hundreds of findings block every commit; churn hides regressions | wire advisory, baseline at current-worst, ratchet down |
| Fixing findings *during* the audit | blends measure with fix; un-auditable; the audit is often wrong | report-only — fixes are separate reviewed PRs |
| `select = ["PLR"]` (blanket group) | lit 300–400+ findings in one shot, blocked teams | select specific codes (`PLR0911/0912/0913/0915`) |
| Scoring a dimension without running its measure command | adjectives, not evidence | every grade is backed by a count |
| Auditing only `HEAD` for secrets | the leak is in history | `gitleaks detect` over full history (dimension 12) |
| One mega "improve structure" refactor | unreviewable, speculative boundaries | one category per PR; `architecture-decision-guard` first |
| Treating the scorecard as the deliverable | a score nobody acts on is noise | the ratcheting roadmap is the deliverable |
