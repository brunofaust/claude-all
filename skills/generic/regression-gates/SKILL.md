---
name: regression-gates
description: >-
  Introduce a NEW lint/quality/correctness gate to an existing (brownfield) codebase WITHOUT a
  big-bang cleanup — the regression-only baseline harness + the three-step warn→error rollout. Use
  when: adding a custom checker/AST rule/pre-commit hook to a repo that already has violations,
  "how do I roll out a gate without fixing everything first", "baseline the existing findings",
  ratcheting tech debt down, "make this rule fail only on new code", wiring a gate into CI, or writing
  a static checker (single migration head, banned env-var, junk-drawer module, module-level private
  names). Ships a runnable `baseline_gate.py` template + example checkers under `checkers/`. The
  governing principle: a rule in prose gets violated; a rule encoded as a checker holds — so every
  "we should always…" becomes an executable gate, seeded against today's debt and ratcheted to zero.
disable-model-invocation: false
user-invocable: true
---

# regression-gates — roll out a gate without a big-bang cleanup

> **Two meta-findings behind this skill.** (1) *A rule in prose gets violated; a rule encoded as a
> checker holds.* Every "we should always…" should become a lint rule / AST check / pre-commit hook /
> CI gate — prose is only for the gap before the checker exists and for judgment a checker can't make.
> (2) *Almost every high-severity bug traces to a test, mock, or config that agreed with the code
> instead of with reality.* A gate that only restates the code's assumptions is theatre — pin it to an
> external truth (the migration schema, the CI runner's env, the real engine).

A new gate on a real codebase finds existing violations. The wrong move is to fix them all in one
giant PR (un-reviewable, merge-conflict magnet) or to flip the gate to `--strict` and block every
commit on legacy noise. The right move is to **baseline today's findings and ratchet them to zero.**

## A. The regression-only baseline harness (`baseline_gate.py`)

`baseline_gate.py` (in this skill's directory) wraps any checker and compares its findings against a
grandfathered `<gate>_baseline.txt`:

| Finding | Verdict |
| --- | --- |
| **NEW** — seen now, not in baseline | **FAIL** — the gate bites on regressions |
| **BASELINED** — seen now, in baseline | PASS — legacy debt is tolerated |
| **STALE** — in baseline, not seen now | **FAIL** — delete the line; the baseline only shrinks |

Four properties make it a ratchet, not a dumping ground — and a naive rebuild misses them:

1. **Stale entries fail too.** `stale = baseline − seen`. When you fix a finding it stops matching,
   which fails the gate until you delete its baseline line. The file can therefore only shrink toward
   empty — you can't quietly accumulate debt.
2. **Key by stable identity, not line number.** Findings are keyed `path: message`, so an unrelated
   edit ten lines up doesn't churn the baseline (which would force a re-seed and hide regressions).
3. **Fail closed.** If the checker can't run (missing dep, crash, non-zero exit) the gate ERRORS — it
   never reports a false clean. A gate that passes when its tool is absent is worse than no gate.
4. **One file per gate.** Each gate owns its own `<gate>_baseline.txt`; don't share.

```bash
# seed once (commit the baseline file)
python baseline_gate.py --baseline private_names_baseline.txt --update -- \
    python checkers/module_private.py src/

# enforce — identical command in pre-commit AND CI
python baseline_gate.py --baseline private_names_baseline.txt -- \
    python checkers/module_private.py src/
```

**Checker contract** (so anything composes with the harness): print one finding per line as a stable
`path: message` key on stdout; exit `0` when the checker RAN (regardless of how many findings it
printed); exit non-zero ONLY on an internal error. The harness turns a non-zero exit into a
fail-closed gate failure.

## B. The three-step rollout (warn → scope → error)

Never flip a new gate straight to blocking on a brownfield repo. Roll out in three reviewable steps:

1. **Seed & warn.** Run the checker, `--update` the baseline (or wire it advisory / `continue-on-error`
   in CI). Nothing blocks yet; you've captured the starting debt.
2. **Scope to what can trigger it.** Point the gate only at the files/dirs that can produce the
   finding (e.g. `src/` for module rules, `migrations/` for the head check). A gate scoped to the
   whole tree is slow and noisy and tends to get disabled.
3. **Flip warn → error.** Make the gate blocking. From here, NEW findings fail and the baseline can
   only shrink. Burn it down one notch per PR.

Rollout rules that keep gates honest (guardrail engineering):

- **Regression-only thresholds.** Seed numeric caps (complexity, coverage, count) *just above today's
  worst case*, then ratchet down — never at an aspirational target that blocks day one.
- **Specific rule codes, not blanket groups.** Enable `B008,SIM105`, not "all of B + SIM" — a blanket
  group silently pulls in new rules on upgrade and blocks unrelated work.
- **The gate must run in CI, not just pre-commit.** `pre-commit` is bypassable (`--no-verify`, `SKIP=`)
  and agents follow incentives literally — if a bypass exists they'll use it. CI is the real gate.
- **A cleanup ships with its checker.** If you fix a class of bug, land the checker that prevents its
  return in the *same* change — otherwise it regresses by the next PR.
- **Config that names code rots silently.** A baseline/allowlist keyed to paths or messages drifts as
  code moves; the stale-entry rule (A.1) is what forces it back in sync.

Pairs with `architecture-decision-guard` (don't add a gate/boundary without a present need) and
`repo-audit` (whole-repo measure → baseline → ratchet). For Python specifically, `prek` documents the
pre-commit/`local`-hook wiring and `SKIP=` discipline.

## C. Example checkers (`checkers/`)

Generic, runnable, and used as worked examples with the harness. Each is Python, but the *principle*
is stack-neutral — translate to your toolchain. All fail open on unparseable files (a sibling syntax
gate owns those) and exit 0 so they compose with `baseline_gate.py`.

| Checker | Lesson | What it catches |
| --- | --- | --- |
| `checkers/migration_head.py` | distributed-systems correctness | >1 migration head, dangling `down_revision`, over-length revision ids — pure static parse, no DB/import. Pairs with `alembic-migration` + `migration-reviewer`. |
| `checkers/ci_env_guard.py` | tests must agree with reality | `os.environ.setdefault(...)` of a CI-reserved var (`CI`, `GITHUB_*`, `RUNNER_*`, …) in test bootstrap — `setdefault` loses to the runner's real value, so the "mock" silently points at the real service in CI. |
| `checkers/junk_drawer.py` | single ownership | files named `helpers`/`utils`/`common`/`misc`/`shared` — ownerless attractors that grow into hidden god-modules. |
| `checkers/module_private.py` | single ownership / dead-code visibility | module-level `_private` names (Python) — they blind dead-code detectors and aren't a real export mechanism; use `__all__` instead. |

### Advanced: embedded-SQL-against-migration-schema validation

A high-value but stack-specific gate (Python + SQL) validates embedded SQL strings against a virtual
`{table: columns}` schema folded from the migrations — no DB. It is **not shipped here** because it
needs `sqlglot` and a SQL-bearing codebase to verify; the `prek` skill documents it as a
"if-your-repo-has-SQL, add this gate" pattern with the make-or-break gotchas (`qualify` validates
SELECT columns but not DML; it stops at the first unresolved column; trailing-comma leniency;
`ON CONFLICT` targets; `:name` bind params; gate version-specific syntax against the *production*
engine version). Pair it with the harness above: on first run it finds real bugs — baseline them and
burn down.

## Applying the lessons to your own gate

Any gate you add must be: **(a) generic** (no project specifics), **(b) green on its own repo's tree**
before you commit it, **(c) shipped with its checker in the same change**, and **(d) rolled out
regression-only** per section B. Verify (b) literally — run the checker on the repo and confirm zero
unexpected findings — before wiring it blocking.
