---
name: repo-audit
description: >-
  Whole-repo, point-in-time code-quality audit for an existing / brownfield codebase in ANY language
  or architecture (Python, TypeScript/JS & frontend, Go, Rust, …). It audits the repo against a set of
  GENERIC boundaries — format/lint, static type safety, bounded complexity, layering & dependency
  direction, single-owner external systems, typed contracts at trust boundaries, no silent error
  swallowing, docs, dead code, tests/coverage, config discipline, secrets/SAST — plus IaC
  (CloudFormation + Terraform) and a process-tooling pass (session-harvest). The brunofaust-python-style
  standard + prek are the REFERENCE instantiation of these boundaries; for other stacks you translate
  the same idea to the stack's tooling (eslint/tsc, golangci-lint, clippy, …) and reason about
  anything with no off-the-shelf tool. Also profiles the project and recommends which claude-all
  agents/skills/hooks to install — run it per-project. Use when: onboarding a colleague or inherited
  repo, a first-time congruence audit, establishing a quality baseline before adopting gates, deciding
  what to fix first, or a recurring health check. Produces a per-dimension scorecard + a RATCHETING
  remediation roadmap (improve without a commit-blocking big-bang). Report-only — measures and plans;
  fixes happen in later reviewed PRs. Distinct from verification-loop (gates ONE diff), code-review-
  discipline (review output shape), and security-audit (security layers — this delegates to it).
disable-model-invocation: false
user-invocable: true
---

# Repo Audit

A whole-repo congruence audit for an **existing / brownfield** codebase in **any language**. It answers
one question — *"how far is this repo from the quality boundaries, and what is the safe order to close
the gap?"* — and produces two artifacts: a **scorecard** and a **ratcheting remediation roadmap**.

This is **not** a diff review. `verification-loop` gates one PR; `code-review-discipline` defines the
shape of a review; this audits the *whole repo* at a point in time and plans the cleanup.

## The boundaries are generic — the Python stack is just the reference

The quality ideas this audit checks are **language-agnostic boundaries**: typed contracts at trust
edges, bounded complexity, enforced dependency direction, single-owner external systems, no silent
error swallowing, tests that mirror source, no scattered config. `brunofaust-python-style` + `prek`
are the **reference instantiation** (ruff / mypy / import-linter / banned-api / interrogate / vulture
/ bandit / gitleaks). **For any other stack you translate the same boundary to that stack's tooling**
— and where no off-the-shelf tool exists, you **audit it by reasoning + `grep`**. Never skip a
dimension because "there's no linter for it here" — the boundary still applies; only the enforcement
mechanism changes.

______________________________________________________________________

## The brownfield thesis — measure, baseline, ratchet (never big-bang)

The instinct on inheriting a messy repo is to turn every gate to `--strict` and reformat everything.
That is the one thing you must not do. Enabling a strict gate on a legacy codebase lights up
**hundreds** of pre-existing findings, **blocks every commit**, and buries the *new* signal under
legacy noise — a thousand-file reformat PR also hides real regressions in the churn.

The audit's job is the opposite:

1. **Measure** every dimension in *count-only* mode — never fix during the audit.
1. **Baseline** the gates at *current-worst + a small margin* so nothing passing today breaks.
1. **Ratchet** the caps down one notch per PR/sprint, so the gate blocks *new* debt from day one
   while legacy debt is paid on a schedule.

See the `prek` skill, *"Rolling out a new hook or complexity cap without a backlog"*, and
`architecture-decision-guard`, *"Rolling out enforcement gates without a backlog"*. This applies to
**every** stack's gate (eslint rule, `tsc` strictness, golangci-lint linter, clippy lint), not just ruff.

______________________________________________________________________

## When to invoke / when not

**Invoke when:** a colleague joins or you inherit an existing product (any language); before adopting
quality gates on a repo that never had them; to decide *what to fix first* in a large codebase;
recurring health check (quarterly / before a launch).

