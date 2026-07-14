---
name: aws-debug-loop
description: >-
  Structured debug loop for AWS dev environments. Covers e2e and integration test failures: how to split a full test into isolated pieces, hotfix the dev environment directly (env vars, timeouts, image versions) before deploying, validate each fix in isolation, run independent pieces in parallel, sweep ALL log groups with `awslogs` for scattered/async root causes, and know when to declare a piece fixed vs when to redeploy. Stop condition: the full test passes clean — never stop earlier. Use when: debugging e2e or integration test failures against AWS dev environments, working with Lambda / Step Functions / SQS / DynamoDB / ECS, investigating multi-step pipeline failures, sweeping CloudWatch logs across every log group for a symptom with no obvious owner, or deciding whether to hotfix dev vs deploy.
user-invocable: true
---

# AWS Dev Debug Loop

Fail fast on the smallest possible piece. Never re-run the full test while
individual pieces are still failing — full runs are slow and expensive.

______________________________________________________________________

## The Loop (3 phases, repeat until clean)

```
Phase 1 — Full run     →  capture ALL failures at once
Phase 2 — Isolate      →  split into pieces, fix each in isolation (parallel)
Phase 3 — Verify       →  full run again only when all pieces pass in isolation
```

Stop condition: **Phase 3 passes with zero failures.**

______________________________________________________________________

## Phase 1 — Full run

Run the complete e2e or integration test **once**.

