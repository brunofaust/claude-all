## lean-ctx — ctx MCP tools (active)
ALWAYS prefer lean-ctx MCP tools: `ctx_read` over Read/cat, `ctx_shell` over Bash, `ctx_search` over Grep, `ctx_tree` over ls/find. Native Edit/StrReplace unchanged; use `ctx_edit` only if Edit requires a prior Read that's unavailable.

| Tool | Purpose |
|---|---|
| `ctx_read(path, mode)` | Read file — modes: auto/full/map/signatures/diff/lines:N-M |
| `ctx_search(pattern, path)` | Code search with compact results |
| `ctx_shell("cmd")` | Run command with output compression |
| `ctx_tree(path, depth)` | Compact directory listing |

`lean-ctx gain` • `lean-ctx doctor` • `lean-ctx off/on`