**Do not invoke for:** a single PR or diff (→ `verification-loop`), a security-only pass
(→ `security-audit`), or to *fix* findings (→ `lint-fixer` / `python-module-migrator` — this skill
only measures and plans).

______________________________________________________________________

## Two modes

- **Baseline (first run)** — full inventory across every dimension, establish the scorecard, write
  the roadmap. Goal is the *map*, not the fix. Lower confidence bar — surface everything, then prioritise.
- **Recurring (health check)** — re-run, diff against the last baseline, report the trend per dimension
  (**new / fixed / regressed**) and whether the ratchet schedule is on track. Only flag movement and
  new high-severity debt.

______________________________________________________________________

## The audit process — six phases

Run in order. Delegate heavy output to a subagent so the main session stays clean (see *Delegate the
heavy lifting*).

### Phase 0 — Detect the stack, then inventory the gates

First **detect the language(s)/architecture** (Phase 0 of *Project profiling*, below) — that decides
*which* tools each dimension uses. Then inventory what enforcement already exists; you cannot enforce
what isn't wired:

```bash
# Gate orchestrators + configs across stacks
ls prek.toml .pre-commit-config.yaml lefthook.yml .husky/ 2>/dev/null
ls pyproject.toml package.json .eslintrc* tsconfig.json .golangci.yml Cargo.toml clippy.toml 2>/dev/null
ls .claude/hooks/ .claude/settings.json 2>/dev/null   # session-time guards
```

Record, per gate: **wired & blocking / wired but advisory / absent**, across commit-time gates and
session-time guards (the `.claude/hooks/` stack — see `claude-hooks`). A boundary with no gate is the
highest-leverage fix.

### Phase 1 — Measure each dimension (count-only, NEVER fix)

For every dimension, run the stack's measure command in **statistics / count mode** (`--statistics`,
`--max-warnings`, `| wc -l`, coverage totals). Capture the number + one example, not a 400-line dump.
Where the stack has no tool for a boundary, measure by reasoning + `grep`.

### Phase 2 — Score

Grade each dimension from the counts (grading rubric below). Assemble the **scorecard**.

### Phase 3 — Prioritise (severity × effort)

| Bucket | Definition | Example |
| --- | --- | --- |
| **Quick win** | deterministic, auto-fixable, zero behaviour change | formatter (`ruff format` / `prettier` / `gofmt`), EOF/whitespace, typos |
| **Gate-it** | wire the gate in measure mode + baseline the cap | turn on complexity caps, doc coverage, dependency-direction lint |
| **Scheduled debt** | judgment refactor, one category per PR, ratchet | remove `any`/`dict[str, Any]`, extract owner modules, fix layering |
| **Out of scope** | legacy that's stable & isolated — leave, per-file-ignore | a frozen module nobody touches |

### Phase 4 — Roadmap (ratchet plan) · ### Phase 5 — Report

Turn the buckets into a phased plan (template below) and emit scorecard + roadmap. **Report-only** —
do not edit source. Fixes are separate, reviewed PRs.

______________________________________________________________________

## Audit dimensions (generic boundaries)

Each dimension is a **boundary**; the measure column says what to count. Use the *per-stack
translation* table below to pick the actual tool. (`<src>` = the source root.)