- Capture every failure — do not stop at the first one.
- Map each failure to its owner resource (Lambda fn, SF state, SQS consumer, DynamoDB access pattern, …).
- Group failures by resource — one resource may produce multiple symptoms.
- Run the [all-groups log sweep](#all-groups-log-sweep-awslogs--the-highest-yield-failure-finder)
    now too — the test output names only its own failures; the sweep surfaces
    scattered/async root causes it never mentions.

> Do not re-run the full test again until Phase 2 is complete for all pieces.

______________________________________________________________________

## Phase 2 — Isolate and fix

For each failing piece (run independent pieces **in parallel**):

```
while piece still failing:
    1. Read the error carefully — what exact thing failed?
    2. Form a hypothesis — what is the root cause?
    3. Apply the smallest possible fix (hotfix dev env if possible, else deploy only that resource)
    4. Run the isolated test for that piece
    5. Read the result:
       - Same error      → fix did not work. Re-examine. Repeat.
       - Different error → fix worked. The new error is the next bug. Continue loop.
       - No error        → piece is fixed. Move on.
```

### Hotfix dev env first — zero deploy time

Before writing code and deploying, check whether the root cause can be fixed
directly in the dev environment:

| Symptom                          | Hotfix (no deploy needed)                   |
| -------------------------------- | ------------------------------------------- |
| Lambda timeout                   | Increase timeout in Lambda config           |
| Lambda OOM                       | Increase memory in Lambda config            |
| Missing env var                  | Add env var directly in Lambda config       |
| Wrong env var value              | Update env var directly in Lambda config    |
| Lambda pulling wrong image       | Update function to point to correct ECR tag |
| SQS visibility timeout too short | Update attribute on the queue               |
| SQS batch size wrong             | Update event source mapping                 |
| Lambda concurrency too low       | Update reserved/provisioned concurrency     |
| DynamoDB capacity exhausted      | Switch to on-demand or increase RCU/WCU     |
| IAM permission missing           | Attach inline policy to the role            |

If the hotfix resolves it → great, no deploy needed.
If the root cause requires a code change → deploy only the affected resource, then re-test that piece in isolation.

### What counts as "isolated test for a piece"

| Resource             | Isolated test                                                                 |
| -------------------- | ----------------------------------------------------------------------------- |
| Lambda function      | Direct invoke with a crafted payload matching the real event shape            |
| SQS consumer Lambda  | Send a message to the dev queue, watch the Lambda process it                  |
| Step Functions state | See [Step Functions splitting](#step-functions-splitting) below               |
| DynamoDB access      | Run the exact query/write in isolation (dynamodb-inspector / direct SDK call) |
| ECS task             | Trigger the task directly with the same input                                 |
| API Gateway endpoint | `curl` / HTTP client against the dev endpoint with the exact request          |

______________________________________________________________________

## Step Functions splitting

When a Step Function execution fails, do not re-run the whole SF to test a
single state fix. Split it.

### Option A — Direct Lambda invoke (fastest)

Best when: the state's logic is self-contained and you only need to verify the
Lambda handler, not the SF routing.

1. Read the failed execution history to get the exact input the failing state received.
1. Invoke the Lambda behind that state directly with that input.
1. Fix → re-invoke directly → confirm different/no error.
1. Only then re-run the SF (or just the sub-flow that includes that state).

### Option B — SF re-run from crafted input (when routing matters)

Best when: the bug involves SF input/output mapping, error catchers, retry
policies, Wait states, or branching.

1. Identify the exact state where execution failed.
1. Start a **new SF execution** with the input that failing state needs — craft
    it from the failed execution's event history.
1. Fix → start another execution → confirm it advances past the previously
    failing state.

### Choosing A vs B

| Scenario                                                        | Use               |
| --------------------------------------------------------------- | ----------------- |
| Lambda handler bug (bad code, missing key, unhandled exception) | A — direct invoke |
| SF `Parameters` / `ResultSelector` / `ResultPath` mapping wrong | B — SF re-run     |
| Error catcher / retry policy not triggering as expected         | B — SF re-run     |
| Lambda works fine but SF never calls it (IAM, resource ARN)     | B — SF re-run     |
| Parallel branch coordination or Map state bug                   | B — SF re-run     |

______________________________________________________________________

## Parallel testing

Independent pieces can be tested simultaneously. A piece is independent when:

- It reads from / writes to **different** resources than other pieces under test.
- A fix to one does not change the output another piece depends on.

If piece A's output feeds piece B → fix and validate A first, then B.

When in doubt, test sequentially. Parallel is an optimisation, not a requirement.

______________________________________________________________________

## Progress signals

| Result of isolated test | Meaning                      | Action                                           |
| ----------------------- | ---------------------------- | ------------------------------------------------ |
| **Exact same error**    | Fix did not work             | Re-read the error, re-form hypothesis, try again |
| **Different error**     | Fix worked — new bug exposed | Capture the new error, loop on it                |
| **No error**            | Piece is fixed               | Mark done, move to next piece                    |
| **Unrelated new error** | Side-effect of the fix       | Investigate — may have introduced a regression   |

Never interpret "different error" as a failure. It is progress.

______________________________________________________________________

## Phase 3 — Full run (verification)

Run the full e2e / integration test **only** after every piece passes its
isolated test.

- If it passes → done.
- If it fails → new bugs surfaced by integration. Return to Phase 2 with the
    new failure set.

______________________________________________________________________

## All-groups log sweep (`awslogs`) — the highest-yield failure finder

When a symptom has **no obvious owner** (a step "did nothing", a downstream
record never appeared, a vague "could not process"), do **not** grep only the
one suspect log group. Pull **every** log group for the env over the failure
window and grep a fixed error-signature set. Root causes scatter across
services, and a crash in a **scheduled / background / async** resource (a cron
Lambda, a sweeper, a queue consumer, a retry worker) is invisible to *both* the
happy-path e2e **and** a single-resource cold-start probe — the all-groups sweep
is the only thing that catches it. In practice this is repeatedly the single
highest-yield move of a debug session.

Use [`awslogs`](https://github.com/jorgebastida/awslogs)
(`brew install awslogs` or `pipx install awslogs`): its `get <group> ALL` pulls
**all streams** of a group in one call — what `aws logs tail` on a single stream
won't give you in a sweep.

**The sweep** — delegate the fan-out to the `cloudwatch-inspector` /
`incident-responder` agents (large output; don't hand-run it inline in the main
session):

```bash
export AWS_PROFILE=myapp-dev
mkdir -p logs
# 1. Enumerate EVERY group for the env — not just the suspect one:
awslogs groups | grep 'myapp-dev-'
# 2. Pull ALL streams of each group over the failure window, to files:
for g in $(awslogs groups | grep 'myapp-dev-'); do
  awslogs get "$g" ALL --start='3h ago' --no-color > "logs/${g##*/}.txt"
done
# 3. Grep one fixed signature set across every file:
grep -niE 'error|exception|traceback|fail|denied|ValidationError|timeout|throttl|conflict|[45][0-9][0-9]' logs/*.txt
```

`warn|warning` is a wider, noisier pass — add it when hunting a silent-degradation
bug, but expect benign hits to triage out.

**Then loop the sweep** (this is the "analyse in loop" part):

```
1. Dedupe hits into a table:  group | signature | count | first-seen
2. Triage each row to an owner resource — feed real bugs into Phase 2.
3. Fix the smallest piece.
4. RE-SWEEP the same window.
   - Signature gone AND no new signature  → that fix is confirmed.
   - Signature still present              → not fixed. Re-hypothesise.
   - New signature appeared               → the fix caused a regression. Triage it.
```

Report the table **even when empty** ("swept N groups, 0 signatures") so a clean
sweep is on record — a silent skip reads as "nothing was wrong" when nothing was
looked at.

Where it plugs into the loop:

- **Phase 1** — run it alongside mapping the test's own failures; it surfaces the
    scattered/async root causes the test output never names.
- **Phase 3** — run it as a mandatory regression gate; it catches new crashes in
    **unrelated scheduled resources** that the happy-path verification can't see.

______________________________________________________________________

## Rules

1. **Full test runs at most twice per outer iteration** — once to gather
    failures (Phase 1), once to verify all fixes (Phase 3).
1. **Hotfix dev env before deploying** — zero deploy time is always faster.
1. **Deploy only the failing resource** — never redeploy unrelated services.
1. **Parallel where independent** — cuts total debug time significantly.
1. **Never stop at "it looks better"** — stop only when Phase 3 passes clean.
1. **Capture every error message verbatim** — exact text matters for diagnosing
    "same vs different" error comparison.
1. **One hypothesis per iteration** — changing two things at once makes it
    impossible to know which fix worked.
1. **Sweep ALL log groups, not the suspect one** — the all-groups `awslogs` sweep
    is the only thing that catches crashes in scheduled/async resources the
    happy-path test and cold-start probe both miss; re-sweep to confirm each fix.
