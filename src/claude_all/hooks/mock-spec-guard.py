#!/usr/bin/env python3
"""PreToolUse hook — steer test mocks toward `spec`/`autospec` (kill mock drift).

Fires on `Edit`/`Write`/`MultiEdit` of a **Python test file** and scans the
content being written for **bare** `MagicMock()` / `AsyncMock()` — mocks created
without `spec=` / `spec_set=` / `autospec=` / `wraps=`.

Mock drift is the #1 silent-failure class: a bare mock accepts ANY attribute and
ANY call signature, so when the real function's signature, return shape, or module
path changes, the test keeps passing against a mock that no longer resembles
reality. `spec=RealClass` / `autospec=True` (or `create_autospec`) makes the mock
track the real object, so the same refactor fails the test loudly instead.

This is a **non-blocking reminder** (exit 0 + `additionalContext`), addressed to
Claude — it never blocks the edit and never fatigues the user with prompts. It
stays silent unless the anti-pattern is actually present in the new content, and
only on test files. Bare mocks are not *always* wrong (an identity-only stand-in
is fine) — the reminder asks Claude to confirm each is intentional.

`create_autospec(...)` is the good pattern and is never flagged.

## Configuration

- `CLAUDE_ALL_MOCK_SPEC_OK=1` — opt out; the hook returns 0 always.

Exit codes: 0 always (non-blocking). Any malformed input / unexpected error → 0.
"""

from __future__ import annotations

import json
import os
import re
import sys

__all__ = ["main"]

# Mock classes that default to auto-speccing everything (the drift-prone ones).
_MOCK_CALL_RE: re.Pattern[str] = re.compile(
    r"\b(MagicMock|AsyncMock|NonCallableMagicMock|NonCallableMock)\s*\("
)
# Keywords that make a mock track a real object — presence means "not bare".
_SPEC_KW_RE: re.Pattern[str] = re.compile(r"\b(spec|spec_set|autospec|wraps)\s*=")

_ARG_SCAN_LIMIT = 600  # bound the balanced-paren scan per call


def _remind(message: str) -> int:
    """Emit a non-blocking reminder into Claude's context, then allow the tool."""
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": message,
            }
        },
        sys.stdout,
    )
    return 0


def _is_python_test_file(file_path: str) -> bool:
    """True if ``file_path`` is a Python test file (test_*.py / *_test.py / under tests/)."""
    norm = file_path.replace("\\", "/")
    if not norm.endswith(".py"):
        return False
    base = norm.rsplit("/", 1)[-1]
    if base.startswith("test_") or base.endswith("_test.py"):
        return True
    return "/tests/" in norm or norm.startswith("tests/")


def _new_text(tool_name: str, tool_input: dict[str, object]) -> str:
    """Extract the text being written by this Edit/Write/MultiEdit call."""
    if tool_name == "Write":
        content = tool_input.get("content", "")
        return content if isinstance(content, str) else ""
    if tool_name == "Edit":
        new = tool_input.get("new_string", "")
        return new if isinstance(new, str) else ""
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if not isinstance(edits, list):
            return ""
        parts: list[str] = []
        for e in edits:
            if isinstance(e, dict):
                ns = e.get("new_string", "")
                if isinstance(ns, str):
                    parts.append(ns)
        return "\n".join(parts)
    return ""


def _call_args(text: str, open_paren_idx: int) -> str:
    """Return the argument substring of a call starting at ``open_paren_idx``.

    Walks from the opening paren tracking depth, skipping quoted strings so
    parens inside string literals don't confuse the balance. Bounded by
    ``_ARG_SCAN_LIMIT`` characters.

    Args:
        text: The full source text.
        open_paren_idx: Index of the "(" that opens the call.

    Returns:
        The text between the parens (best-effort, possibly truncated).
    """
    depth = 0
    quote: str | None = None
    out: list[str] = []
    end = min(len(text), open_paren_idx + _ARG_SCAN_LIMIT)
    for i in range(open_paren_idx, end):
        ch = text[i]
        if quote is not None:
            if ch == quote:
                quote = None
            out.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "(":
            depth += 1
            if depth == 1:
                continue  # don't include the opening paren
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        out.append(ch)
    return "".join(out)


def _count_bare_mocks(text: str) -> int:
    """Count MagicMock/AsyncMock instantiations that lack a spec/autospec/wraps."""
    count = 0
    for m in _MOCK_CALL_RE.finditer(text):
        args = _call_args(text, m.end() - 1)
        if not _SPEC_KW_RE.search(args):
            count += 1
    return count


def main() -> int:
    if os.environ.get("CLAUDE_ALL_MOCK_SPEC_OK") == "1":
        return 0

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name not in {"Edit", "Write", "MultiEdit"}:
        return 0

    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path", "")
    if not isinstance(file_path, str) or not _is_python_test_file(file_path):
        return 0

    n = _count_bare_mocks(_new_text(tool_name, tool_input))
    if n == 0:
        return 0

    base = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    noun = "bare mock" if n == 1 else "bare mocks"
    return _remind(
        f"[mock-spec-guard] {n} {noun} without spec/autospec in `{base}`. Mock "
        "drift is the #1 silent-failure class — a bare MagicMock/AsyncMock accepts "
        "any attribute and any call signature, so a change to the real function's "
        "signature or return shape won't fail this test. Prefer `autospec=True` / "
        "`spec=RealClass` (or `create_autospec`), and build config/settings mocks "
        "from the real model. Identity-only stand-ins are fine — confirm each is "
        "intentional."
    )


if __name__ == "__main__":
    sys.exit(main())