| # | Boundary — what good looks like | Measure (count-only) |
| --- | --- | --- |
| 0 | **Gates wired** — the boundaries below are actually enforced | Phase 0 inventory; per gate blocking/advisory/absent |
| 1 | **Format + lint clean** | run the stack linter+formatter in check mode; count findings |
| 2 | **Static type safety, no escape hatches** | strict type-check error count + count of `any` / `as any` / `interface{}` / `dict[str, Any]` / `unwrap()` escapes |
| 3 | **Bounded complexity & size** | functions/files over the complexity & length caps (cyclomatic, params, returns, lines) |
| 4 | **Layering / dependency direction enforced** | folder layout vs intended architecture; import-direction / forbidden-dependency violations |
| 5 | **External systems have a single owner (containment)** | raw SDK / HTTP / DB-driver imports *outside* the designated owner module |
| 6 | **Typed contracts at trust boundaries** | untyped / `any` / loosely-typed blobs crossing a module or I/O boundary (validate at the edge) |
| 7 | **No silent error swallowing** | empty catches, ignored error returns, swallowed promise rejections, broad catch-all |
| 8 | **Docs coverage + mandatory files** | doc-comment coverage %; README / CHANGELOG / architecture docs present |
| 9 | **No dead code; minimal public surface** | unused exports/symbols; over-broad visibility |
| 10 | **Tests mirror source; coverage meets the per-layer bar** | coverage %; test↔source structure; anti-patterns (module-global mocks) |
| 11 | **No scattered / hardcoded config** | env reads outside the config module; hardcoded endpoints / timeouts / model names / resource names |
| 12 | **Secrets clean + SAST** | delegate to **`security-audit`**: secret scan over *full git history* + SAST |
| 13 | **Infrastructure-as-Code** | CFN: `cfn-lint` + `checkov --framework cloudformation`. Terraform: `terraform fmt -check`, `validate`, `tflint`, `checkov`/`tfsec`, `plan -detailed-exitcode` (drift) |
| 14 | **Process tooling captured** | delegate to **`session-harvest`** — histories → backlog of skills/agents/hooks/instructions (est. % improvement) |
| 15 | **Right resources installed for the stack** | profile the project → recommend claude-all resources + net-new (see *Project profiling*) |

> **Frontend repos** add UI lenses that are dimensions 1–12 specialised for the view layer — delegate
> them to the dedicated skills: `react-correctness` (hooks rules, effect deps, keys, render safety),
> `react-testing`, `vercel-composition-patterns`, `web-design-guidelines` (design-system adherence + a11y),
> `web-security` (XSS / CSP / secrets in bundles), `seo` (Core Web Vitals, meta, structured data).
> Plus: no `any` across component boundaries, bounded component size, no business logic in components.

> Per-layer coverage targets (dimension 10): pure utils ≥ 90%, domain/services ≥ 85%, handlers/
> presentational ≥ 80%, orchestration/containers ≥ 70%. Project gate default 80%. (From `code-review-discipline`.)

> Dimensions 14 & 15 audit the *development setup*, not the code. **No double-run:** repo-audit runs
> `session-harvest` **once** as dim 14 — don't also invoke it separately in the same pass. Run
> `session-harvest` standalone only for history-only mining outside an audit.

______________________________________________________________________

## Translate the standard to the repo's stack

Same boundary, different tool. Python/`prek` is the reference column; map it to the repo's actual stack.
Where a cell is blank or no tool exists, **audit the boundary by reasoning + `grep`** — don't drop it.

