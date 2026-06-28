---
name: ship
description: >-
  Lightweight pre-commit pipeline — run the quality gates and commit, in order, stopping on the first
  hard failure. Sequence: test-coverage gate → lint-fixer → test-runner → verification-loop →
  (confirm) → git-committer.
  Use when: "ship this", "run the gates and commit", finishing a small change and wanting it linted +
  tested + committed without a full PR ceremony. This is the LIGHT flow — no code review, no PR. For
  the heavier review + draft-PR flow use `/ship-pr`. Orchestrator only: it sequences existing agents
  and skills and gates on their results; it never re-implements their logic.
disable-model-invocation: true
user-invocable: true
---

# /ship — lint → test → verify → commit

A thin orchestrator for the common "I'm done with this change, get it clean and committed" loop. It
**delegates each step to the focused agent/skill** (keeping this session's context clean) and **stops
on the first hard failure** with a summary, so you never commit over a red gate.

## Steps (run in order; STOP and report on any hard failure)

Pre-flight — show what's about to ship and bail if there's nothing:
```bash
git status --short && git diff --stat
```
If the working tree is clean, stop: "nothing to ship".

1. **Test-coverage gate — confirm the change ships its tests (BEFORE lint/test run).** Inspect the
   working diff and split it into *behavior* changes (a new feature, endpoint, business rule, bug fix)
   vs. pure refactor/rename/format/docs/config. For every behavior change:
   - **Unit tests** — confirm the diff also adds/updates/deletes the unit tests covering the
     new/changed code paths (tests mirror `src/`). New/changed code with no matching unit-test change
     is a gap. Unit tests validate the *code*.
   - **e2e / integration tests (the priority).** If the repo HAS an e2e/integration suite
     (`tests/e2e`, `tests/integration`, `*.e2e.*`, `*_integration_test*`, Playwright/Cypress, etc.),
     confirm the diff adds/updates e2e/integration tests that exercise the new feature **end-to-end
     against its business requirements** — the user-observable behaviour / acceptance criteria, NOT
     the implementation. A new or changed feature with zero new e2e/integration coverage is a hard gap.
   - **Map every business requirement** the change introduces to a test that asserts it; list any
     requirement with no covering test. e2e/integration assert the *requirements*; unit tests assert
     the *code* — both must move when behavior moves.

   **Verdict:** PASS only when every behavior change has matching unit tests AND — where an
   e2e/integration suite exists — e2e/integration tests covering each business requirement. Otherwise
   **STOP**: report exactly which requirements/code paths lack tests and offer to write them
   (`test-author` for unit gaps; author the e2e/integration tests against the business requirements)
   before continuing. Skip the gate only for diffs with no behavior change — and say so explicitly.
2. **Lint — `lint-fixer` agent.** Dispatch it on the changed files to clear mechanical findings
   (`ruff --fix`/format, eslint --fix) and fix judgment findings (types, complexity) at the ROOT CAUSE
   — no `# noqa` / `# type: ignore` / config-loosening. If it can't fix something cleanly, stop and
   surface it.
3. **Tests — `test-runner` agent.** Run the affected tests. If anything is red, **stop** and report
   the failures verbatim (do not "fix" by deleting/skipping tests). Hand off to `debugger` only if the
   user asks.
4. **Verify — `verification-loop` skill.** Run the pre-commit gate table (lint/format → types → tests
   → coverage → security/secrets → diff review) to a single READY / NOT READY verdict. If NOT READY,
   stop with the failing gates.
5. **Commit — `git-committer` agent (after confirm).** Only when every gate is green: show the diff
   summary and the proposed Conventional Commits message, get a one-word confirm, then commit to the
   **current branch**. Never branch/push/PR here — that's `/ship-pr`.

## Rules

- **Stop-on-hard-fail.** A missing-test gap (a behavior change with no unit and/or e2e/integration
  coverage), a red test, an unfixable lint finding, or a NOT-READY verdict halts the pipeline — report
  and let the user decide. Don't paper over a gate to keep moving.
- **Tests gate the feature, not just the code.** A new/changed feature must ship the e2e/integration
  tests that validate its **business requirements** (where such a suite exists), plus the unit tests
  for the code. Shipping a feature with no business-requirement coverage is a hard gap, not a warning.
- **Delegate, don't inline.** Each verbose step runs in its agent so this context stays small.
- **Confirm the commit.** Committing is the one state-changing step; show the message and wait for yes.
- **Light by design.** No code review, no security review, no PR. Reach for `/ship-pr` when the change
  warrants review or you're opening a PR.

## Output

A PASS/FAIL line per step, then the commit SHA (or the reason the pipeline stopped):
```
ship: coverage ✓ (unit + e2e) · lint ✓ · tests ✓ (42 passed) · verify READY · commit <sha>
```
