## React correctness — react-correctness skill

When writing or reviewing React components/hooks (`*.tsx` / `*.jsx`), apply the `react-correctness` skill (correctness/architecture — distinct from the Vercel `react-best-practices` perf skill).

- `useEffect` is for syncing with an external system only — **NOT** derived state, data transforms, reset-on-prop-change (use `key={id}`), or notifying parents.
- State location, lowest first: local → lift to parent → URL → server-state lib (React Query/RSC) → context (low-frequency reads only) → global store.
- Default to **no** memoization (React 19 compiler); memo only a measured hot path. Never use the array `index` as a key for reorderable lists.
- React 19: `use()`, `useOptimistic`, `useActionState`, `useTransition`, ref-as-prop (no `forwardRef`).

Treat `react-hooks/exhaustive-deps` as a CI error for new code. Verify behavior with `react-testing`.
