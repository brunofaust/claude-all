## Subagent prompting — write self-contained dispatch prompts
Subagent has ZERO memory of this conversation. Fill before dispatching: (1) Goal, (2) Inputs inline, (3) Output schema, (4) Success criteria, (5) Time/token budget, (6) Refuse-conditions, (7) No-parent-memory reminder, (8) Tool allow/deny, (9) Return summary ≤ N lines, (10) Verbatim evidence rule.

If you wrote "see X" / "as discussed" / "the plan file" → subagent doesn't know. Inline it.
