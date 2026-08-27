---
name: hook-authoring
description: >-
  Authoring and debugging Claude Code hooks — the scripts Claude Code runs automatically around tool
  calls and lifecycle events. Use when: writing a new hook (a PreToolUse guard, a PostToolUse reaction,
  a Stop/SessionStart action), wiring a hook into settings.json, debugging why a hook fires / blocks /
  is ignored, or hardening a hook so its own failure never breaks a session. Covers the hook events +
  matchers, the stdin/stderr/exit-code contract, the two archetypes (a guard that BLOCKS with exit 2
  vs a utility that must NEVER break a turn → exit 0), the resilient-shim pattern, exit-code capture,
  the settings.json schema, and how to test a hook. References this repo's hooks/ examples.
disable-model-invocation: false
user-invocable: true
---

# Authoring Claude Code Hooks

A hook is a small program Claude Code runs **automatically** on a lifecycle event — most often before
or after a tool call. It reads a JSON event on **stdin**, can print to **stderr**, and its **exit
code** decides what happens. Because a hook fires on *every* matching event, a careless hook can
silently break every session — so robustness is the whole game.

## Events + matchers

| Event | When | Can block? |
| --- | --- | --- |
| `PreToolUse` | before a tool runs | **yes** (exit 2 stops the tool) |
| `PostToolUse` | after a tool returns (sees the result) | no |
| `UserPromptSubmit` | when the user sends a message | yes (exit 2 drops it) |
| `Stop` / `SubagentStop` | when the main / sub agent finishes | **yes** (exit 2 blocks stoppage; stderr goes to Claude) |
| `PreCompact` | before context compaction | no |
| `SessionStart` / `Notification` | session begins / a notification fires | no |

`matcher` filters by tool name (regex), e.g. `"Bash"`, `"Edit|Write|MultiEdit"`, `".*"`.

## The I/O contract

```python
import json, sys
data = json.load(sys.stdin)            # event payload
tool = data.get("tool_name")           # e.g. "Bash"
cmd  = data.get("tool_input", {}).get("command", "")     # PreToolUse
exit_code = data.get("tool_response", {}).get("exit_code", 0)  # PostToolUse only
print("message for Claude", file=sys.stderr)
sys.exit(0)
```

**Exit codes:**

- `0` — allow / success (stderr is informational).
- `2` — **BLOCK** (PreToolUse: the tool does NOT run; stderr is shown to Claude as the reason).
- any other non-zero — **non-blocking** error: stderr is shown, the tool still runs.

## The two archetypes (the core discipline)

1. **Guard hook** — *blocks bad actions on purpose.* Returns **exit 2** on a match (e.g.
   `destructive-command-guard.py` stopping `rm -rf /`). Must be **precise**: a false positive blocks
   real work, so scope patterns tightly and provide an explicit override (see below). Failing closed
   is the point.
2. **Utility / reminder hook** — *adds a nudge or reaction* (a style reminder, a suggestion,
   telemetry, auto-formatting trigger). It must **NEVER break a turn**: if the hook's *own* machinery
   fails (missing dep, bad parse, unset env var), **exit 0**. A reminder that crashes is worse than no
   reminder. Use exit `1` only for an intended non-blocking warning, never for an internal crash.

> Decide which archetype you're writing first — it dictates your failure behavior.

## Robustness rules

- **Read stdin defensively** — wrap `json.load` in try/except and `return 0` on error; never crash on
  a malformed payload.
- **Resilient shim** (for hooks that shell out): prefer a local binary, fall back
  (`command -v tool || npx --prefer-offline tool`), and for *utility* hooks end the chain with
  `|| exit 0`. Guard unset env: `"${CLAUDE_PLUGIN_ROOT:-}"`.
- **Be fast** — it runs on every event; keep well under the timeout, no slow network in the hot path
  (cache if you must call out).
- **Never leak secrets**, never write the payload to a world-readable temp file, use absolute paths.
- **Idempotent + side-effect-light** — a hook that mutates state is a footgun; prefer read-only.

## PostToolUse — capture the command outcome

```bash
exit_code=$(jq -r '.tool_response.exit_code // 0' <<<"$PAYLOAD")
[ "$exit_code" -eq 0 ] && status=ok || status=fail
```

## Wiring (settings.json)

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command", "timeout": 5,
                    "command": "python3 /abs/path/to/my-hook.py" }] }
    ]
  }
}
```

`timeout` is measured in **seconds**. `--user` → `~/.claude/settings.json`; `--project` →
`./.claude/settings.json`. In this repo, hook
scripts live in `hooks/`; the installer wires them in (see README "Hooks").

## Test a hook before shipping it

Pipe a synthetic payload and assert the exit code — no live session needed:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' | python3 my-hook.py; echo "exit=$?"
```

Run a battery of should-block / should-allow / should-warn cases (this is how
`destructive-command-guard.py` was verified against 26 commands).

## Anti-patterns

| Anti-pattern | Why | Instead |
| --- | --- | --- |
| Utility hook crashes on a missing dep | breaks every tool call | catch + `exit 0` |
| Guard hook with a loose regex | blocks legitimate work | tight patterns + explicit override marker |
| Slow / network call in the hot path | adds latency to every event | cache or move off the hot path |
| `exit 1` for an internal error | shows noise as if it were a finding | `exit 0` on self-failure; `2` only to block |
| Hook that mutates files/state | surprising side effects every event | read-only; reactions belong elsewhere |
| Shipping without a payload test | discover breakage in a live session | pipe sample JSON, assert exit code |

## Examples in this repo

- `hooks/destructive-command-guard.py` — a **guard** (exit 2, with allowlist + override).
- `hooks/config-protection.py` — a non-blocking guard (exit 0 + JSON `additionalContext` telling Claude to get user confirmation first).
- `skills/*/hook.py` + `hook.json` — domain reminder hooks shipped with skills.
