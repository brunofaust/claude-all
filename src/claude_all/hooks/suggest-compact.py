#!/usr/bin/env python3
"""PreToolUse hook — suggest /compact as the context window fills.

Fires on all tools (matcher ""). Prefers a TOKEN-aware signal: it reads the most
recent `message.usage` from the session transcript and estimates current context
occupancy as `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`
(what the model was actually sent on the last turn). When that crosses a threshold
it suggests /compact — and re-suggests as occupancy keeps climbing, resetting after
a compaction drops it back down. Token occupancy tracks context pressure far better
than a raw tool-call count, since one big tool result can consume the window.

Reading the transcript every call would be wasteful (matcher "" = every tool), so a
cheap per-session counter amortizes it: the token check runs every CHECK_EVERY calls.
If the transcript / usage is unavailable, it falls back to the old "suggest every
SUGGEST_EVERY tool calls" behavior so it still does something useful.

Uses exit 0 + JSON `systemMessage` so it surfaces as a normal warning, not a "hook
error". Tunables via env: CC_COMPACT_TOKEN_THRESHOLD, CC_COMPACT_SUGGEST_EVERY.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

# Token occupancy at which to suggest compaction (≈80% of a 200K window). Override
# via env for larger/smaller context models.
TOKEN_THRESHOLD = int(os.environ.get("CC_COMPACT_TOKEN_THRESHOLD", "160000"))
REWARN_STEP = 20000  # re-suggest after occupancy climbs this much past the last warning
CHECK_EVERY = 10  # only read the transcript every Nth tool call (amortize cost)
TAIL_BYTES = 262144  # read at most this much from the end of the transcript
SUGGEST_EVERY = 50  # fallback: suggest every N tool calls when no token signal


def state_path(kind: str, session_id: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"cc-compact-{kind}-{session_id}.txt")


def read_int(path: str) -> int:
    try:
        with open(path) as f:
            return int(f.read().strip() or "0")
    except (ValueError, OSError):
        return 0


def write_int(path: str, value: int) -> None:
    try:
        with open(path, "w") as f:
            f.write(str(value))
    except OSError:
        pass


def context_tokens(transcript_path: str) -> int | None:
    """Estimate current context occupancy from the last usage in the transcript tail.

    Args:
        transcript_path: Path to the session's JSONL transcript file.
    """
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read()
    except OSError:
        return None
    for line in reversed(tail.decode("utf-8", errors="ignore").splitlines()):
        line = line.strip()
        if '"usage"' not in line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue  # a truncated first tail line — skip
        usage = (obj.get("message") or {}).get("usage")
        if isinstance(usage, dict) and "input_tokens" in usage:
            return (
                int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0)
            )
    return None


def suggest(message: str) -> int:
    json.dump({"systemMessage": message}, sys.stdout)
    return 0


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    session_id: str = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "no-session")
    count = read_int(state_path("count", session_id)) + 1
    write_int(state_path("count", session_id), count)

    transcript = data.get("transcript_path", "")
    occupancy = context_tokens(transcript) if (transcript and count % CHECK_EVERY == 0) else None

    if occupancy is not None:
        warned_at = read_int(state_path("warned", session_id))
        if occupancy < TOKEN_THRESHOLD:
            write_int(state_path("warned", session_id), 0)  # reset after a compaction
            return 0
        if warned_at == 0 or occupancy - warned_at >= REWARN_STEP:
            write_int(state_path("warned", session_id), occupancy)
            pct = round(100 * occupancy / TOKEN_THRESHOLD)
            return suggest(
                f"[suggest-compact] Context is ~{occupancy:,} tokens (~{pct}% of the "
                f"{TOKEN_THRESHOLD:,} threshold). Consider /compact now to avoid an abrupt "
                "auto-compaction mid-task."
            )
        return 0

    # Fallback: no token signal available — use the tool-call cadence.
    if occupancy is None and not transcript and count % SUGGEST_EVERY == 0:
        return suggest(
            f"[suggest-compact] {count} tool calls this session. Consider running /compact "
            "to keep the context window healthy before it fills and forces an abrupt compaction."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
