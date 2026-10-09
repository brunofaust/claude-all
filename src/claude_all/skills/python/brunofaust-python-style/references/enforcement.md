# Enforcement Hook Matrix

Every rule in this skill has an enforcement mechanism. If a rule has no enforcement, it is aspirational, not required.

## Matrix

| Rule                                  | Enforced by                                                        | Bypass                                     |
| ------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------ |
| Pydantic on boundaries                | mypy strict + `pydantic_contract.py` (regression baseline) — the eight rules below. **Supersedes** `skill_enforcer.py` rule `no_dict_any_in_signatures`, which only saw *parameters*; the checker also covers **returns** and **model fields**. Retire the old rule rather than running both. | none — see the per-rule rows below |
| No raw boto3 outside core/aws/        | ruff `banned-api` (TID251)                                         | `[per-file-ignores]` in pyproject.toml     |
| No raw httpx outside integrations/    | ruff `banned-api` (TID251)                                         | `[per-file-ignores]` in pyproject.toml     |
| No silent except                      | ruff `BLE001`, `skill_enforcer.py` rule `no_debug_in_except`       | `# noqa: BLE001` with explanation          |
| Public names only (`__all__` not `_`) | vulture + `skill_enforcer.py` rule `no_module_underscore_names`    | add to `__all__`                           |
| Thin lambda handlers (\<20 stmts)     | `skill_enforcer.py` rule `thin_lambda_handlers`                    | none — split into feature service          |
| Dockerfile per resource               | `skill_enforcer.py` rule `resource_mandatory_files`                | none                                       |
| CLAUDE.md per resource                | `skill_enforcer.py` rule `resource_mandatory_files`                | none                                       |
| Layer dependency direction            | `import-linter`                                                    | refactor required                          |
| Docs updated with code                | `precommit_docs.sh` + GitHub Action                                | `skip-docs` label                          |
| Resource CLAUDE.md updated            | `precommit_resource_docs.sh` + GitHub Action                       | none                                       |
| Conventional commits                  | commitizen `commit-msg` hook                                       | none                                       |
| Docstrings optional, size-bounded     | `docstring_budget.py` (`[tool.docstring-budget]`)                  | none — shorten it or move the prose to a reference doc; never raise a budget to fit one symbol |
| No bare `# type: ignore`              | `python-check-blanket-type-ignore`                                 | use specific code                          |
| No bare `# noqa`                      | ruff `RUF100`                                                      | use specific code                          |
| No `Any` from a typed return          | mypy strict `no-any-return`                                        | none — `Model.model_validate(...)` at the seam. **Not** `cast(...)`: that asserts a type instead of proving one and is itself banned by `pydantic_contract.py` rule `no-cast` |
| `Final` attr not redeclared           | mypy `[misc]`                                                      | rethink the override                       |
| No raw `asyncio.to_thread`            | ruff `banned-api` (TID251) → `run_in_thread()`                     | `[per-file-ignores]`                       |
| No raw `subprocess`                   | ruff `banned-api` (TID251) → `run_exec()`/`run_shell()`            | `scripts/**` per-file-ignore               |
| Stdlib `json` banned → orjson         | ruff `banned-api` (TID251) → `orjson.loads`/`orjson.dumps`         | one serde/codec `[per-file-ignore]` with a reason |
| Stdlib `logging` banned → structlog   | ruff `banned-api` (TID251) → `structlog.get_logger()`             | the logging-bootstrap module `[per-file-ignore]` |
| No `os.getenv` outside `Settings`     | ruff `banned-api` (TID251) → the `Settings` singleton             | `src/**/settings.py` `[per-file-ignore]`   |
| Annotations, not type comments        | prek type-annotation-enforcement hook                              | none                                       |

**Two layers for the library rules.** The `json` / `logging` / `os.getenv` /
concurrency bans above are the **CI layer** (ruff `banned-api`, caught at
commit/CI). claude-all also ships the **edit-time layer** — four PreToolUse
guards (`python-orjson-guard`, `python-structlog-guard`, `python-settings-env-guard`,
`python-thread-subprocess-guard`) that **block the Write in Claude Code before the
bad import lands**, so generation is steered rather than corrected after the fact
(edit-time guards steer generation better than review comments). Each has a
`# guard:allow` / env-var escape hatch for the one owner file that legitimately
keeps the stdlib. Install them at user level (`claude-all --all --user`); they
apply in every repo. The two layers are complementary — the guard stops it being
written, the ruff ban stops it being merged.

