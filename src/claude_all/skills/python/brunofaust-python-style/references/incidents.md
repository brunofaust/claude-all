# Incidents — the failures these rules exist to prevent

Every mechanical rule in this skill was paid for by a real failure. This file is
the catalog: the symptom, the mechanism, **why it hid**, and the rule that now
catches it. Read it when a rule feels like ceremony — each one is a scar.

The through-line: **a green check that verified nothing.** Every incident below
passed its tests, its type-checker, or its gate while being wrong. The lesson is
never "add more Pydantic" — it is "make the check actually check."

## 1. The silent billing failure — `model_validate(orjson.loads(raw))`

**Symptom.** Billing was silently skipped in production for months. No error, no
alarm, no failed request.

**Mechanism.** A billing client returned `orjson.loads(body)` — a plain `dict` —
and the caller did `ReserveResponse.model_validate(that_dict)` on a **strict**
model. Pydantic strict mode is *context-aware*: given raw JSON bytes it knows a
`UUID` / `datetime` / enum can only *arrive* as a string (JSON cannot express
them natively) and converts them. Pre-parsing with `orjson.loads` throws that
context away — Pydantic now sees an ordinary `dict[str, str]`, and `strict=True`
correctly rejects it. Measured on the same bytes / model / config:

```text
ReserveResponse.model_validate(orjson.loads(body))  -> REJECTED (3 errors: UUID, datetime, enum)
ReserveResponse.model_validate_json(body)           -> ACCEPTED
```

So every *populated* response was rejected. The caller **failed open**
(`except ValidationError: return None`), which downstream code read as "nothing
to bill".

**Why it hid.** The test fixture's list was empty, so no row was ever validated —
the one path that fails only runs on real data. *The mock agreed with the code,
not with reality.* The same shape sat latent in four other call sites that were
green only because none of their models had a `datetime` / `UUID` / enum field
**yet**.

**The rule.** Parse and validate in ONE step: `Model.model_validate_json(raw)`
(and `model_dump_json()` to emit). `model_validate(orjson.loads(...))` on a strict
model **is** the bug. Enforced by `model_contract.py` rule
`json-parse-then-validate`. orjson stays the right tool for dumping and for
genuinely untyped data — but a strict model owns its own JSON boundary.

## 2. Two gates went silently blind — the base-class-name blind spot

**Symptom.** A gate guarding ~285 models reported clean while inspecting **zero**
of them.

**Mechanism.** The checker identified a model by its base-class *name*:
`MODEL_BASES = {"BaseModel", "RootModel"}`. A refactor introduced one project base
(`class AppModel(BaseModel)`, then everything extended `AppModel`), and overnight
every model stopped matching. The gate saw no models and passed. Its real findings
degraded into "stale baseline entries" — one re-baseline away from being deleted
as fixed. A sibling lambda-validation gate went blind the same way.

**Why it hid.** The gate that guarded 285 models **had no tests at all**, and it
failed toward FALSE CLEAN — the dangerous direction. "Config that names code rots
silently" is a rule this skill applies to production code; here it bit the checkers
themselves.

**The rule.** `MODEL_BASES` is a `--model-base NAME` (repeatable) option, and the
checker's docstring flags the rot loudly: register your project base or its models
go unchecked. Add a test that resolves every `MODEL_BASES` name against its real
module, so a rename fails a test instead of quietly narrowing what the gate can
see. See `pydantic_contract.py` and `model_contract.py`.

**The tell that this was progress, not regression.** When the gate was fixed the
baseline went *up* (271 → 299) — the only time it rose. Not newly-written debt:
dataclasses had been a total blind spot (no model rule ever inspected them), so
converting 85 of them to models made 28 pre-existing opaque fields *visible for
the first time*. A baseline that rises after a gate is un-blinded is the gate
working, not the code regressing.

## 3. Fixtures that lied — what `extra="forbid"` exposed

**Symptom.** Tests were green over contracts that could not hold in production.

**Mechanism.** Turning on `extra="forbid"` across the models surfaced fixtures
asserting a field the real query never returns — a `token` "flowing through" an
API whose `SELECT` never selects it (it lives in a secrets manager), and request
bodies posting fields (`temperature`, `ai_model`) that map to no column and are
silently dropped today. The fixtures had been written to match the *code's
assumptions*, not the *system*.

**Why it hid.** A permissive model silently accepts and drops the extra key, so
the fixture and the code agreed with each other forever. Nothing pinned either to
the database or the wire.

**The rule.** `extra="forbid"` on every boundary model (`pydantic_contract.py`
rule `extra-forbid`), and the standing discipline: **pin every fixture to an
external truth at least once** — the real DB at the production version, the
migration schema, the SDK at the pinned version. A fixture that only restates the
code verifies nothing. → `testing.md`.

## 4. The re-export barrel — an `__init__.py` that costs the whole package

**Symptom.** Import latency and a second, shadow name for every symbol.

**Mechanism.** An `__init__.py` that re-exports its submodules makes every
consumer pay to import all of them. Measured, package import:

