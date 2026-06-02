## React / frontend testing — react-testing skill

When writing or reviewing frontend tests (React Testing Library / Vitest / Jest / Playwright-CT), apply the `react-testing` skill.

- Query priority: `getByRole` → `getByLabelText` → text → `getByTestId` (last resort). `userEvent` over `fireEvent`.
- Mock at the **network layer with MSW** — don't stub `fetch`/`axios`. Async via `findBy*`/`waitFor`, never arbitrary sleeps.
- **Avoid component snapshot tests** — assert observable behavior. Don't assert render counts or mock React hooks (refactor instead). a11y via `axe`.
- Per-layer coverage: utils ≥ 90% / hooks ≥ 85% / presentational ≥ 80% / container ≥ 70%.

Frontend counterpart to `test-author` (Python). Run suites via the `test-runner` agent.