| `__all__` import contract valid       | `all_contract.py` rule `not-in-all` — `from x import y` requires `y` in `x.__all__`. pyright's `reportPrivateImportUsage` is the slower pre-push backstop. | fix the import, or declare the name in `__all__` if it is genuinely public |
| No `_private` name exported in `__all__` | `all_contract.py` rule `private-in-all`                          | none — `__all__` IS the export contract; an underscore name is not public |
| A module with public names declares `__all__` | `all_contract.py` rule `missing-all` — a module that defines a public module-level `def`/`class` but has no `__all__`. Closes the fail-open hole in `not-in-all`: without it, deleting `__all__` opts a module out of the gate entirely (in one repo, 53% of modules were unenforced while the gate stayed green). | none — add `__all__`; exempt BY CONSTRUCTION (a module with nothing public is never flagged) |
| `__init__.py` is docstring-ONLY (no barrel) | `model_contract.py` rule `barrel-init` — ANY import/def/assign in an `__init__.py` is flagged. A re-export barrel forces every consumer to load the whole package (measured 324ms across 12 submodules → 0.3ms once emptied). ruff `RUF067` is INSUFFICIENT here: it permits docstrings **and re-exports**, and the re-exports are exactly what this bans. | none — a barrel is always wrong; move logic to a real module |
| Stay async (no de-async on no-`await`)| ruff `RUF029` disabled in config (by design)                       | n/a — keep the API uniformly `async`       |
| Bounded copy-paste duplication        | `jscpd` (regression-only `--threshold`) — catches copy-paste (same *text*) only, **not** same-responsibility-different-text; structural dup is invisible to it at any threshold (→ `external-system-ownership.md`, "Structural duplication"). Its allowlist is a burn-down list, not a graveyard (below). | dedup the clone — never `SKIP=jscpd`       |
| Raw SQL valid vs migration schema     | `check_raw_sql.py` (sqlglot, regression baseline, no DB)           | fix the query / baseline a real bug        |
| Single alembic head + id ≤ 32 chars   | [`regression-gates/checkers/migration_head.py`](../../../generic/regression-gates/checkers/migration_head.py) (AST, no DB) — also flags duplicate ids and dangling `down_revision`. Reads BOTH `revision = "x"` and the annotated `revision: str = "x"` recent Alembic templates emit. | merge heads into one linear chain          |
| CI-reserved env vars hard-set in tests| pygrep `no-ci-env-setdefault` (`GITHUB_*`/`RUNNER_*`/`CI`)         | assign directly, never `os.environ.setdefault` |
| Unit tier is ONE flat mirror of src   | `flat_test_mirror.py` rules `not-flat`, `non-test-file`, `grab-bag`. **Supersedes** `skill_enforcer.py` rule `test_mirrors_src`, which assumed a NESTED tree — retire the old rule rather than running both. | none — `src/<pkg>/a/b.py` ⇒ `tests/unit/test_a_b.py` |
| No `*_extra` / `*_coverage` grab-bags | `flat_test_mirror.py` rule `grab-bag`                              | none — add the case to the module's own mirror |
| Async target patched with an async-aware double | [`mock-drift-sweep/checkers/async_mock_target.py`](../../../generic/mock-drift-sweep/checkers/async_mock_target.py) rule `async-mock` — a `patch("dotted")` / `patch.object(Cls, "m")` whose target resolves to an `async def` **in the scanned tree** and supplies none of `AsyncMock` / `autospec=True` / `new_callable=AsyncMock`. A bare `MagicMock` is never awaited, so the test passes whether or not the code awaits — a real sync-`def`-fed-to-`async with` shipped that way. Resolution is conservative: an unresolvable target (module not scanned, re-exported name, ambiguous suffix, non-simple `patch.object` object) stays **silent**, so there are no false positives. Pass BOTH `src` and `tests` so targets resolve. | none — use an async-aware double, and pair the seam with one real-invocation test (see `references/testing.md`, "A `MagicMock` on an async target…") |
| `patch()` target must exist somewhere | [`mock-drift-sweep/checkers/patch_target_exists.py`](../../../generic/mock-drift-sweep/checkers/patch_target_exists.py) rule `patch-target-missing` — `patch()` never validates that the attribute exists; it creates it. So a rename/move/delete leaves the patch string "working" and the test green while testing nothing. Same conservative resolution as its siblings. | repoint the patch at the real name (or delete the dead test) |
| `assert_called_with()` must fit the real signature | [`mock-drift-sweep/checkers/mock_assert_signature.py`](../../../generic/mock-drift-sweep/checkers/mock_assert_signature.py) rule `assert-signature` — the assertion compares against the mock, never the real function, so a signature change with no assertion update stays green. Regression-only (`--baseline`/`--check`). | update the assertion to the new signature |
| No unspecced double for a patched model class | [`mock-drift-sweep/checkers/unspecced_model_mock.py`](../../../generic/mock-drift-sweep/checkers/unspecced_model_mock.py) rule `unspecced-model-mock` — a real `extra="forbid"` model already fails loudly on drift; the gap is a bare `MagicMock` standing in for the model class, which invents any attribute asked of it. Regression-only. | `spec=` / `autospec=True` / `create_autospec()` |
| A `src`-dead, test-alive function is a finding | `grep -rn NAME src/ --include='*.py'` — **no committed checker yet** (grep recipe). Dead-code tools (vulture) count a call *from a test* as a use, so a helper whose only callers live in `tests/` reads as live while production silently lost its wiring (a send-to-queue helper orphaned for weeks; the consumer drained an empty queue). Audit liveness by grepping `src/` **excluding** `tests/`; a whole-tree grep is not the check. | resolve the finding two ways: restore the lost production caller (a bug) **or** delete the code AND its tests together (dead) — see `references/testing.md`, "Tests are not callers" |
| No `TypedDict` carrying a contract    | `pydantic_contract.py` rule `no-typeddict` (regression baseline)   | none — it validates nothing at runtime; make it a `BaseModel` |
| No `cast()`                           | `pydantic_contract.py` rule `no-cast` (regression baseline)        | none — `Model.model_validate(...)` proves the type instead of asserting it |
| Every model forbids unknown fields    | `pydantic_contract.py` rule `extra-forbid` (regression baseline)   | none — no exceptions; a schema change must force a code change |
| No masking default on a model field   | `pydantic_contract.py` rule `masking-default` (regression baseline)| none — optional ⇒ `T \| None = None`, required ⇒ no default |
| No opaque annotation (`Any`, `dict[str, Any]`, bare `dict`/`Mapping`) in params, returns, model fields | `pydantic_contract.py` rule `opaque-annotation` (regression baseline) | prek `exclude` on a path holding a genuinely polymorphic vendor payload, documented inline — or baseline the entry with a `# TICK-1: …` note. `Mapping[str, str]` / `dict[VectorKey, SearchResult]` are already legal; the container was never the problem |
| No `**model.model_dump()` splat       | `pydantic_contract.py` rule `splat` (regression baseline)          | none — name the fields. Logging receivers (`log.bind(**ctx)`) are already exempt in the checker |
| No `SELECT *`                         | `pydantic_contract.py` rule `select-star` (regression baseline)    | none — name the columns; this is what `extra-forbid` relies on |
| Credential/PII fields are `repr=False`| `pydantic_contract.py` rule `secret-repr` (regression baseline)    | none — add `Field(repr=False)`; verify with `repr(Model(...))` |
| Lambda event parsed at the boundary   | `lambda_event_validation.py` rule `missing-validation`             | `--allow DIR=CALLABLE`, which is re-verified every run (below) |
| An allowlist entry still earns it     | `lambda_event_validation.py` rule `stale-allowlist`                | none — the exemption proves its own reason or becomes a finding |
| No parse-then-validate at a seam      | `model_contract.py` rule `json-parse-then-validate` — bans `MyModel.model_validate(orjson.loads(raw))`; strict mode is context-aware and rejects a pre-parsed dict, so use `model_validate_json(raw)`. A real system skipped billing for months because the caller failed open on the swallowed error. | none — the parse-callee set (`orjson.loads`, `json.loads`) is the trigger, not an escape hatch |
| `model_config` starts from the shared config | `model_contract.py` rule `pydantic-config` — `model_config` must be `PYDANTIC_CONFIG \| ConfigDict(...)`; a bare `ConfigDict(...)` silently drops `extra="forbid"`/`strict=True`. | `--config-symbol NAME` names the shared config — a project knob, not a per-model exemption |
| Verbatim content field keeps whitespace | `model_contract.py` rule `verbatim-strip` — a field whose name matches `content\|body\|text\|diff\|snippet\|patch\|raw\|chunk_text\|output\|source\|html\|preview` on a model that does NOT set `str_strip_whitespace=False`; the shared strict config strips whitespace and silently corrupted RAG code chunks. | none — set `str_strip_whitespace=False` on the model; the field-name pattern is the trigger |
| No pydantic field alias               | `model_contract.py` rule `no-alias` — bans `Field(alias=...)` / `populate_by_name`; dig the wire key out explicitly so a renamed key fails loud. | none |
| No `@dataclass`                       | `model_contract.py` rule `no-dataclass` — a dataclass validates nothing; use Pydantic. | none — live objects go in a model with `arbitrary_types_allowed=True` (an isinstance check); see data-modeling.md |
| No process-global state | `process_globals.py` — module lazy slots, module mutable literals, module-level locks/ContextVar/`Async*()`/engines/HTTP clients/template envs, `global`, class-body mutable attrs, cls-mutating classmethods, `__new__` singletons, namespace classes, module-level first-party instances | `--exempt GLOB` (symbol or `path::symbol`); `Final`/`Mapping`/`Sequence`/`frozenset`/`tuple` annotations |
| No ad-hoc caches | `adhoc_cache.py` — `@functools.lru_cache`/`@functools.cache` and imports of cachetools/diskcache/aiocache/beaker | `--allow-path GLOB` for the one sanctioned cache-owner module |
| Lazy singleton under a lock | `unlocked_singleton.py` — `global X; if X is None: X = ...` outside a lock-named `with` | add lock names via `--lock-hint` |
| No identity `or`-fallback | `masking_or_fallback.py` — `x or 0` / `x or ""` where the defaulted name or receiving kwarg is an identity (`org_id`, `*_id`, `*_key`, `token`, `*_arn`, …) | `--allow-name` (tracing names), `--sink-exclude` (default `key`), `--identity GLOB` |
| No dynamic first-party import | `dynamic_import.py` — `importlib.import_module("<pkg>…")` / `__import__` with a literal first-party name | computed names and relative imports are exempt |
| e2e tests drive real execution | `e2e_no_bypass.py` — patching/spec'ing first-party code, env mutation, or calling the entrypoint in-process from e2e tests | `--sdk-boundary DOTTED`, `--shared-env NAME` |
| No cross-object private access        | `model_contract.py` rule `private-access` — a `_name` reached ACROSS objects (`other._conn`); `self._x`/`cls._x`/`super()._x`/`OwnClass._x` and dunders are allowed. | `--allow-private PATHSUFFIX=attr` + a documented-public-despite-underscore set (e.g. SQLAlchemy's `_mapping`); re-verified and `(path, attr)`-keyed so it can't drift silently |

### Positively-verified allowlists

An exemption must never just `continue`. `--allow api=Mangum` does not mean "skip
`api/`" — it means "`api/` is exempt **because** it calls `Mangum(...)`", and the
checker re-proves that on every run. Refactor the proxy into a plain handler and
the predicate stops holding, so the gate **re-arms itself** and reports a distinct
`stale-allowlist` finding instead of leaving a permanent hole:

```text
handlers/api: [stale-allowlist] allowlisted because it calls Mangum(...), but no
Mangum(...) call found — allowlist stale?
```

Generalise the shape to every allowlist you add: an entry is
`{target: (reason, machine-checkable predicate)}`, and a failing predicate is its
own violation class. A name-set allowlist cannot do this — it rots silently, and
nothing tells you the exemption outlived its reason.

### Duplication-gate allowlists are burn-down lists, not graveyards

A `jscpd`/codecongruence allowlist is the classic name-set allowlist that rots. Each
entry is a *known duplicate the gate agreed to ignore* — i.e. **backlog**, not a
permanent exemption. Left ungoverned it becomes an unmerged-refactor dumping ground
and, worse, a **config-rot graveyard**: entries naming functions that were deleted
long ago, which the gate can never re-emit, so they read as neither present nor
stale and silently pad the count. One real allowlist of ~50 pairs held **8 genuinely
extractable groups (~200 LOC)** and **12 dead entries naming deleted functions**.

Govern it as a burn-down:

1. **Every entry carries a classification**, not just a pair of paths:
   - `MERGE` — the same thing lives in two spots; collapse to one. Do it, delete the entry.
   - `EXTRACT-CORE` — recurring pattern that belongs to one owner (`core/`, a store module). Extract, delete the entry.
   - `JUSTIFIED: <reason>` — genuinely-independent look-alike pairs that will diverge (Rule of Three doubt). The reason is written down and must still hold.
2. **Sweep dead entries.** An allowlist naming code that no longer exists **is** config
   rot (same class as an import-linter contract naming a deleted module). Grep each
   entry's identifiers against the tree; a match-nothing entry is deleted, not kept.
   A `jscpd` clone key that no longer resolves to real spans should fail the gate, not
   pad it — prefer a gate that re-verifies its allowlist targets exist (the
   positively-verified shape above), so a stale entry surfaces itself.
3. **The list length only shrinks.** A PR may remove entries (fixed or dead) and may
   not add one without a `JUSTIFIED:` reason reviewed like any other exemption. Track
   the count; a rising count is a regression to explain, never a default.

**Two sanctioned shapes, and why.** The gate accepts `Model.model_validate(event)`
*or* `Model(field=event.get(...))`. The second is often preferable for an AWS
envelope: `model_validate` on AWS's raw dict forces `extra="ignore"` (AWS adds
fields you do not control), whereas extracting your own fields lets the model stay
`extra="forbid"`. A gate that permits every correct shape and documents the
trade-off gets adopted; a one-true-way gate gets `SKIP=`'d.

