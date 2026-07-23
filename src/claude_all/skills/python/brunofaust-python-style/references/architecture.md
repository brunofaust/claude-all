# Architecture principles + anti-patterns

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

> **These patterns are tools, not defaults.** The default is minimalism —
> [`yagni.md`](yagni.md): one implementation → no `Protocol`; a data-access class
> that only forwards to SQLAlchemy → inline it; called once → no wrapper. Reach for
> a Service / Repository / Protocol-DI *layer below only when a concrete present
> need justifies the boundary* (a real second implementation, a genuine test seam,
> the Rule of Three). The examples here show the shape of each pattern *when it is
> warranted* — they are NOT an instruction to add all of them to every feature. If
> `yagni.md` and this file seem to disagree, minimalism wins until you can write
> down the need. Several examples below carry a **When to reach for this** note.

### Pattern 1: KISS - Keep It Simple

Choose the simplest solution that works. Complexity must be justified by concrete requirements.

Before adding complexity, ask: does a simpler solution work?

```python
# Over-engineered: Factory with registration
class OutputFormatterFactory:
    _formatters: dict[str, type[Formatter]] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(formatter_cls):
            cls._formatters[name] = formatter_cls
            return formatter_cls

        return decorator

    @classmethod
    def create(cls, name: str) -> Formatter:
        return cls._formatters[name]()


@OutputFormatterFactory.register("json")
class JsonFormatter(Formatter): ...


# Simple: Just use a dictionary
FORMATTERS = {
    "json": JsonFormatter,
    "csv": CsvFormatter,
    "xml": XmlFormatter,
}


# Simple beats clever
# Instead of a factory/registry pattern:
def get_formatter(name: str) -> Formatter:
    """Get formatter by name."""
    if name not in FORMATTERS:
        raise ValueError(f"Unknown format: {name}")
    return FORMATTERS[name]()
```

The factory pattern adds code without adding value here. Save patterns for when they solve real problems.

### Pattern 2: Single Responsibility Principle

Each class or function should have one reason to change.
Separate concerns into focused components.

```python
# BAD: Handler does everything
class UserHandler:
    async def create_user(self, request: Request) -> Response:
        # HTTP parsing
        data = await request.json()

        # Validation
        if not data.get("email"):
            return Response({"error": "email required"}, status=400)

        # Database access
        user = await db.execute(
            "INSERT INTO users (email, name) VALUES ($1, $2) RETURNING *",
            data["email"],
            data["name"],
        )

        # Response formatting
        return Response({"id": user.id, "email": user.email}, status=201)


# GOOD: Separated concerns
class UserService:
    """Business logic only."""

    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def create_user(self, data: CreateUserInput) -> User:
        # Only business rules here
        user = User(email=data.email, name=data.name)
        return await self._repo.save(user)


class UserHandler:
    """HTTP concerns only."""

    def __init__(self, service: UserService) -> None:
        self._service = service

    async def create_user(self, request: Request) -> Response:
        data = CreateUserInput(**(await request.json()))
        user = await self._service.create_user(data)
        return Response(user.to_dict(), status=201)
```

Now HTTP changes don't affect business logic, and vice versa.

### Pattern 3: Separation of Concerns

Organize code into distinct layers with clear responsibilities.

```
┌─────────────────────────────────────────────────────┐
│  API Layer (handlers)                                │
│  - Parse requests                                    │
│  - Call services                                     │
│  - Format responses                                  │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Service Layer (business logic)                      │
│  - Domain rules and validation                       │
│  - Orchestrate operations                            │
│  - Pure functions where possible                     │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Repository Layer (data access)                      │
│  - SQL queries                                       │
│  - External API calls                                │
│  - Cache operations                                  │
└─────────────────────────────────────────────────────┘
```

**When to reach for this:** only when the layers carry *distinct, real* logic. If
the "service" only forwards to the "repository", collapse them into one. If the
"repository" only wraps SQLAlchemy without adding translation or a real query, it
is a banned pass-through ([`yagni.md`](yagni.md)) — inline the query. A three-box
diagram is not a target to hit; most single-table reads are one thin store class
with a query per method.

