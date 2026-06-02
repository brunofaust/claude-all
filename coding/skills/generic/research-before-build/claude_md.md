## Research before building — research-before-build skill

Before writing any non-trivial new feature, module, library, or "feels-common" utility (auth, retries, parsing, pagination, caching, a state machine, date/money math), apply the `research-before-build` skill.

- Walk the reuse hierarchy: **internal codebase** (grep first) → **Context7** / vendor docs → **`gh search`** repos/code for an 80%-solution → package registries (npm/PyPI/crates) → web.
- Decide deliberately: adopt / fork / wrap / build — checking license, maintenance, supply-chain, and size.
- Record a one-line research note (what exists, what we reuse vs build, why).

Reuse beats generation on both tokens and reliability. Net-new is the last option, not the first.