**Single enforcement tool:** `scripts/skill_enforcer.py` — AST-based, config-driven via `skill_rules.toml`. One hook in `prek.toml`, all rules toggleable.

## `skill_enforcer.py` skeleton

```python
import ast, sys, pathlib, tomllib


class SkillChecker(ast.NodeVisitor):
    def __init__(self, path, rules):
        self.path = path
        self.rules = rules
        self.errors = []

    def visit_FunctionDef(self, node):
        # Rule: no dict[str, Any] params outside integrations/
        # RETIRED — `pydantic_contract.py` rule `opaque-annotation` owns this now
        # (it also checks returns and model fields). Shown for historical shape only.
        if "integrations/" not in str(self.path):
            for arg in node.args.args:
                if self._is_dict_any(arg.annotation):
                    self.errors.append(f"{self.path}:{node.lineno} dict[str, Any] in signature")
        # Rule: no business logic in lambda handlers
        if "aws_resources/lambdas/" in str(self.path) and node.name == "lambda_handler":
            stmt_count = sum(1 for n in ast.walk(node) if isinstance(n, ast.stmt))
            if stmt_count > self.rules.get("thin_lambda_handlers", {}).get("max_statements", 20):
                self.errors.append(
                    f"{self.path}:{node.lineno} handler too thick ({stmt_count} stmts)"
                )
        self.generic_visit(node)

    def visit_Assign(self, node):
        # Rule: ban module-level underscore-prefixed names
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id.startswith("_") and not t.id.startswith("__"):
                self.errors.append(f"{self.path}:{node.lineno} module-level _{t.id} — use __all__")

    def visit_ImportFrom(self, node):
        # Rule: no raw SDK imports outside owner folders
        banned = self.rules.get("banned_imports", {})
        for sdk, owner_glob in banned.items():
            if sdk == "enabled":
                continue
            if node.module and node.module.startswith(sdk) and owner_glob not in str(self.path):
                self.errors.append(
                    f"{self.path}:{node.lineno} import {sdk} only allowed in {owner_glob}"
                )

    def visit_ExceptHandler(self, node):
        # Rule: no silent except (log.debug inside except = swallowing)
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and self._is_log_debug(n):
                self.errors.append(
                    f"{self.path}:{node.lineno} log.debug inside except — silent swallow"
                )


def main():
    rules = tomllib.loads(pathlib.Path("skill_rules.toml").read_text())
    errors = []
    for f in pathlib.Path("src").rglob("*.py"):
        tree = ast.parse(f.read_text())
        c = SkillChecker(f, rules)
        c.visit(tree)
        errors.extend(c.errors)
    if errors:
        print("\n".join(errors))
        sys.exit(1)
```

## `skill_rules.toml` example