Each layer depends only on layers below it:

```python
# Repository: Data access
class UserRepository:
    async def get_by_id(self, user_id: str) -> User | None:
        row = await self._db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return User(**row) if row else None


# Service: Business logic
class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def get_user(self, user_id: str) -> User:
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user


# Handler: HTTP concerns
@app.get("/users/{user_id}")
async def get_user(user_id: str) -> UserResponse:
    user = await user_service.get_user(user_id)
    return UserResponse.from_user(user)
```

### Pattern 4: Composition Over Inheritance

Build behavior by combining objects rather than inheriting.

```python
# Inheritance: Rigid and hard to test
class EmailNotificationService(NotificationService):
    def __init__(self):
        super().__init__()
        self._smtp = SmtpClient()  # Hard to mock

    def notify(self, user: User, message: str) -> None:
        self._smtp.send(user.email, message)


# Composition: Flexible and testable
class NotificationService:
    """Send notifications via multiple channels."""

    def __init__(
        self,
        email_sender: EmailSender,
        sms_sender: SmsSender | None = None,
        push_sender: PushSender | None = None,
    ) -> None:
        self._email = email_sender
        self._sms = sms_sender
        self._push = push_sender

    async def notify(
        self,
        user: User,
        message: str,
        channels: set[str] | None = None,
    ) -> None:
        channels = channels or {"email"}

        if "email" in channels:
            await self._email.send(user.email, message)

        if "sms" in channels and self._sms and user.phone:
            await self._sms.send(user.phone, message)

        if "push" in channels and self._push and user.device_token:
            await self._push.send(user.device_token, message)


# Easy to test with fakes
service = NotificationService(
    email_sender=FakeEmailSender(),
    sms_sender=FakeSmsSender(),
)
```

### Pattern 5: Rule of Three

Wait until you have three instances before abstracting.
Duplication is often better than premature abstraction.

```python
# Two similar functions? Don't abstract yet
def process_orders(orders: Sequence[Order]) -> Sequence[Result]:
    results = []
    for order in orders:
        validated = validate_order(order)
        result = process_validated_order(validated)
        results.append(result)
    return results


def process_returns(returns: Sequence[Return]) -> Sequence[Result]:
    results = []
    for ret in returns:
        validated = validate_return(ret)
        result = process_validated_return(validated)
        results.append(result)
    return results


# These look similar, but wait! Are they actually the same?
# Different validation, different processing, different errors...
# Duplication is often better than the wrong abstraction

# Only after a third case, consider if there's a real pattern
# But even then, sometimes explicit is better than abstract
```

#### Rule of Three vs the two-copy trigger — reconciling "wait for three" with "extract at two"

The Rule of Three governs **uncertain** similarity: code that *looks* alike but may
turn out to change for different reasons (`process_orders` / `process_returns`
above — different validation, different errors). Waiting protects you from
abstracting on a coincidence and building the wrong shared thing.

It does **not** govern **structurally certain** sameness — where the second copy is
the same *by construction*, not by resemblance, and cannot diverge in *purpose*
even though it will diverge in *detail* if left as twins. Two cases are certain:

- **Same external store/API surface** — a second call site hand-assembling access to
  the same store (the same table + index + cache read, the same multi-step API
  dance). See [`external-system-ownership.md`](external-system-ownership.md),
  "Query surfaces are external systems" and "Structural duplication".
- **Same control-flow skeleton** — a second copy of the same wrapper shape
  (cache-check → run → finish; fetch → build-result; guard → delete). See
  "Same-skeleton wrappers" below.

For those two, the trigger is the **SECOND** copy, not the third. The similarity is
proven, so there is nothing to wait to learn — and the copies drift silently
(the twin-resolver serialization divergence below is that drift realized). Rule of
Three is a rule about *doubt*; when there is no doubt, it does not apply.

