# YAGNI & Minimalism — do not over-engineer

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps
> a condensed summary; this file holds the full depth.

**Default to the simplest thing that satisfies the CURRENT requirement.** Structure
is a cost, not a virtue. You must be able to name a concrete, *present* reason for
every function, class, file, and abstraction you add. "Might need it later", "more
flexible", "cleaner", "best practice", and "separation of concerns" are **not**
reasons — they are the four phrases that precede almost every piece of dead
scaffolding in a codebase.

This is the counterweight to [`architecture.md`](architecture.md). That file's
Service / Repository / Protocol-DI patterns are **tools you reach for when a
concrete need justifies the boundary** — not the default. The default is here.
When the two seem to disagree, minimalism wins until you can write down the need.

## Target shapes — start here, argue in writing before exceeding

| You have… | Write… | Not… |
| --- | --- | --- |
| Data access for one table | one class (or module-level `async def`s) + its Pydantic model; `get_x(id)` runs the query and returns the model. Nothing else. | a Repository interface + impl, a Service that only forwards to it |
| A thing called from one place | the code, inlined at the call site | a wrapper/helper function |
| One implementation | the concrete type | an interface / ABC / `Protocol` |
| One method | a function | a class with one method |

```python
# GOOD: the whole data-access story for one table
class CustomerStore:
    """Reads customers. One query per method; returns the model."""

    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    async def get(self, customer_id: str) -> Customer | None:
        """Return the customer, or None. The query IS the method."""
        row = await self._db.fetchrow(
            "SELECT id, name, interval_seconds FROM customers WHERE id = $1", customer_id
        )
        return Customer.model_validate(dict(row)) if row else None
```

There is no `CustomerRepository(Protocol)`, no `CustomerService` forwarding to it,
no `AbstractStore` base class. When a second reader or a real test-seam appears,
add exactly that — not before.

## Pass-through chains — the most common over-engineering

The single most frequent way simple code turns complex: **one operation smeared
across a chain of methods that each only forward to the next.** A plain "select a
row, return the model" becomes six hops:

```python
# BAD: six methods to run one query. Each hop only forwards.
class CustomerStore:
    async def get_by_id(self, id: str) -> Customer | None:
        return await self._get_by_id(id)

    async def _get_by_id(self, id: str) -> Customer | None:
        return await self._get_from_database(id)

    async def _get_from_database(self, id: str) -> Customer | None:
        row = await self._query(id)
        return self._result_as_pydantic(row)

    async def _query(self, id: str):
        return await self._db.fetchrow("SELECT ... WHERE id = $1", id)

    def _result_as_pydantic(self, row) -> Customer | None:
        return Customer.model_validate(dict(row)) if row else None
```

```python
# GOOD: one method. Read it top to bottom.
class CustomerStore:
    async def get_by_id(self, id: str) -> Customer | None:
        """Return the customer, or None."""
        row = await self._db.fetchrow("SELECT id, name FROM customers WHERE id = $1", id)
        return Customer.model_validate(dict(row)) if row else None
```

Every private method in the bad version has **exactly one caller** and does nothing
but hand off — `_get_by_id` → `_get_from_database` → `_query` → `_result_as_pydantic`.
That is not "separation of concerns"; it is one concern chopped into pieces you now
have to reassemble in your head. Collapsing it is a routine **~30% line reduction**
with zero behaviour change.

**Private methods are fine — a chain of forwarders is not.** The test for keeping a
private method: does it do something *genuinely distinct and reused*, or does it
just pass its arguments along? A private helper called from **one** place that only
forwards → inline it. A private helper that does a real, separable step called from
**two or more** methods → keep it. The smell is the *chain*: A calls B calls C calls
D and each has a single caller. The whole operation should be readable in one
method top to bottom; reach for a private helper only when a step is both distinct
and shared.

## Banned by default — stop and write down the need before adding one

