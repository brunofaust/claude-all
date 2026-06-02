---
name: architecture-decision-guard
description: >-
  Guardrails before adding structural boundaries to a codebase. Use when: deciding whether to split a
  module into layers/tiers, introducing an abstraction or interface "for flexibility", adding a new
  package boundary, debating containment vs layering, designing where shared/generic code should live,
  or rolling out a new lint/complexity gate across an existing codebase. The core rule: don't add a
  boundary (layer, tier, abstraction, indirection) without a concrete present need — prefer
  containment (single-owner + banned-api enforcement) over layering when the only goal is "keep this
  kind of code in one place". Prevents speculative architecture (tiers that create DI/base-class
  puzzles they were meant to avoid) and commit-blocking lint backlogs. Pairs with
  brunofaust-python-style (project-structure, external-system-ownership) and python-module-migration.
disable-model-invocation: false
user-invocable: true
---

# Architecture Decision Guard

Most architecture damage is **speculative structure** — a boundary added for a problem you don't have
yet, which creates real problems now. This skill is a short set of gates to run *before* you split,
layer, or abstract.

## The one rule

> **Don't add a boundary without a concrete present need.**

A "boundary" is a layer, a tier, a package split, an interface/Protocol, an abstract base class, or
any indirection. Each one has a carrying cost (more files, DI wiring, base-class puzzles, harder
navigation). Add it only when a *current* force demands it:

- A second implementation exists **today** (real swappability — not "we might swap Postgres someday").
- A dependency direction must be **mechanically enforced** (and you'll wire `import-linter` to enforce it).
- A genuine reuse boundary exists (the code is, or is about to be, shared by ≥2 consumers).

If the only goal is "keep all the X code in one place," you want **containment**, not **layering**.

## Containment vs layering

| | Containment | Layering |
|---|---|---|
| Mechanism | One owner module + a lint rule (`banned-api`/TID251) blocking the SDK/dep elsewhere | Stacked packages with an enforced import direction |
| Cost | Low — a folder + a ruff rule | High — DI wiring, base classes, cross-layer plumbing |
| Use when | "all boto3 lives in `core/aws/`", "all Jira calls go through `JiraClient`" | A real tier needs to vary independently (e.g. swappable persistence) |
| Failure mode | — | Tiers you split "for cleanliness" create base.py puzzles + DI headaches they were meant to prevent |

**Default to containment.** It gives you the "one place to change it" benefit with almost none of the
layering tax. Reach for layering only when a force above genuinely applies.

## Smell tests (stop and reconsider)

- "We *might* need to swap this later" → YAGNI. Add the seam when the second implementation arrives.
- "It's cleaner / more enterprise" → not a force. Name the concrete problem the boundary solves *now*.
- The new boundary forces an abstract `base.py` / interface that only ever has one implementer → the
  boundary is the problem, not the solution.
- You're moving code into tiers AND wiring DI to glue them back together → you've added cost without
  decoupling anything. Containment (single-owner + banned-api) would have sufficed.
- A refactor "to improve structure" is producing a base-class hierarchy nobody asked for → revert to
  containment.

## Reverting a speculative split

If a layering split is causing more friction than it removes (base-class puzzles, DI churn, no actual
second implementation), **collapse it back to containment** — that's a legitimate, healthy move, not a
failure. Use the `python-module-migration` skill / `python-module-migrator` agent to do the moves
safely, then enforce the single-owner boundary with `banned-api` instead of folder tiers.

## Rolling out enforcement gates without a backlog

Adding a strict lint/complexity gate (e.g. blanket `PLR` caps, `mypy --strict`, docstring coverage)
to an existing codebase is itself a boundary decision — it can light up hundreds of pre-existing
findings and block every commit, burying the *new* signal. Introduce gates at **current-worst +
margin** and ratchet down; select specific rule codes, not blanket groups. (See the `prek` skill,
"Rolling out a new hook or complexity cap without a backlog".)

## When NOT to apply this

- You're inside a boundary that already exists and is enforced — just follow it.
- A framework dictates the structure (FastAPI routers, Django apps) — use the idiomatic layout.
- The boundary is cheap AND a force genuinely applies — then add it without ceremony.