```toml
# RETIRED — superseded by `pydantic_contract.py` rule `opaque-annotation`, which
# also covers returns and model fields. Keep it `false`: two gates for one rule
# means two baselines, two allow lists, and a disagreement about which is truth.
[rules.no_dict_any_in_signatures]
enabled = false

[rules.banned_imports]
enabled = true
"httpx" = "src/*/integrations/**"
"boto3" = "src/*/core/aws/**"
"aioboto3" = "src/*/core/aws/**"
"atlassian" = "src/*/integrations/jira/**"

[rules.no_module_underscore_names]
enabled = true
exclude_files = ["**/conftest.py", "**/__init__.py"]

[rules.thin_lambda_handlers]
enabled = true
max_statements = 20
paths = ["src/*/aws_resources/lambdas/**/handler.py"]

[rules.no_debug_in_except]
enabled = true

[rules.resource_mandatory_files]
enabled = true
resource_folders = [
    "src/*/aws_resources/lambdas/*",
    "src/*/aws_resources/ecs_tasks/*",
    "src/*/aws_resources/batch_jobs/*",
    "src/*/aws_resources/step_functions/*",
    "src/*/aws_resources/codebuild_projects/*",
    "src/*/aws_resources/glue_jobs/*",
]
required_files = ["README.md", "CLAUDE.md"]
require_dockerfile = ["lambdas/*", "ecs_tasks/*", "batch_jobs/*"]

# RETIRED — superseded by `flat_test_mirror.py`, which enforces the FLAT mirror
# (`src/<pkg>/a/b.py` ⇒ `tests/unit/test_a_b.py`). This rule assumed a NESTED tree
# and contradicted it. Two gates for one rule = two sources of truth that disagree.
[rules.test_mirrors_src]
enabled = false
```


## Plug into `prek.toml`

A project-specific `skill_enforcer.py` lives in the project, so it is a `local` hook (the
checkers this skill ships are wired by `claude-all --install-hooks` instead):

```toml
[[repos]]
repo = "local"
hooks = [{
  id = "skill-enforcer",
  name = "🐍 skill · Enforce coding rules via AST",
  entry = "python scripts/skill_enforcer.py",
  language = "system",
  files = "\\.py$"
}]
```

## Wiring the checker gates

Every checker this skill ships is a hook in the claude-all hook repo. Don't copy scripts into
the project. Generate the wiring:

```bash
claude-all --install-hooks --dry-run   # shows the hooks + diff for this project
claude-all --install-hooks             # writes the managed block (pinned rev)
```

### 1. Greenfield — the bare hook

Each checker exits 1 on any finding, so the generated entry
(`{ id = "pydantic-contract", args = ["src"] }`) fails the commit by itself. The same pinned
hook runs in CI (`prek run --all-files`), so `--no-verify` can't bypass it.

### 2. Existing debt — ratchet with a baseline

Seed once and commit the file (an uncommitted baseline means there is no gate):

```bash
claude-all-check pydantic-contract --baseline pydantic_baseline.txt --update src
git add pydantic_baseline.txt
```

Then add the baseline to the hook's args **inside the managed block** (the next
`--install-hooks` run keeps hand-added args only if you re-add them, so note them in the PR):

```toml
{ id = "pydantic-contract", args = ["--baseline", "pydantic_baseline.txt", "src"] },
```

NEW findings fail, baselined ones pass, and STALE ones (fixed but still listed) also fail,
so the file only shrinks. Burn one notch per PR. Never `SKIP=pydantic-contract` and never
`--no-verify`. If a finding truly can't be fixed now, baseline it with a ticket comment:

```text
# TICK-1: myapp/integrations/acme/payload.py — polymorphic vendor body, model it in Q3
src/myapp/integrations/acme/payload.py: [opaque-annotation] parse(body) — parameter is opaque (dict[..., Any]) …
```

Baseline the SAME paths the hook checks (see *Baseline hygiene* below). Adopt rules
incrementally with `--select` (one hook entry and one baseline per rule set) when the
full set is too big to land at once: `args = ["--select", "no-cast,extra-forbid", "src"]`.

### 3. Gotcha — `prek run --all-files` can report a vacuous PASS

`prek run --all-files` only inspects **git-tracked** files, and only runs the
**pre-commit** stage. A brand-new checker or baseline that is still **untracked**
is silently skipped and the run reports green. The tell:

```text
🐍 skill · Pydantic data contract..........................(no files to check) Skipped
```

`Skipped` on a hook you just added is a FAILING signal, not a passing one.

- `git add` the checker, the baseline, and the config **before** trusting any run.
- Run the other stage too: `prek run --all-files --hook-stage pre-push`.
- Prove the gate bites before believing it: introduce one violation, confirm the
  hook fails, revert, confirm it passes.

### Every checker prints its denominator and fails closed on zero

A green checker over 800 files looks exactly like a green checker over 0 files: a glob that
stopped matching, a hook passed the wrong paths, a matcher that no longer recognises the pattern.
So every checker:

- prints `scanned=<files>`, plus a second denominator for the candidates it classified
  (e.g. `candidates=314 flagged=53`);
- exits **2** (error, not pass) when either count is zero;
- is itself checked: a meta-gate fails when a `check_*.py` never prints `scanned=`, or when a
  checker script exists that no hook in `prek.toml` runs. In the incident, the checker, its
  baseline and its tests all landed, but the hook registration did not, and it stayed unarmed
  for three days.

### Baseline hygiene — baseline the SAME paths the hook `--check`s

The `--baseline` seed run and the enforcing run must scan the **identical** path
argument. Seed against `src/` but `--check` only `src/myapp/` and every finding
under the wider tree is baselined yet never re-checked — permanent, invisible
amnesty. One real incident wrote **618 baseline entries for a hook that checks
281 files**: the ~337 orphans could never be cleared (the enforcing run never
re-emits them, so they read as neither present nor stale) and silently forgave
real debt outside the checked scope. `baseline_gate.py` carries a
scope-consistency guard for exactly this — it refuses to run (exit 2) when the
baseline was seeded over a wider path set than the run is checking — but the
discipline is still yours: seed and enforce with the **same** trailing path.

## Checker rule catalogs (verbatim from former module docstrings)

### `all_contract.py`

````text
Checker: enforce the ``__all__`` export contract — import only what a module exports.

WHY
---
``__all__`` is the real export contract. A module-level name that is not in
``__all__`` is **not public**, so importing it couples you to an implementation
detail that can move, be renamed, or vanish without notice — and without any
signal to the importer. The module never promised that name; the import invented
the promise.

This pairs with the sibling rule that **module-level names never start with an
underscore**. A leading ``_`` at module scope blinds dead-code tools — vulture
treats an underscore-prefixed module-level name as intentionally-unused and stops
reporting it, so ``_helper`` rots forever instead of being deleted. ``__all__``,
not a leading underscore, is how a module says "private": list the public names,
and everything else is private *by omission* while staying visible to tooling.

