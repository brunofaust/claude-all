# React / Frontend Testing

Test **behavior the user observes**, not implementation detail. A test that breaks when you refactor
internals (without changing behavior) is a bad test. RTL is designed around this — lean into it.

## Query priority (use the first that fits)

Pick queries the way a user / assistive tech finds elements. `getByTestId` is the **last** resort.

1. `getByRole` (+ `name`) — buttons, headings, inputs, links. The default.
1. `getByLabelText` — form fields.
1. `getByPlaceholderText` / `getByText` / `getByDisplayValue`.
1. `getByAltText` / `getByTitle`.
1. `getByTestId` — only when there's genuinely no accessible handle (and consider that a a11y smell).

`getBy*` (throws if missing) for presence, `queryBy*` for absence, `findBy*` (async) for things that
appear later.

## Interactions & async

- **`userEvent` over `fireEvent`** — it replays the real browser sequence (focus, keydown, input,
  change), catching bugs `fireEvent.change` misses. `const user = userEvent.setup()`.
- Async: `await screen.findByText(...)` / `await waitFor(() => expect(...))`. **Never** arbitrary
  `setTimeout`/`sleep` — wait for the assertion to become true.
- Don't fight `act()` warnings — they signal a real un-awaited state update. Fix the test's awaiting.

## Mock at the network layer, not the function

- Use **MSW** (Mock Service Worker) to intercept HTTP — your component uses its real `fetch`/client.
  Don't `vi.mock('axios')` / stub `fetch` directly; that couples tests to the data layer.
- Reset handlers between tests; override per-test for error/edge cases.

## What to test (and not)

- **Avoid component snapshot tests** — brittle, rubber-stamped on update, assert nothing meaningful.
  Assert specific visible output instead. (Snapshots are OK for small pure serializers.)
- **Don't assert on render counts** or internal state — assert what the user sees/does.
- **Don't mock React hooks** (`useState`/`useEffect`) — if you need to, the component wants refactoring
  (extract logic into a testable function/custom hook).
- Behavior-describing test names: `falls back to substring search when the API is unavailable`, not
  `test handleSearch`.

## Helpers

- A **custom `render`** that wraps providers (router, query client, theme, i18n) — every test uses it.
- **`renderHook`** for custom hooks; assert on returned values + `act()` around triggers.
- **a11y**: `expect(await axe(container)).toHaveNoViolations()` (`jest-axe`/`vitest-axe`) on key views.
- **Playwright component testing** (or E2E) for real-browser integration, visual, and cross-component
  flows RTL/jsdom can't model (layout, true focus, drag, file upload).

## Per-layer coverage targets

Coverage is a floor, not a goal — but set it per layer (deeper logic = higher bar):

| Layer | Target |
| --- | --- |
| utils / pure logic | ≥ 90% |
| hooks | ≥ 85% |
| presentational components | ≥ 80% |
| container / page components | ≥ 70% |

Cover branches and error paths, not just the happy line. (For Python services, see `test-author`.)

## Anti-patterns

| Anti-pattern | Why | Use instead |
| --- | --- | --- |
| `getByTestId` everywhere | bypasses accessibility, tests internals | role/label queries |
| `fireEvent.change(...)` | skips the real event sequence | `userEvent` |
| `vi.mock('fetch'/'axios')` | couples to data layer | MSW at network layer |
| component snapshot tests | brittle, meaningless diffs | assert specific output |
| asserting render count / internal state | implementation detail | assert observable behavior |
| mocking `useState`/`useEffect` | untestable design | extract logic, test that |
| `await sleep(500)` | flaky | `findBy*` / `waitFor` |

## Enforcement

- ESLint: `eslint-plugin-testing-library` (bans `fireEvent` misuse, container queries, etc.),
  `eslint-plugin-jest-dom`.
- Coverage thresholds per layer in `vitest.config`/`jest.config` (`coverageThreshold`), enforced in CI.
- `vitest-axe`/`jest-axe` in the a11y test suite; Playwright-CT in the integration job.

## References (track for updates)

- Adapted from [affaan-m/ECC](https://github.com/affaan-m/ECC) — [`rules/react/testing.md`](https://github.com/affaan-m/ECC/blob/main/rules/react/testing.md) and [`rules/common/testing.md`](https://github.com/affaan-m/ECC/blob/main/rules/common/testing.md).
- [Testing Library — query priority](https://testing-library.com/docs/queries/about/#priority) · [Guiding principles](https://testing-library.com/docs/guiding-principles/)
- [MSW (Mock Service Worker)](https://mswjs.io/) · [Playwright component testing](https://playwright.dev/docs/test-components)