#### Same-skeleton wrappers — extract the skeleton at copy two

A family of functions that share a **control-flow skeleton** and differ only in the
step they wrap — `cache-check → run → store`, `fetch → shape-into-result`,
`guard → delete → confirm` — is structurally-certain sameness, not a coincidental
resemblance. Extract the skeleton as a higher-order helper (a decorator, or a
function taking the varying step as a callable) the moment the **second** copy
appears. These families drift silently: each twin looks correct in its own file,
and one gets a fix or a field the others don't.

Real incident: a family of near-identical resolver methods — each `fetch row →
build the response model` — had already diverged on **one field's serialization**
(one resolver JSON-encoded it, its twins passed it raw). Every method's own test
passed; the bug lived only in the disagreement *between* them. The skeleton
(`fetch → build-result`) was the same in all of them; only the query and the field
list varied. One helper taking `(query, row_to_model)` would have made the
serialization single-sourced and the drift impossible.

```python
# BAD: three resolvers, same skeleton, drifting bodies
async def resolve_widget(id: str) -> WidgetOut:
    row = await store.fetch_widget(id)
    return WidgetOut(id=row.id, spec=orjson.dumps(row.spec).decode())  # JSON-encoded

async def resolve_gadget(id: str) -> GadgetOut:
    row = await store.fetch_gadget(id)
    return GadgetOut(id=row.id, spec=row.spec)  # raw — drifted!


# GOOD: the skeleton is single-sourced; only the varying parts are arguments
async def resolve[R: BaseModel](
    fetch: Callable[[str], Awaitable[Row]],
    build: Callable[[Row], R],
    id: str,
) -> R:
    """Fetch a row and build its response model — the one fetch→build skeleton."""
    return build(await fetch(id))
```

Distinct from the *cross-language* twins below (Python-vs-SQL): that is one rule
re-expressed in two dialects; this is one *skeleton* re-expressed in the same
language. Both drift; the fixes differ (collapse to one place vs. extract the
skeleton).

### Twin implementations — the same rule in two languages/layers is a bug farm

The Rule of Three tolerates duplication *within one language* until a pattern proves itself. It does
**not** license the same business rule living in **two languages or layers at once** — a validation in
Python **and** in SQL, a computation in the app **and** in a stored procedure, a limit in code **and**
in a config schema. Two twins that must agree by hand drift the moment one is edited and the other
isn't, and the drift is silent: each twin looks correct in its own file.

Real incident: a "within working hours" window existed twice — a Python twin that correctly handled
an **overnight** range (e.g. 22:00–06:00, where `start > end`) and a SQL twin written as
`WHERE hour BETWEEN start AND end`, which **silently never matched** the overnight case. Both passed
their own tests; the composite behavior was wrong for every overnight window.

Two rules:

1. **Duplication across languages/layers is a bug farm — eliminate one twin when you can.** Compute
   the rule in *one* place and have the other layer consume the result (a single query the app calls,
   or a value the app writes that SQL reads), rather than re-expressing the same logic in both
   dialects where the dialects have different edge-case semantics (`BETWEEN` vs a Python comparison,
   NULL handling, integer division, timezone math).
2. **When you DELETE one twin, port its boundary tests to the survivor in the same change.** The
   deleted twin's tests — the overnight-window case, the empty-set case, the off-by-one boundary —
   were often the *only* thing pinning the correct behavior. Drop them and the survivor is now
   unprotected at exactly the edges that broke before. Move the boundary assertions onto the survivor
   before the twin's tests disappear with it.

### Pattern 6: Function Size Guidelines

Keep functions focused. Extract when a function:

- Exceeds 20-50 lines (varies by complexity)
- Serves multiple distinct purposes
- Has deeply nested logic (3+ levels)

