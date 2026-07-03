# Visibility Convention — `__all__` over `_` prefix

**Rule:** Module-level names never start with `_`. Use `__all__` to declare public API.

## Why

Vulture, ruff (`F841`), pyright (`reportUnusedVariable`), and IDE unused-variable checks all **ignore** underscore-prefixed names. Using `_` for "private" silences every dead-code check at module scope.

## Note on overlap with Naming conventions table

The SKILL.md Naming conventions table lists "Private methods / Private attributes — leading underscore". That convention applies to **class-scope** members (`self._client`, `def _validate(self): ...`). For **module-level** names — module-level variables, module-level functions — this section overrides: use `__all__` instead of `_`.

## Anti-pattern — module-level `_` prefix

```python
# BAD: invisible to vulture, ruff, pyright
_dynamodb_resource: Any = None
_comprehend_client: Any = None

def _dynamodb(): ...
def _table(): ...

def write_item(...): ...  # public by convention only
```

## Correct — `__all__` declares public API

```python
# GOOD: visible to dead-code tools, public API explicit
__all__ = ["write_item", "write_items", "read_item"]

dynamodb_resource: Any = None
comprehend_client: Any = None

def get_dynamodb(): ...
def get_table(): ...

def write_item(...): ...
```

## Exception — keep `_` only for

- Unused tuple/function args: `_x, y = get_pos()`
- Loop throwaways: `for _ in range(10):`
- Instance attributes inside classes: `self._client` (acceptable inside class scope; vulture handles classes differently)
- `__init__.py` shadow imports that re-export: `from .client import JiraClient as _JiraClient` — rare, prefer `__all__` re-export instead.

Module-level functions and module-level variables: never `_` prefix.

## Migration recipe

```bash
rg -n "^_[a-z]" src --type py
```

For each match, decide:

- If it's actually used outside the module → drop the `_`, add to `__all__`
- If it's module-internal helper → drop the `_`, omit from `__all__` (still visible to dead-code tools)
- If it's truly unused → delete it

## Enforcement

`__all__` is a checker-enforced contract, not just a convention — a missing or stale
`__all__` is a build failure, not a style nit:

- Vulture in pre-commit (`--min-confidence 80`).
- `skill_enforcer.py` rule `no_module_underscore_names` — flags module-level `Name` nodes starting with `_` (not `__`). See `references/enforcement.md`.
- **`__all__` import-contract gate** (two prek hooks): a **pyright** pass + an **AST**
  pass that verify every name listed in `__all__` actually exists and that each
  module's public API is declared via `__all__`. A name exported but undefined (or
  public-but-absent from `__all__`) fails the gate.
