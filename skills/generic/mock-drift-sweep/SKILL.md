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

## The deeper fix: one real-dependency test per contract

A fully-mocked test of a DB or SDK call validates nothing about SQL syntax, the real schema, or the
SDK's real exception types — it only checks that your code calls the mock the way you told the mock to
expect. For each external contract, keep **at least one test against the real engine** (a real
Postgres in a container, a localstack/SDK sandbox), pinned to the **production version**. Mocks make
the other 95% fast; the one real test is what catches the drift mocks can't see.

Pairs with `adversarial-verification` (revert-and-rerun to prove a test actually fails when the code
is wrong), `test-author` / `react-testing` (write the tests), and `test-runner` (run them).