| Boundary (dim) | Python (reference) | TypeScript / JS / frontend | Go | Rust |
| --- | --- | --- | --- | --- |
| Format + lint (1) | `ruff`, `ruff format` | `eslint` + `prettier` | `gofmt`/`goimports`, `go vet` | `rustfmt`, `clippy` |
| Type safety (2) | `mypy --strict`; ban `Any` | `tsc --strict`; ban `any`/`as any` (`@typescript-eslint/no-explicit-any`) | compiler + `staticcheck`; avoid `interface{}` | compiler; `#![deny(warnings)]`; avoid `unwrap` |
| Complexity & size (3) | ruff `PLR0911/12/13/15`, fn ≤ 50 / file ≤ 800 | eslint `complexity`, `max-lines`, `max-depth`, `max-params` | `gocyclo`/`gocognit`/`funlen` (golangci-lint) | clippy `cognitive_complexity`, `too_many_arguments` |
| Layering / direction (4) | `import-linter` contracts | `dependency-cruiser`, `eslint-plugin-boundaries`, Nx tags | `depguard`, `go-arch-lint`, `internal/` | crate/module boundaries, `clippy` |
| Single-owner + banned-api (5) | ruff `banned-api` (TID251) | `eslint` `no-restricted-imports` | `depguard` | module privacy / `disallowed_methods` |
| Typed contracts (6) | Pydantic / frozen dataclass | `zod` / `io-ts` at I/O edges | structs + validation | `serde` structs |
| No silent swallow (7) | ruff `BLE001`; ban `suppress(Exception)` | eslint `no-empty`, `no-floating-promises` | `errcheck`; wrap with `%w` | no `unwrap`/`expect` in prod; `Result` + `?` |
| Docs (8) | `interrogate` | TSDoc/JSDoc coverage | `godoc` on exported | `rustdoc` on `pub` (`missing_docs`) |
| Dead code / visibility (9) | `vulture`; `__all__` over `_` | `knip` / `ts-prune` | `staticcheck U1000` | clippy `dead_code`; minimal `pub` |
| Tests + coverage (10) | `pytest --cov` | `vitest`/`jest --coverage` + testing-library | `go test -cover` | `cargo test` / `tarpaulin` |
| Config discipline (11) | Settings singleton; no scattered `os.getenv` | central config; no scattered `process.env` | config pkg; no scattered `os.Getenv` | config crate; no scattered `env!` |
| Secrets + SAST (12) | `gitleaks`, `bandit` | `gitleaks`, `pnpm/npm audit`, `eslint-plugin-security` | `gitleaks`, `govulncheck`, `gosec` | `gitleaks`, `cargo audit`, `cargo deny` |
| Gate orchestrator (0) | `prek` / `pre-commit` | `husky` + `lint-staged` (or `prek`) | `lefthook` / `pre-commit` | `pre-commit` / `cargo-husky` |

______________________________________________________________________

## Project profiling & resource recommendations (dimension 15)

Profile **what this project is**, then recommend the claude-all resources that fit it — repeatable
per-project, each repo gets its own list.

### Step A — profile the project

Read manifests/configs (don't guess): language/runtime (`pyproject.toml` / `package.json` / `go.mod`
/ `Cargo.toml`), framework (FastAPI / Django / Next.js / React / Vue / Spring), cloud/infra (`*.tf`,
CFN/SAM/CDK, `serverless.yml`), data/DB (ORM, migrations), async/messaging, tests/CI, AI/LLM usage.

### Step B — map the profile to claude-all resources (`claude-all --list`)

| If the project has… | Recommend installing |
| --- | --- |
| Python | `brunofaust-python-style`, `prek`, `verification-loop`, `code-review-discipline`, `lint-fixer`, `test-runner` |
| TypeScript / JS (any) | `prek` (or husky), `verification-loop`, `code-review-discipline`, `lint-fixer` |
| React / frontend | `react-correctness`, `react-testing`, `vercel-composition-patterns`, `web-design-guidelines`, `web-security`, `seo` |
| FastAPI / any API surface | `web-security`, `security-audit` |
| AWS resources | `aws-architecture`, `aws-cost-optimization`, `iam-auditor`, `cloudformation-reviewer`, relevant `*-inspector` agents |
| Terraform / CloudFormation | `cloudformation-reviewer` / `terraform-reviewer` agents, `aws-architecture` |
| SQLAlchemy + Alembic | `alembic-migration` |
| Postgres | `postgres-query` agent, `postgres` MCP |
| LLM / agent code | `security-audit` (LLM trust-boundary lens), `subagent-prompting` |
| Layered architecture / big refactor | `architecture-decision-guard`, `python-module-migration` |

### Step C — propose net-new, project-specific resources

Where nothing fits, propose creating one scoped to this project (a project `CLAUDE.md` of conventions,
a guard hook for a footgun, a domain skill for a recurring workflow). Use the `session-harvest`
resource-type rubric (hook vs instruction vs agent vs skill). Always `research-before-build` first.

### Output — recommendation list

