---
name: agent-orchestration
description: >-
  Measured failure modes of running many subagents in parallel against one
  repository, and the dispatch rules that fixed them. Use when: fanning out
  parallel work across worktrees, an agent went silent / "parked" / returned a
  status line instead of a report, deciding whether to believe a subagent's
  report before acting on it, a long verification run needs to be proven,
  partitioning a retrospective or audit across several agents, or two
  individually-green PRs broke the main branch. Covers what happens AFTER
  dispatch — `subagent-prompting` covers writing the prompt itself.
disable-model-invocation: false
user-invocable: true
---

# Agent orchestration

> `subagent-prompting` is about writing ONE dispatch prompt.
> This is about running a FLEET: what breaks at scale, and what to do about it.

Every rule below is an observed behaviour with a count, from ~40 subagents and 84
merges against one repository in 72 hours. Not theory.

**What this does NOT restate** — cross-reference, don't duplicate:

| Topic                                                                                 | Lives in                   |
| ------------------------------------------------------------------------------------- | -------------------------- |
| The 10-point dispatch prompt, return-status enum, parallel independence preconditions | `subagent-prompting`       |
| Verifying claims **you** are about to make                                            | `adversarial-verification` |
| Mining merged diffs for durable guardrails                                            | `diff-retrospective`       |
| A gate that passed because it checked nothing (vacuous PASS)                          | `prek`                     |
| Polling for a real readiness condition instead of waiting blind                       | `wait-for-ready`           |
| Pulling main into a branch and resolving semantic conflicts                           | `merge-main`               |

> `adversarial-verification` governs claims **you make**.
> Sections 3 and 4 govern claims **you receive**. Different failure, different fix.

---

## 1. Agents park forever waiting for a notification nobody sends

**Five of five** agents did this in one session; two lost 30–45 minutes of
uncommitted work. The tell is a final turn reading *"I'll wait for the completion
notification"* or *"the pollers are armed."* Nothing is watching. Pausing is not a
terminal state — the agent reports `completed` with a status line where the report
should be, and its work is still uncommitted in a worktree.

Dispatch-prompt clauses that stopped it:

- **Run gates in the FOREGROUND with an explicit `timeout`.** No backgrounding
  inside a subagent — it has nothing to wake it. (If a real readiness condition
  exists, poll it: `wait-for-ready`.)
- **"DO commit and report the SHA."** Commit BEFORE verifying, not after. Say it
  positively: *"don't commit to main"* gets read as *"don't commit at all"*, and
  that is exactly how the lost work was lost.
- **"A timeout is a RESULT."** Report `TIMED OUT` with what ran, and move on.
  Never retry the same long command.
- **"Your next message must be the report block"** — with `NOT RUN` on any line
  it could not complete. An incomplete report beats no report.

**Recovery:** a parked agent is not dead. Sending it a message resumes it from its
own transcript with context intact — cheaper than re-dispatching from zero.

## 2. Long commands auto-background — so no subagent can prove a long run

Past a hard ceiling (10 minutes in the harness measured here), asking for a longer
timeout does not extend the limit — the command is **auto-backgrounded** instead.
Inside a subagent that is fatal: it gets an empty output file, no completion signal,
and can only honestly report `NOT PROVEN`. A 13-minute test tier is therefore
unprovable inside a subagent, no matter how the prompt is worded.

**Run long verification from the main session**, backgrounded, redirecting to a
scratch file, then tail only the last lines. Dispatch subagents for work that fits
under the ceiling; keep the long proof upstairs.

## 3. An agent's SUMMARY drifts from its own EVIDENCE — read the evidence

Measured four-plus times in one session:

- a report claiming **"483 passed"** whose own transcript said **544**;
- two PRs reported merged with the **same** merge SHA (it had echoed the main
  branch's tip twice);
- a "still-open PRs" list assembled from a **pre-fetch** state;
- **"origin/main NOW AT &lt;sha&gt;"** quoted **31 commits stale**.

None were malicious, and **every one was caught by re-running a single command.**

**Rule: verify any number you are about to act on or relay.** SHAs, pass counts, PR
states, branch tips. One `git rev-parse`, one PR query, one re-run of the suite is
cheaper than a decision built on a stale figure.

## 4. Verdicts that contradict their own data — the evidence wins

One agent concluded *"×0 refusals — confirms the fix holds"* when the fix was **not
deployed** and the refusals had demonstrably occurred: it read *absence of a log
line* as *absence of the event*. Another declared a config change safe by summing
the bytes it would add, when the cloud provider had **already rejected that exact
change**.

**When an agent's conclusion and its evidence disagree, the evidence wins.** Two
checks before accepting a verdict:

- Does the conclusion depend on something **not appearing**? Absence of a log line
  proves nothing about the event unless that line is proven to appear when it does.
- Did reality already answer this? A prior error, rejection, or failing run outranks
  a fresh recomputation that concludes the opposite.

## 5. Working directory does not persist between Bash calls

One agent `cd`'d once, then edited the **primary checkout** instead of its worktree
for an entire session. Its work was the only copy of that change.

- **cd-prefix EVERY single Bash call.** Not the first one — every one.
- Have long runs **echo `PWD` and `HEAD` into their own log**, so a wrong-tree run
  is visible in the output rather than inferred afterwards.
- Put the absolute worktree path in the dispatch prompt and require it back in the
  report block.

## 6. Tree-wide git writes destroy other sessions' work

A `git reset --soft origin/main` briefly staged reverts of **three other sessions'
already-merged work**; caught before push, by luck.

**Never** `git stash`, `git reset`, `git checkout .`, `git clean`, or a blind
`git add -A` in a repository other sessions are live in. **Stage explicit paths.**
State this as a refuse-condition in every dispatch prompt that touches git.

## 7. Environment gaps that read as passes

A fresh worktree has no installed frontend packages, so four frontend lint hooks
failed with `No such file or directory` — and **six agents in a row** reported that
as *"environmental, not a code issue."* Read in sequence, that reads as *"the
frontend gates passed."* They never ran. Same class: a shared virtualenv whose
`.pth` file points at a different worktree, so imports resolve against someone
else's tree.

**An environmental failure and a real one must be distinguishable, or the gate is
decorative.** Fix it in the dispatch, not the report:

- Symlink the virtualenv and the package directory into every new worktree
  **before** dispatching, and say in the prompt that they are expected to exist.
- Require the report to list gates as `PASS` / `FAIL` / **`NOT RUN (reason)`** —
  never let a third state collapse into the first.

## 8. Guess a ticket number and you link the wrong ticket

Branch names auto-link to the tracker by ticket id. Guessing the next free number
**collided twice** with tickets other agents had filed minutes earlier — the branch
then auto-linked to someone else's work.

**File the ticket first, take the number the tracker assigns, then name the branch**
`<user>/TICK-<n>-<slug>`. Never derive the number from "the highest one I saw".

## 9. Two individually-green PRs can break the main branch

Measured twice in one day. Two PRs merged an hour apart each passed alone, merged
with **zero textual conflict**, and broke the main branch: one added required
keyword-only arguments, the other's new tests called the same function without them.
Later, two fixes each correct in isolation defeated each other through a **shared
mutable flag**.

Whole-corpus and pairwise gates are structurally blind to this: each PR is green
against the tree it was written on. A `post-merge` hook can detect it but **cannot
block** — git ignores a post-merge hook's exit code. The orchestrator's duty:

- **Run the full tier against the MERGED result**, not against each branch
  (`merge-main` for pulling main in first).
- When two in-flight PRs touch adjacent code, **name both diffs to the reviewer**
  and ask it to check the seam explicitly — signature changes, shared module-level
  state, and new required arguments are where they collide.
- Serialize merges of adjacent-code PRs; never batch-merge a group sharing a file.

## 10. Partition parallel work by SUBSYSTEM, not by time

Five retrospective sweeps partitioned **by subsystem** each surfaced cross-PR
interactions that a per-PR review structurally cannot see — a per-PR or per-day
split hides exactly the seam failures in §9.

**Contention is real and it is arithmetic.** 13 agents each running `pytest -n 6` is
**78 test workers** on one machine. Cap `-n 2` when many agents share the box, and
put the number in the dispatch prompt — an agent left to choose picks the solo default.

---

## Dispatch-prompt checklist — the delta

Adds to `subagent-prompting`'s 10-point checklist; does not replace it. Its points 2
(inline every fact — no "see above") and 7 (zero-memory preamble) still apply
verbatim. These five are what this session measured as additionally load-bearing:

1. **Foreground + explicit timeout on every gate.** No backgrounding inside a
   subagent; nothing will wake it. Anything over the ceiling stays in the main
   session (§2).
1. **Commit BEFORE verifying, and report the SHA.** Phrase positively — *"DO commit
   on your branch and report the SHA"* — so it cannot be read as "don't commit" (§1).
1. **"If your evidence contradicts your conclusion, report the EVIDENCE and say
   `NOT PROVEN`."** Plus: a timeout is a `RESULT` (`TIMED OUT`, no retry), and every
   gate is reported `PASS` / `FAIL` / `NOT RUN (reason)` (§1, §4, §7).
1. **Name the files other agents own**, and the absolute worktree path this agent
   owns. Require `PWD` + `HEAD` echoed in the report (§5).
1. **The never-violate list, verbatim in the prompt:** no `SKIP=` / `--no-verify`;
   never widen a gate to make a finding vanish; no `git stash` / `reset` /
   `checkout .` / `clean` / blind `git add -A`; merge with `--merge`, never `--squash`.

**Report block to require** (one line per gate, `NOT RUN (reason)` allowed):

```
STATUS: DONE | BLOCKED | TIMED OUT | NOT PROVEN
BRANCH / WORKTREE / PWD / HEAD:
COMMIT SHA:
GATES: lint=<...>  types=<...>  tests=<...>  hooks(pre-commit)=<...>  hooks(pre-push)=<...>
EVIDENCE: <verbatim lines — exit codes, counts, error text>
PROBLEMS:
```

## Before you act on any agent report

1. Is the final message a **report**, or a status line plus a promise to wait? A
   promise means it parked — resume it with a message; don't accept the turn (§1).
1. Re-run one command for every **number or SHA** you are about to relay (§3).
1. Does any conclusion rest on something **not appearing** in output? (§4)
1. Any gate reported as "environmental"? That is `NOT RUN`, not `PASS` (§7).

## Hand-offs

- Writing the prompt itself → `subagent-prompting`.
- Checking your own final claim before reporting → `adversarial-verification`.
- Turning a batch of merged PRs into new gates → `diff-retrospective`.
