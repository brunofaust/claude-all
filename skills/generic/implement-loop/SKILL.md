---
name: implement-loop
description: >-
  Implement an approved backlog/PRD one story at a time — each story in a FRESH subagent context, in
  dependency order, committed with an acceptance-criteria trace, reviewed diff-only, with progress fed
  forward. The structured "story-by-story" form of the Ralph loop. Use when: building a multi-story
  feature/refactor from a spec, "implement this backlog/PRD", "work through these stories one by one",
  or autonomously delivering a planned change without context drift. Pairs with `requirements-ears`
  (produces the stories + `[bN]` ids), `subagent-prompting` (fresh-context dispatch),
  `adversarial-verification` (per-story evidence), `code-review-discipline` (per-diff review), and
  `/ship-pr` (open the PR at the end). User-invoke only — it writes code and commits.
disable-model-invocation: true
user-invocable: true
---

# implement-loop — one story per fresh context, in order

Large features fail when one long session accumulates context and drifts — early decisions get
forgotten, later code contradicts earlier code, the model loses the plot. This loop fixes that by
making each story a **clean, bounded unit**: a fresh subagent implements exactly one story, it's
reviewed and committed on its own, and only a short progress note carries forward.

## Why story-by-story (vs a naive Ralph loop)

A naive Ralph loop re-runs the *same prompt* with fresh context and lets the agent decide what to do
next from a spec/progress file — simple and resilient, good for fuzzy/exploratory work, but it can
thrash, repeat work, or drift on what "next" means, and has no clean termination. **Story-by-story is
the structured form:** the work is pre-decomposed into discrete stories with dependencies and
acceptance-criteria ids, so each iteration has a *defined* scope, a *defined* done-condition, runs in
*dependency order*, and the loop *terminates* when the backlog is empty. You trade a little upfront
planning for determinism, traceability (story → `[bN]` criteria → test → commit), and reviewable
per-story diffs. Use the naive loop for spikes; use this for delivering a planned change.

## Inputs

- A **backlog/PRD**: an ordered list of stories, each with — an id, a one-line goal, the acceptance
  criteria it satisfies (`[bN]` ids from `requirements-ears`), the files it likely touches, and its
  dependencies (which stories must land first). If none exists, build it first (`requirements-ears`
  → stories, or `/retro`/a plan) before looping.
- A **progress file** (`progress.md` or `.jsonl`) the loop reads + appends to across iterations.

## The loop (one story per iteration)

1. **Pick the next unblocked story** — dependencies satisfied, not already done. If stories are
   independent (disjoint file sets), they may be dispatched in parallel; if file sets overlap,
   serialize.
2. **Dispatch a FRESH subagent** with ONLY what this story needs (per `subagent-prompting`): the one
   story + its `[bN]` criteria, the relevant files, and a short progress summary — **not** the whole
   session history. Budget it small (≈≤200 LOC); if a story is bigger, split it first.
3. **Implement + test.** The subagent writes the code and the tests that defend each `[bN]` criterion
   (name them `test_bN_…`), and runs the gates locally (lint, types, the affected tests).
4. **Review the DIFF only.** Run `/code-review` (or a reviewer subagent) on this story's diff —
   ideally a **different model** than implemented it (`code-review-discipline` → cross-model second
   opinion). Treat Block findings as a hard stop.
5. **Commit the story** (after the review is clean and tests are green) with an acceptance-criteria
   trace, e.g. a commit-body line `ac_trace: b3,b4` + one line of evidence per criterion. One story =
   one small, traceable commit on the current branch.
6. **Record progress** — append the story's outcome (done / blocked / escalated + evidence) to the
   progress file, so the next iteration starts from current truth, not stale context.
7. **Next story**, until the backlog is empty.

When the backlog is done, hand off to **`/ship-pr`** to review the assembled change and open the PR.

## Rules

- **Fresh context per story** — this is the whole point. Never carry one story's full working context
  into the next; the progress file is the hand-off, not the transcript.
- **Bounded stories** — keep each ≈≤200 LOC; split anything larger so the diff stays reviewable.
- **Reviewer sees the diff, not the repo** — per-story review, scoped to what changed.
- **Stop and escalate, don't grind** — on a Block finding, a genuinely ambiguous requirement, or a
  story that fails twice, write it to progress and **ask the user**. Cap retries (≈2) — never loop a
  failing story indefinitely.
- **Confirm before the run** — it writes code and commits. Commit per story to the current branch;
  leave pushing/PR to `/ship-pr`.
- **Per-story evidence** — each commit's claim of "done" follows `adversarial-verification` (ran it,
  quoted output) — not "should work".

## Output

A running log: per story → `id · done|blocked|escalated · commit <sha> · [bN] covered`, then a final
summary (stories completed, anything escalated) and the hand-off to `/ship-pr`.
