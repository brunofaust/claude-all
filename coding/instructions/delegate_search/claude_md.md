### Command dispatch — broad codebase search → `Explore` (built-in)

| Pattern                                                                    | Agent     |
| -------------------------------------------------------------------------- | --------- |
| "where is X used", "how does Y work", "find all callers/usages/references" | `Explore` |
| Multi-repo / multi-directory sweeps to understand a codebase               | `Explore` |
| Iterative `grep -r` → read a file → `grep` again loops across many files   | `Explore` |

Anti-patterns:

- A multi-step "grep → open file → grep again" exploration loop in the main (Opus) session — that iteration is what burns Opus turns wandering the tree. Hand the QUESTION to `Explore` and act on the conclusion it returns.
- `Bash(grep -r ... | grep ...)` chained sweeps, broad `find`, or broad `rtk` searches whose purpose is "understand the codebase" — delegate to `Explore` (read-only; it reads excerpts and returns the conclusion, not file dumps).
- Re-deriving a map of a repo you already had `Explore` survey earlier — reuse its summary instead of re-searching.

Stay inline (do NOT delegate — delegating adds a round-trip for tiny output):

- A single targeted `grep pattern path/to/file`, or the built-in `Grep` tool for one known file/dir.
- `grep`-ing output you already have in the session.
- A one-shot lookup whose answer is a couple of lines.

Note: `Explore` is read-only and returns conclusions, not a faithful dump of every match. When you specifically need the EXACT matching lines preserved (a mechanical "give me every hit"), a scoped `grep -n ... | head` inline is fine — that is small output, not an exploration loop.
