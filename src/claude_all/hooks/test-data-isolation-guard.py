#!/usr/bin/env python3
"""Warn when a test file hard-codes a tenant/scope id (test-data isolation).

The recurring, high-severity mistake this catches: a test that reuses a
hard-coded tenant/scope id (``org_id=1``, ``tenant_id="acme"``) instead of
creating its own data. Shared or hard-coded ids make tests fight over the same
rows (flaky under xdist) and let a foreign key cross a tenant boundary — the bug
class that reaches production. The rule ("each test owns its own rows; dynamic
ids from a factory; FKs never cross tenants") is already written in the style
guide, but prose alone kept getting violated — so this is the checker.

Archetype: **guard**, but it only *speaks* when it detects the smell (silent
otherwise) and is **non-blocking** — it emits a Claude-facing reminder via
``additionalContext`` and always exits 0. Deduped per (session, file) so editing
one file repeatedly doesn't repeat the warning.

Detection is deliberately narrow to keep false positives near zero: it flags a
hard-coded LITERAL (number or quoted string) assigned to a known tenant/scope id
field. A value that references a fixture/variable/factory call
(``org_id=org.id``, ``org_id=make_org()``) is NOT a literal and never matches.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile

# Known tenant/scope id fields. A hard-coded literal for any of these in a test
# is the "shared/hard-coded id" smell the style guide forbids.
_TENANT_FIELDS = (
    "org_id",
    "organization_id",
    "tenant_id",
    "account_id",
    "customer_id",
    "workspace_id",
    "company_id",
    "group_id",
    "project_id",
    "project_key",
)
# field = <int literal> | <quoted string literal>   (NOT a variable / call)
_LITERAL_ASSIGN = re.compile(
    r"\b(" + "|".join(_TENANT_FIELDS) + r")\s*=\s*(\d+|[\"'][A-Za-z0-9_\-]+[\"'])"
)


def _is_test_file(path: str) -> bool:
    if not path.endswith(".py"):
        return False
    base = os.path.basename(path)
    return base.startswith("test_") or base.endswith("_test.py") or "/tests/" in path


def _new_content(tool_name: str, tool_input: dict) -> str:
    """The text being written/edited, across Write / Edit / MultiEdit shapes."""
    if tool_name == "Write":
        return str(tool_input.get("content", ""))
    if tool_name == "Edit":
        return str(tool_input.get("new_string", ""))
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if isinstance(edits, list):
            return "\n".join(str(e.get("new_string", "")) for e in edits if isinstance(e, dict))
    return ""


def _already_warned(session_id: str, path: str) -> bool:
    """True if we've already warned for this (session, file); records it if not."""
    key = hashlib.sha1(f"{session_id}:{path}".encode()).hexdigest()[:16]
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-test-tenant-{key}.flag")
    if os.path.exists(flag):
        return True
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(path[:200])
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — never break a turn

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    path = str(tool_input.get("file_path", ""))
    if not _is_test_file(path):
        return 0

    hits = _LITERAL_ASSIGN.findall(_new_content(tool_name, tool_input))
    if not hits:
        return 0  # no hard-coded tenant id — nothing to say

    if _already_warned(data.get("session_id") or "no-session", path):
        return 0

    fields = sorted({field for field, _ in hits})
    example = f"{hits[0][0]}={hits[0][1]}"
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    f"Test-data isolation: this test file hard-codes a tenant/scope id "
                    f"({example}; fields: {', '.join(fields)}). Each test must own its data — "
                    "use dynamic ids from a factory/DB, never hard-code or share ids across "
                    "tests, and keep every foreign key inside one tenant. Shared ids make tests "
                    "fight over the same rows (flaky under xdist) and let an FK cross a tenant "
                    "boundary. See the testing style guide's 'Test data isolation' rules. "
                    "If this literal is genuinely tenant-agnostic (e.g. an enum/status code, not "
                    "a scope id), ignore this."
                ),
            }
        },
        sys.stdout,
    )
    return 0  # advisory only — never block the edit


if __name__ == "__main__":
    sys.exit(main())
