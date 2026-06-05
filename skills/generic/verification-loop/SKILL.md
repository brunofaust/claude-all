---
name: verification-loop
description: >-
  Structured pre-PR verification with explicit PASS/FAIL per gate and a formal report. Six phases (lint/format → types → tests → coverage → security/secrets → diff review) culminating in a READY / NOT READY verdict. Complements adversarial-verification (which is about claim verification) by enforcing a uniform gate format before any PR opens. Use when: finishing a feature or significant change, before opening a PR, after refactoring, or any time you want to declare "ready to ship" with evidence. Adapt the commands to the project stack (Python/Node/Go/etc.).
user-invocable: true
---

# Verification Loop

A formal pre-PR gate. Run six phases, capture verdicts, produce one report.
No phase may be skipped silently — record SKIP with a reason.

______________________________________________________________________

## When to invoke

- After completing a feature or significant code change
- Before opening or updating a pull request
- After a refactor that touched multiple files
- Any moment you're about to claim "done"

Pair with `adversarial-verification` (which verifies individual claims) — this
skill verifies the WHOLE diff is ready to ship.

______________________________________________________________________

## The six phases

Run in order. Each phase has a single command (or short pipeline), a PASS/FAIL
condition, and an output line for the final report.

### Phase 1 — Lint + Format

```bash
# Python
prek run --all-files                # covers ruff lint + format + typos + secrets + markdown

# Node
pnpm lint && pnpm format --check
```

**PASS** = exit 0 with no auto-modified files.
**FAIL** = exit non-zero OR any file modified (hook auto-fixed something —
stage and re-run).

### Phase 2 — Type check

```bash
# Python
uv run mypy . 2>&1 | tail -20

# TypeScript
pnpm tsc --noEmit 2>&1 | tail -20
```

**PASS** = exit 0, zero errors.
**FAIL** = any error. Report `(N errors)` in the line.

### Phase 3 — Tests

```bash
# Python
uv run pytest -q 2>&1 | tail -20

# Node
pnpm test --run 2>&1 | tail -20
```

**PASS** = all tests green, zero failures, zero errors.
**FAIL** = any failure / error. Report `(X failed / Y passed)`.

### Phase 4 — Coverage threshold

```bash
# Python (assumes pyproject.toml has --cov-fail-under)
uv run pytest --cov --cov-fail-under=80 -q 2>&1 | tail -5

# Node
pnpm test --coverage --coverage.thresholds.lines=80
```

**PASS** = coverage ≥ project threshold (default 80%).
**FAIL** = below threshold. Report `(N%)`.

### Phase 5 — Security / secrets

```bash
# Already covered by prek if gitleaks is wired in — re-run just the secret hooks
prek run gitleaks --all-files

# Manual sweep for stragglers
grep -rEn "(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|aws_secret|password\s*=)" \
  --include="*.py" --include="*.ts" --include="*.js" --include="*.env*" .
```

**PASS** = zero matches.
**FAIL** = any match. Report `(N findings)` — STOP and remediate before PR.

### Phase 6 — Diff review

```bash
git diff --stat origin/main...HEAD
git diff origin/main...HEAD --name-only
```

For each changed file, eyeball:

- Unintended changes (formatter churn, stray prints, commented-out code)
- Missing error handling on new I/O paths
- New TODOs / FIXMEs introduced
- Public API changes without docstring update
- Tests added for new code paths

**PASS** = nothing unexpected.
**FAIL** = any unintended change. List per file in the report.

______________________________________________________________________

## Output format (mandatory)

After running all phases, produce **exactly** this block:

```
VERIFICATION REPORT
===================
Lint+Format: [PASS / FAIL / SKIP] <details>
Types:       [PASS / FAIL / SKIP] (N errors)
Tests:       [PASS / FAIL / SKIP] (X/Y, Zs)
Coverage:    [PASS / FAIL / SKIP] (N%)
Security:    [PASS / FAIL / SKIP] (N findings)
Diff:        [PASS / FAIL / SKIP] (N files changed)

Overall:     [READY / NOT READY] for PR

Issues to fix:
  1. <file:line> <what is wrong>
  2. ...
```

Rules for the report:

- Numbers are **counts**, not adjectives ("3 errors" not "some errors").
- `SKIP` requires a one-line reason next to it.
- `NOT READY` if ANY phase failed.
- `READY` only when all six are PASS or justifiably SKIP.

______________________________________________________________________

## Continuous mode

For long sessions (> 1 hour of active editing), run the loop:

- After every milestone (feature complete, refactor done, bug fixed)
- Before any commit that touches > 5 files
- Before any PR push

Do not run after trivial edits (single typo fix, comment update) — wasted time.

______________________________________________________________________

## Anti-patterns

- ❌ "Looks good to me" without running the gates — every claim must have evidence.
- ❌ Skipping a phase silently — always record SKIP + reason.
- ❌ Running tests but ignoring the failure count because "those are pre-existing" — verify with `git diff origin/main` that the failures aren't your fault.
- ❌ Reporting `READY` while any phase says FAIL — the verdict is mechanical.
- ❌ Re-running phases until they pass without addressing root cause (e.g. `pytest --lf` loops). One iteration per phase per loop.
- ❌ Running this on every keystroke — it's a gate, not a watch.

______________________________________________________________________

## Integration with other skills

| Use this skill             | After                                                    | Before                   |
| -------------------------- | -------------------------------------------------------- | ------------------------ |
| `verification-loop`        | finishing a feature, fixing a bug, completing a refactor | opening/updating a PR    |
| `adversarial-verification` | individual claims ("this fixes X", "this test passes")   | committing               |
| `aws-debug-loop`           | e2e or integration failures                              | re-running the full test |

`verification-loop` is the macro gate. `adversarial-verification` is the micro
gate per claim. `aws-debug-loop` is the debug discipline before either gate
runs clean.
