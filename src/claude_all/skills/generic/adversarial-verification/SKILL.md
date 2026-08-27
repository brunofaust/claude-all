---
name: adversarial-verification
description: >-
  Use before claiming success, completion, passing tests, a fixed bug or PR readiness, and after applying a fix.
disable-model-invocation: false
user-invocable: true
---

# Adversarial verification

> **"Don't confirm it works — try to break it."**

Default mode for any agent (or human) about to claim a task is done. Refuse to emit success language until the 5-step gate has run and produced a verbatim evidence block.

## Core rule

**No success word without a fresh command run quoted verbatim.**

Forbidden phrases until step 5 is complete:

- "should work" / "should be fine"
- "looks good"
- "seems to" / "appears to"
- "probably" / "likely"
- "I think it's working"
- "the fix is in"
- "Great!" / "Perfect!" / "Done!" (exclamatory satisfaction before verification)

If you typed one of these, **STOP**, restart the gate.

## The 5-step gate (verbatim, in order)

```
1. IDENTIFY  — name the specific claim you're about to make
               ("test X now passes" / "the API returns 200")
2. RUN       — execute the command that proves or disproves it (no skipping)
3. READ      — read the FULL output; quote exit code + last 20 lines
4. VERIFY    — match output against the claim. Mismatch → STOP, the claim is false
5. CLAIM     — only now write the success/failure verdict, with evidence inline
```

You do not get to claim PASS until step 5. You DO get to claim FAIL at any point.

## Epistemic markers — tag every claim by evidence status

When you state something during analysis or planning, mark *what kind* of statement it is, so an
unverified guess can't masquerade as a fact:

- **`[FACT]`** — verified now, or trivially verifiable (you ran it / read it / quoted it).
- **`[INFERENCE]`** — a logical conclusion from facts (could be wrong if a premise is).
- **`[ASSUMPTION]`** — unverified. **Must be validated before you build on it** — an `[ASSUMPTION]`
  driving an implementation decision is a bug waiting to happen.

The Feynman test: if you can't explain *how you know* a claim, it's not a `[FACT]`. Downgrade it.
The adversarial pass (and any reviewer) should hunt for `[ASSUMPTION]`s dressed up as `[FACT]`s, and
for `[INFERENCE]`s whose premise was never checked.

## Observation corollary — claims about behavior cite OBSERVED state

A claim that something *works* (UI renders, endpoint responds, job ran) is only `[FACT]` if you
observed the actual current state — not the code that *should* produce it. Acceptable observations:

- a screenshot / DOM dump (Playwright), a `curl` of the rendered response, a real log line, a query
  result, a test run quoted verbatim.

"The code looks correct so the page works" is an `[INFERENCE]`, not evidence — reading source is not
observing behavior. A claim about runtime behavior with **zero observation is incomplete by policy**;
go observe, then claim. (This is the same discipline as the 5-step gate, applied to non-test claims.)

## Completeness corollary — verify against the ORIGINAL ask, not just the last claim

A test passing proves the tested code is correct. It says nothing about whether you did **everything**
that was asked — the 5-step gate operates on one claim at a time and has no view of the whole task.

Before claiming the TASK (not just one claim) is done:

1. Re-read the original request / plan.
2. Build a checklist — one line per distinct requirement.
3. Verify each line individually (a passing test suite does not verify "I did the refactor AND updated
   the docs AND removed the old code path" — check each separately).
4. Report gaps explicitly. "Tests passing" is not itself a checklist item — it's one form of evidence
   for some of the items.

If a subagent did part of the work: diff its actual file changes (`git diff` / `git show`) against the
claim it returned — a subagent's summary can hallucinate success; the diff is the ground truth.

## Regression discipline (for bug-fix claims)

A test that passed before AND after a fix proves nothing. Run the revert-cycle:

```bash
# 1. Write the test FIRST
# 2. Run with the fix applied
pytest tests/test_X.py::test_bug_repro  # PASS expected

# 3. Revert the fix
git stash

# 4. Run again — the test MUST fail. If it still passes, the test doesn't exercise the bug.
pytest tests/test_X.py::test_bug_repro  # FAIL required

# 5. Restore the fix
git stash pop

# 6. Run a third time — confirm green
pytest tests/test_X.py::test_bug_repro  # PASS confirmed
```

Skip steps 3-5 only if you have a written reason. "I don't want to revert" isn't a reason.

## Try-to-break-it probe (one per claim)

Before claiming PASS, run at least ONE failure-case probe:

- Edge input (empty string, `None`, max int, unicode)
- Concurrent caller (race the operation)
- Missing dependency (env var unset, service down)
- Stale state (cache hit on wrong key, dirty fixture)

Quote what you ran + what you observed. If you can't think of a failure case, the claim isn't tested enough.

## Output template

After step 5:

````
**STATUS:** PASS | FAIL | PARTIAL

**Claim:** <single sentence, observable, no hedging>

**Evidence (verbatim):**
```
$ pytest tests/test_auth.py::test_token_expiry -x --tb=short
============================= test session =============================
collected 1 item
tests/test_auth.py::test_token_expiry PASSED [100%]
============================ 1 passed in 0.42s ==========================
```

**Tried-to-break with:**
- Empty `Authorization` header → returns 401 (verified, see auth_test.log:42)
- Token with `exp` 1 second in the past → returns 401 (verified)
- Token with `exp` 1 second in the future → returns 200 (verified)

**Regression check:**
- `git stash && pytest tests/test_auth.py::test_token_expiry` → FAILED (test correctly exercises the bug)
- `git stash pop && pytest ...` → PASSED (fix restored)
````

For `PARTIAL`: list what passed + what's untested + what would need to change to upgrade to PASS.

## Severity escalation

| Verdict | When                                                                                       |
| ------- | ------------------------------------------------------------------------------------------ |
| PASS    | All steps run, evidence quoted, try-to-break probes ran, regression check ran (if bug fix) |
| PARTIAL | Some claims verified, others can't be tested in this environment (note WHY)                |
| FAIL    | Evidence contradicts claim, OR verification couldn't run at all                            |
| BLOCKED | Pre-condition missing (auth, env, deps) — name the precondition, do not claim PASS         |

## Red flags — restart the gate if any of these fire

- Said "should" in your own response
- Skipped step 3 (didn't read the output)
- Used a cached result from earlier in the session as evidence
- Claimed PASS based on absence of error (no news ≠ good news)
- Marked a flaky test as PASS after the third re-run "this time it worked"
- Treated a clean compile as proof of correctness (compiles ≠ works)
- Said "the test I just wrote passes" without the revert-cycle

## Anti-patterns (NEVER do this)

- ❌ "All tests pass" → you ran `pytest` once, didn't read the count, claimed pass.
- ❌ "Manual testing confirms" → manual ≠ tested. Write the test.
- ❌ "It's a one-line change, it can't break" → famous last words.
- ❌ "The test was failing before, now it passes" → without revert-cycle, the test may always pass.
- ❌ Claim PASS based on agent return value alone (agents can hallucinate success).

## Judge the artifact, not the effort (anti-sycophancy)

When you EVALUATE something — your own work, a PR, an agent's output, a generated result — grade what
IS, not the attempt:

- **No cope phrases** that soften a failing verdict: "solid foundation", "good start", "has potential",
  "almost there", "on the right track". That's sycophancy, not assessment.
- **No points for effort or intent.** It works (evidence) or it doesn't. "Tried hard" / "complex
  problem" don't move the verdict.
- **State the verdict first, plainly**, then the evidence. If it fails, say "fails" and show the
  failing case — don't bury it under praise.
- Be specific about what's wrong and what would make it pass. Honest-and-actionable beats kind-and-vague.

The flip side of the evidence rule: just as you don't claim success without proof, you don't grant
partial credit without it either.

## Hand-offs

- For executing the test: `test-runner` agent.
- For multi-service scenarios: `e2e-scenario-runner` agent (it already encodes step-level evidence).
- For "did the agent skip something" suspicion: `self-rationalization-guard` skill.

## Inspiration

- [obra/superpowers — verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md)
- [alirezarezvani/claude-skills — adversarial-reviewer](https://github.com/alirezarezvani/claude-skills/blob/main/engineering-team/skills/adversarial-reviewer/SKILL.md)
- [robertoecf/adversarial-review](https://github.com/robertoecf/adversarial-review)
