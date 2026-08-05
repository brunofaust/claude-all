---
name: mock-drift-sweep
description: >-
  Sweep and update every mock/fake/stub after changing a function signature, return shape, exception
  type, or import path — so green tests don't hide a broken production seam. Use when: changing a
  function/method signature or return type, renaming or moving a module, changing what an external SDK
  or DB call returns or raises, "the tests pass but prod is broken", "update the mocks", migrating an
  SDK, or reviewing a diff that touches a widely-mocked boundary. Mock drift is the #1 silent failure:
  agents are excellent at making tests pass — they satisfy the fixture you gave them, not the
  production system. A mock left asserting the old shape is a green test over a broken contract.
disable-model-invocation: false
user-invocable: true
---

# mock-drift-sweep — keep mocks honest after a change

> **The lesson.** Almost every high-severity bug traces to a test, mock, or config that agreed with
> the code instead of with reality. When you change a signature, return shape, exception, or import
> path, the *implementation* and its *callers* get updated — but the mocks that stood in for that seam
> keep asserting the OLD shape. Tests stay green; production breaks. Treat every change to a mocked
> boundary as a mock-update obligation in the SAME change.

## When this triggers

Any of these is a mock-drift risk — sweep before you call the change done:

- A function/method **signature** changed (new/removed/reordered/renamed param).
- A **return shape** changed (new key, renamed field, tuple→object, sync→async).
- A type migrated from an untyped **`dict` to a model** (Pydantic / dataclass), or a model was
  **frozen**. A mock still returning a dict literal where production now returns a model is a GREEN
  test over a broken seam — the mock accepts `["key"]` / `.get()` / `**` forever, production doesn't.
- The **exception type** a call raises changed (especially real SDK/DB exceptions).
- A module **moved or was renamed** (every `patch("old.path.thing")` now patches nothing).
- You **migrated an SDK/client library** (the new client's methods, return objects, and exception
  hierarchy differ — and the mocks were written against the old one).

## The sweep

1. **Find every mock of the changed seam.** Search for all the forms — they hide in different places:
   - patch strings: `patch("pkg.mod.thing")`, `@patch.object(Cls, "method")`, `mocker.patch(...)`
   - constructed fakes: `Mock()`, `MagicMock()`, `AsyncMock()`, `return_value=`, `side_effect=`
   - hand-written fakes / stub classes / fixture factories
   - mock servers / recorded fixtures (responses, VCR cassettes, MSW handlers, WireMock)
   - config objects built by hand in tests
   ```bash
   # the symbol's name, and the dotted patch-target of its module
   grep -rn "thing\|patch(.*old\.path" tests/
   ```
   For a **`dict`→model** migration the seam is the *loader*, not the type — sweep three targets:
   any mock whose `return_value` / `side_effect` is a **dict literal** (or a list of them), any
   **fixture that hand-builds a dict** for that payload, and every **`patch()` target for the changed
   loader**. Consumers rarely name the type, so grep the loader's call sites rather than the type.
2. **Update each to the NEW shape in the same change.** Return the new fields, raise the new exception
   type, match the new signature. A mock that no longer mirrors reality is worse than no mock.
3. **Prefer spec'd mocks over bare ones.** `autospec=True` / `create_autospec` / `spec=Cls` /
   `Mock(spec=...)` make the mock reject calls and attributes the real object doesn't have — so the
   NEXT signature change fails the test loudly instead of silently. A bare `Mock()` accepts anything,
   which is exactly how drift goes unnoticed. (`pygrep`'s `python-check-mock-methods` catches a few
   classic mistakes, e.g. `assert_called_once` typo'd as an attribute — keep it on.)
4. **Build config/data mocks FROM the real model, not by hand.** Instantiate the real
   dataclass/Pydantic model/TypedDict and mutate it, rather than hand-writing a dict that drifts from
   the schema. When the model gains a required field, a hand-built dict silently omits it; a real
   instance won't construct.
5. **Verify the patch TARGETS still resolve — and know what doesn't catch it.**
   `pytest --collect-only` imports test modules, so it catches a `patch("dead.import.path")` whose
   *module* is gone (ImportError). It does **NOT** resolve the patch *string's attribute*: `patch(
   "live.module.renamed_func")` collects fine and only fails (or worse, silently no-ops with
   `create=True`) at run time. After a rename, grep the old symbol name across `tests/` and run the
   affected tests, don't just collect.

## Gate it: `checkers/`

This skill ships four AST checkers under `checkers/` that turn the sweep above
into an enforced gate instead of a habit to remember. All four are pure AST
parses (no import of the code under test, no DB, fast enough for every
commit) and share `mock_drift_common.py`'s dotted-target resolution — every
one of them is conservative by design: silence over a false positive, because
a noisy hook gets disabled and then protects nothing.

- **`patch_target_exists.py`** — a `patch("dotted.path")` string whose target
  does not exist anywhere in the scanned tree (the #1 mock-drift class: a
  rename/move/delete leaves the string "working" because `patch()` happily
  creates the attribute it can't find).
- **`async_mock_target.py`** — an `async def` patched with a plain
  `MagicMock`/`Mock` instead of `AsyncMock`/`autospec=True` — never awaited,
  never fails, so the test passes whether or not the code actually awaits it.
- **`mock_assert_signature.py`** — `mock.assert_called_with(...)` /
  `assert_any_call(...)` asserting more positional args than the real
  (patch-bound) signature accepts, or a keyword that isn't a real parameter
  name. Regression-only (ships a `--baseline`/`--check` JSON ratchet — expect
  real findings on first run against an existing codebase).
- **`unspecced_model_mock.py`** — a `patch()`-replaced Pydantic `BaseModel`
  subclass stood in for by an unspecced `MagicMock`/`Mock`/`AsyncMock` (the gap
  next to a real model construction, which already fails loudly on drift when
  every model sets `extra="forbid"`). Also regression-only — the noisiest rule
  in the family by design.

```bash
uv run python checkers/patch_target_exists.py tests src/myapp
uv run python checkers/async_mock_target.py tests src/myapp
uv run python checkers/mock_assert_signature.py tests src/myapp --check
uv run python checkers/unspecced_model_mock.py tests src/myapp --check
```

Wire each as a prek/pre-commit hook (`language = "system"`) scoped to
`tests/` + your source dir; pin `language_version` on each hook, since these
parse with the interpreter's own `ast` module and an older interpreter
silently fails to parse newer syntax it wasn't built to understand.

## The deeper fix: one real-dependency test per contract

A fully-mocked test of a DB or SDK call validates nothing about SQL syntax, the real schema, or the
SDK's real exception types — it only checks that your code calls the mock the way you told the mock to
expect. For each external contract, keep **at least one test against the real engine** (a real
Postgres in a container, a localstack/SDK sandbox), pinned to the **production version**. Mocks make
the other 95% fast; the one real test is what catches the drift mocks can't see.

Pairs with `adversarial-verification` (revert-and-rerun to prove a test actually fails when the code
is wrong), `test-author` / `react-testing` (write the tests), and `test-runner` (run them).
