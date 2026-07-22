---
name: execution-trace-audit
description: >-
  Debugger-style flow-level audit of a service's entrypoints — trace each one hop-by-hop the way you'd
  step a debugger, counting DB/network round-trips, to surface dead code and producer/consumer bugs
  that file-level review misses. Use when: doing a periodic audit of Lambda / ECS / K8s / CLI / HTTP
  entrypoints, after a big migration or refactor, hunting latency (too many round-trips) or flow-dead
  code (a branch nothing can reach today, a helper only tests call), or when file-by-file review keeps
  passing code that breaks in production. Produces a risk-rated simplification table + a separate bug
  ledger. The honest payoff is NOT lines removed (usually single-digit %) — it's the round-trips saved
  and the confirmed bugs the trace uncovers.
disable-model-invocation: false
user-invocable: true
---

# execution-trace-audit — trace each entrypoint like a debugger

> **Why file-level review misses these.** Reading a file top-to-bottom tells you the file is
> internally consistent. It does **not** tell you whether the *branch* is reachable given who can
> actually produce the input, whether the same row is fetched twice across three helpers in one
> invocation, or whether a producer and its consumer still agree on the shape they pass. Those are
> **flow** properties — visible only when you follow one real request from the entrypoint to the last
> side effect. This audit does exactly that, per entrypoint, and it reliably finds two things a file
> pass cannot: **flow-dead code** and **producer/consumer drift** (real bugs).

## When to run it

- A **periodic** pass over all service entrypoints — lambdas, ECS/K8s tasks, CLI commands, HTTP
  handlers, queue consumers, scheduled jobs.
- **After a big migration/refactor**, when whole branches may have been orphaned or contracts moved.
- **Hunting latency** — chatty code (N adjacent round-trips that could be one) shows up as a hop count.
- **Hunting dead code** a file-level or dead-code tool misses because a branch is *reachable in
  principle* but *unreachable given who produces the state* (see `references/yagni.md` — a defensive
  branch on an input the callers already guarantee).

## The method

Seven steps. Steps 1–5 are read-only analysis; step 6 is the implementation pass; step 7 is how to
fan it out across agents.

### 1. Inventory the entrypoints

List every place execution *starts*: each handler, task `main`, CLI subcommand, route, consumer.
One row per entrypoint. This is the audit's unit of work — everything below is done per entrypoint.

### 2. Trace the DOMINANT realistic scenario, hop by hop

For each entrypoint, pick the **one scenario that actually dominates traffic** (the happy path a real
request takes), not an exotic edge. Then trace it like stepping a debugger — **one line per hop**:

```
hop  what runs                                          round-trip?
1    handler parses event → Model.model_validate         —
2    load config for tenant                              DB (SELECT)   #1
3    load the same tenant row again inside helper_x       DB (SELECT)   #2  ← duplicate of #2
4    fetch work item                                     DB (SELECT)   #3
5    call downstream service                             NET (HTTP)    #1
6    write result                                        DB (INSERT)   #4
7    enqueue follow-up                                   NET (queue)   #2
```

**Tag and count every DB and network round-trip.** The count is the primary output of the trace —
it is what makes "this invocation runs four reads, two of them for the same row" a fact instead of a
feeling. A hop that is pure in-process logic gets a `—`.

### 3. Interrogate each hop with the YAGNI questions

Walk the hops and ask — these are the [`references/yagni.md`](../../python/brunofaust-python-style/references/yagni.md)
deletion-pass questions, applied at flow scale rather than to a single file:

- **Pass-through only?** Does this hop just forward its input to the next call and add nothing? →
  inline it.
- **Loaded twice per invocation?** Is a row/config/token fetched here already in hand from an earlier
  hop of the *same* invocation? → pass it down; collapse the second round-trip.
- **Reachable today — who produces this state?** For each branch, name the concrete producer that
  could deliver the input that selects it. If nothing in the system produces it anymore (a status a
  migration retired, a field a former caller set), the branch is **flow-dead**. Verify the producer,
  don't assume it.
- **Adjacent round-trips collapsible?** Two reads / two API calls back-to-back that one query or one
  batched call could serve? → collapse.
- **Defensive check on type-guaranteed input?** An `if x is None` on a value the type and every caller
  already guarantee non-null? → delete (it hides the real contract).
- **Loop-invariant work inside a loop?** A fetch/compute inside a loop that doesn't depend on the loop
  variable? → hoist it.

### 4. Produce a risk-rated simplification table + an explicit do-not-cut list

Turn the interrogation into a decision table — one row per proposed simplification:

| Simplification | LOC | Round-trips saved | Risk | Follow-up-safe? |
| --- | --- | --- | --- | --- |
| Collapse duplicate tenant load (hops 2–3) | −8 | −1 SELECT | low | y |
| Inline pass-through `helper_x` | −15 | 0 | low | y |
| Remove flow-dead `status == "legacy"` branch | −40 | 0 | med | n (needs owner) |