```python
# Too long, multiple concerns mixed
def process_order(order: Order) -> Result:
    # 50 lines of validation...
    # 30 lines of inventory check...
    # 40 lines of payment processing...
    # 20 lines of notification...
    pass


# Better: Composed from focused functions
def process_order(order: Order) -> Result:
    """Process a customer order through the complete workflow."""
    validate_order(order)
    reserve_inventory(order)
    payment_result = charge_payment(order)
    send_confirmation(order, payment_result)
    return Result(success=True, order_id=order.id)
```

### Pattern 7: Dependency Injection

Pass dependencies through constructors for testability.

**When to reach for this:** inject a dependency when you have a *real* second
implementation today (two backends, a genuine fake the test needs) — not because
injection is tidy. A `Protocol` with exactly one implementation is banned by
[`yagni.md`](yagni.md): use the concrete type and, if a test needs to substitute
it, inject the concrete type directly. Don't grow a `Protocol` per collaborator on
the chance a second impl might appear.

```python
from typing import Protocol


class Logger(Protocol):
    def info(self, msg: str, **kwargs) -> None: ...
    def error(self, msg: str, **kwargs) -> None: ...


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...


class UserService:
    """Service with injected dependencies."""

    def __init__(
        self,
        repository: UserRepository,
        cache: Cache,
        logger: Logger,
    ) -> None:
        self._repo = repository
        self._cache = cache
        self._logger = logger

    async def get_user(self, user_id: str) -> User:
        # Check cache first
        cached = await self._cache.get(f"user:{user_id}")
        if cached:
            self._logger.info("Cache hit", user_id=user_id)
            return User.from_json(cached)

        # Fetch from database
        user = await self._repo.get_by_id(user_id)
        if user:
            await self._cache.set(f"user:{user_id}", user.to_json(), ttl=300)

        return user


# Production
service = UserService(
    repository=PostgresUserRepository(db),
    cache=RedisCache(redis),
    logger=StructlogLogger(),
)

# Testing
service = UserService(
    repository=InMemoryUserRepository(),
    cache=FakeCache(),
    logger=NullLogger(),
)
```

### Pattern 8: Avoiding Common Anti-Patterns

**Don't expose internal types in APIs:**

```python
# BAD: Leaking ORM model to API
@app.get("/users/{id}")
def get_user(id: str) -> UserModel:  # SQLAlchemy model
    return db.query(UserModel).get(id)


# GOOD: Use response schemas
@app.get("/users/{id}")
def get_user(id: str) -> UserResponse:
    user = db.query(UserModel).get(id)
    return UserResponse.from_orm(user)
```

**Don't mix I/O with business logic:**

```python
# BAD: SQL embedded in business logic
def calculate_discount(user_id: str) -> float:
    user = db.query("SELECT * FROM users WHERE id = ?", user_id)
    orders = db.query("SELECT * FROM orders WHERE user_id = ?", user_id)
    # Business logic mixed with data access


# GOOD: Repository pattern
def calculate_discount(user: User, order_history: list[Order]) -> float:
    # Pure business logic, easily testable
    if len(order_history) > 10:
        return 0.15
    return 0.0
```

**Don't leave re-export shim modules — move the code, repoint the imports:**

A module whose entire body is `from new.location import X` (a pointer left behind
after a refactor) is a shim. It adds a second name for one thing, hides the real
location from "go to definition", and blinds dead-code tools. When you relocate
code, **move the file and repoint every importer** — don't soften the move with a
backward-compatibility shim.

```python
# BAD: src/myapp/old_service.py left behind as a shim after the code moved
from myapp.core.service import Service  # noqa: F401  (re-export for old imports)


# GOOD: the file moved to src/myapp/core/service.py and EVERY old import was
# repointed to `from myapp.core.service import Service`. No module left behind.
```

The one legitimate "module that only imports" is a package's `__init__.py`
declaring its public API via `__all__` (see [`visibility.md`](visibility.md)) —
that is the intended seam, not a shim. For the mechanical move + import-repoint +
`collect-only` verify loop, use the `python-module-migration` skill.
