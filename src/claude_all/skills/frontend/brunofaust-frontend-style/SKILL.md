---
name: brunofaust-frontend-style
description: >-
  Modern React/frontend standards — correctness, performance, composition, testing, security, a11y and
  view transitions in ONE entry point. Use when: writing or reviewing React components and hooks,
  reaching for useEffect, deciding where state lives, memoizing, building compound components or a
  reusable component API, writing frontend tests (RTL/Vitest/Playwright/MSW), rendering user content or
  handling tokens/env vars in the browser, setting a CSP, auditing UI for accessibility, or animating
  route/state changes. Enforce for all frontend work: new components, refactors, bug fixes, perf passes,
  test authoring, and pre-deploy UI review.
disable-model-invocation: false
user-invocable: true
---

# Frontend Style Guide (condensed)

The frontend counterpart to `brunofaust-python-style`: **one entry point** for React and browser work,
with each dimension in its own reference. Read the matching reference BEFORE deep work in that area.

**Minimalism applies here too.** The default is the simplest component that satisfies the CURRENT
requirement — no speculative abstraction, no prop-drilling ceremony, no wrapper that only forwards.
→ [`brunofaust-python-style`'s `yagni.md`](../../python/brunofaust-python-style/references/yagni.md)
(the principle is language-agnostic; the target shapes there translate directly to components).

## Core principles

1. **`useEffect` is for syncing with an EXTERNAL system** — not derived state, not
   reset-on-prop-change (use `key={id}`), not "run on mount". Most effects you reach for are a bug.
2. **State lives at the lowest level that works** — local → lift → URL → server-state → context →
   global. Reaching for global state first is the most common architectural mistake.
3. **Don't memoize by default** (React 19 compiler). Reach for `useMemo`/`useCallback`/`memo` when a
   profiler shows a real cost, not preemptively.
4. **Never render unsanitized HTML**; scheme-allowlist every URL; sessions in `HttpOnly; Secure;
   SameSite` cookies, never `localStorage`.
5. **Test behaviour, not implementation** — `getByRole` first, `userEvent` over `fireEvent`, mock at
   the network layer (MSW), no snapshot tests.
6. **Accessibility is not a later pass** — semantic elements, real labels, focus management, and
   keyboard paths are part of "done".

## Table of references

| If you are… | Read |
| --- | --- |
| Writing/reviewing components & hooks — `useEffect`, state location, derived state, stale closures, keys, React 19 (`use`, `useOptimistic`, `useActionState`, ref-as-prop) | [`references/react-correctness.md`](references/react-correctness.md) |
| Writing frontend tests — RTL query priority, `userEvent`, MSW, async assertions, `renderHook`, axe, Playwright, coverage per layer | [`references/react-testing.md`](references/react-testing.md) |
| Rendering user content, handling tokens/sessions/env vars, setting a CSP, embedding third-party scripts | [`references/web-security.md`](references/web-security.md) |
| Auditing a changed file before shipping (the judgment checklist `/ship` + `/ship-pr` run) | [`references/audit.md`](references/audit.md) |
| Reference hook config — a complete, commented `prek.toml` wiring repo hygiene + the tsc/eslint/prettier/knip/audit gates this skill assumes are running. Copy it to your repo root **and rename it to `prek.toml`** | [`prek.toml.example`](prek.toml.example) |
| **Performance** — memoization, bundle size, data fetching, Server Components, streaming | the **`vercel-react-best-practices`** skill *(vendored from Vercel — kept in place so upstream updates keep flowing; 75 rule files under its `rules/`)* |
| **Composition** — compound components, render props, context providers, flexible component APIs | the **`vercel-composition-patterns`** skill *(vendored)* |
| **Animation** — the View Transition API, `<ViewTransition>`, `addTransitionType`, Next.js integration | the **`vercel-react-view-transitions`** skill *(vendored)* |
| **Accessibility / UX review** — the Web Interface Guidelines checklist | the **`web-design-guidelines`** skill *(vendored)* |

**Why four are referenced, not folded.** Those skills are **vendored** — kept byte-identical to
upstream so `scripts/vendor_sync.py` can pull improvements (Vercel actively updates
`vercel-react-best-practices` for new React versions). Copying their bodies here would fork them permanently.
They stay installed alongside this skill (declared in `claude-all.json`, so installing this one
installs them), and this skill is the single entry point that routes to them.

## Quick rules — what NOT to do

- ❌ `useEffect` to compute derived state → compute during render.
- ❌ `useEffect` to reset state on prop change → `key={id}`.
- ❌ Array `index` as `key` for a reorderable/filterable list.
- ❌ Reaching for context/global state before trying local + lifting.
- ❌ Blanket `useMemo`/`useCallback`/`memo` "for performance" with no measurement.
- ❌ `dangerouslySetInnerHTML` on anything not DOMPurify-sanitized.
- ❌ A raw `href`/`src` from user data (allowlist the scheme — block `javascript:`/`data:`).
- ❌ Session tokens in `localStorage`/`sessionStorage`.
- ❌ A non-framework-prefixed env var in client code (only `NEXT_PUBLIC_*` / `VITE_*`).
- ❌ `getByTestId` when a role/label query works; `fireEvent` when `userEvent` works.
- ❌ Snapshot tests as the primary assertion.
- ❌ A `<div onClick>` where a `<button>` belongs.

## Before finalising a component

- [ ] No `useEffect` that isn't syncing with an external system
- [ ] State at the lowest level that works; no premature context/global
- [ ] Stable, identity-based `key`s (never array index on dynamic lists)
- [ ] No memoization without a measured reason
- [ ] User content sanitized; URLs scheme-allowlisted; no token in web storage
- [ ] Semantic elements + labels; keyboard path and focus handled
- [ ] Behaviour-asserting tests (role queries, `userEvent`, MSW) — not snapshots
- [ ] No speculative abstraction — a wrapper/prop/context that serves no present need is deleted
