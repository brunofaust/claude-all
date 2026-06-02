---
name: react-correctness
description: >-
  React component & hook correctness — the architecture/logic patterns that prevent bugs (distinct
  from the Vercel react-best-practices skill, which is about performance). Use when: writing or
  reviewing components/hooks, reaching for useEffect, deciding where state should live, using React 19
  features (use, useOptimistic, useActionState, ref-as-prop), choosing memoization, or structuring
  container vs presentational components. Covers "useEffect — when NOT to use it", the state-location
  decision tree, derived-state vs effects, the stale-closure trap, keys for dynamic lists, the
  default-don't-memoize stance, and React 19 hooks. Pairs with react-best-practices (perf),
  react-testing (verify), and web-security (safe rendering).
disable-model-invocation: false
user-invocable: true
---

# React Correctness

Most React bugs come from misusing `useEffect`, putting state in the wrong place, or stale closures.
This skill is the correctness layer; for render/bundle performance see `react-best-practices`.

## `useEffect` — when NOT to use it

`useEffect` is for **synchronizing with an external system** (DOM API, subscription, non-React widget,
network on mount). It is **not** for:

- **Derived state** — compute during render: `const full = `${first} ${last}``. Don't store it in
  state + sync it in an effect.
- **Transforming data for render** — filter/sort/map in render (memoize only if proven hot).
- **Resetting state when a prop changes** — give the component a `key={id}` so React remounts it;
  don't `useEffect(() => setX(initial), [id])`.
- **Notifying the parent of a change** — call the parent's handler in the event handler, not in an
  effect watching state.
- **App-wide singletons** (init a client once) — do it at module scope / a provider, not per-mount.

Legit uses: subscribing to a store/event, syncing to `document.title`/`localStorage`, a non-React
widget, fetching on mount (or better: a data-fetching lib / Server Component). **Always return a
cleanup** for subscriptions/timers. Treat `react-hooks/exhaustive-deps` as a CI error for new code.

## State-location decision tree

Put state at the **lowest** level that works; lifting/sharing has a cost.

1. **Local** (`useState`/`useReducer`) — only one component cares. Default.
1. **Lift to the nearest common parent** — two siblings need it. Pass down via props.
1. **URL** (search params / route) — it should survive reload / be shareable / bookmarkable
   (filters, tabs, pagination).
1. **Server-state library** (React Query / SWR / RSC) — it's server data (caching, revalidation,
   dedup). Don't hand-roll fetch-in-effect for this.
1. **Context** — low-frequency, broadly-read values (theme, auth user, locale). ⚠️ Context
   **re-renders every consumer on change** — never put high-frequency state in it.
1. **Global store** (Zustand/Redux) — genuinely cross-cutting, high-frequency, or complex shared state.

Reach for `useReducer` (over multiple `useState`) once you have 3+ related values or conditional
transitions.

## Stale closures

An effect/callback captures the values from the render it was created in. If deps are wrong, it reads
stale values. Fixes: (a) add the value to the dependency array, (b) use the `setState(prev => …)`
updater form, or (c) a `useRef` for a mutable latest-value you intentionally don't want to re-subscribe on.

## Don't memoize by default

- With the React 19 compiler, manual `useMemo`/`useCallback`/`React.memo` is mostly unnecessary —
  **default to none.** Premature memoization adds complexity and its own bugs (wrong deps).
- Memoize only a **measured** hot path, or to keep a stable reference a dependency/`memo` child needs.

## Keys

- Stable, unique keys for lists. **Never use the array index for reorderable/insertable lists** —
  state attaches to the wrong row on reorder. Index is fine only for static, append-only lists.

## React 19 essentials

- **`use(promise)` / `use(context)`** — unwrap a promise (with Suspense) or read context conditionally.
- **`useActionState`** — form action state + pending, pairs with Server Actions.
- **`useOptimistic`** — optimistic UI that auto-reconciles when the real result lands.
- **`useTransition` / `startTransition`** — mark non-urgent updates so input stays responsive.
- **ref as a prop** — `forwardRef` is no longer needed; accept `ref` directly in props.

## Container / presentational split

Keep data-fetching/orchestration (container) separate from rendering (presentational, props-only,
easily testable). Presentational components shouldn't fetch or know about stores.

## Anti-patterns

| Anti-pattern | Why | Use instead |
| --- | --- | --- |
| `useEffect` to derive/transform state | extra render, drift, bugs | compute in render |
| `useEffect(() => setX(init), [id])` to reset | race + extra render | `key={id}` remount |
| high-frequency value in Context | re-renders all consumers | local/lifted state or a store |
| `index` as key on a reorderable list | state binds to wrong item | stable id |
| memoizing everything | complexity + stale-dep bugs | default none; memo measured hot paths |
| fetch-in-`useEffect` for server data | races, no cache | React Query/SWR or RSC |

## Enforcement

- ESLint `react-hooks/rules-of-hooks` (error) + `react-hooks/exhaustive-deps` (error in CI for new
  code). `eslint-plugin-react` for keys + common mistakes. Verify behavior with `react-testing`.

## References (track for updates)

- Adapted from [affaan-m/ECC](https://github.com/affaan-m/ECC) — [`rules/react/`](https://github.com/affaan-m/ECC/tree/main/rules/react) (`coding-style.md`, `hooks.md`, `patterns.md`).
- [react.dev — You Might Not Need an Effect](https://react.dev/learn/you-might-not-need-an-effect) · [Rules of Hooks](https://react.dev/reference/rules/rules-of-hooks)
- [React 19 release notes](https://react.dev/blog/2024/12/05/react-19) (`use`, `useActionState`, `useOptimistic`, ref-as-prop).