- **Risk** = low / med / high. Low: mechanical, behavior obviously identical. Med: a reachability
  claim you're confident of but that touches a boundary. High: skip in this pass — record it, don't
  cut it.
- **Follow-up-safe?** = can this be split into its own tiny PR safely, or does it need the owner's
  sign-off / a producer audit first?

Then write the **do-not-cut list** — the things that *look* removable to a size counter but are
load-bearing, so a later reader (or an agent) doesn't "simplify" them away:

- **Idempotency markers / dedup keys** — written after success, they look like a no-op line.
- **Locks** (advisory, row, distributed) — a lock acquire "does nothing" until two invocations race.
- **Boundary models** — a Pydantic model parsing untrusted input is a foundation, not ceremony
  (see `references/yagni.md`, "YAGNI is for features, not foundations").
- **Docstrings, `repr=False` on secret fields, `finally` cleanup** — never counted as savings.

### 5. Record BUG FLAGS separately — never fix behavior in a simplification pass

Tracing a producer→consumer path is exactly what surfaces **drift**: the producer writes shape A, the
consumer reads shape B; a queue has a producer but no consumer (or vice versa); two paths take the
same locks in opposite orders. These are **bugs, not simplifications** — keep them in a **separate
ledger** and give each a verdict:

- **confirmed** — reproduced or proven by the trace (e.g. "producer sets `.foo`, consumer reads
  `.bar`; grep confirms no writer of `.bar`").
- **not-a-bug** — the trace looked suspicious but the contract holds; say why.
- **needs-owner-decision** — real divergence, but the correct behavior is a product call.

**A simplification pass must never silently change behavior to "fix" a flagged bug.** Cutting code and
changing what the code *does* are different acts with different review needs — separate them.

### 6. Implementation pass — re-verify at HEAD, preserve behavior absolutely

Only now do you cut. For each simplification you decided to take:

- **Re-verify the claim at HEAD** before removing anything — the trace may be hours or days old, and
  main moves. A "duplicate load" someone already collapsed, a "dead branch" someone re-armed, and your
  cut is now wrong.
- **Behavior preservation is absolute.** A simplification changes *how* the code reaches a result,
  never *which* result. If you can't cut without changing behavior, it's a bug-fix (step 5), not this.
- **Update the mirror tests in the same change.** Deleting a hop deletes its coverage; the surviving
  path's tests must still pin the behavior. (When you delete one of two twin implementations, port its
  boundary tests to the survivor — see `brunofaust-python-style` `references/architecture.md`.)
- **Skip the high-risk items** you flagged, with the reason recorded. A partial, safe cut beats a
  complete, risky one.

### 7. Fan-out — one trace agent per entrypoint, disjoint fixers, solo hub owner

For a repo with many entrypoints, parallelize without corrupting each other:

- **Trace phase:** one **read-only** trace agent per entrypoint (they share nothing; the traces are
  independent). Each returns its hop table, its simplification table, and its bug ledger.
- **Fix phase:** per-area **fixer** agents on **disjoint file sets** — two agents must never edit the
  same file. Partition by directory / ownership.
- **Shared-hub files** (a module many entrypoints import — a config loader, a common client) get a
  **single sequential owner**, never parallel writers, or the edits collide at merge time.

See the `subagent-prompting` skill for writing self-contained dispatch prompts, and
`dispatching-parallel-agents` for the independence test.

## The honesty note — do not cut to a quota

Measured reality from a run over roughly two dozen entrypoints: the **LOC savings are typically
single-digit percent**. That is not the win. The wins are:

1. **Round-trips / hops removed** — measurable latency and cost, from collapsing duplicate loads and
   chatty adjacent calls.
2. **The bug harvest** — the trace surfaced *dozens* of confirmed producer/consumer bugs that
   file-level review had passed clean. This is the real return on the audit.

So **never cut to hit a line-count target.** A pass that removes 200 lines by deleting something
load-bearing is a regression; a pass that removes 30 lines and files 20 confirmed bug flags is a
success. Optimize for round-trips and correctness, report LOC honestly as the small number it is.

## Output shape

Per entrypoint: (a) the hop table with round-trip count, (b) the risk-rated simplification table,
(c) the do-not-cut list, (d) the bug ledger with a verdict per flag. Across the audit: a roll-up of
total round-trips saveable and total confirmed bugs, so the value is stated as what it actually is.

## See also

- [`references/yagni.md`](../../python/brunofaust-python-style/references/yagni.md) — the interrogation
  questions in full (the deletion pass, "abstraction IS earned", foundations vs features).
- `brunofaust-python-style` `references/architecture.md` — the twin-implementations rule (deleting one
  of two copies ports its tests to the survivor).
- `repo-audit` — the whole-repo, dimension-scored health check; this audit is the flow-level lens that
  a static per-file pass can't provide.
- `simplify` / `code-review-discipline` — apply mechanical cuts and keep the report-only discipline
  (the bug ledger is reported, not silently fixed).