```text
crud     324ms / 12 submodules  ->  0.3ms / 0   (barrel deleted)
core.aws 226ms / 18 submodules  ->  0.2ms / 0
core.ai  239ms /  7 submodules  ->  0.2ms / 0
```

The barrel was also a *second name* for every symbol: 169 `patch()` targets were
bound to the barrel path rather than the real owner, so mocks drifted from the
code they were meant to stand in for.

**Why it hid.** `ruff RUF067` looks like it covers this — it does not. RUF067
permits "docstrings **and re-exports**", and the re-exports are precisely the
thing that costs. A lazy PEP 562 `__getattr__` barrel was tried first and
rejected: it kept an API almost nobody used (409 direct imports vs 73 barrel) at
the cost of three parallel sources of truth (`__all__`, a registry map, a
`TYPE_CHECKING` block) plus a test whose only job was to catch them drifting.

**The rule.** An `__init__.py` is a **docstring only** — no import, def, or
assignment. Enforced by `model_contract.py` rule `barrel-init` (AST-verified),
because RUF067 permits exactly what this bans. Deleting the barrel also forces
every mock onto the real owner.

## 5. Aliases — a wire-key rename that fails soft

**Symptom.** A renamed or missing key arrives as a default instead of an error.

**Mechanism.** Fourteen models carried `Field(alias=...)`. They existed only so
`model_validate()` could eat a raw wire dict whose keys differed from the field
names — the fields were always legal Python. An alias silently maps
`wire_key → field`, so if the producer renames the key it maps to nothing and the
field falls back to its default, no error. One "vendor" alias (`class`) turned out
to be *our own* persisted JSONB key: someone chose a Python keyword and then wrote
three models with aliases to read it back.

**Why it hid.** The alias is invisible at the call site — the model just
constructs, and a soft-defaulted field looks identical to a present one.

**The rule.** Aliases are banned (`model_contract.py` rule `no-alias`). Dig the
wire key out explicitly in a classmethod so a rename fails loud at the parse site:

```python
@classmethod
def from_raw_claims(cls, raw: Mapping[str, Any]) -> Self:
    """Parse the raw claims dict — a missing key raises here, at the boundary."""
    return cls(org_id=raw["custom:org_id"], ...)  # KeyError, loud, at the seam
```

## 6. `str_strip_whitespace=True` — the shared config that ate indentation

**Symptom.** Every code chunk entering the search index lost its leading
indentation. No error, no log.

**Mechanism.** The shared strict config set `str_strip_whitespace=True` — correct
for names and emails, silent corruption for *verbatim content*. A field holding
code / a diff / an HTML fragment got `"    def foo():"` turned into `"def foo():"`
at validation time, invisibly.

**The rule.** A field carrying verbatim content must opt out with
`PYDANTIC_CONFIG | ConfigDict(str_strip_whitespace=False)`. `model_contract.py`
rule `verbatim-strip` flags a content-named field (`content`, `body`, `text`,
`diff`, `snippet`, `patch`, `raw`, `chunk_text`, `output`, `source`, `html`,
`preview`) on a model that hasn't opted out.

## Strict config is not one config — it is (at least) two

Incidents 1 and 6 both trace to a single shared strict base carrying
`extra="forbid"`, `strict=True`, `str_strip_whitespace=True`,
`validate_assignment=True`. That base is right for the models *we* construct and
parse. It is **wrong** at two seams a framework already owns — and forcing it
there produces false rejections, not safety:

| Seam | Why the strict base fails | What to use |
| --- | --- | --- |
| A web framework's request body (e.g. FastAPI) | The framework parses the body itself and calls `validate_python` on an already-parsed dict — never `validate_json` — so a strict `id: UUID` field 422s a *valid* request. | A separate `REQUEST_CONFIG` that relaxes **only** `strict`, nothing else. |
| A DB driver returning a native enum/type (e.g. asyncpg + a PG enum) | The driver has no idea the PG enum maps to your Python enum, so the column arrives as `str` and a strict model rejects it. | Fix it ONCE at the connection boundary — register a driver codec — not with a per-model `WireEnum` annotation, a `::text` cast, and a hand-rolled `BeforeValidator`. One codec deleted three layers of per-model workaround. |

The general shape: **when a strict model rejects real data, the fix is almost
never to weaken the model.** It is to parse JSON as JSON (incident 1), fix the
type at the boundary the driver owns (asyncpg codec), or scope the relaxation to
the exact seam a framework controls (request config) — never to relax the base
everyone else depends on. Relaxing the shared config to make one seam pass is the
same move as `extra="ignore"`: it silences the signal for everybody. →
`data-modeling.md`, `config.md`.

## The meta-lesson

Five of these six failed **open** — a no-op, a dropped key, a silent strip — not a
crash. That is why they lived so long: an exception gets noticed, a silent default
does not. Every rule here converts a soft, invisible failure into a loud one at
the boundary. The checkers exist because *the same discipline in prose got
violated* — including, in incident 2, the checkers' own.
