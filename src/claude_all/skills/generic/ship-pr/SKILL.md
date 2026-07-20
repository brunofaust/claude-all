---
name: ship-pr
description: >-
  Heavyweight pre-PR pipeline in three phases, with the review/gate phase run in PARALLEL so it is not
  a 30-minute serial crawl. Phase 1 (serial, mutating): skill audit + /simplify → lint-fixer. Phase 2
  (CONCURRENT subagents, read-only): test-coverage gate · test-runner · full prek gate (--all-files,
  both stages) · /code-review · security-review (if security surface) · seo (if HTML surface) ·
  architecture-decision-guard (if structural) · IaC review (if CFN/Terraform) · migration-reviewer
  (if a DB migration) · dependency review (if a pyproject/package.json/lockfile changed — CVE gate +
  version-currency advice). Phase 3 (serial): docs-updater → (confirm) → git-committer → open a PR
  ready for review. Surface-scoped reviews run only when the diff touches their surface. Use when: "open a PR for this", "review and ship", finishing a substantive change
  that warrants review before it goes out. For the quick lint+test+commit loop with no review/PR, use
  the lighter `/ship`. Orchestrator only: it sequences existing agents and skills and gates on results.
disable-model-invocation: false
user-invocable: true
---

# /ship-pr — [P1 mutate] → [P2 verify+review, parallel] → [P3 docs+commit+PR]

