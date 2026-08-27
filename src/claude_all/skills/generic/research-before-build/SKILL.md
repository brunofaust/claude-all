---
name: research-before-build
description: >-
  Use before adding code, CLI flags, agents, skills, hooks or utilities beyond a one-liner, or selecting dependencies and reuse candidates.
disable-model-invocation: false
user-invocable: true
---

# Research Before You Build

The cheapest, most reliable code is the code you don't write. Before generating a non-trivial new
thing, spend a few minutes finding what already solves it. Net-new is the *last* option, not the first.

Before writing anything beyond a one-liner, make at least one local search for an existing
implementation, including CLI flags, agents, skills, hooks and utilities. For small glue,
that search may be enough; widen only when local code does not settle the reuse decision.

## The reuse hierarchy (walk it in order)

1. **Internal codebase first.** Does this already exist in the repo? `Grep`/`Glob` for the concept,
   check shared `utils/`/`core/`/`lib/`. Don't reinvent a sibling module. (RAG/code-graph tools if present.)
1. **Official / vendor docs** — via **Context7** (`mcp__context7`) or the library's own docs. The
   framework may already provide it (don't hand-roll what the stdlib/framework ships).
1. **Open-source that solves 80%+** — `gh search repos` / `gh search code` (delegate to `gh-runner`).
   Prefer adopting/forking/wrapping a maintained project over building from scratch.
1. **Package registries** — npm / PyPI / crates.io / pkg.go.dev for a focused library.
1. **The web** (Exa / general search) for prior art, RFCs, reference implementations, gotchas.

Stop as soon as you find something that fits — you don't need to walk all five every time.

## Decide: adopt / fork / wrap / build

Once you've found candidates, choose deliberately:

- **Adopt (add as a dependency)** — well-maintained, good fit, acceptable license + size. The default
  when a focused library exists.
- **Wrap** — good engine, awkward API or a boundary you want to own → put it behind one owner module
  (see `brunofaust-python-style` external-system-ownership / `architecture-decision-guard`).
- **Fork / port** — solves 80% but unmaintained, wrong language, or needs surgery you can't get
  upstream. Copy with attribution + license compliance.
- **Build** — only when nothing fits, the problem is genuinely novel/core to you, or every option
  fails the guardrails below. Then say *why* in the research note.

### Selection guardrails

- **License** compatible with your project (MIT/Apache/BSD fine; GPL/AGPL needs a decision).
- **Maintenance** — recent commits, releases, open-but-answered issues; not abandoned.
- **Supply-chain** — popularity/usage, maintainer trust, transitive-dep weight, known CVEs. A random
  10-star package handling untrusted input is a risk, not a shortcut.
- **Size/fit** — don't pull a 500 KB dependency for a 10-line utility. Right-size the solution.
- **Exit cost** — how hard to replace later (wrapping lowers this).

## Output — a short research note

Before coding the build/fork path, record (in the PR description, an ADR, or the plan):

```
## Research — <thing>
Looked at: <internal X> · <lib A (npm/pypi)> · <repo B (gh)>
Decision: adopt `lib-a@^2` / fork repo-b / wrap lib-c / BUILD
Why: <one line — fit, license, maintenance, or why nothing fit>
```

This makes the reuse decision reviewable and prevents the next person re-litigating it.

## Anti-patterns

| Anti-pattern | Why | Instead |
| --- | --- | --- |
| Generating a parser/retry/auth from scratch without searching | reinvents a solved, battle-tested problem | walk the hierarchy first |
| Re-implementing something already in the repo | drift + duplicate maintenance | grep internal first |
| Adding a heavy dependency for a trivial util | bundle/supply-chain bloat | inline the few lines |
| Forking without checking license/maintenance | legal + dead-code risk | run the guardrails |
| "I'll just write it, it's faster" | usually slower + buggier than a maintained lib | time-box the search; reuse wins |

## Why this pays off

Reusing a maintained solution beats generating net-new on **both** axes that matter: **tokens** (you
write a wrapper, not the engine) and **reliability** (battle-tested code has fewer edge-case bugs than
freshly-generated code). The few minutes of search routinely save hours of building + debugging.

## References (track for updates)

- Adapted from [affaan-m/ECC](https://github.com/affaan-m/ECC) — [`rules/common/development-workflow.md`](https://github.com/affaan-m/ECC/blob/main/rules/common/development-workflow.md) and [`rules/common/patterns.md`](https://github.com/affaan-m/ECC/blob/main/rules/common/patterns.md).
