---
name: subagent-prompting
description: >-
  How to write a self-contained one-shot subagent dispatch prompt. Use BEFORE
  invoking the Agent / Task tool. The subagent has ZERO memory of the parent
  conversation — every input, success criterion, and refuse-condition must be
  inlined. Use for: dispatching a research task, parallel investigation,
  delegating mechanical work to a haiku agent, fanning out to multiple
  general-purpose agents. Synthesized from obra/superpowers subagent-driven-
  development + dispatching-parallel-agents + kadaliao worker-prompt-craft +
  undeadlist/claude-code-agents.
disable-model-invocation: false
user-invocable: true
---

# Subagent prompting

> **"Pretend the subagent woke up in a new universe with zero context. Give it everything."**

A subagent dispatch fails when the prompt assumes parent-session context that doesn't transfer. Output is then vague / wrong-shape / dispatch-the-same-thing-again. This skill is the dispatch-prompt checklist.

## Self-containment rule (the most-violated)

Subagent has NO memory of:
- This conversation's prior turns
- The user's preferences set hours ago
- Files referenced "above" or "in the plan"
- TodoWrite items currently in flight
- Previous subagent outputs (unless you paste them in)

If you wrote "see X" / "as discussed" / "the plan file" / "you already know that" — the subagent doesn't. Inline it or fail.

## The 10-point dispatch-prompt checklist

Fill in EVERY field before sending. Skip one → dispatch usually misfires.

```
1. GOAL
   One sentence, imperative, testable.
   ✓ "List the top 10 slowest pytest tests in the busydone repo and their durations."
   ✗ "Look into pytest performance."

2. INPUTS
   Every path, ID, env var, value pasted inline.
   No "see above" / "as discussed".

3. OUTPUT SCHEMA
   Exact shape — JSON keys, markdown sections, status enum.
   The subagent will pattern-match this; vagueness here = vague output.

4. SUCCESS CRITERIA
   Observable. "Returns a 10-row markdown table" beats "good output".

5. TIME / TOKEN BUDGET
   Hard ceiling. "≤ 5 minutes" / "≤ 800 words" / "≤ 20 tool calls".
   Agent should REFUSE with BLOCKED rather than overshoot.

6. REFUSE-CONDITIONS
   When to return BLOCKED instead of guessing.
   ✓ "If pytest isn't installed, return BLOCKED with the install command."

7. NO-PARENT-MEMORY REMINDER
   "You have NO memory of this conversation. Everything you need is in this prompt."

8. TOOL ALLOW / DENY LIST
   Especially for destructive ops.
   ✓ "Read, Glob, Grep, Bash (read-only). Never Edit/Write/MultiEdit."

9. RETURN-ONLY-SUMMARY
   Final message ≤ N lines. No narration of intermediate steps.
   ✓ "Return ONLY the Markdown synthesis at the end. No preamble."

10. VERBATIM EVIDENCE RULE
    Quote exit codes / error lines / row counts. Don't paraphrase.
    ✓ "Quote the failing assertion message exactly, including the file:line prefix."
```

## Return-status enum

Standardize subagent return values so parent can route automatically:

| Status | Meaning | Parent action |
|---|---|---|
| `DONE` | All criteria met, evidence quoted | Use the result |
| `DONE_WITH_CONCERNS` | Criteria met but caveats — list them | Use + verify caveats |
| `NEEDS_CONTEXT` | Subagent hit ambiguity not resolvable from inputs | Add missing inputs, re-dispatch |
| `BLOCKED` | Precondition missing (auth, env, tool) | Fix precondition, re-dispatch |
| `OVER_BUDGET` | Time/token budget exhausted | Re-scope smaller or bigger budget |

Always paste the enum + meanings in the dispatch prompt.

## Parallel dispatch — independence precondition

Before fanning out N subagents in parallel, verify ALL of:

1. **No shared writable state** — none write to the same file / table / queue.
2. **No sequential dependency** — subagent B doesn't need subagent A's output.
3. **No race-prone resource** — none mutate the same Lambda / deploy / branch.

If any fail → serial dispatch, not parallel.

For research tasks (read-only), parallel is almost always safe. For deploys, refactors, schema migrations — almost never.

## Output ceiling — the return-only-summary rule

Subagent transcripts can balloon: tool call → response → tool call → response × N. The PARENT only sees the FINAL message. Be explicit:

```
**Output format:** Return ONLY the Markdown synthesis at the end. No preamble.
No "I will now..." / "Let me start by...". The first character of your final
response must be the first character of the deliverable.
```

This stops the subagent from narrating intermediate work in the final return.

## Three anti-patterns + rewrites

### Anti-pattern 1 — Open-ended scope

❌ "Review the codebase for issues."

✅ "Read `src/busydone/handlers/dispatcher.py` and identify the top 5 functions exceeding 50 lines. Return a Markdown table: function name, line count, recommended refactor (extract / split / leave). ≤ 200 words."

### Anti-pattern 2 — Assumed context

❌ "Apply the changes we discussed to the auth module."

✅ "In `src/busydone/auth/jwt.py`, replace the `os.getenv('SECRET_KEY')` call on line 42 with `settings.jwt_secret_key` (already imported from `.settings`). Run `uv run ruff check src/busydone/auth/jwt.py` after the edit and report the diff + ruff status."

### Anti-pattern 3 — Multiple writers to same file in parallel

❌ Dispatch 3 subagents in parallel to "refactor `models.py`, `schemas.py`, `routes.py` — all import from each other".

✅ Either: (a) one subagent does all three; (b) one subagent per file BUT only after pasting the cross-references inline so each can refactor independently.

## Self-check before dispatch

Re-read your dispatch prompt and ask:

- [ ] If I deleted this conversation and only had this prompt, could a fresh agent do the work?
- [ ] Is the output schema specific enough that I can grep / parse the result?
- [ ] Did I cap the budget?
- [ ] Did I name destructive ops in the deny list?
- [ ] Did I demand verbatim evidence on critical claims?

Any "no" → fix before sending.

## Hand-offs

- After dispatch: apply `adversarial-verification` to the subagent's output before trusting it.
- If subagents repeatedly return `NEEDS_CONTEXT`: your prompts are missing inputs — re-read this skill, not the subagent.
- For parallel fan-out specifically: `superpowers-extended-cc:dispatching-parallel-agents` skill has the independence-test recipe.

## Inspiration

- [obra/superpowers — subagent-driven-development](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md)
- [obra/superpowers — dispatching-parallel-agents](https://github.com/obra/superpowers/blob/main/skills/dispatching-parallel-agents/SKILL.md)
- [undeadlist/claude-code-agents](https://github.com/undeadlist/claude-code-agents)
- [kadaliao/claude-code-skills-collection — worker-prompt-craft](https://github.com/kadaliao/claude-code-skills-collection)
