# Enforcement Hook Matrix

Every rule in this skill has an enforcement mechanism. If a rule has no enforcement, it is aspirational, not required.

## Matrix

| Rule                                  | Enforced by                                                        | Bypass                                     |
| ------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------ |
| Pydantic on boundaries                | mypy strict + `pydantic_contract.py` (regression baseline) — the eight rules below. **Supersedes** `skill_enforcer.py` rule `no_dict_any_in_signatures`, which only saw *parameters*; the checker also covers **returns** and **model fields**. Retire the old rule rather than running both. | none — see the per-rule rows below |
| Frozen dataclasses internally         | `skill_enforcer.py` rule `dataclass_must_be_frozen`                | `# skill-allow: mutable-dataclass` comment |
| No raw boto3 outside core/aws/        | ruff `banned-api` (TID251)                                         | `[per-file-ignores]` in pyproject.toml     |
| No raw httpx outside integrations/    | ruff `banned-api` (TID251)                                         | `[per-file-ignores]` in pyproject.toml     |
| No silent except                      | ruff `BLE001`, `skill_enforcer.py` rule `no_debug_in_except`       | `# noqa: BLE001` with explanation          |
| Public names only (`__all__` not `_`) | vulture + `skill_enforcer.py` rule `no_module_underscore_names`    | add to `__all__`                           |
| Thin lambda handlers (\<20 stmts)     | `skill_enforcer.py` rule `thin_lambda_handlers`                    | none — split into feature service          |
| Dockerfile per resource               | `skill_enforcer.py` rule `resource_mandatory_files`                | none                                       |
| CLAUDE.md per resource                | `skill_enforcer.py` rule `resource_mandatory_files`                | none                                       |
| Layer dependency direction            | `import-linter`                                                    | refactor required                          |
| CHANGELOG updated                     | `precommit_changelog.sh` + GitHub Action                           | `skip-changelog` label                     |
| Docs updated with code                | `precommit_docs.sh` + GitHub Action                                | `skip-docs` label                          |
| Resource CLAUDE.md updated            | `precommit_resource_docs.sh` + GitHub Action                       | none                                       |
| Conventional commits                  | commitizen `commit-msg` hook                                       | none                                       |
| Docstring coverage 100%               | `interrogate` (`fail-under = 100`)                                 | none — carve out the noise case explicitly (`ignore-magic`, `ignore-setters`, `ignore-overloaded-functions`, `ignore-init-module`), never lower the floor |
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
| Single alembic head + id ≤ 32 chars   | `check_alembic_heads.py` (AST, no DB)                              | merge heads into one linear chain          |
| CI-reserved env vars hard-set in tests| pygrep `no-ci-env-setdefault` (`GITHUB_*`/`RUNNER_*`/`CI`)         | assign directly, never `os.environ.setdefault` |
| Unit tier is ONE flat mirror of src   | `flat_test_mirror.py` rules `not-flat`, `non-test-file`, `grab-bag`. **Supersedes** `skill_enforcer.py` rule `test_mirrors_src`, which assumed a NESTED tree — retire the old rule rather than running both. | none — `src/<pkg>/a/b.py` ⇒ `tests/unit/test_a_b.py` |
| No `*_extra` / `*_coverage` grab-bags | `flat_test_mirror.py` rule `grab-bag`                              | none — add the case to the module's own mirror |
| Async target patched with an async-aware double | `checkers/async_mock_target.py` rule `async-mock` — a `patch("dotted")` / `patch.object(Cls, "m")` whose target resolves to an `async def` **in the scanned tree** and supplies none of `AsyncMock` / `autospec=True` / `new_callable=AsyncMock`. A bare `MagicMock` is never awaited, so the test passes whether or not the code awaits — a real sync-`def`-fed-to-`async with` shipped that way. Resolution is conservative: an unresolvable target (module not scanned, re-exported name, ambiguous suffix, non-simple `patch.object` object) stays **silent**, so there are no false positives. Pass BOTH `src` and `tests` so targets resolve. | none — use an async-aware double, and pair the seam with one real-invocation test (see `references/testing.md`, "A `MagicMock` on an async target…") |
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
| No `@dataclass`                       | `model_contract.py` rule `no-dataclass` — a dataclass validates nothing; use Pydantic. | `--allow-dataclass PATHSUFFIX=ClassName` (repeatable) + a `dataclasses`-import exempt list. Each survivor carries a proven STRUCTURAL reason (holds a live object / DI container / TYPE_CHECKING import / `dataclasses.replace()` target); the `(path, name)` key can't drift to another class |
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

