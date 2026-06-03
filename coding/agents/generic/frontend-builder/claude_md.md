### Command dispatch — frontend builds → `frontend-builder` (Haiku)

| Command | Agent |
|---|---|
| `npm/pnpm/yarn run build`, `vite build`, `next build`, `astro build`, `nuxt build`, `tsc -b`, `webpack`/`rollup`/`esbuild` | `frontend-builder` |

Anti-patterns:

- `Bash(npm run build)` / `Bash(vite build)` / `Bash(next build)` — bundler output (chunk-size tables, transformed-module counts, asset lists, sourcemap warnings) is hundreds of lines and burns Opus/Sonnet tokens. Delegate to `frontend-builder` and act on the bundle-size summary or the error chain.
- Don't start a dev server here — that's a long-running process (use tmux/background), not a one-shot build.

Note: `frontend-builder` detects the build tool from `package.json`/config, runs it, and returns success + bundle size + top chunks, or a tight error chain. Never starts a dev server, never edits config.
