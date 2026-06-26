## React correctness — `react-correctness` skill
Key rules: `useEffect` only for external system sync (not derived state, not reset-on-prop-change — use `key={id}`); state lowest first (local → lift → URL → server-state → context → global); no memoization by default (React 19 compiler); never array `index` as key for reorderable lists.