Three rules enforce that contract:

  not-in-all      ``from x import y`` where ``y`` is not in ``x``'s ``__all__``.
                  Also fires on attribute access through an imported module
                  (``import myapp.core as c; c.y`` / ``myapp.core.y``) — reaching
                  in through a dot is the same coupling as reaching in through an
                  import, so checking only ``from``-imports would leave the door
                  open.
  private-in-all  ``__all__ = ["_helper"]``. Exporting an underscore name is a
                  contradiction: it declares "public" and "private" at once.
                  Drop the underscore (it is public — say so) or drop the entry.
  missing-all     A module that DEFINES a public module-level ``def`` /
                  ``async def`` / ``class`` but declares no ``__all__``. That
                  module has no export contract at all, so ``not-in-all`` cannot
                  verify imports FROM it — deleting ``__all__`` was the escape
                  hatch out of the whole gate. This flags the module itself, from
                  the other side. See the section below.

Dunder names (``__version__``, ``__author__``, …) are always allowed: they are
protocol, not exports. Star imports are skipped — a separate rule bans them.

THE ``missing-all`` RULE — CLOSING THE FAIL-OPEN HOLE
----------------------------------------------------
``not-in-all`` validates an import against the *imported* module's ``__all__``,
and a module that declares none is skipped there — deliberately: you genuinely
cannot verify ``from x import y`` when ``x`` promises nothing, and flagging the
*importer* for the *imported* module's omission would punish the wrong file and
fire on every intra-repo import in a codebase mid-adoption.

But that skip was a fail-open hole big enough to drive a truck through: because a
module with no ``__all__`` is not checked, **deleting ``__all__`` opted a module
out of the gate entirely.** In production this bit hard — over half a package's
modules had no ``__all__`` and got ZERO enforcement while the gate reported
GREEN. It is not cosmetic: a module with public names and no ``__all__`` also
breaks mypy strict's ``no_implicit_reexport`` — a re-export from it fails with
``Module "x" does not explicitly export attribute "Y"``, a real, blocking error.

``missing-all`` closes the hole from the OTHER side. ``not-in-all`` skips ``x``
from the *importer's* file; ``missing-all`` flags ``x`` in ``x``'s OWN file the
moment ``x`` defines a public name and declares no ``__all__``. Once ``x`` gets
its ``__all__``, ``not-in-all`` can enforce every import from it. The two rules
coexist: one names the missing contract, the other enforces the declared one.

The exemption is BY CONSTRUCTION, not by path — there is no allowlist. The rule
fires ONLY when a module DEFINES a public module-level ``def`` / ``async def`` /
``class``: ``__all__`` is the mechanism for saying "this is the public API", so a
module with a public definition and no ``__all__`` has genuinely opted out. A
module with nothing to export — a docstring-only ``__init__.py``, a module of
only ``_private`` definitions (handled by the underscore rule), a module that is
only imports and constants with no public ``def``/``class`` — has no contract to
declare and is NEVER flagged. That carve-out is structural: it cannot drift and
needs no allowlist to maintain. A public name is one that does not start with
``_``; a dunder (``__version__``) is protocol, not exported API, and never counts.
The declaration is recognised in either form — ``__all__ = [...]`` and the
annotated ``__all__: list[str] = [...]`` — so annotating your ``__all__`` never
trips the rule.

CONTRACT
--------
Prints one ``path: [rule] symbol — message`` finding per violation to stdout and
**exits 1 when there is any finding**, so wiring it straight into prek/pre-commit
surfaces the findings and fails the commit — no baseline artifact required.

Keys are rule + enclosing symbol + the imported name, and NEVER a line number, so
an unrelated edit does not churn a baseline. ``not-in-all`` can legitimately fire
many times inside one symbol (a function touching ``c.a`` then ``c.b`` then
``c.a`` again), so its keys carry a per-symbol ordinal — a second occurrence is a
distinct finding rather than a duplicate key that collapses in a set-based
baseline and lets a regression through.

The checker owns NO state: it writes no baseline, no JSON, no cache file. If you
want the regression-only ratchet, compose it with
``regression-gates/baseline_gate.py`` and pass ``--exit-zero`` — that harness
reads a non-zero exit as "the checker crashed" and fails closed, so the flag is
required there and nowhere else.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/all_contract.py src/
    python checkers/all_contract.py --select private-in-all src/
    python checkers/all_contract.py --package myapp src/ tests/

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline all_baseline.txt -- \
        python checkers/all_contract.py --exit-zero src/

The first-party packages are auto-detected from the roots (a ``src/`` layout, a
package dir passed directly, or a file inside one). ``--package`` narrows that
set when a repo ships several. Only first-party modules are resolved — a
third-party import has no in-repo file, so it is never checked.

PARSER NOTE — pin this hook's interpreter
-----------------------------------------
This checker parses with the ``ast`` of the interpreter it RUNS ON, so an
interpreter older than the project's silently fails to parse new syntax (PEP 695
``type X = int``, ``async def run[**P, T]``). Any
Python-AST-based gate shares this: unpinned, bandit's env resolved to 3.11 and
logged "syntax error while parsing AST" for 25 files, SKIPPED them, and **still
exited success** — a security gate silently not scanning. Vulture's resolved to
3.11 and dropped 35 files from dead-code analysis the same way.

So this checker does NOT fail open. An unparsable file exits **2** (a tool error,
distinct from 1 = findings) even under ``--exit-zero``, because a file it could
not read is a file it did not check. That covers the *imported* module too: if
its ``__all__`` cannot be parsed, every import from it would silently pass.

Pin ``language_version`` on THIS hook — a repo-level ``default_language_version``
does NOT reach a hook's isolated env. Gates with their own non-Python parser
(ruff, jscpd, tree-sitter-based tools) are immune and need no pin.
````

### `docstring_budget.py`

````text
Checker: enforce per-symbol docstring and comment SIZE budgets.

WHY
---
Docstrings and comments rot faster than code: a paragraph explaining a
three-line function is read once and then drifts. This gate caps their size
relative to the code they describe. Documentation stays OPTIONAL — a missing
docstring or comment is never a finding; only an oversized one is.

LIMITS
------
Per symbol kind (``module``, ``class``, ``method``, ``function``)::

    docstring limit = min(docstring_max_chars, floor(docstring_code_ratio * code_chars))
                      (no ratio key -> just docstring_max_chars)
    comment limit   = max(comments_max_chars, floor(comments_code_ratio * code_chars))

Counts are raw source characters, whitespace included. Each comment belongs to
its innermost enclosing symbol (span includes decorators and trailing,
deeper-indented comments). ``code_chars`` is the symbol span minus all docs:
nested code counts toward the parent, nested docs do not.

CONFIG
------
``[tool.docstring-budget]`` in ``--config`` (default ``./pyproject.toml``)::

    [tool.docstring-budget]
    function.docstring_max_chars = 150
    function.docstring_code_ratio = 1.0
    function.comments_max_chars = 150
    function.comments_code_ratio = 0.5
    module.docstring_max_chars = 500

Keys given override the built-in defaults key by key; a missing table or file
means all defaults. Unknown keys or wrong types are an error.

CONTRACT
--------
Exit 0 clean, 1 findings, 2 errors. Zero selected files, an invalid config or
an unparsable file is an ERROR (exit 2), never a pass. The last line always
carries ``scanned=N`` so a green run shows its denominator.

USAGE
-----
    python checkers/docstring_budget.py src/myapp tests
    python checkers/docstring_budget.py --config pyproject.toml --limit 0 src/myapp/core.py
````

### `flat_test_mirror.py`

