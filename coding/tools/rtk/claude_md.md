## RTK — token-killer wrapper (USE INSTEAD OF raw commands)

`rtk` wraps common dev commands and slashes their output token cost. `rtk discover --all --since 30` proves how many tokens are being burned on raw commands.

**Default rule:** any time you'd run one of the commands below, run the `rtk`-prefixed version instead. Same args, same semantics, much smaller output.

### Mandatory substitutions

| Native command | Use this instead | Why |
|---|---|---|
| `git log ...` | `rtk git log ...` | huge diff/log output → summarized |
| `git diff ...` | `rtk git diff ...` | same |
| `git blame ...` | `rtk git blame ...` | same |
| `grep -n ...` / `grep -rn ...` | `rtk grep ...` | grep output collapsed |
| `cat <file>` | `rtk read <file>` (or use the `Read` tool) | file content with smart truncation |
| `find <path> ...` | `rtk find ...` (or use the `Glob` tool) | trimmed result set |
| `ls <path>` | `rtk ls ...` (or use the `Glob` tool) | terse listing |
| `wc -l <file>` | `rtk wc -l <file>` | trivial passthrough but accounted |
| `aws ...` (any subcommand) | `rtk aws ...` | AWS JSON responses are massive |
| `make <target>` | `rtk make <target>` | wraps long build output |
| `terraform <cmd>` | `rtk terraform <cmd>` | massive plan / apply logs |
| `pytest ...` | `rtk pytest ...` | tracebacks + coverage compressed |
| `gh pr ...` / `gh issue ...` | `rtk gh ...` | PR / issue content trimmed |
| `npm run <script>` | `rtk npm run ...` | build/dev output trimmed |
| `npx eslint ...` | `rtk lint ...` | lint output grouped |
| `npx playwright ...` | `rtk playwright ...` | browser test output trimmed |
| `psql ...` / `PGPASSWORD=... psql ...` | `rtk psql ...` | rows + plan trimmed |

### Anti-patterns (NEVER do this when rtk is installed)

- ❌ `Bash(git log --oneline -50)` — use `rtk git log --oneline -50` OR delegate to `git-runner` agent (which already prefers rtk internally)
- ❌ `Bash(grep -rn 'foo' src/)` — use `Grep` tool, OR `rtk grep ...` if you must shell out
- ❌ `Bash(cat path/to/file | head -50)` — use `Read` tool with `offset` + `limit`, OR `rtk read`
- ❌ `Bash(find . -name '*.py')` — use `Glob "**/*.py"`, OR `rtk find`
- ❌ `Bash(AWS_PROFILE=X aws lambda invoke ...)` — use `rtk aws lambda invoke ...` OR delegate to `aws-lambda-deployer`
- ❌ `Bash(make tf-plan)` — use `rtk make tf-plan` OR delegate to `terraform-deployer`
- ❌ `Bash(PYTHONPATH=src .venv/bin/pytest ...)` — use `rtk pytest ...` OR delegate to `test-runner`

### Precedence

1. **Built-in tools first** — `Read`, `Glob`, `Grep` beat any rtk command for filesystem ops.
2. **Specialized agents second** — `git-runner`, `gh-runner`, `aws-lambda-deployer`, `terraform-deployer`, `test-runner`, `code-quality`, `docker-runner`, `frontend-builder` all internally prefer rtk where it helps.
3. **rtk wrapper third** — when shelling out is unavoidable, prefix with `rtk`.
4. **Raw command last** — only when rtk doesn't ship a wrapper for that command.

### Verifying adoption

Run periodically:

```bash
rtk discover --all --since 30
```

If the report shows thousands of "MISSED SAVINGS" lines for `git log`, `grep -n`, `cat`, `aws`, etc., the adoption is failing — re-read this block, escalate to invoking the matching agent, or wrap the call in `rtk`.

### Meta

```bash
rtk gain              # show your token-savings stats
rtk gain --history    # session-by-session breakdown
rtk proxy <cmd>       # bypass rtk wrappers if you genuinely need raw output
```
