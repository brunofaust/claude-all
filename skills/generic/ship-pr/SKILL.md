---
name: ship-pr
description: >-
  Heavyweight pre-PR pipeline — the full /ship gate sequence PLUS code review and a draft PR. Sequence:
  lint-fixer → test-runner → verification-loop → /code-review (gate) → (security-review if the change
  touches a security surface) → (confirm) → git-committer → open a DRAFT PR. Use when: "open a PR for
  this", "review and ship", finishing a substantive change that warrants review before it goes out.
  For the quick lint+test+commit loop with no review/PR, use the lighter `/ship`. Orchestrator only: it
  sequences existing agents and skills and gates on their results.
disable-model-invocation: true
user-invocable: true
---

# /ship-pr — lint → test → verify → review → commit → draft PR

The heavier sibling of `/ship`: it adds the review gate and PR creation for changes that are going out
for others to see. Review runs **once here**, on the assembled diff — deliberately NOT on every commit
(that's slow and noisy). Each step delegates to its focused agent/skill; the pipeline **stops on the
first hard failure**.

## Steps (run in order; STOP and report on any hard failure)

1. **Gates — run the `/ship` sequence:** `lint-fixer` → `test-runner` → `verification-loop`. If any
   hard-fails, stop there (same rules as `/ship`).
2. **Code review — `/code-review` skill (gate).** Review the working diff. Treat **Block** findings as
   a hard stop: fix them (loop back through the gates) or surface them for a decision. Warnings are
   reported, not blocking.
3. **Security review — `security-review` skill (conditional).** If the diff touches a security surface
   (auth, secrets, input handling, IaC/IAM, shelling out, tenant-scoped state), run it and gate on its
   Block findings too. Skip for changes that clearly don't.
4. **Commit — `git-committer` agent (after confirm).** When review is clean, show the diff summary +
   proposed Conventional Commits message, get a one-word confirm, commit to the current branch.
5. **Draft PR — (after confirm).** Push the branch and open a **draft** PR (title + body summarizing
   the change and the gate results). Opening a PR is outward-facing — confirm before doing it, and
   default to draft. Do not enable auto-merge.

## Optional tail — review an already-open PR

`/ship-pr` reviews the *working diff before* it becomes a PR. To review an *already-opened* PR by
number (someone else's, or a re-review after pushes), use the existing **`review`** skill —
`review <pr#>` — rather than folding PR-number review into this pipeline.

## Rules

- **Review once, here — not per commit.** Keep `/ship` cheap; pay the review cost when you're actually
  opening a PR.
- **Block findings are a hard stop.** Never commit/open over an unresolved Block from code or security
  review.
- **Confirm the two outward steps** (commit, then PR) separately; default the PR to draft; never push
  force / enable auto-merge from here.
- **Delegate, don't inline;** stop-on-hard-fail; one PASS/FAIL line per step.

## Output

```
ship-pr: lint ✓ · tests ✓ · verify READY · review ✓ (0 block, 2 warn) · sec n/a · commit <sha> · PR #NN (draft)
```