````text
Checker: enforce the FLAT source-mirrored unit-test convention.

WHY
---
``tests/unit/`` is ONE flat folder holding one file per source module, named
``test_<source path with '/' -> '_'>.py``::

    src/myapp/core/aws/s3.py                    -> tests/unit/test_core_aws_s3.py
    src/myapp/features/pii_detection/service.py -> tests/unit/test_features_pii_detection_service.py

"Mirror ``src/``" is ambiguous prose — a NESTED tree
(``tests/unit/features/pii_detection/test_service.py``) and a flat one both claim
to comply, so both appear, and the mirror stops being a lookup you can do in your
head. Flat makes the mapping total and mechanical: given a source path there is
exactly ONE legal test path, and given a test file there is exactly one source
module. That is what makes "does this module have tests?" answerable by a glob
instead of a walk.

Three rules, scanned over the whole ``tests/unit/`` tree:

  not-flat        A subdirectory under the unit tier — a topical folder or a
                  stray package dir. It re-introduces the two-spellings problem
                  and hides a mirror where no glob will find it.
  non-test-file   A non-mirror module parked in the unit tier (``helpers.py``,
                  ``factories.py``). Shared test code belongs in ``conftest.py``
                  or a real package — a file here that is not a mirror breaks the
                  one-file-per-module bijection. ``conftest.py`` / ``__init__.py``
                  are the only exemptions.
  grab-bag        A ``*_extra`` / ``*_edges`` / ``*_coverage[N]`` / ``*_boost[N]``
                  / ``*_remaining`` / ``*_near_threshold`` file parallel to a real
                  mirror. This is the file a coverage-chasing agent writes when
                  it would rather append a new module than read the existing one:
                  the module's tests end up split across files nobody knows to
                  open, and the second copy drifts. Add the tests to the module's
                  mirror instead.

CONTRACT
--------
Prints one ``path: [rule] message`` finding per line to stdout and **exits 1 when
there is any finding**, so wiring it straight into prek/pre-commit surfaces the
findings and fails the commit — no baseline artifact required.

Keys are the offending path plus the rule and NEVER a line number. This checker
is filesystem-based — it inspects names and directory shape, never file contents
— so its keys are naturally path-based and an unrelated edit cannot churn them.

The checker owns NO state: it writes no baseline, no JSON, no cache. If you want
the regression-only ratchet, compose it with ``regression-gates/baseline_gate.py``
and pass ``--exit-zero`` — that harness reads a non-zero exit as "the checker
crashed" and fails closed, so the flag is required there and nowhere else.

Because it never parses Python source, it has no interpreter blind spot and needs
no ``language_version`` pin: an AST-based gate silently fails to parse new syntax
on an old interpreter, but a checker that only reads directory entries cannot.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/flat_test_mirror.py
    python checkers/flat_test_mirror.py --root tests/unit
    python checkers/flat_test_mirror.py --select grab-bag

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline flat_mirror_baseline.txt -- \
        python checkers/flat_test_mirror.py --exit-zero

Wire it with ``pass_filenames: false`` — it walks the tree itself rather than
taking the staged-file list, so a rename that leaves a nested file behind is still
caught on the commit that did not touch it.
````

### `lambda_event_validation.py`

````text
Checker: every Lambda handler validates its raw ``event`` through a Pydantic model.

WHY
---
A Lambda ``event`` is the most untrusted dict in the codebase: it arrives from SQS,
SNS, EventBridge, Step Functions, or a direct invoke, and nothing in the runtime
checks it. Reading ``event["org_id"]`` straight off that dict means a renamed
producer field surfaces as a ``KeyError`` three frames deep — or worse, an
``event.get("org_id")`` returns ``None`` and the None flows on. The
brunofaust-python-style rule is that the event is parsed into a model AT THE
BOUNDARY, before any logic, so a malformed payload fails loudly at the one place
that knows what the payload should be.

TWO SANCTIONED SHAPES — both are validation, and shape 2 is usually the better one
for an AWS-owned envelope::

    1.  parsed = MyEvent.model_validate(event)
    2.  parsed = MyEvent(org_id=event.get("org_id"), run_id=event.get("run_id"))

Shape 1 is right when the payload IS our shape — an SQS body we produced ourselves
and control end to end. But handing AWS's raw envelope to ``model_validate`` forces
the model to ``extra="ignore"``, because AWS puts fields in there that we neither
own nor read (an EventBridge envelope carries a pile of them), and ``extra="ignore"``
is exactly the setting that stops a typo in one of OUR fields from failing. Shape 2
extracts only the fields we declare, which lets the model stay ``extra="forbid"``:
AWS may add envelope fields freely, while a typo in one of ours fails loud. Both
shapes are accepted here on purpose — a gate that permits every correct shape and
explains the trade-off gets adopted; a one-true-way gate gets ``SKIP=``'d.

POSITIVELY-VERIFIED ALLOWLIST — the important idea in this checker
Some handlers validate through an indirection this AST check cannot see: an ASGI
proxy (``handler = Mangum(app)``, where FastAPI/Pydantic validate per-route), or a
shared factory (``handler = make_lambda_entry(...)``, which validates inside its own
dispatch). ``--allow DIR=CALLABLE`` exempts such a handler dir — but the exemption
NEVER just ``continue``s. It asserts its own stated reason still holds: if the module
does not actually call ``CALLABLE(...)``, that is a finding of a DISTINCT class
(``stale-allowlist``). So the day someone refactors the exempt module away from its
factory, the gate re-arms itself automatically instead of leaving a permanent hole
that outlives the reason it was punched. An allowlist entry is a claim, and this
checker makes the claim carry its own proof.

  missing-validation  A handler module with an entry point but no Pydantic model
                      built at the boundary — neither `Model.model_validate(event)`
                      nor `Model(field=event.get(...))`.
  stale-allowlist     A `--allow DIR=CALLABLE` exemption whose module no longer
                      calls `CALLABLE(...)`, so the reason for the hole is gone.

CONTRACT
--------
Prints one ``path: [rule] symbol — message`` finding per violation to stdout and
**exits 1 when there is any finding**, so wiring it straight into prek/pre-commit
surfaces the findings and fails the commit — no baseline artifact required.

Keys are rule + handler directory name and NEVER a line number, so an unrelated edit
does not churn a baseline. At most one finding of each rule can arise per module, so
no ordinal discriminator is needed.

The checker owns NO state: it writes no baseline, no JSON, no cache. If you want the
regression-only ratchet, compose it with ``regression-gates/baseline_gate.py`` and
pass ``--exit-zero`` — that harness reads a non-zero exit as "the checker crashed"
and fails closed, so the flag is required there and nowhere else.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/lambda_event_validation.py src/myapp/lambdas/
    python checkers/lambda_event_validation.py --handler-glob 'lambdas/*/app.py' src/

    # positively-verified exemptions (repeatable)
    python checkers/lambda_event_validation.py \
        --allow api=Mangum --allow notifier=make_lambda_entry src/myapp/lambdas/

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline lambda_event_baseline.txt -- \
        python checkers/lambda_event_validation.py --exit-zero src/