```
PROJECT PROFILE & RECOMMENDATIONS
=================================
Profile: TypeScript · Next.js/React · Vercel · Postgres(Prisma) · vitest · eslint (no strict tsc)

Install now (existing claude-all resources):
  ✓ react-correctness, react-testing, vercel-composition-patterns   — React layer
  ✓ web-design-guidelines, web-security, seo                  — UI / public surface
  ✓ verification-loop, code-review-discipline, lint-fixer     — review + gate baseline

Create (project-specific, no existing fit):
  + instruction · server-action-trust-boundary   validate every Server Action input   (S)
  + hook · block-any-in-shared                    flag new `any` in shared/ types       (S)

Out of scope: aws-* (no AWS), alembic-migration (no Python/Alembic)
```

Report-only: it recommends; the user runs `./claude-all --all --user <name>` and creates the proposals.

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
Repo: <name>   Stack: <languages/frameworks>   Mode: <baseline|recurring>   Commit: <sha>   Date: <date>

Dim  Boundary                  Gate          Findings    Grade   Δ vs last
 1   Format & lint             advisory      214         D       ▲ new
 2   Type safety               absent        87 errors   D       —
 3   Complexity & size         absent        12 fns      C       ▼ -4
 …
12   Secrets & SAST            wired         0           A       =

Overall grade: C-      Gates wired: 6/16
Single most important next step: <one concrete action>
```

Rules: numbers are **counts**, not adjectives. Recurring mode fills `Δ vs last` (new / fixed=▼ /
regressed=▲ / =). A dimension that can't be measured records `SKIP` + a one-line reason.

______________________________________________________________________

## Remediation roadmap format (output)

Phased so quality climbs without ever blocking the team on legacy debt (examples are Python; translate
to the stack):

```
REMEDIATION ROADMAP
===================
Phase 0 — Wire the gates (advisory/measure mode)         [~0.5 day, 1 PR]
  Add the missing gates (prek / husky / golangci-lint / clippy) in NON-blocking mode; record baselines.

Phase 1 — Quick wins (deterministic, zero behaviour change)   [1 PR, lint-fixer]
  Formatter + auto-fixable lint + EOF/whitespace + typos. Review the diff, not each line.

Phase 2 — Baseline + ratchet the caps                         [1 PR + recurring]
  Set complexity / doc-coverage / type-strictness caps at current-worst + margin → gate NEW code;
  per-file-ignore legacy hotspots with a TODO. Ratchet one notch per sprint.

Phase 3 — Scheduled structural debt (one category / PR)       [N PRs, on a schedule]
  - untyped blobs on boundaries → typed contracts        (dim 6)
  - raw SDK imports → single owner + banned-api           (dim 5)
  - layering violations → dependency-direction lint       (dim 4)
  Each category is its own reviewed PR; never one mega-refactor.

Phase 4 — Recurring health check                              [quarterly]
  Re-run this skill; track the scorecard trend; lower the ratchet caps.
