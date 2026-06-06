## lean-ctx — context compression layer (active via shell hook)

lean-ctx is installed and active. Shell hooks auto-compress command output — no manual prefix needed.
For explicit compression: `lean-ctx -c "command"`. MCP tools (`ctx_read`, `ctx_search`, `ctx_shell`)
are available for AI-native file access with aggressive compression.

### Precedence (same as before, lean-ctx fills the gaps)

1. **Built-in tools first** — `Read`, `Glob`, `Grep` beat any shell call for filesystem ops.
2. **Specialized agents second** — `git-runner`, `gh-runner`, `aws-lambda-deployer`, `terraform-deployer`,
   `test-runner`, `code-quality`, `docker-runner`, `frontend-builder` all benefit from lean-ctx hooks automatically.
3. **lean-ctx MCP tools third** — use `ctx_shell("command")` when shelling out and the MCP is available.
4. **Raw Bash last** — lean-ctx hooks still compress output, but prefer the above.

### MCP tools (when lean-ctx MCP is active)

| Goal | Use |
|------|-----|
| Read a file | `ctx_read(path, mode="auto")` — 10 modes incl. `map`, `signatures`, `diff` |
| Search code | `ctx_search(pattern, path)` |
| Run a command | `ctx_shell("command")` |
| Directory listing | `ctx_tree(path, depth)` |

### Meta commands

```bash
lean-ctx gain              # token savings dashboard
lean-ctx gain --history    # session-by-session breakdown
lean-ctx doctor            # verify installation + hook status
lean-ctx off / lean-ctx on # temporarily disable / re-enable compression
```