PARSER NOTE — pin this hook's interpreter
-----------------------------------------
This checker parses with the ``ast`` of the interpreter it RUNS ON, so an interpreter
older than the project's silently fails to parse new syntax (PEP 695 ``type X = int``,
``async def run[**P, T]``). Any Python-AST-based gate shares
this: unpinned, bandit's env resolved to 3.11 and logged "syntax error while parsing
AST" for 25 files, SKIPPED them, and **still exited success** — a security gate
silently not scanning.

So this checker does NOT fail open. An unparsable file exits **2** (a tool error,
distinct from 1 = findings) even under ``--exit-zero``, because a file it could not
read is a file it did not check — and here that file is a Lambda boundary.

Pin ``language_version`` on THIS hook — a repo-level ``default_language_version`` does
NOT reach a hook's isolated env. Gates with their own non-Python parser (ruff,
tree-sitter-based tools) are immune and need no pin.
````

### `model_contract.py`

````text
Checker: enforce the Pydantic MODEL rules — the model IS the contract.

WHY
---
A Pydantic model built on the project's SHARED config object is the contract
between every layer of an app: strict typing, ``extra="forbid"``, whitespace
policy, all decided ONCE. A model that opts out of that config — or is not a
model at all (a bare dataclass), or is fed pre-parsed JSON, or reaches into
another object's ``_private`` — is a hole in the contract, and the failure mode
is almost always SILENT: a validated-looking value that was never validated.

Each rule below has a production incident behind it. None of them is style.

  json-parse-then-validate  🔴 THE HEADLINE. ``Model.model_validate(orjson.loads(raw))``
                    instead of ``Model.model_validate_json(raw)``. Pydantic's
                    strict mode is CONTEXT-AWARE: given RAW JSON it knows a
                    ``UUID``/``datetime``/enum can only ARRIVE as a string (JSON
                    can't express those natively) and converts it. Pre-parsing
                    with ``orjson.loads`` throws that context away — pydantic now
                    sees an ordinary ``dict[str, str]`` and ``strict=True``
                    correctly REJECTS it. A caller that fails open
                    (``except ValidationError: return None``) then reads as "no
                    enforcement": a real system had every populated response
                    silently rejected and billing skipped for months, hidden
                    because the test fixture's list was empty so no row was ever
                    validated. The fix is ``Model.model_validate_json(raw)``.
  barrel-init       An ``__init__.py`` that does anything beyond a module
                    docstring (any import / assignment / def). Importing a barrel
                    makes every consumer load the WHOLE package (measured
                    324ms/12 submodules -> 0.3ms once emptied). Ruff's RUF067
                    does NOT cover this — it PERMITS "docstrings and re-exports",
                    which is exactly what is banned. Only a bare docstring (and an
                    empty ``__all__`` anti-barrel marker) is allowed.
  pydantic-config   A model whose ``model_config`` does not START FROM the shared
                    config object. A bare ``ConfigDict(...)`` silently drops
                    ``extra="forbid"`` / ``strict=True`` / ``validate_assignment=True``.
                    The sanctioned shapes are ``<CONFIG>`` and
                    ``<CONFIG> | ConfigDict(...)`` — the shared config's name is
                    project-specific, so it is the ``--config-symbol`` option.
  verbatim-strip    A model field whose NAME matches a verbatim-content pattern
                    (``content``, ``body``, ``diff``, ``snippet``, ``raw`` ...) on a
                    model that does NOT declare ``str_strip_whitespace=False``. The
                    shared config sets ``str_strip_whitespace=True`` (right for
                    names/emails), which SILENTLY strips leading indentation from
                    code/content — it corrupted every code chunk entering a RAG
                    index. A verbatim field needs
                    ``<CONFIG> | ConfigDict(str_strip_whitespace=False)``.
  no-alias          A pydantic ``Field(alias=...)`` / ``AliasChoices`` /
                    ``populate_by_name`` usage. Aliases are banned: dig the wire
                    key out explicitly and construct field-by-field (a
                    ``from_raw_claims()``-style classmethod is the reference), so a
                    renamed vendor key fails LOUD at the parse site instead of
                    arriving as a default.
  no-dataclass      A ``@dataclass`` (or ``@dataclasses.dataclass``). A dataclass
                    validates nothing — use a Pydantic model. There is NO
                    allowlist: a live object goes in a model with
                    ``arbitrary_types_allowed=True`` (an isinstance check), a
                    Protocol field is ``@runtime_checkable``, and a changed copy is
                    ``type(m).model_validate({**dict(m), **changes})``.
  private-access    A ``_name`` reached ACROSS objects (``store._conn``,
                    ``connector._client``). The leading underscore IS the contract
                    ("may change without notice"), so an external caller depending
                    on it has no contract. ONLY cross-object access is a violation:
                    ``self._x`` / ``cls._x`` / ``super()._x`` / ``OwnClass._x`` (from
                    inside ``OwnClass``) are the object touching its own internals
                    and are ALLOWED; a dunder (``obj.__aenter__``) is a language
                    protocol, never private access.

NOT owned here: ``no-typeddict``. The sibling ``pydantic_contract.py`` already owns
it (plus ``extra-forbid``, ``no-cast``, ``masking-default``, ``opaque-annotation``,
``dict-return``, ``splat``, ``select-star``, ``secret-repr``). Run both checkers —
this one is the model/parse/barrel/private half, that one is the field-shape half.

⚠️ MODEL_BASES ROTS SILENTLY — a KNOWN LIMITATION. ``--model-base`` names SYMBOLS
(``BaseModel``, ``RootModel``), so it rots when a base is RENAMED, and it rots in
the WORST direction: an unrecognised base makes a class INVISIBLE to every
model-shaped rule here, so 0 findings reads as CLEAN instead of as "the checker
saw no model at all". This has bitten real gates twice (a returns-checker saw
ZERO models in a 285-model codebase). Keep ``--model-base`` in lockstep with the
project's actual bases, and pin it with a test that resolves each name against
the real modules — a rename must fail a test, not blind the gate.

CONTRACT
--------
Prints one ``path: [rule] symbol — message`` finding per violation to stdout and
**exits 1 when there is any finding**, so wiring it straight into prek/pre-commit
surfaces the findings and fails the commit — no baseline artifact required.

Keys are rule + enclosing symbol (+ field name where relevant) and NEVER a line
number, so an unrelated edit does not churn a baseline; the repeatable rules
(``json-parse-then-validate``, ``barrel-init``, ``no-alias``, ``private-access``)
carry a per-symbol ordinal so a second occurrence is a distinct finding rather
than a duplicate key.

The checker owns NO state: it writes no baseline, no JSON, no cache. If you want
the regression-only ratchet, compose it with ``regression-gates/baseline_gate.py``
and pass ``--exit-zero`` — that harness reads a non-zero exit as "the checker
crashed" and fails closed, so the flag is required there and nowhere else.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/model_contract.py src/
    python checkers/model_contract.py --select json-parse-then-validate,no-alias src/
    python checkers/model_contract.py --config-symbol MY_CONFIG \
        --model-base BaseModel --model-base RootModel src/

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline model_baseline.txt -- \
        python checkers/model_contract.py --exit-zero src/

