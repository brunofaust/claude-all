---
name: ship-pr
description: >-
  Heavyweight pre-PR pipeline — the full /ship gate sequence PLUS a standard simplification audit, code
  review, a docs/CLAUDE.md refresh, and a PR. Sequence: simplification audit (vs yagni.md) → lint-fixer →
  test-runner → verification-loop → /code-review (gate) → (security-review if the change touches a
  security surface) → docs-updater (revise CLAUDE.md + docs from the diff) → (confirm) → git-committer
  → open a PR. Use when: "open a PR for this", "review and ship", finishing a substantive change
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

1. **Simplification audit (STANDARD — not optional) — audit every changed file for over-engineering,
   then `/simplify`.** Run it first so its edits pass through the gates below. **Audit each changed
   file against the `brunofaust-python-style` skill's `references/yagni.md` "Audit checklist"** (for
   Python) — pass-through chains (`a()` → `_b()` → `_c()` where each only forwards), one-impl
   `Protocol`s, a "repository" wrapping SQLAlchemy that adds nothing, factories a dict replaces,
   config for one-value options, defensive branches on type-guaranteed inputs, speculative extension
   points. For non-Python, audit for the same shape (reuse, simplification, efficiency, altitude).
   Apply the mechanical fixes via `/simplify`; report judgment calls. A trivial diff (rename / format /
   one-liner) gets a quick pass; feature code gets the full checklist. It doesn't hunt bugs — the
   review gates below do that. It does NOT strip the skill's hard rules (a boundary model, an owner
   class, a docstring stay).
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
4. **Security review — `security-review` skill (conditional).** If the diff touches a security surface
   (auth, secrets, input handling, IaC/IAM, shelling out, tenant-scoped state), run it and gate on its
   Block findings too. Skip for changes that clearly don't.
5. **Docs & CLAUDE.md — `docs-updater` agent.** With the code now final, revise `CLAUDE.md` (and
   `README` / `ARCHITECTURE` / `CHANGELOG` where affected) to match the diff, so the always-loaded
   guidance never drifts from the code. It proposes diffs — confirm doc changes before they're staged.
   No-op if the diff changes nothing a doc describes.
6. **Commit — `git-committer` agent (after confirm).** When review is clean and docs are in sync, show
   the diff summary + proposed Conventional Commits message, get a one-word confirm, commit to the
   current branch.
7. **PR — (after confirm).** Push the branch and open a PR (title + body summarizing the change and
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
ship-pr: audit ✓ (yagni) · coverage ✓ (unit + e2e) · lint ✓ · tests ✓ · verify READY · review ✓ (0 block, 2 warn) · sec n/a · docs ✓ · commit <sha> · PR #NN
```
