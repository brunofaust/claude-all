## Research before building — `research-before-build` skill
Apply before writing any non-trivial new feature, module, or "feels-common" utility (auth, retries, parsing, pagination, caching, state machine, date/money math).

Reuse hierarchy: internal codebase (grep first) → Context7/vendor docs → `gh search` repos → package registries (npm/PyPI) → web. Decide: adopt/fork/wrap/build — check license, maintenance, supply-chain, size.
