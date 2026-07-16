# pyproject.toml — project configuration

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Project Configuration (pyproject.toml)

Centralize all tool configuration in `pyproject.toml`. This is the single source of truth
for Ruff, mypy, and project metadata.

## Ruff — top-level

```toml
[tool.ruff]
target-version = "py314"
line-length = 120
preview = true
fix = true
output-format = "concise"
format.indent-style = "space"
format.quote-style = "double"
exclude = [ "alembic/", "vendor/", ".claude/" ]
```

**Do NOT add `"tests/"` to `exclude`.** It is tempting (tests trip `D`, `S105`, `S106`) and it is
wrong: the whole data-modeling standard in this skill exists because a *test fixture* lied — it
matched neither the DB nor its `TypedDict`, and mypy stayed green. Excluding tests from lint leaves
the least-checked code in exactly the place that caused the incident, and the standing rule is
*make fixtures agree with REALITY*. Lint tests like production code and relax the genuinely
test-only rules by name via `per-file-ignores."tests/**"` (see below).

## Ruff — the reasoned select/reject table

Anyone can list rule groups to select. The expensive knowledge is which groups to **reject, and why**.
The general principle: **prefer a measured subset over a blanket group.** A group that lights up
hundreds of findings does not get fixed — it gets ignored, or `# noqa`'d into meaninglessness, and
the gate stops meaning anything. Enable the blanket group once, *measure the noise*, then keep the
high-value subset and record the count so the next person does not re-enable it.

### Selected

| Rule | Why |
| --- | --- |
| `ASYNC` | flake8-async — detect blocking calls in async |
| `B` | flake8-bugbear |
| `B904` | raise-without-from-inside-except: chain re-raises with `from exc` / `from None` |
| `BLE` | flake8-blind-exception: BLE001 = no bare `except Exception` |
| `C4` | flake8-comprehensions |
| `C90` | mccabe cyclomatic complexity (cap in `lint.mccabe`) |
| `D` | pydocstyle — presence, structural syntax, formatting |
| `E` / `W` / `F` / `I` | pycodestyle, pyflakes, isort |
| `RUF` | ruff-specific rules |
| `S` | flake8-bandit (security) |
| `SIM` | flake8-simplify |
| `TID` | flake8-tidy-imports (banned-api below) |
| `UP` | pyupgrade |

### Rejected — with the measured reason

| Rejected | Measured | Keep instead |
| --- | --- | --- |
| `DOC` (pydoclint) | DOC501/DOC502 **cannot trace exceptions through function calls: 196 false positives.** The `D` rules already enforce presence, structure, and Google convention. | nothing — `D` covers it |
| blanket `PLR` | The full group lights up **~346 style findings** (PLR2004 magic-value, PLR6301 no-self-use, PLR0914 too-many-locals) that are explicitly unwanted. | the COMPLEXITY caps only: `PLR0911`, `PLR0912`, `PLR0913`, `PLR0915` |
| umbrella `TRY` (tryceratops) | `TRY003` (long inline exception messages) is idiomatic here and lights up **~185 findings**; `TRY300` (move-to-else-block) is low-value stylistic churn (**~30**). | the high-value subset: `TRY002`, `TRY004`, `TRY201` (+ `TRY301`, `TRY400`) |

