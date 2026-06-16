## Agent-era standing rules
Two meta-findings from running AI coding agents on a production codebase. They govern the rules below.

1. **Make tests/mocks/config agree with REALITY, not with the code.** Almost every high-severity bug traced to a fixture, mock, or setting that restated the code's own assumptions. An agent will satisfy the fixture you gave it, not the production system. Pin every contract to an external truth at least once (real DB/SDK at the production version; the migration schema; the CI runner's real env).
2. **A rule in prose gets violated; a rule encoded as a checker holds.** Turn every "we should always…" into a lint rule / AST check / pre-commit + CI gate. Prose is only for the gap before the checker exists and for judgment a checker can't make.

### Altitude rule — keep this file small
- The always-loaded root instruction file holds ONLY global, every-turn rules. Area-specific rules live in per-directory instruction files loaded on demand; lookup/reference material lives in docs.
- When splitting an instruction file, carry a signature line from EVERY original section into its new home, then confirm each is reachable — so no rule is silently dropped in the move.

### Distilled rules (detail lives in the named skill / per-area file)
- **Mock drift is the #1 silent failure.** On any signature/return/exception/import change, sweep and update every mock in the same change; prefer spec'd mocks; build config mocks from the real model. → `mock-drift-sweep`.
- **Roll out new gates regression-only** (baseline today's findings, stale entries also fail, ratchet to zero; specific rule codes; gate runs in CI not just pre-commit; a cleanup ships with its checker). → `regression-gates`.
- **Test-suite hygiene:** no "known pre-existing failure" amnesty; a run that collects zero tests is a hard red; pin runtimes to a full version; `continue-on-error` only for proven-environmental flakiness, with a path back to blocking.
- **Single ownership:** one owner per external system; extract before the third copy; no junk-drawer (`utils`/`helpers`/`common`) modules; no module-level private names that blind dead-code tools; delete speculative scaffolding.
- **Config & wiring is bidirectional:** no tunable as a module constant; a setting is "wired" only when read in code AND set in every deploy unit AND documented; baked assets must be baked by every build, and any runtime-fetch fallback must log loudly.
- **Distributed correctness:** write idempotency markers AFTER success (or release in `finally`); report partial batch failures; paginate to exhaustion; one migration head; test fresh-DB migration.
- **Security defaults:** fetch secrets at point of use (never write them to transit/storage); `repr=False` on objects carrying customer content; never a global cache on tenant-bound state; argv lists, not string-joined shell (model-generated filenames are injection-reachable).
- **LLM seams:** structured output is an API contract — round-trip-test schema→consumer with REAL model output; constrained fields use enums in the schema (the model can't read docstrings); when migrating SDKs, port the tests too.
- **Operating agents:** parallel sessions drift contracts at merge time; agents follow incentives literally (if `SKIP=` works they'll use it); edit-time guards steer generation better than review comments; retrospect on DIFFS, not just PR descriptions (→ `diff-retrospective`).
