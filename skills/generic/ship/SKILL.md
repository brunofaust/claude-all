---
name: ship
description: >-
  Lightweight pre-commit pipeline — run the quality gates and commit, in order, stopping on the first
  hard failure. Sequence: lint-fixer → test-runner → verification-loop → (confirm) → git-committer.
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

1. **Lint — `lint-fixer` agent.** Dispatch it on the changed files to clear mechanical findings
   (`ruff --fix`/format, eslint --fix) and fix judgment findings (types, complexity) at the ROOT CAUSE
   — no `# noqa` / `# type: ignore` / config-loosening. If it can't fix something cleanly, stop and
   surface it.
2. **Tests — `test-runner` agent.** Run the affected tests. If anything is red, **stop** and report
   the failures verbatim (do not "fix" by deleting/skipping tests). Hand off to `debugger` only if the
   user asks.
3. **Verify — `verification-loop` skill.** Run the pre-commit gate table (lint/format → types → tests
   → coverage → security/secrets → diff review) to a single READY / NOT READY verdict. If NOT READY,
   stop with the failing gates.
4. **Commit — `git-committer` agent (after confirm).** Only when every gate is green: show the diff
   summary and the proposed Conventional Commits message, get a one-word confirm, then commit to the
   **current branch**. Never branch/push/PR here — that's `/ship-pr`.

## Rules

- **Stop-on-hard-fail.** A red test, an unfixable lint finding, or a NOT-READY verdict halts the
  pipeline — report and let the user decide. Don't paper over a gate to keep moving.
- **Delegate, don't inline.** Each verbose step runs in its agent so this context stays small.
- **Confirm the commit.** Committing is the one state-changing step; show the message and wait for yes.
- **Light by design.** No code review, no security review, no PR. Reach for `/ship-pr` when the change
  warrants review or you're opening a PR.

## Output

A PASS/FAIL line per step, then the commit SHA (or the reason the pipeline stopped):
```
ship: lint ✓ · tests ✓ (42 passed) · verify READY · commit <sha>
```
