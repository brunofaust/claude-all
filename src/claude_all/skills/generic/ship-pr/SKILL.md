---
name: ship-pr
description: >-
  Heavyweight pre-PR pipeline — the full /ship gate sequence PLUS a standard skill audit, code
  review, a docs/CLAUDE.md refresh, and a PR. Sequence: skill audit (each changed file vs its stack
  skill's audit.md) → lint-fixer → test-runner → verification-loop → /code-review (gate) →
  security-review (if a security surface) → seo review (if the diff renders crawler-visible HTML) →
  docs-updater (revise CLAUDE.md + docs from the diff) → (confirm) → git-committer → open a PR. Use when: "open a PR for this", "review and ship", finishing a substantive change
  that warrants review before it goes out. For the quick lint+test+commit loop with no review/PR, use
  the lighter `/ship`. Orchestrator only: it sequences existing agents and skills and gates on results.
disable-model-invocation: false
user-invocable: true
---

# /ship-pr — audit → gates → review → docs → commit → PR

The heavier sibling of `/ship`: it adds the review gate and PR creation for changes that are going out
for others to see. Review runs **once here**, on the assembled diff — deliberately NOT on every commit
(that's slow and noisy). Each step delegates to its focused agent/skill; the pipeline **stops on the
first hard failure**.

## Steps (run in order; STOP and report on any hard failure)

1. **Skill audit (STANDARD — not optional) — audit every changed file against its stack skill's
   `audit.md`, then apply fixes via `/simplify`.** Runs first so edits pass through the gates below.
   Map each changed file to the skill that governs it and run that skill's judgment-audit checklist:

   | Changed file | Audit against |
   | --- | --- |
   | `*.py` | `brunofaust-python-style` → `references/audit.md` (minimalism/yagni, layering, error-handling, async, boundaries, config, tests, ownership) |
   | `*.tsx` `*.jsx` `*.ts` (frontend) | `brunofaust-frontend-style` → `references/audit.md` *(when that skill lands; until then audit for the same shape)* |
   | other stacks | the same over-engineering shape — reuse, simplification, efficiency, altitude |

   The audit is the **judgment** layer — the mechanical rules are already gated by the checkers/lint,
   so it never restates them; it catches pass-through chains, speculative abstractions, I/O mixed with
   logic, a swallowed `except`, a fixture that restates the code, `os.getenv` outside `Settings`, etc.
   Apply mechanical fixes via `/simplify`; report judgment calls. **Scales to the diff** — a trivial
   rename/format gets a quick pass, feature code gets the full checklist — but is never skipped, and
   never strips a hard rule (a boundary model, an owner class, a docstring stay).
2. **Gates — run the `/ship` sequence:** `test-coverage gate` → `lint-fixer` → `test-runner` →
   `verification-loop`. If any hard-fails, stop there (same rules as `/ship`). The **test-coverage
   gate runs first**, before lint/test: it confirms this change ships the unit tests for its
   new/changed code AND — where an e2e/integration suite exists — the e2e/integration tests that
   validate each **business requirement** of the feature (user-observable behaviour, not the
   implementation). A new feature with no business-requirement coverage is a hard stop; offer to write
   the missing tests before continuing.
3. **Code review — `/code-review` skill (gate).** Review the working diff. Treat **Block** findings as
   a hard stop: fix them (loop back through the gates) or surface them for a decision. Warnings are
   reported, not blocking.
4. **Security review — `security-review` skill (surface-scoped, standard).** Run it whenever the diff
   touches a security surface — auth, secrets, input handling, IaC/IAM, shelling out, tenant-scoped
   state — and gate on its Block findings. This is not optional judgment: if the diff touches any of
   those surfaces, the review runs. Skip only when the diff clearly touches none (a docs/test/config
   tweak). `web-security` (frontend XSS/CSP/tokens) is covered by the frontend skill audit in step 1;
   this step is the cross-stack `security-audit`.
5. **SEO review — `seo` skill (surface-scoped).** Run it whenever the diff produces **user-facing
   HTML/pages** — a frontend component or page route, an SSR template, `<head>`/meta/OpenGraph,
   JSON-LD, `sitemap.xml`, `robots.txt`, canonicals/hreflang. This is scoped by *surface*, not stack: a
   server-rendered page (even non-frontend) counts; a pure JSON/data API does not. Gate on Block
   findings (missing canonical, no `<h1>`, malformed structured data). Skip when the diff renders no
   crawler-visible HTML.
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
- **Block findings are a hard stop.** Never commit/open over an unresolved Block from code or security
  review.
- **No feature without its tests.** The test-coverage gate runs before the other gates: a new/changed
  feature must ship unit tests for its code AND e2e/integration tests validating its business
  requirements (where such a suite exists). A missing-coverage gap is a hard stop, not a warning.
- **Confirm the two outward steps** (commit, then PR) separately; open the PR ready for review (not a
  draft); never push force / enable auto-merge from here.
- **Simplify before the gates, docs after review.** Code-mutating steps (the simplification audit,
  lint-fixer) run before tests so their edits are validated; the docs/CLAUDE.md refresh runs after the
  code is final so docs reflect exactly what ships.
- **The simplification audit is standard, not optional.** Every changed file is audited against
  `yagni.md` (Python) or the same over-engineering shapes (other stacks). It *scales* to the diff — a
  trivial rename/format gets a one-line pass, feature code gets the full checklist — but it is never
  skipped. The docs refresh stays skippable when it's a genuine no-op.
- **Delegate, don't inline;** stop-on-hard-fail; one PASS/FAIL line per step.

## Output

```
ship-pr: audit ✓ (py) · coverage ✓ (unit + e2e) · lint ✓ · tests ✓ · verify READY · review ✓ (0 block, 2 warn) · sec ✓ · seo n/a · docs ✓ · commit <sha> · PR #NN
```