```toml
lint.select = [
  "ASYNC",   # flake8-async (detect blocking calls in async)
  "B",       # flake8-bugbear
  "B904",    # raise-without-from-inside-except: chain re-raises with `from exc`/`from None`
  "BLE",     # flake8-blind-exception: BLE001 = no bare `except Exception`
  "C4",      # flake8-comprehensions
  "C90",     # mccabe cyclomatic complexity (cap in lint.mccabe below)
  "D",       # pydocstyle (checks presence, structural syntax, formatting)
  # DOC (pydoclint) NOT selected: DOC501/DOC502 can't trace exceptions through function
  # calls (196 false positives). D-rules already enforce presence, structure, and Google convention.
  "E",       # pycodestyle errors
  "F",       # pyflakes
  "I",       # isort
  # Pylint COMPLEXITY caps only — NOT the blanket "PLR" group. The full group lights up
  # ~346 style findings (PLR2004 magic-value, PLR6301 no-self-use, PLR0914 too-many-locals)
  # that are explicitly unwanted here. Caps live in lint.pylint below.
  "PLR0911", # too-many-return-statements
  "PLR0912", # too-many-branches
  "PLR0913", # too-many-arguments
  "PLR0915", # too-many-statements
  "RUF",     # ruff-specific rules
  "S",       # flake8-bandit (security)
  "SIM",     # flake8-simplify
  "TID",     # flake8-tidy-imports (banned-api below)
  # tryceratops — high-value subset only. The umbrella "TRY" is intentionally NOT
  # selected: TRY003 (long inline exception messages) is idiomatic here and lights up
  # ~185 findings, and TRY300 (move-to-else-block) is low-value stylistic churn (~30).
  "TRY002",  # create your own exception instead of raising bare Exception
  "TRY004",  # prefer TypeError for type-check failures
  "TRY201",  # use bare `raise` to re-raise the active exception
  "TRY301",  # abstract `raise` to an inner function (avoid raise inside try)
  "TRY400",  # use `logging.exception` instead of `logging.error` inside except
  "UP",      # pyupgrade
  "W",       # pycodestyle warnings
]
lint.ignore = [
  "D105",   # Missing docstring in magic method (e.g. __str__)
  "D107",   # Missing docstring in __init__ (document the class instead)
  "E501",   # line length handled by formatter
]
lint.isort.known-first-party = [ "myapp" ]
lint.pydocstyle.convention = "google"
# Complexity caps — regression-only gate. Set just above the current worst-case so only
# genuinely extreme functions flag; raise these deliberately, never to silence a refactor.
lint.mccabe.max-complexity = 12
# 8-10 args is legitimate for DB-row constructors and LLM invokers (N config knobs);
# >10 is a genuine god-function.
lint.pylint.max-args = 10
lint.pylint.max-branches = 12
# 7-8 returns is clean early-return/guard-clause style, not a smell; >8 is excessive.
lint.pylint.max-returns = 8
lint.pylint.max-statements = 60
```

Do **not** add flake8-future-annotations (`FA100`/`FA102`). On Python 3.14, PEP 649 makes
`from __future__ import annotations` an anti-pattern — that rule would enforce one.

## `banned-api` (TID251) — external-system ownership, made mechanical

The rule *"one owner module per external system; all SDK calls flow through it"* is prose until
TID251 enforces it. Each ban names the owner and the escape hatch:

