## Subagent prompting — write self-contained dispatch prompts

Subagent has ZERO memory of this conversation. Every input, success criterion, and refuse-condition must be inlined. Before calling Agent / Task tool, fill the 10-point checklist:

1. **Goal** — one imperative sentence
1. **Inputs** — all paths/IDs/values inline (no "see above")
1. **Output schema** — exact shape (JSON keys, sections, status enum)
1. **Success criteria** — observable
1. **Time / token budget** — hard ceiling
1. **Refuse-conditions** — when to return BLOCKED
1. **No-parent-memory reminder** — "you have no memory of this conversation"
1. **Tool allow/deny** — especially destructive ops
1. **Return-only-summary** — final message ≤ N lines, no preamble
1. **Verbatim evidence rule** — quote exit codes / errors / counts

Status enum: `DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED` / `OVER_BUDGET`.

Parallel dispatch ONLY when: no shared writable state + no sequential dependency + no race-prone resource. Otherwise serial.

If you wrote "see X" / "as discussed" / "the plan file" → subagent doesn't know what you mean. Inline it or fail.
