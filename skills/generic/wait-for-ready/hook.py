#!/usr/bin/env python3
"""PreToolUse hook (ships with the `wait-for-ready` skill).

Fires on the `Bash` tool. Catches two friction patterns:

- A long fixed `sleep N` (N >= threshold) in the main session — it blocks the
  session for the whole duration.
- The `… && sleep N && curl …` (or `while/until … sleep … curl/pg_isready …`)
  readiness loop — a fixed delay is flaky: too short and the probe fails, too
  long and you wait for nothing.

On match it emits a NON-BLOCKING reminder (exit 0 + JSON `additionalContext`, so
it is NOT rendered as a hook error) pointing at the `wait-for-ready` skill, which
polls until the service/container is actually healthy (timeout + interval). This
hook is installed alongside that skill, so the skill it points to is always present.

Bypass: set CC_ALLOW_SLEEP=1 to skip the check.
"""

from __future__ import annotations

import json
import os
import re
import sys

# Long fixed sleeps (seconds) are worth flagging on their own.
SLEEP_THRESHOLD_SECONDS = 5.0

_SLEEP_RE = re.compile(r"\bsleep\s+(\d+(?:\.\d+)?)")
# Readiness probes that, when paired with any sleep, indicate a poll-by-delay loop.
_PROBE_RE = re.compile(
    r"\b(curl|wget|nc\s+-z|pg_isready|psql|redis-cli\s+ping|grpc_health_probe|"
    r"docker\s+(inspect|ps)[^\n]*health|wait-for-it|healthcheck|until\b|while\b)",
    re.IGNORECASE,
)


def _nudge(message: str) -> int:
    """Emit a non-error reminder into Claude's context, then allow the tool."""
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}},
        sys.stdout,
    )
    return 0


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name") != "Bash":
        return 0

    if os.environ.get("CC_ALLOW_SLEEP"):
        return 0  # explicit bypass

    command: str = data.get("tool_input", {}).get("command", "")
    if not command:
        return 0

    sleeps = [float(m) for m in _SLEEP_RE.findall(command)]
    if not sleeps:
        return 0

    has_probe = bool(_PROBE_RE.search(command))
    long_sleep = any(s >= SLEEP_THRESHOLD_SECONDS for s in sleeps)
    if not (has_probe or long_sleep):
        return 0  # short, standalone sleep — fine

    if has_probe:
        reason = "a fixed `sleep` paired with a readiness probe (poll-by-delay)"
    else:
        reason = f"a blocking `sleep {max(sleeps):g}` in the main session"
    return _nudge(
        f"[wait-for-ready] Detected {reason}. Fixed-delay waits stall the session and are flaky "
        "(too short → probe fails; too long → wasted wait). Use the `wait-for-ready` skill to poll "
        "the URL/container until it is actually healthy (with a timeout + interval) instead of a "
        "fixed `sleep`. For a genuinely long wait, run it in the background rather than blocking. "
        "Set CC_ALLOW_SLEEP=1 to bypass when a literal fixed sleep is truly intended."
    )


if __name__ == "__main__":
    sys.exit(main())