- **Pass-through functions** that only forward their arguments to one other call.
- **Abstraction layers over libraries that are already abstractions** — a
  "repository" wrapping SQLAlchemy, a "client" wrapping `httpx` that adds nothing,
  a "manager" wrapping a dict. (An *owner class* that translates errors or holds a
  connection is different — it carries real logic. See
  [`external-system-ownership.md`](external-system-ownership.md).)
- **Factories, strategies, registries, managers, base classes with a single
  subclass.** A dict literal replaces most factories (see `architecture.md`
  Pattern 1); a function replaces most strategies.
- **Config / parameter plumbing for options that have exactly one value.** A
  `timeout: float = 30.0` nobody ever passes a second value to is a constant
  wearing a parameter's clothes.
- **Defensive handling of inputs the types or callers already guarantee.** A
  `if x is None:` branch on a parameter typed `X` (not `X | None`), reachable from
  callers that always pass a value, is dead code that hides the real contract.

## Why — the wrong abstraction costs more than the duplication

The enemy has a name: **speculative generality** — building features, layers, and
extension points for an imagined future that usually never arrives (studies put
the share of features that are rarely or never used around two-thirds). And it is
not free to carry: *every line of code must be understood, tested, debugged, and
updated when requirements change.* Speculative code is maintenance burden with no
offsetting use. Premature abstraction is not a harmless "we'll grow into it" — it
is a *liability* you pay down every time the code changes:

- **The wrong abstraction couples things that only looked alike.** Two functions
  that share shape today diverge tomorrow (different validation, different errors),
  and now every change has to thread a flag through the shared path. *Duplication
  is far cheaper than the wrong abstraction* — duplicated code is easy to see and
  easy to delete; a bad abstraction is load-bearing and everyone is afraid to
  touch it.
- **Every indirection is a hop `go-to-definition` can't skip.** A pass-through, a
  one-subclass base, a Protocol with one impl — each adds a name to learn and a
  file to open to answer "what actually runs here?".
- **Speculative flexibility is almost always the wrong flexibility.** The
  extension point you built "to be safe" rarely matches the change that actually
  arrives; you end up bending the code around *two* shapes — the imagined one and
  the real one.

Duplicate first. Abstract when the third real case teaches you what the shared
thing actually is — see `architecture.md` Pattern 5 (Rule of Three). *Carve-out:*
this governs **uncertain** similarity. **Structurally-certain** sameness — a second
call site on the same store surface, or a second copy of the same control-flow
skeleton — has nothing to wait to learn and extracts at the **second** copy
(`architecture.md`, "Rule of Three vs the two-copy trigger";
`external-system-ownership.md`).

## When an abstraction IS earned

Reach for the boundary the moment — and only the moment — one of these is *true
now*, not imagined:

- **A genuine third instance exists** (Rule of Three) and they share a real, stable
  core — not just a superficial shape.
- **A second concrete implementation exists today** — then a `Protocol` earns its
  keep (two DB backends, a real fake for tests you cannot otherwise build).
- **A real test seam you cannot reach otherwise** — inject the dependency because
  the test genuinely needs to substitute it, not because injection is tidy.
- **A boundary the deploy/runtime forces** — a Lambda handler, an ECS entry point,
  a trust boundary that must parse untrusted input (that model is a *present*
  need, not speculation).

If you can name the trigger in one sentence, build it. If the sentence contains
"later" or "flexible", you have not earned it yet.

## The architectural exception — YAGNI is for features, not foundations

YAGNI governs **features and abstractions** — the things you can add incrementally
later, cheaply, when the need is real. It does **not** license skipping the few
decisions that are *expensive to reverse*. You can't build a skyscraper by adding
the foundation later. For those, a little foresight now is correct, not
over-engineering:

- **The data model at a trust boundary** — a Pydantic model parsing untrusted input
  is a foundation, not speculation. Getting it wrong ships silent-data bugs (see
  [`incidents.md`](incidents.md)). Model it up front.
- **Storage / schema shape, the DB choice, the message contract** — a table or an
  event schema is costly to change once data and consumers exist. Design it
  deliberately.
