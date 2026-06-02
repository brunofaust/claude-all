---
name: adversarial-verification
description: >-
  Evidence-first verification discipline. Use BEFORE claiming work complete, before opening a PR, after applying a fix, before saying "tests pass" / "it works" / "the bug is fixed". The rule: no success word without a fresh command run quoted verbatim. Tries to BREAK the change instead of confirming it. Pairs with `test-runner` (executor) and `e2e-scenario-runner` (multi- service probe). Synthesized from obra/superpowers `verification-before- completion`, alirezarezvani/claude-skills `adversarial-reviewer`, robertoecf/adversarial-review.
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

```
**STATUS:** PASS | FAIL | PARTIAL

**Claim:** <single sentence, observable, no hedging>

**Evidence (verbatim):**
```

$ pytest tests/test_auth.py::test_token_expiry -x --tb=short

=== =========================== test session ==============================

collected 1 item
tests/test_auth.py::test_token_expiry PASSED [100%]

=== ===================== 1 passed in 0.42s =======================

```

**Tried-to-break with:**
- Empty `Authorization` header → returns 401 (verified, see auth_test.log:42)
- Token with `exp` 1 second in the past → returns 401 (verified)
- Token with `exp` 1 second in the future → returns 200 (verified)

**Regression check:**
- `git stash && pytest tests/test_auth.py::test_token_expiry` → FAILED (test correctly exercises the bug)
- `git stash pop && pytest ...` → PASSED (fix restored)
```

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
