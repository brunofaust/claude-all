# Audit checklist — the judgment gate for a changed `.py` file

> Reference page for the `brunofaust-python-style` skill. `/ship` and `/ship-pr`
> run this against **every changed Python file** as a standard step.

This is the **judgment** layer. The *mechanical* rules — `no-typeddict`,
`no-cast`, `extra-forbid`, `masking-default`, `opaque-annotation`, `dict-return`,
`splat`, `select-star`, `secret-repr`, `missing-all`, `barrel-init`,
`no-alias`, `pydantic-config`, `verbatim-strip`, `private-access` — are already
gated by the checkers (`checkers/*.py`) and ruff/mypy. **Do not restate them
here.** This file catches what a checker *cannot* see: the calls that need a
human eye. For each item, either it's clean or you fix it (mechanical
simplifications via `/simplify`; the rest reported).

Scales to the diff: a rename / format / one-liner gets a quick pass; feature code
gets the whole list.

## Minimalism / over-engineering → [`yagni.md`](yagni.md)

- [ ] **Pass-through chain** — `a()` → `_b()` → `_c()` where each hop only forwards. Collapse to one method.
- [ ] **Speculative abstraction** — a `Protocol`/ABC/base with one impl, a factory a dict replaces, a "repository" wrapping SQLAlchemy that adds nothing, config for a one-value option. Name a present need or delete it.
- [ ] **Deletion pass done** — every new function/class/file/param serves a concrete *present* reason, else inlined/removed.

## Layering & responsibility → [`architecture.md`](architecture.md)

- [ ] **I/O not mixed with business logic** — SQL / HTTP / SDK calls don't sit inside a pure calculation. The layer boundary, if any, carries *real distinct* logic (not a forwarder).
- [ ] **No layer added without a present need** — didn't grow a Service/Repository/Protocol tier speculatively (yagni). Containment over layering.
- [ ] **Function does one thing** — not 3 concerns in 60 lines; but also not chopped into tiny forwarders (fewer, longer, obvious wins).

## Error handling → [`error-handling.md`](error-handling.md)

- [ ] **`except` is narrow and acted-on** — catches the specific class, logs at `warning`/`error` with structured context, `raise ... from e` when converting. No catch-and-continue that hides a bug.
- [ ] **Partial-batch failures reported** — a loop over N items returns successes *and* failures; one bad item doesn't silently drop the rest.

## Async correctness → [`async-patterns.md`](async-patterns.md)

- [ ] **No blocking call in async** — file/CPU/sync-SDK work goes through `run_in_thread()`, not inline in a coroutine.
- [ ] **Idempotency marker written AFTER success** (or released in `finally`); pagination runs to exhaustion; no double-retry (app + client lib).

## Boundaries & contracts → [`data-modeling.md`](data-modeling.md)

- [ ] **Every entry point parses its payload** — Lambda event / SQS-SNS-EventBridge record / ECS env / API body is a Pydantic model as the first line, before any logic.
- [ ] **Required-vs-optional is right** — a field that must be present has no default; an optional one is `T | None = None`. (The *presence* of a masking default is checker-gated; whether the field is *genuinely* optional is the judgment call here.)
- [ ] **Model our side of a boundary, not the vendor's wire** — raw-JSON digging stays dict access; only the return is a model.
- [ ] **JSON parsed as JSON** — `model_validate_json(raw)`, never `model_validate(orjson.loads(raw))` on a strict model. → [`incidents.md`](incidents.md)

## Config → [`config.md`](config.md)

- [ ] **Nothing environment-varying is hardcoded** — model names, statuses, resource names, endpoints, timeouts, batch sizes, feature flags live in `Settings`, not a module/class constant.

## Tests → [`testing.md`](testing.md)

- [ ] **Tests assert behaviour, not implementation** — an e2e/integration test checks the *requirement* (what the user gets), not what the code happens to do.
- [ ] **Fixtures pinned to reality** — a fixture matches the real DB/migration schema / SDK at the production version, not the code's own assumptions. A fixture that only restates the code verifies nothing. → [`incidents.md`](incidents.md)
- [ ] **Per-test data isolation** — dynamic ids, each test owns its rows, green under `-n auto`.

## Ownership & visibility

- [ ] **One owner per external system** — SDK/HTTP calls flow through the owner module (not a raw client scattered in a feature). → [`external-system-ownership.md`](external-system-ownership.md)
- [ ] **No module-level `_name`** — public surface via `__all__`. → [`visibility.md`](visibility.md)

---

**This audit never strips a hard rule.** A boundary model, a docstring, an owner
class, `extra="forbid"` stay — the goal is removing *speculative structure* and
catching *judgment* violations, not thinning the code. If a fix would delete a
safety rule, it's wrong — report it instead.