## Wiring the pydantic contract gate

`pydantic_contract.py` prints findings and always exits 0; the ratchet comes from
wrapping it in `baseline_gate.py` (NEW findings fail, baselined ones pass, STALE
ones also fail so the count only goes down).

### 0. Copy the two scripts into the project

Both ship with the skills — copy them next to this project's other gates, into
`scripts/` (the convention the rest of this file uses):

| Copy from                                                       | To                          |
| --------------------------------------------------------------- | --------------------------- |
| `brunofaust-python-style/checkers/pydantic_contract.py`         | `scripts/pydantic_contract.py` |
| `regression-gates/baseline_gate.py`                             | `scripts/baseline_gate.py`  |

### 1. Seed the baseline once, and commit it

```bash
python scripts/baseline_gate.py --baseline pydantic_baseline.txt --update -- \
    python scripts/pydantic_contract.py --exit-zero src/
git add pydantic_baseline.txt   # an uncommitted baseline = no gate
```

Wiring it WITHOUT the ratchet is simpler and needs neither script — the checker
exits 1 on any finding all by itself, so prek prints them and fails the commit:

```bash
python scripts/pydantic_contract.py src/          # exits 1 if anything is found
```

Use the bare form on a greenfield (or once the baseline reaches zero); use the
ratchet when adopting the gate on a codebase that already has findings.

Roll out **regression-only**: today's debt is grandfathered, tomorrow's is
blocked. Then ratchet to zero — burn one notch per PR, deleting the fixed line
from `pydantic_baseline.txt` (a stale entry fails the gate, so the file cannot
rot). Never `SKIP=pydantic-contract` and never `--no-verify`; if a finding is
truly not fixable now, baseline it with a ticket comment:

```text
# TICK-1: myapp/integrations/acme/payload.py — polymorphic vendor body, model it in Q3
src/myapp/integrations/acme/payload.py: [opaque-annotation] parse(body) — parameter is opaque (dict[..., Any]) …
```

### 2. Enforce in prek AND in CI — the same command in both places

A gate that only runs pre-commit is bypassable with `--no-verify`, so the CI job
runs the identical line:

```toml
[[repos]]
repo = "local"
hooks = [{
  id = "pydantic-contract",
  name = "🐍 skill · Pydantic data contract (regression baseline)",
  # `--exit-zero` is REQUIRED here and nowhere else: baseline_gate reads a non-zero
  # exit as "the checker crashed" and fails closed. Without the flag, every run with
  # findings would look like a tool error. (Wiring the checker WITHOUT the ratchet?
  # Drop both baseline_gate and --exit-zero — it exits 1 on findings by itself.)
  entry = "python scripts/baseline_gate.py --baseline pydantic_baseline.txt -- python scripts/pydantic_contract.py --exit-zero src/",
  language = "system",
  # Pin the interpreter. This checker parses with the `ast` of the Python it RUNS
  # ON, so an env older than the project silently fails to parse new syntax (PEP
  # 695 `type X = int`, PEP 758 `except A, B:`) — see the interpreter-pin rule in
  # the `prek` skill. A repo-level `default_language_version` does NOT reach a
  # hook's isolated env. The checker exits 2 rather than skipping, so a wrong pin
  # fails loudly instead of silently reporting clean.
  language_version = "3.14",  # or your project's Python
  pass_filenames = false,
  always_run = true,
  files = "\\.py$"
}]
```

`pass_filenames = false` + `always_run = true` are load-bearing: `baseline_gate`
diffs the FULL finding set against the baseline, so feeding it only the staged
files would make every un-fed baseline entry look STALE and fail the gate.

`.pre-commit-config.yaml` is the same hook, one level nested:

```yaml
- repo: local
  hooks:
      - id: pydantic-contract
        name: 🐍 skill · Pydantic data contract (regression baseline)
        entry: python scripts/baseline_gate.py --baseline pydantic_baseline.txt -- python scripts/pydantic_contract.py src/
        language: system
        pass_filenames: false
        always_run: true
```

`pass_filenames = false` + `always_run = true` are load-bearing: the checker
scans `src/` whole. Fed only the staged files it would report zero findings for
untouched paths, and every baselined entry would look STALE.

Adopt rules incrementally with `--select` (one gate per rule, one baseline each)
when the full set is too big to land at once:

```bash
python scripts/pydantic_contract.py --select no-cast,extra-forbid src/
```

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