PARSER NOTE — pin this hook's interpreter
-----------------------------------------
This checker parses with the ``ast`` of the interpreter it RUNS ON, so an
interpreter older than the project's silently fails to parse new syntax (PEP 695
``type X = int``, ``async def run[**P, T]``). Any
Python-AST-based gate shares this: unpinned, bandit's env resolved to 3.11 and
logged "syntax error while parsing AST" for 25 files, SKIPPED them, and **still
exited success** — a security gate silently not scanning.

So this checker does NOT fail open. An unparsable file exits **2** (a tool error,
distinct from 1 = findings) even under ``--exit-zero``, because a file it could
not read is a file it did not check.

Pin ``language_version`` on THIS hook — a repo-level ``default_language_version``
does NOT reach a hook's isolated env. Gates with their own non-Python parser
(ruff, jscpd, tree-sitter-based tools) are immune and need no pin.
````

### `pydantic_contract.py`

````text
Checker: enforce the Pydantic data-contract rules — no untyped dict carries a contract.

WHY
---
A ``dict`` carrying a contract lets a missing, blank, or renamed key slip through
silently. ``TypedDict`` does NOT fix this: it is a *static* annotation that
validates nothing at runtime, so ``cast(plan_row_dtype, dict(row))`` is a no-op
that only pretends to type — mypy stays green while the payload lies. Pydantic
validates at construction, at the boundary, at the point of failure.

The bug class is NOT the ``.get(k, default)`` spelling — that is a symptom. It is
a **default on a field that is required**. Once a payload has a real model, the
required-vs-optional decision is forced and the masking default becomes
removable. So these rules push payloads into models, then pin the contract:

  no-typeddict      TypedDict validates nothing at runtime — use a BaseModel.
  no-cast           `cast()` asserts a type instead of proving one.
  extra-forbid      Every model forbids unknown fields. No exceptions: a schema
                    change must be followed by a code change, and a query names
                    its columns (`SELECT a, b`), so no unmodelled key can arrive.
  masking-default   Optional ⇒ `T | None = None`. Required ⇒ no default. Any
                    other default (`""`, `0`, `[]`, `"task"`) is one more
                    spelling of "absent" and hides a missing key.
  opaque-annotation `Any`/`object` at ANY nesting depth — `Sequence[Any]`,
                    `list[dict[str, Any]]` — is the untyped dict one level down.
                    The *container* is fine when subscripted with concrete types:
                    `Mapping[str, str]` and `dict[VectorKey, SearchResult]`
                    (runtime keys, typed values) both stay legal.
  dict-return       A function returning a raw dict — including a CONCRETE
                    `dict[str, str]`, and including an unannotated
                    `return {...}` — leaks a payload across a boundary. Stricter
                    than `opaque-annotation`, and return-position only.
  splat             `f(**model.model_dump())` unpacks the model back into an
                    untyped dict and skips per-field checking at the one site
                    that pins the contract. Logging is the only exemption
                    (`log.bind(**ctx)` — arbitrary context by design).
  select-star       `SELECT *` re-introduces an unmodelled shape the code never
                    declared, which is exactly what `extra-forbid` assumes away.
  secret-repr       A credential/PII field without `repr=False` leaks the value
                    into any log line that reprs the model.

MODEL RECOGNITION ROTS SILENTLY — register your own base
---------------------------------------------------------
A class only gets the field-level rules (extra-forbid, masking-default,
secret-repr, opaque-annotation on fields) when it subclasses a base this checker
recognises — the ``MODEL_BASES`` set below. That set names SYMBOLS by string, so
it rots silently: rename a base, or introduce your own project base
(``class AppModel(BaseModel)`` and then have everything extend ``AppModel``), and
every such model becomes INVISIBLE to the checker. Zero findings then reads as
clean when it actually means "nothing was inspected" — the exact silent-rot this
tool exists to prevent. Register each project base with a (repeatable)
``--model-base NAME`` so its subclasses are checked:

    python checkers/pydantic_contract.py --model-base AppModel src/

The default set stays ``{BaseModel, BaseSettings, RootModel}``; ``--model-base``
only ADDS to it.

CONTRACT
--------
Prints one ``path: [rule] symbol — message`` finding per violation to stdout and
**exits 1 when there is any finding**, so wiring it straight into prek/pre-commit
surfaces the findings and fails the commit — no baseline artifact required.

Keys are rule + enclosing symbol + field name and NEVER a line number, so an
unrelated edit does not churn a baseline; the repeatable rules carry a per-symbol
ordinal so a second occurrence is a distinct finding rather than a duplicate key.

The checker owns NO state: it writes no baseline, no JSON, no cache. If you want
the regression-only ratchet, compose it with ``regression-gates/baseline_gate.py``
and pass ``--exit-zero`` — that harness reads a non-zero exit as "the checker
crashed" and fails closed, so the flag is required there and nowhere else.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/pydantic_contract.py src/
    python checkers/pydantic_contract.py --select no-cast,extra-forbid src/
    python checkers/pydantic_contract.py --model-base AppModel src/  # register a base

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline pydantic_baseline.txt -- \
        python checkers/pydantic_contract.py --exit-zero src/

PARSER NOTE — pin this hook's interpreter
-----------------------------------------
This checker parses with the ``ast`` of the interpreter it RUNS ON, so an
interpreter older than the project's silently fails to parse new syntax (PEP 695
``type X = int``, ``async def run[**P, T]``). Any
Python-AST-based gate shares this: unpinned, bandit's env resolved to 3.11 and
logged "syntax error while parsing AST" for 25 files, SKIPPED them, and **still
exited success** — a security gate silently not scanning. Vulture's resolved to
3.11 and dropped 35 files from dead-code analysis the same way.

So this checker does NOT fail open. An unparsable file exits **2** (a tool error,
distinct from 1 = findings) even under ``--exit-zero``, because a file it could
not read is a file it did not check.

Pin ``language_version`` on THIS hook — a repo-level ``default_language_version``
does NOT reach a hook's isolated env. Gates with their own non-Python parser
(ruff, jscpd, tree-sitter-based tools) are immune and need no pin.
````

### `hook.py`

````text
Reminder hook for brunofaust-python-style skill.

Fires PreToolUse on Edit|Write. If target file is Python, emit a one-time
non-blocking reminder per Claude Code session so Sonnet remembers the skill's
conventions WITHOUT flooding the transcript with the same message on every edit.

This is the HIGH-SIGNAL trigger: it fires at the moment Python is actually being
written, which is when the skill most needs loading. It dedups on its OWN flag
(`claude-all-brunofaust-py-edit-<session_id>`), independent of the SessionStart
loader (`python-style-skill-loader.py`) — so the reminder still lands on the
first real `.py` edit even when the session-start nudge already fired (that early
nudge is easy to forget dozens of turns before any Python work). At most one
session-start reminder + one first-edit reminder per session; they never pile
onto the same edit.

Session detection: Claude Code passes `session_id` in the hook input JSON.
We flag `<tmpdir>/claude-all-brunofaust-py-edit-<session_id>` on each emit and
re-fire at most **once per hour** — the flag's mtime is the last-fired time, so a
long session keeps the conventions fresh instead of being reminded only once.
Edits within the hour see a fresh flag and exit silently.
````