The heavier sibling of `/ship`: it adds the review gate and PR creation for changes that are going out
for others to see. Review runs **once here**, on the assembled diff — deliberately NOT on every commit
(that's slow and noisy). Each step delegates to its focused agent/skill; the pipeline **stops on the
first hard failure**.

## Steps — three phases: mutate (serial) → verify+review (PARALLEL) → finalize (serial)

Do NOT run these one-agent-at-a-time top to bottom — that is the 30-minute ship. The heavy read-only
steps are independent and **fan out as parallel subagents** (Phase 2). Only the code-*mutating* steps
and the final commit/PR are serial.

### Phase 1 — mutate the code (SERIAL; must finish before Phase 2 reads it)

1. **Skill audit + `/simplify` (STANDARD — not optional).** Audit every changed file against its stack
   skill's `audit.md` and apply the simplifications, so Phase 2 gates the *final* code:

   | Changed file | Audit against |
   | --- | --- |
   | `*.py` | `brunofaust-python-style` → `references/audit.md` (minimalism/yagni, layering, error-handling, async, boundaries, config, tests, ownership) |
   | `*.tsx` `*.jsx` `*.ts` (frontend) | `brunofaust-frontend-style` → `references/audit.md` *(when that skill lands; until then the same shape)* |
   | other stacks | the same over-engineering shape — reuse, simplification, efficiency, altitude |

   Judgment layer only (mechanical rules are checker-gated — never restate them): pass-through chains,
   speculative abstractions, I/O mixed with logic, a swallowed `except`, a fixture that restates the
   code. Scales to the diff; never strips a hard rule (a boundary model, an owner class, a docstring stay).
2. **Lint-fixer — `lint-fixer` agent.** Clear mechanical findings + fix judgment findings at the ROOT
   CAUSE. Also mutates code, so it stays in Phase 1, before the parallel gates.

### Phase 2 — verify + review the final code (PARALLEL — one subagent each, dispatched together)

These are **read-only over the now-final tree**, mutually independent, so launch them **concurrently**
(multiple Agent tool-uses in ONE message), then collect. **Any hard fail / Block in the batch stops the
ship** — fix the root cause and re-run Phase 1→2. Run only the ones that apply (skip a review whose
surface the diff doesn't touch); a skipped review is not a failure.

- **Test-coverage gate** — the change ships unit tests for its code AND, where an e2e/integration suite
  exists, e2e/integration tests validating each **business requirement**. Missing business-requirement
  coverage is a hard stop.
- **Tests — `test-runner`.** Affected tests green.
- **Full prek gate — `code-quality`, whole repo, both stages.** `prek run --all-files` AND
  `prek run --all-files --hook-stage pre-push`, **zero `Failed`**, **no pre-existing-issue amnesty** —
  a hook failing on a file outside the diff still blocks the PR. Read per-hook status (a
  `(no files to check) Skipped` on input it should inspect is a vacuous pass, not green).
- **Code review — `/code-review` (gate).** Block findings are a hard stop.
- **Security review — `security-review` (if a security surface: auth, secrets, input handling, IaC/IAM,
  shelling out, tenant-scoped state).** Gate on Block findings. `web-security` (frontend XSS/CSP) rides
  the Phase-1 frontend audit; this is the cross-stack `security-audit`.
- **SEO review — `seo` (if the diff renders crawler-visible HTML** — a frontend page, an SSR template,
  `<head>`/meta, JSON-LD, `sitemap.xml`/`robots.txt`). Scoped by *surface*, not stack; a JSON API is
  skipped. Gate on Block findings.
- **Architecture review — `architecture-decision-guard` (if the diff is STRUCTURAL** — a new package or
  module boundary, a new layer/tier, a new interface/ABC/Protocol, a new cross-module dependency, or a
  new lint/complexity gate rolled repo-wide). The cross-file boundary lens (vs the per-file yagni audit
  in Phase 1): don't add a boundary without a concrete present need; prefer containment over layering;
  don't ship a commit-blocking gate big-bang. Skip for changes that add no structure.
- **IaC review — `cloudformation-reviewer` / `terraform-reviewer` + the `aws-architecture` and
  `aws-cost-optimization` lenses (if the diff touches infrastructure-as-code** — `*.tf`, a
  CloudFormation template/change-set, a CDK stack). Two lenses, both gating: **architecture fitness**
  (Lambda package/timeout limits, SQS visibility ≥ 6× processing + DLQ, DynamoDB partition keys / no
  hot-path scans, HTTP API vs REST, NAT → VPC endpoints) and **cost** (right-size before commitments,
  Graviton, `gp2`→`gp3`, CW log retention, stale snapshots/EIPs). A new AWS resource ships reviewed for
  both. Read-only — the reviewers never `apply`/`deploy`. Skip when the diff touches no IaC.
- **Migration review — `migration-reviewer` (if the diff adds/changes a DB migration** — an
  `alembic/versions/*` file, or the stack's equivalent). A bad migration is a production incident: new
  `NOT NULL` needs a `server_default`; no million-row `UPDATE` in `upgrade()`; `ALTER TYPE … ADD VALUE`
  is non-transactional; the downgrade must round-trip; one head. Gate on BLOCK. Skip when no migration
  changed.
- **Dependency review — `research-before-build` lens + a CVE scan (if a dependency manifest changed** —
  `pyproject.toml` / `uv.lock` / `requirements*.txt` on the backend, `package.json` / lockfile on the
  frontend). For each **added or bumped** dependency, report to the user:
  - **CVE / advisory scan** (`uv audit` / `pip-audit`; `npm audit --audit-level=high`) — a **high or
    critical** advisory is a hard **gate**; lower severities are reported.
  - **Version currency & fit — ADVISORY** (this is the "advise the user" part, not a block): is the
    pinned version current, or is a newer stable release out (check via Context7 / the registry)? Is
    the package actively maintained and licence-compatible? And — per `research-before-build` — is the
    dependency even needed, or does stdlib / an existing dep already cover it? Surface the advice; the
    user decides.
  Skip entirely when no manifest changed. (This step owns the dependency slice of the supply-chain
  surface; the broader `security-review` above need not re-scan dep CVEs.)

### Phase 3 — finalize (SERIAL)

6. **Docs & CLAUDE.md — `docs-updater` agent.** With the code now final, revise `CLAUDE.md` (and
   `README` / `ARCHITECTURE` / `CHANGELOG` where affected) to match the diff, so the always-loaded
   guidance never drifts from the code. It proposes diffs — confirm doc changes before they're staged.
   No-op if the diff changes nothing a doc describes.
7. **Commit — `git-committer` agent (after confirm).** When review is clean and docs are in sync, show
   the diff summary + proposed Conventional Commits message, get a one-word confirm, commit to the
   current branch.
8. **PR — (after confirm).** Push the branch and open a PR (title + body summarizing the change and
   the gate results), ready for review — **not** a draft. Opening a PR is outward-facing — confirm
   before doing it. Do not enable auto-merge.

## Optional tail — review an already-open PR

`/ship-pr` reviews the *working diff before* it becomes a PR. To review an *already-opened* PR by
number (someone else's, or a re-review after pushes), use the existing **`review`** skill —
`review <pr#>` — rather than folding PR-number review into this pipeline.

## Rules

- **Review once, here — not per commit.** Keep `/ship` cheap; pay the review cost when you're actually
  opening a PR.
- **Every PR is full green — no pre-existing-issue amnesty.** `prek run --all-files` on BOTH stages
  (pre-commit + pre-push) over the whole repo must be zero-`Failed` before the PR opens. A hook failing
  on a file outside your diff still blocks — "pre-existing" is never a pass; fix the root cause.
- **Block findings are a hard stop.** Never commit/open over an unresolved Block from code or security
  review.
- **No feature without its tests.** The test-coverage gate runs before the other gates: a new/changed
  feature must ship unit tests for its code AND e2e/integration tests validating its business
  requirements (where such a suite exists). A missing-coverage gap is a hard stop, not a warning.
- **Confirm the two outward steps** (commit, then PR) separately; open the PR ready for review (not a
  draft); never push force / enable auto-merge from here.
- **Three phases; the review/gate phase runs in PARALLEL.** Phase 1 (mutating: the simplification
  audit + lint-fixer) is serial and finishes first, so the code is final. Phase 2 — tests, the full
  prek gate, code review, security, SEO, architecture — is **read-only and independent, so dispatch it
  as concurrent subagents (multiple Agent tool-uses in one message), not one after another.** Collect
  results, stop the ship on any hard-fail/Block, else proceed to Phase 3 (docs → commit → PR, serial).
  This is what keeps `/ship-pr` from being a 30-minute serial crawl. Never parallelize a mutator with a
  reader of the same files — that is exactly why Phase 1 is serial and comes first.
- **The simplification audit is standard, not optional.** Every changed file is audited against
  `yagni.md` (Python) or the same over-engineering shapes (other stacks). It *scales* to the diff — a
  trivial rename/format gets a one-line pass, feature code gets the full checklist — but it is never
  skipped. The docs refresh stays skippable when it's a genuine no-op.
- **Delegate, don't inline;** stop-on-hard-fail; one PASS/FAIL line per step.

## Output

```
ship-pr: [P1] audit ✓ (py) · lint ✓  ‖  [P2 parallel] coverage ✓ (unit+e2e) · tests ✓ · prek ✓ (both stages, all-files) · review ✓ (0 block, 2 warn) · sec ✓ · seo n/a · arch n/a · iac n/a · migration n/a · deps ✓ (1 bumped, current) ‖  [P3] docs ✓ · commit <sha> · PR #NN
```
