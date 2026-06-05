______________________________________________________________________

## name: requirements-ears description: > Convert a business idea, feature request, or change into precise, testable acceptance criteria using EARS notation (Easy Approach to Requirements Syntax). Use BEFORE implementing a feature or refactor when the requester wants to specify behavior at the business level without writing code or tests. Triggers: "what should this do", "write acceptance criteria", "spec this feature", "turn this into requirements", or handing a brainstorm output into implementation. Pairs with brainstorming (which decides WHAT to build) by pinning HOW each behavior must work. Output feeds directly into tests. user-invocable: true

# Requirements as EARS Acceptance Criteria

## Purpose

The requester specifies behavior at the business level. This skill converts that
into unambiguous, testable statements. Each statement becomes a test; the
implementation is written to pass it. The requester never writes code or tests —
only decides what correct behavior is.

This closes the "trust-then-verify gap": plausible-looking code that doesn't handle
edge cases. An EARS criterion is a spec the implementation cannot weasel around,
because it maps 1:1 to a deterministic test.

## When to use

- After a brainstorm has decided WHAT to build, to pin HOW it must behave.
- Before implementing any `core/` capability or handler workflow.
- When a bug report needs to become a regression criterion.

Do NOT use for: five-line fixes, throwaway scripts, or exploratory spikes where
behavior is still unknown. EARS is for behavior you can commit to.

## The five EARS patterns

Every requirement fits one of these. Use the exact keywords — they are what make
the statement testable.

1. **Ubiquitous** (always true, no trigger):
    `THE SYSTEM SHALL <response>.`

    > THE SYSTEM SHALL store every embedding request with a traceable source id.

1. **Event-driven** (`WHEN` a trigger occurs):
    `WHEN <trigger> THE SYSTEM SHALL <response>.`

    > WHEN a ticket has an empty description THE SYSTEM SHALL skip it and log the reason.

1. **State-driven** (`WHILE` in a state):
    `WHILE <state> THE SYSTEM SHALL <response>.`

    > WHILE the Bedrock endpoint is unavailable THE SYSTEM SHALL queue requests for retry.

1. **Unwanted behavior** (`IF`/`THEN` — errors, edge cases):
    `IF <unwanted condition> THEN THE SYSTEM SHALL <response>.`

    > IF input text exceeds the model max tokens THEN THE SYSTEM SHALL split it into chunks.

1. **Optional feature** (`WHERE` a feature is present):
    `WHERE <feature is enabled> THE SYSTEM SHALL <response>.`

    > WHERE cross-customer training is opted in THE SYSTEM SHALL include the request in the training set.

Complex behavior combines them:
`WHILE <state>, WHEN <trigger>, THE SYSTEM SHALL <response>.`

## Process

When invoked with a feature or business intent:

1. **Restate the intent** in one business sentence. Confirm scope.
1. **Enumerate behaviors** — happy path, every edge case, every failure mode. Ask the
    requester about gaps; do not invent business rules. The most commonly missed are
    the unwanted-behavior (`IF`/`THEN`) cases — probe for them.
1. **Write each as an EARS statement.** One behavior per statement. No "and".
1. **Make each measurable.** Replace vague words. "Fast" → "within 2 seconds".
    "Handle errors gracefully" → a specific `IF`/`THEN`. If a statement can't be turned
    into a pass/fail test, it isn't done — sharpen it.
1. **Group** by capability (which `core/` subject owns it) so criteria map to the code.
1. **Hand off**: the criteria become the test spec. State explicitly that
    implementation will be written to pass these and nothing merges until each is green.

## Quality bar

A good EARS set is:

- **Unambiguous** — one reading only. No "should probably", no "etc".
- **Testable** — each maps to a single assertion.
- **Complete on edges** — empty input, oversize input, downstream failure, concurrent
    calls, opt-out/opt-in states all covered.
- **Business-level** — describes outcomes, not implementation. "SHALL retry 3 times"
    is fine; "SHALL use a for-loop" is not.

## Example: end-to-end

Business intent: "MyApp should generate embeddings for ticket text."

Criteria produced:

- WHEN ticket text is provided THE SYSTEM SHALL return a vector embedding.
- IF the text is empty THEN THE SYSTEM SHALL reject the request with a clear error.
- IF the text exceeds the model's max input tokens THEN THE SYSTEM SHALL split it into chunks and embed each.
- WHILE the embedding provider is unavailable THE SYSTEM SHALL queue the request for retry rather than dropping it.
- THE SYSTEM SHALL record the source id of every embedded text for audit traceability.

These five map directly to five tests on `core/` embeddings. The requester decided all
five behaviors; they wrote no code and no tests.

## Handoff line

End every invocation with: "These criteria are the spec. Implementation will be written
to pass each one as a test, and CI will block merge until all are green. Approve or
adjust the criteria before I implement."
