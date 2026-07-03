---
name: diff-retrospective
description: >-
  Turn a range of merged PRs / commits into durable guardrails — read the DIFFS (not just the PR
  descriptions), cluster recurring root causes, and emit for each (a) a CLAUDE.md rule and, wherever
  possible, (b) an executable checker. Use when: "do a retrospective on the last N PRs", "what keeps
  going wrong", "turn these merged changes into lint rules / guardrails", post-mortem on a sprint or
  release, or hardening a codebase after a bug cluster. Complements `session-harvest` (which mines
  assistant chat histories) and `friction-analyzer` (one session transcript) — this one mines the
  SHIPPED CODE. Pairs with the `lessons-extractor` agent, which fans the diff-reading out in parallel.
disable-model-invocation: false
user-invocable: true
---

# diff-retrospective — merged PRs → guardrails

> **Read diffs, not descriptions.** A PR title says what the author *intended*; the diff says what
> actually shipped — including the bug they fixed, the test they had to add, and the mock they forgot.
> Retrospecting on descriptions surfaces themes; retrospecting on diffs surfaces *root causes you can
> encode as a checker*. This skill is the worked method behind "every recurring fix becomes a gate".

## Method

### 1. Pull the range as diffs

```bash
# every merged PR in a window, as patches (adjust the range/date to taste)
git log --merges --since="3 weeks ago" --pretty="%H %s"
# or a commit range
git log --oneline BASE..HEAD
# the actual changes — this is the signal
git show <sha>            # one change
git diff BASE..HEAD       # the whole range
```

For a large range, partition it and fan out with the **`lessons-extractor`** agent (it runs parallel
readers over sub-ranges and merges) so you don't blow the context window on raw patches.

### 2. Classify each change by what it reveals

For every non-trivial diff, ask: *what failure did this change exist to fix or prevent?* Tag it
against a root-cause taxonomy (extend per your stack):

| Cluster | Tell-tale in the diff |
| --- | --- |
| Mock/test drift | a mock updated alongside a signature/return change; a test that only now asserts the real shape |
| Real-dependency gap | a first integration test added against a real DB/SDK; a SQL/schema fix |
| Config/wiring | a setting added to a second deploy unit; a constant promoted to config; a baked asset added to a build |
| Distributed correctness | idempotency marker moved after success / into `finally`; partial-batch reporting; pagination to exhaustion; a migration merge |
| Security | a secret moved to point-of-use; `repr=False` added; a per-tenant cache bug; `shell=True`→argv list |
| Ownership/dup | a third copy extracted to one owner; a junk-drawer module split; dead scaffolding deleted |
| LLM seam | a structured-output schema fixed against real model output; an enum added to a constrained field; SDK migration |

### 3. Cluster and rank

Group the tagged diffs. A cluster with **≥2 independent occurrences** is a pattern worth a guardrail —
rank clusters by frequency × severity. A one-off stays a one-off (note it, don't gate it).

### 4. Emit a guardrail per cluster — checker first, prose second

For each cluster produce BOTH where possible:

- **(b) an executable checker** — the durable form. A lint rule, AST check, or pre-commit/CI gate that
  fails on the recurrence. Roll it out regression-only via the **`regression-gates`** skill (baseline
  today's findings, ratchet to zero) and **ship it with the fix that motivated it**. Many clusters map
  to a ready checker: mock drift → spec'd-mock discipline; config → "no tunable as a module constant";
  ownership → `junk_drawer` / `module_private`; migrations → `migration_head`; CI env → `ci_env_guard`.
- **(a) a CLAUDE.md rule** — for the gap before the checker exists and for judgment a checker can't
  make. Keep it small and place it at the right altitude (see `agent-era-rules`): global rule → root
  file; area-specific → a per-directory instruction loaded on demand.

A prose lesson is **not** a deliverable. If a cluster can only be expressed as prose, say why a checker
can't catch it.

### 5. Output

A short report: each cluster, its evidence (the specific diffs/SHAs — verbatim, no paraphrase), the
proposed checker (with a rollout note) and/or the CLAUDE.md rule, and the clusters you deliberately
left as one-offs. Report-only — propose; the human decides what to wire.

## Why diffs beat descriptions and transcripts

- **vs PR descriptions** — descriptions are aspirational and omit the embarrassing fix; the diff is
  ground truth.
- **vs `session-harvest` / `friction-analyzer`** — those mine *how the work felt* (chat histories,
  reverts, command thrash). This mines *what shipped*. Run both: friction tells you where the agent
  struggled; diffs tell you which struggles became bugs.