| Banned import | Owner |
| --- | --- |
| `aiobotocore` / `boto3` / `botocore` | `myapp.core.aws` |
| `anthropic` / `openai` | `myapp.core.ai.llm` |
| `httpx` | `myapp.core.connector` |
| `asyncio.to_thread` | `myapp.core.thread_pool.run_in_thread()` |
| `concurrent.futures` | `myapp.core.thread_pool.ThreadPool` |
| `json` | **orjson** — `orjson.loads` / `orjson.dumps` (this skill's *Preferred libraries*: never stdlib `json`) |
| `logging` | **structlog** — `structlog.get_logger()` |
| `os.getenv` | the `Settings` singleton — config is read once, typed, at startup; never scattered `os.getenv` calls |

The last three are not external SDKs but the skill's own **library-preference and config
rules made mechanical** — the same TID251 mechanism, so "use orjson", "use structlog",
"config through `Settings`" stop being prose the moment they are wired. `json` and
`logging` are banned *everywhere* except a single owner: a serde/codec boundary that
genuinely needs stdlib `json`, and the logging-bootstrap module that configures the
stdlib backend `structlog` wraps — each per-file-ignored with that reason.

```toml
# External system ownership — all SDK access goes through core/ modules.
# Violations mean a raw SDK is being used outside its designated core/ owner.
# Owner folders have TID251 excluded via per-file-ignores below.
lint.flake8-tidy-imports.banned-api.aiobotocore.msg = "Use myapp.core.aws. Raw aiobotocore only in core/aws/**."
lint.flake8-tidy-imports.banned-api.boto3.msg = "Use myapp.core.aws. Raw boto3 only in core/aws/**."
# botocore (incl. botocore.exceptions.ClientError) is owned by core/aws: the wrappers TRANSLATE
# ClientError -> semantic errors, and consumers catch THOSE (e.g. dynamodb.ConditionalCheckFailed,
# s3.ObjectNotFound), never botocore. A caller that imports botocore to catch ClientError has
# reached around the translation and re-coupled itself to the SDK's error vocabulary.
lint.flake8-tidy-imports.banned-api.botocore.msg = "Use myapp.core.aws + its semantic exceptions (myapp.core.aws.exceptions). Raw botocore only in core/aws/**."
lint.flake8-tidy-imports.banned-api.anthropic.msg = "Use myapp.core.ai.llm. Raw anthropic SDK only in core/ai/llm/**."
lint.flake8-tidy-imports.banned-api.openai.msg = "Use myapp.core.ai.llm.openai. Raw openai SDK only in core/ai/llm/**."
lint.flake8-tidy-imports.banned-api.httpx.msg = "Use myapp.core.connector. Raw httpx only in core/connector/**."
lint.flake8-tidy-imports.banned-api."asyncio.to_thread".msg = "Use run_in_thread() from myapp.core.thread_pool — configurable pool + structured logging. Raw asyncio.to_thread only in core/thread_pool.py."
lint.flake8-tidy-imports.banned-api."concurrent.futures".msg = "Use myapp.core.thread_pool.ThreadPool. Raw ThreadPoolExecutor only in core/thread_pool.py."
# The skill's own library-preference + config rules, made mechanical (not external SDKs).
lint.flake8-tidy-imports.banned-api.json.msg = "Use orjson (orjson.loads/orjson.dumps). Stdlib json only in a documented serde/codec boundary."
lint.flake8-tidy-imports.banned-api.logging.msg = "Use structlog (structlog.get_logger()). Stdlib logging only in the logging-bootstrap module structlog wraps."
lint.flake8-tidy-imports.banned-api."os.getenv".msg = "Read config through the Settings singleton (typed, validated once at startup) — never scattered os.getenv."

# Owner folders — the ONLY places the raw SDK is legal.
lint.per-file-ignores."src/myapp/core/aws/**" = [ "TID251" ]
lint.per-file-ignores."src/myapp/core/ai/llm/**" = [ "TID251" ]
lint.per-file-ignores."src/myapp/core/connector/**" = [ "TID251" ]
lint.per-file-ignores."src/myapp/core/thread_pool.py" = [ "TID251" ]
# stdlib json/logging owners: the one serde boundary + the logging bootstrap. Settings owns os.getenv.
lint.per-file-ignores."src/myapp/core/serde.py" = [ "TID251" ]        # stdlib json where a lib requires it
lint.per-file-ignores."src/myapp/core/logging_setup.py" = [ "TID251" ] # configures the stdlib backend structlog wraps
lint.per-file-ignores."src/myapp/core/settings.py" = [ "TID251" ]      # the ONE place os.getenv is read
# Deploy-time scripts run outside the app runtime, before the wrappers exist.
lint.per-file-ignores."scripts/**" = [ "D301", "T201", "TID251" ]
# Tests are LINTED (see the exclude note above) — only the genuinely test-only rules relax.
# S105/S106: hardcoded dummy credentials are fine in tests.
# TID251: test files may import raw SDKs to mock connector internals.
lint.per-file-ignores."tests/**" = [ "D", "S105", "S106", "TID251" ]
```

Every per-file-ignore carries a comment naming *why that path owns that exemption*. An exemption
without a stated reason is indistinguishable from an accident and never gets removed.

## `[tool.mypy]`

```toml
[tool.mypy]
python_version = "3.14"
strict = true
plugins = [ "pydantic.mypy" ]
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
no_implicit_optional = true
check_untyped_defs = true
explicit_package_bases = true
mypy_path = "src"
exclude = [ "^alembic/", "^vendor/" ]
overrides = [
  { module = "tests.*", disallow_untyped_defs = false },
  { module = "alembic.*", ignore_errors = true },
]
```

## `[tool.bandit]` — justified skips

Ruff's `S` group covers most of bandit; a separate bandit run is for the checks ruff has not ported.
Same discipline: every skip states its reason.

```toml
[tool.bandit]
exclude_dirs = [ "tests" ]
skips = [
  "B101", # assert statements
  "B108", # /tmp usage — intentional (ephemeral containers)
  "B404", # import subprocess — acceptable
  "B405", # xml.etree — controlled internal data, not untrusted XML
  "B608", # SQL injection — SQLAlchemy parameterized queries
]
```

## `[tool.vulture]` — every ignore carries a why

Dead-code detection only survives if the ignore list is auditable. An `ignore_names` entry without a
stated reason rots: nobody can tell later whether the name is genuinely reachable-by-framework or
was just noisy that day, so nobody ever deletes it. The pattern **is** the point.

```toml
[tool.vulture]
# Framework-invoked entry points — vulture can't see the router/decorator call.
ignore_decorators = [ "@router.*", "@require_*", "@app.*" ]
ignore_names = [
  "exc_type", "exc_val", "exc_tb",  # __exit__ signature, dictated by the protocol
  "transition_task",   # Protocol method required by the connector interface
  "fetch_changes",     # Protocol method required by the extractor interface
  "get_ticket_limit",  # Plan gate utility — called via registry lookup
  "*Collector",        # Registered collector classes — instantiated by name
]
paths = [ "src/myapp" ]
min_confidence = 80
```

## `[tool.interrogate]`

```toml
[tool.interrogate]
# 100 is the FLOOR, not an aspiration. A percentage floor below 100 cannot say
# WHICH missing docstring is acceptable, so the gap silently fills with whatever
# was written last — the number drifts down to whatever today's code happens to
# score. Carve out the genuinely-noise cases by NAME instead, so each exemption is
# a decision someone made rather than slack in a percentage.
fail-under = 100
ignore-init-module = true          # a re-export-only __init__.py documents nothing
ignore-magic = true                # __repr__ / __eq__ — the dunder IS the contract
ignore-setters = true              # the property's getter carries the docstring
ignore-overloaded-functions = true # @overload stubs; the implementation documents it
exclude = [ "__init__.py", "tests", ".venv", "conftest.py", "alembic" ]
```

## `[tool.importlinter]` — dependency direction

TID251 stops the wrong *SDK* import; import-linter stops the wrong *internal* import. The contract
**names** are the lesson — each one is a sentence someone would otherwise have to re-derive:

| Contract name | Type | Stops |
| --- | --- | --- |
| Config/message models stay pure (no I/O dependencies) | `forbidden` | a data model importing the DB / API / entry layers |
| Core base modules have no project dependencies | `forbidden` | the base layer reaching "up" into app code |
| AWS service wrappers are mutually independent | `independence` | one service wrapper importing a sibling wrapper |
| LLM providers are mutually independent | `independence` | one provider module delegating to a sibling provider |
| core/aws is a project-agnostic base layer | `forbidden` | project-specific logic leaking into the generic client layer |
| Connector vendors are mutually independent | `independence` | one vendor integration importing another |
| Lambda entry points are mutually independent | `independence` | one deployment unit importing another's package |

**"X are mutually independent" is the reusable contract shape.** Whenever N sibling modules each own
one external system, an `independence` contract stops them quietly importing each other — which is
how a "containment" layout silently degrades into a tangle. Exclude the shared base / `__init__`
aggregator from the module list: every sibling legitimately imports the base, and listing it flags
that valid import as a violation.

```toml
[tool.importlinter]
root_packages = [ "myapp" ]

# Containment, not layering: one module owns one external system. Each core/aws/* wrapper
# wraps exactly one AWS service and must NOT import a sibling. Shared infra (core.aws.base
# and the package __init__ aggregator) is intentionally excluded — every wrapper imports base.
[[tool.importlinter.contracts]]
name = "AWS service wrappers are mutually independent"
type = "independence"
modules = [
  "myapp.core.aws.dynamodb",
  "myapp.core.aws.s3",
  "myapp.core.aws.sqs",
  "myapp.core.aws.sns",
]

[[tool.importlinter.contracts]]
name = "core/aws is a project-agnostic base layer"
type = "forbidden"
source_modules = [ "myapp.core.aws" ]
forbidden_modules = [ "myapp.api", "myapp.aws_resources", "myapp.cli", "myapp.db" ]
```

⚠️ **Contract-reference integrity.** import-linter treats a module name that no longer resolves as
*trivially satisfied* — a contract listing a deleted or renamed package goes green while protecting
nothing. When renaming a package, update every contract naming it **in the same PR**; otherwise the
gate reports success over an unenforced rule and nobody notices for days.

Run with:

```bash
uv run ruff check --fix .  # Lint and auto-fix
uv run ruff format .       # Format code
uv run mypy .              # Type check
uv run interrogate -c pyproject.toml .  # Docstring coverage (fail-under = 100)
uv run lint-imports         # Architectural dependency direction
uv run vulture              # Dead code
```

## Checker exception config — `[tool.*]` / hook flags

The first-party AST checkers this skill ships (`pydantic_contract.py`,
`lambda_event_validation.py`, `flat_test_mirror.py`, `all_contract.py`,
`model_contract.py`) take their project config as **CLI flags on the prek `entry`
line** — that entry string *is* the checker's config, versioned next to
`pyproject.toml`. Every allowlist knob below obeys ONE discipline:

> **An allowlist entry carries a proven reason or it rots.** Key every entry on a
> `(path suffix, name)` pair — a bare name-set can silently match a second call
> site the exemption was never meant to cover, whereas `(path, name)` can't
> drift. State the reason inline; a checker that can re-prove the reason turns a
> stale exemption into its own finding. **An entry that matches no code is itself
> dead — delete it** (the same rule vulture's `ignore_names` obeys above).

### `pydantic_contract.py` — model-base registration, per-rule rollout, opaque exclude

```toml
[[repos]]
repo = "local"
hooks = [{
  id = "pydantic-contract",
  name = "🐍 skill · Pydantic data contract",
  # --model-base: register EVERY project model base or the checker goes blind to
  #   its subclasses and they rot invisibly (models it can't see are models it
  #   can't gate). Name your own base the moment you add one.
  # --select: adopt rules one at a time on a legacy tree (one baseline per rule).
  entry = "python scripts/pydantic_contract.py --model-base myapp.core.model.StrictModel --select no-cast,extra-forbid src/",
  language = "system",
  language_version = "3.14",
  pass_filenames = false,
  always_run = true,
  files = "\\.py$"
}]
```

`opaque-annotation` has no CLI allowlist — a genuinely-polymorphic vendor payload
is excluded by PATH at the prek layer, with the reason inline, so the exemption
is one auditable line and not a blanket:

```toml
# acme's webhook body is a true union we don't control — model it in TICK-1.
# Scope the exclude to the ONE file, never the package.
lint.per-file-ignores  # (n/a — this is a prek `exclude`, shown for shape)
# prek.toml:  exclude = "^src/myapp/integrations/acme/payload\\.py$"
```

### `lambda_event_validation.py` — `--allow DIR=CALLABLE`, positively verified

```toml
# --allow api=Mangum does NOT mean "skip api/" — it means "api/ is exempt BECAUSE
# it calls Mangum(...)", re-proved every run. Refactor the proxy away and the
# predicate stops holding, so the gate re-arms and reports `stale-allowlist`.
entry = "python scripts/lambda_event_validation.py --allow api=Mangum src/"
```

Each `--allow` is `(dir suffix, callable)` — the callable IS the machine-checkable
reason. No reason ⇒ no exemption; a reason that no longer holds ⇒ a finding.

### `flat_test_mirror.py` — `--root`, no allowlist by design

```toml
# --root points at the flat unit tier. There is deliberately NO allowlist:
# every src module maps to exactly one `tests/unit/test_<a>_<b>.py` mirror, and
# "this one file is special" is precisely the drift the rule exists to stop.
entry = "python scripts/flat_test_mirror.py --root tests/unit src/"
```

### `all_contract.py` — `--package`

```toml
# --package names the import root whose `__all__` export contract is enforced.
# No per-name allowlist: a name is public (declared in __all__) or it is not.
entry = "python scripts/all_contract.py --package myapp src/"
```

### `model_contract.py` — config symbol + two `(path, name)` allowlists

```toml
[[repos]]
repo = "local"
hooks = [{
  id = "model-contract",
  name = "🐍 skill · Model contract (7 rules)",
  # --config-symbol: the shared ConfigDict every model_config must START FROM
  #   (`PYDANTIC_CONFIG | ConfigDict(...)`). A bare ConfigDict(...) silently drops
  #   extra="forbid"/strict=True, so `pydantic-config` flags it.
  # --allow-dataclass PATHSUFFIX=ClassName (repeatable): a @dataclass survivor with
  #   a PROVEN structural reason — holds a live object / DI container / a
  #   TYPE_CHECKING-only import / a `dataclasses.replace()` target. `(path, name)`
  #   keyed, so it can't leak to another class of the same name elsewhere.
  # --allow-private PATHSUFFIX=attr: a `_name` that is public-despite-underscore
  #   (e.g. SQLAlchemy Row's `_mapping`), likewise `(path, attr)` keyed.
  # verbatim-strip's field-name pattern
  #   (content|body|text|diff|snippet|patch|raw|chunk_text|output|source|html|preview)
  #   is built in — set str_strip_whitespace=False on the model, don't widen it.
  entry = """python scripts/model_contract.py \
    --config-symbol PYDANTIC_CONFIG \
    --allow-dataclass core/container.py=AppContainer \
    --allow-dataclass core/typing_shim.py=VendorStub \
    --allow-private core/db/row.py=_mapping \
    src/""",
  language = "system",
  language_version = "3.14",
  pass_filenames = false,
  always_run = true,
  files = "\\.py$"
}]
```

Read each allowlist entry as `(path suffix, name)` + a REQUIRED reason:

| Flag | `(path suffix, name)` | Required reason (inline comment) |
| --- | --- | --- |
| `--allow-dataclass` | `(core/container.py, AppContainer)` | wires live singletons; a Pydantic model would validate the DI graph on every access |
| `--allow-dataclass` | `(core/typing_shim.py, VendorStub)` | `TYPE_CHECKING`-only shim for an untyped vendor class — never instantiated at runtime |
| `--allow-private` | `(core/db/row.py, _mapping)` | SQLAlchemy's documented public accessor that happens to be underscore-prefixed |

`no-alias`, `no-dataclass` (beyond the allowlist), `barrel-init`,
`json-parse-then-validate`, and cross-object `private-access` (beyond the
allowlist) have **no** escape hatch — they are always wrong. If one of the two
`--allow-*` entries above ever matches no code (the class was deleted, the attr
renamed), the entry is dead: remove it in the same PR, never leave it as a
standing hole the next drift can slip through.
