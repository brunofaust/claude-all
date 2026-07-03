## Tool dispatch — token efficiency

Before running a Bash command, check whether a built-in tool or an installed agent fits the job. Bash spawns are slow and their output bloats the main context.

### Filesystem exploration — use built-in tools, not Bash

| Goal | Use | Not |
|---|---|---|
| Find files by pattern | `Glob` (`*.py`, `**/test_*.ts`) | `Bash(find ...)`, `Bash(ls ...)` |
| Search text across files | `Grep` (regex, multi-file) | `Bash(grep -rn ...)` |
| Read a file | `Read` (with line range) | `Bash(cat file \| head -N)`, `Bash(sed -n ...)` |
| List a single directory (rare) | `Bash(ls dir)` is OK when you need permissions/size | — |

Only fall back to Bash for filesystem when the built-in can't express the query — piped commands across grep/awk, comparing two outputs, etc.

### Semantic search — prefer RAG plugins/MCPs over `Grep`

If the project has any of these installed, query them BEFORE falling back to `Grep`:

- **`code-review-graph`** — incremental codebase knowledge graph. Better than grep for "where is X used", "what depends on Y", "show me the auth flow". `code-review-graph query "..."`, `code-review-graph context <symbol>`.
- **`claude-mem`** — persistent cross-session memory of prior findings / decisions / debugging notes (`mcp__plugin_claude-mem_mcp-search__*`).
- **`mcp-search` corpora** — semantic search across the whole repo (`mcp__mcp-search__search`, `smart_search`, `query_corpus`).
- **`context7`** MCP — fresh library docs instead of guessing from training data.

Grep stays right for exact-string searches, known regex, tight loops. RAG wins for conceptual queries, cross-cutting concerns, "where does X happen", historical context.

### Self-check before raw Bash with `aws` / `psql` / `terraform`

Before ANY `Bash(aws ...)`, `Bash(psql ...)`, `Bash(terraform ...)`, `Bash(make tf-*)`, `Bash(make *lambda*)`:

1. Is there an agent for this command class? → DELEGATE.
2. Is the work multi-service (touches > 1 AWS service in one turn)? → `e2e-scenario-runner`.
3. Am I bypassing because a previous agent call failed? → RE-INVOKE the agent after the precondition is fixed; don't improvise.

If you can't justify why you're not delegating, you're wrong — delegate.
