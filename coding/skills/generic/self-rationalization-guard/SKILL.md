______________________________________________________________________

## name: self-rationalization-guard description: >- Behavioral guard — detects when an agent is writing explanations / restating constraints / pre-emptively surrendering instead of executing the task. Fires when the agent emits >2 sentences before any tool call on an actionable request. Pairs with `adversarial-verification` (output-side discipline). Synthesized from obra/superpowers writing-skills + verification-before- completion + kadaliao/claude-code-skills-collection. disable-model-invocation: false user-invocable: true

# Self-rationalization guard

> **"Stop explaining. Run the command. Quote the output."**

Detects the seven most common AI execution-avoidance patterns and forces a redirect to action.

## When this skill fires

Trigger: the agent has emitted **more than 2 sentences** before ANY tool call on a task that explicitly asked for work to be done. (Skill explanation / clarifying questions are exempt — but a clarifying question must be one sentence + an actual question, not three paragraphs of hedging.)

## The 7 behavioral signals

Detect any of these in your OWN response. Restart if found.

### 1. Explaining instead of executing

Trigger phrases:

- "Let me describe what would happen if I ran…"
- "The approach here would be to…"
- "We need to first understand…"

Fix: **stop. Run the command. Show the output.**

### 2. Restating constraints

Trigger phrases:

- "Given that we cannot X, the answer is…"
- "Since we don't have access to Y…"
- "Because the framework restricts Z…"

Fix: **name the line of code / docs / rule that imposes the constraint, OR drop the constraint and try.** A constraint you can't cite isn't real.

### 3. Pre-emptive surrender

Trigger phrases:

- "This is too ambiguous to proceed without clarification."
- "I'd need more context before I can…"
- "Without knowing X, Y, Z, I can't say…"

Fix: **one tool call to resolve the ambiguity.** Read the file. List the directory. Query the DB. Then proceed.

### 4. Spirit-vs-letter dodge

Trigger phrases:

- "I followed the intent even though I skipped the step."
- "The spirit of the rule is X, so technically…"
- "It's about the principle, not the ritual."

Fix: **skipping the step IS skipping the rule.** Run the step or call out that you intentionally skipped it.

### 5. Retroactive scope shrink

Trigger phrases (after hitting friction):

- "The task actually only needs…"
- "We can simplify by skipping…"
- "Actually X is enough for now."

Fix: **the task is what was asked, not what's convenient now.** If scope MUST shrink, name the blocker explicitly.

### 6. False-equivalence substitution

Trigger phrases:

- "Manual testing achieves the same thing."
- "Code review is equivalent to running it."
- "Visual inspection of the diff is enough."

Fix: **run the actual test.** Manual ≠ tested. Inspection ≠ verified. Compile ≠ works.

### 7. Authority deflection

Trigger phrases:

- "The user probably meant…"
- "The convention is to…"
- "Industry best practice says…"

Fix: **either ask the user, or quote the source.** Unsourced authority is invented authority.

## Redirection prompts (paste back to yourself)

When a signal fires, paste one of these to re-orient:

1. **"Stop explaining. Run the command. Quote the output."**
1. **"You stated a constraint — name the line of code or rule that imposes it, or drop it."**
1. **"If you used the word 'should', delete the sentence and try again with evidence."**

## Restart contract

When a signal fires:

1. Discard the current draft response (don't send it).
1. Emit ONE tool call that advances the task.
1. THEN write the response, with the tool's output quoted as evidence.

Exception: signals 3 (pre-emptive surrender) and 7 (authority deflection) may legitimately require asking the user. But the question must be ONE sentence, name the EXACT decision needed, and offer 2-3 concrete options.

## Bad clarifying-question shape

❌ "I'd need to know more about your requirements, including the data shape, expected scale, and downstream consumers, before I can recommend an approach. Could you provide…"

## Good clarifying-question shape

✅ "Postgres or DynamoDB? (Postgres = stronger consistency + joins; DDB = scale + cost.)"

## Anti-patterns

- ❌ Wrapping every action in 3 paragraphs of context (the action gets lost).
- ❌ Listing risks / caveats / preconditions instead of trying.
- ❌ "I'll start by analyzing…" then 200 words later still no tool call.
- ❌ Treating uncertainty as a stop condition instead of a reason to probe.

## When NOT to apply this skill

- The task IS explanation (user asked "explain X"). Skill doesn't fire on explainers.
- The task IS design/brainstorming (no execution expected). Use `brainstorming` skill instead.
- The user explicitly said "don't run anything, just describe…".

## Hand-offs

- After redirecting yourself: apply `adversarial-verification` to whatever output you produce.
- If the rationalization is specifically AVOIDING a test: hand to `test-driven-development` skill.

## Inspiration

- [obra/superpowers — writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)
- [obra/superpowers — verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md)
- [kadaliao/claude-code-skills-collection — self-rationalization-guard](https://github.com/kadaliao/claude-code-skills-collection)