- **Security and tenant boundaries** — retrofitting isolation is a rewrite. Draw
  the boundary at the start.
- **The module layout / dependency direction** — cheap to get right early, painful
  to untangle later.

The test: *can I add this incrementally later at reasonable cost, or is it a
foundation everything else sits on?* Incremental → defer (YAGNI). Foundational and
expensive-to-reverse → decide now. This is the productive tension — say "no" to
future-proofing instincts on features, "yes" to foresight on foundations. When you
defer, **write the idea down** (a `TODO` / ticket) and revisit it when concrete
evidence arrives — deferred is not forgotten.

## The deletion pass — run it before you call the change done

For **each** unit you added — every function, class, file, parameter, layer — do
one of two things:

1. State the concrete, present need it serves (a real caller, a real second impl,
   a real test seam, a forced boundary), **or**
2. inline it / delete it.

Bias hard toward deleting. **Fewer, longer, obvious functions beat many tiny
indirections.** A 40-line function you can read top to bottom is simpler than six
6-line functions you have to jump between — even though the metric "lines per
function" prefers the six. Optimize for "how many files must I open to understand
this?", not for a size counter.

```text
Deletion-pass questions, per unit:
  - Who calls this, TODAY? (0 or 1 caller → inline it)
  - How many implementations, TODAY? (1 → drop the Protocol/ABC)
  - What second value does this parameter ever take? (none → make it a constant)
  - What input does this defensive branch actually catch that the types allow?
    (none → delete the branch)
```

## Audit checklist — run on every changed file

`/ship` and `/ship-pr` audit each changed file against this list as a **standard
step**. For each changed file, flag and fix:

- [ ] **Pass-through chain** — a method calls a private method that calls another
      that only forwards (each with one caller). Collapse to one method.
- [ ] **Pass-through function** — forwards its args to one other call and adds
      nothing. Inline it at the call site.
- [ ] **`Protocol` / ABC / base class with one implementation.** Use the concrete type.
- [ ] **A "repository"/"client"/"manager"/"wrapper" over a library that is already
      an abstraction (SQLAlchemy, httpx, a dict)** and adds no real logic. Inline it.
- [ ] **Factory / strategy / registry** where a dict literal or a function does it.
- [ ] **A parameter/config option with exactly one value** ever passed. Make it a constant.
- [ ] **A defensive branch on an input the types/callers already guarantee.** Delete it.
- [ ] **Speculative extension point** ("might need it later") with no present caller.
- [ ] **Many tiny functions** where fewer, longer, obvious ones would read better —
      "how many files/hops to understand this?" is the metric, not lines-per-function.

For each flag: either name the concrete *present* need it serves, or simplify.
Mechanical simplifications go through `/simplify`; judgment calls are reported.
Trivial diffs (rename/format/one-liner) get a quick pass; feature code gets the
full list. This audit does **not** touch the skill's hard rules — a boundary model,
a docstring, an owner class stay (see below).

## Interaction with the rest of this skill

Minimalism does **not** license skipping the skill's hard rules — those exist
because their absence caused real incidents, not for tidiness:

- Still Pydantic at every boundary, `extra="forbid"`, no masking defaults — a
  model is a *present* need (untrusted input), not speculation. → `data-modeling.md`
- Still full type hints, docstrings, no silent except. Minimal ≠ terse-and-cryptic.
- Still one owner class per external system — that owner carries real translation
  logic; it is not a pass-through. → `external-system-ownership.md`

The rule is narrow and sharp: **remove structure that serves no present need.** It
is not "remove structure". Delete the speculative `Protocol`, keep the boundary
model.

## See also

- [`architecture.md`](architecture.md) — the patterns (KISS, Rule of Three, SRP,
  function size); this file is when NOT to apply the heavier ones.
- The `architecture-decision-guard` skill — the same rule at package scale: don't
  add a layer/tier/abstraction without a concrete present need; prefer containment
  (single-owner + a banned-api check) over layering.
- [`data-modeling.md`](data-modeling.md) — "one table = one class + its model" in full.
