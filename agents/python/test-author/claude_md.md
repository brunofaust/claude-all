### Command dispatch — writing unit tests → `test-author` (Sonnet)

| Goal | Agent |
|---|---|
| "write tests for X", "add unit tests", "increase/raise coverage", "hit the coverage gate" | `test-author` |
| RUN an existing suite / report pass-fail / coverage number | `test-runner` (haiku) |

Anti-patterns:
- Writing unit tests in the main (Opus) session — test authoring is Sonnet-class judgment work
  (edge cases, fixtures, assertions). Delegate to `test-author`; don't burn Opus on it.
- Asking `test-runner` to "write the missing tests" — it only RUNS tests. Authoring → `test-author`.

`test-author` is coverage-driven (measures gaps via `pytest --cov`, writes behavior-asserting tests to
the gate), follows the `brunofaust-python-style` test conventions (factories, DI not module-patching,
tests mirror src/), and NEVER coverage-games or edits source to fudge the number. It pairs with
`test-runner` (author writes → runner verifies) and defers real bugs to `debugger` and source
refactors to `python-refactorer`.