```

Pair the roadmap with `architecture-decision-guard` before any *structural* phase-3 move — don't add a
boundary without a concrete present need; prefer containment (single-owner + banned-api) over layering.

______________________________________________________________________

## Delegate the heavy lifting

| Task | Delegate to | Why |
| --- | --- | --- |
| Detect the stack; inventory layout / where SDK calls live (Phase 0 recon) | `Explore` agent | broad fan-out search, returns conclusions not dumps — do NOT build a dedicated agent for this |
| Deep correctness review of hot subsystems (recent churn, uncommitted diffs, tricky domain logic) | `bug-hunter` agent | reasoning-based bug classes linters can't see; severity-tagged, read-only |
| Run lint/type/test count commands (any stack) | `test-runner` / `code-quality` agents | absorb large output, return counts + verbatim errors |
| Frontend / UI dimensions | `react-correctness` / `react-testing` / `web-design-guidelines` / `web-security` / `seo` | UI-layer specialists |
| The security dimension (12) | `security-audit` skill | full six-layer + secrets-history pass |
| The IaC dimension (13) | `cloudformation-reviewer` + `iam-auditor` agents, `aws-architecture` skill | CFN/Terraform correctness, IAM, cost |
| The process-tooling dimension (14) | `session-harvest` skill | assistant histories → resource backlog with est. % improvement |
| The project-profile dimension (15) | `Explore` agent + `claude-all --list` | profile → recommend; `research-before-build` before net-new |
| Fixing findings (Phases 1, 3) — *after* the audit | `lint-fixer`, `python-module-migrator` | root-cause fixes, never during the audit |
| Mining a single Claude transcript for one guard rule | `friction-analyzer` agent | narrower than `session-harvest` |

Return errors **verbatim** (file:line + message) per the repo's agent error-reporting rule.

### Deep-dive lanes (optional add-on, parallel)

The count-only dimensions miss logic bugs. When the user asks for a *bug hunt* (not just a
scorecard), fan out **scoped lanes in parallel** after Phase 0 recon, one subagent per hot area:

- **Hot code lanes → `bug-hunter`.** Recon tells you where the risk is: uncommitted diffs, recent
  churn (`git log --since=`), the largest/most complex modules, new untracked scripts. Dispatch one
  lane per area with the file list, hot spots, and bug-class emphasis inlined.
- **Bespoke infra lanes → one-off prompts, not new agents.** A domain config outside the dimensions
  (a reverse-proxy cache, a queue topology, a cron fleet) gets a per-run checklist written fresh
  from recon context, following `subagent-prompting` (scope + checklist + severity format + output
  budget + "if you can't find it, say where you looked"). The checklist IS the per-run value —
  don't can it into a single-purpose agent you'll use once.

Every lane: read-only, CRITICAL/HIGH/MEDIUM/LOW with `file:line`, hard output budget (≤ 60–70
lines), and a closing 3-line assessment so the parent can merge lanes into one report.

______________________________________________________________________

## Integration with other skills

| Skill / agent | Relationship |
| --- | --- |
| `brunofaust-python-style` | the **reference instantiation** of the boundaries (Python); other stacks translate via the table above |
| `prek` | how to wire gates + baseline-and-ratchet without a backlog (applies to every stack's gate) |
| `code-review-discipline` | severity model, size/complexity gates, report-only rule |
| `verification-loop` | the per-PR gate the roadmap leads toward — repo-audit is the macro, one-time map |
| `react-correctness` / `react-testing` / `vercel-composition-patterns` / `web-design-guidelines` / `web-security` / `seo` | own the frontend/UI lenses (dims 1–12 for the view layer) |
| `security-audit` | owns dimension 12 (delegate, don't reimplement) |
| `aws-architecture` / `aws-cost-optimization` / `iam-auditor` / `cloudformation-reviewer` | own dimension 13 (IaC) |
| `session-harvest` | owns dimension 14 — mines assistant histories into a resource backlog |
| `claude-all --list` catalog + `research-before-build` | dimension 15 — match the profile to resources; avoid duplicates |
| `architecture-decision-guard` | gate every structural phase-3 move (containment > layering) |
| `python-module-migration` | executes layering / move-by-subject fixes safely (Python) |
| `lint-fixer` / `test-author` | execute Phase 1/3 fixes + close coverage gaps (later PRs) |

______________________________________________________________________

## Anti-patterns

| Anti-pattern | Why | Instead |
| --- | --- | --- |
| Skipping a dimension because "no linter for it in this stack" | the boundary still applies | translate it, or audit by reasoning + `grep` |
| Big-bang reformat / `--strict` everything on day one | hundreds of findings block every commit; churn hides regressions | wire advisory, baseline at current-worst, ratchet down |
| Fixing findings *during* the audit | blends measure with fix; un-auditable; the audit is often wrong | report-only — fixes are separate reviewed PRs |
| Enabling a blanket lint group at tight defaults | lights up 300–400+ findings in one shot, blocks teams | select specific rules; cap at current-worst |
| Scoring a dimension without running its measure command | adjectives, not evidence | every grade is backed by a count |
| Auditing only `HEAD` for secrets | the leak is in history | secret scan over full git history (dimension 12) |
| One mega "improve structure" refactor | unreviewable, speculative boundaries | one category per PR; `architecture-decision-guard` first |
| Treating the scorecard as the deliverable | a score nobody acts on is noise | the ratcheting roadmap is the deliverable |
