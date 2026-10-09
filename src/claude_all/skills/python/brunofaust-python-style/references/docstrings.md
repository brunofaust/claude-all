# Docstrings and comments — optional, bounded

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Who reads them

Docstrings and comments are read mostly by **AI models**, not by people browsing an API
reference. A model already sees the signature, the type hints and the code. What it cannot
recover from those is **intent and non-obvious constraints**: why the code is shaped this way,
which incident a check prevents, and what must not be "simplified". Google-style
`Args:` / `Returns:` / `Raises:` sections mostly repeat the signature. They cost context on
every read and drift away from the code.

So:

- **Optional.** No docstring-coverage floor (`interrogate` is not used), and ruff `D` / `DOC`
  rules are not selected. A missing docstring is never a finding.
- **Bounded.** When present, a docstring or comment has a **size budget** (below), and oversize
  is a finding. Long prose belongs in a reference doc or the PR, not on the symbol.
- **No required format.** No Google sections, no `Args:` restating typed parameters.

### What to write when you write one

- One or two sentences on **why** or **what must stay true**. Don't restate the name or the types.
- Name the incident or measurement that justifies a non-obvious line (`# strict rejects "1"
  from DynamoDB N — cast here`).
- Never narrate the code (`# loop over items`) or leave changelog notes (`# changed in PR 12`).

```python
# GOOD — states the constraint a reader (human or model) can't infer
async def lock_org_secrets(org_id: PositiveId) -> AsyncIterator[None]:
    """Distributed lock: Parameter Store has no conditional put, and Lambda scales across containers."""


# BAD — restates the signature, costs context, drifts
async def lock_org_secrets(org_id: PositiveId) -> AsyncIterator[None]:
    """
    Lock org secrets.

    Args:
        org_id: The org id.

    Returns:
        An async iterator.
    """
```

### Size budget (enforced)

`checkers/docstring_budget.py` (stdlib only) measures raw characters per symbol. Configure it in
`pyproject.toml`; the defaults are shown:

```toml
[tool.docstring-budget]
class.docstring_max_chars = 150
class.docstring_code_ratio = 1.0     # docstring ≤ min(max_chars, ratio × code chars)
class.comments_max_chars = 150
class.comments_code_ratio = 0.5      # comments ≤ max(max_chars, ratio × code chars)
function.docstring_max_chars = 150
function.docstring_code_ratio = 1.0
function.comments_max_chars = 150
function.comments_code_ratio = 0.5
method.docstring_max_chars = 150
method.docstring_code_ratio = 1.0
method.comments_max_chars = 150
method.comments_code_ratio = 0.5
module.docstring_max_chars = 500
module.comments_max_chars = 150
module.comments_code_ratio = 0.5
```

- A docstring may never be longer than the code it documents (`ratio = 1.0`). A three-line
  function does not get a paragraph.
- Comments scale with the code (half of the code size), with a 150-char floor, so a large
  function can carry its incident notes.
- Each comment counts toward its innermost enclosing symbol. Nested code counts toward the
  parent's code size; nested docs do not.
- Exit 0 means clean, 1 means findings, 2 means error. Zero files, a bad config or a parse
  failure is an error, never a pass. The checker prints `scanned=N`.

Wire it like the other checkers (see [`enforcement.md`](enforcement.md)). Exclude generated code
such as Alembic `versions/`.
