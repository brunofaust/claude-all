### `Explore` (built-in) — broad codebase search
| "where is X used", "how does Y work", "find all callers", multi-file sweeps, iterative grep loops | `Explore` |
⛔ Multi-step grep→read→grep loop in main session; chained `Bash(grep -r ... | grep ...)` for conceptual queries
✓ OK inline: single targeted `Grep`/grep on a known file/dir; 1-shot lookup with a few lines of output
