## Authoring Claude Code hooks — claude-hooks skill

When writing or debugging a Claude Code hook (a script Claude Code runs on `PreToolUse`/`PostToolUse`/`Stop`/etc.), or wiring one into `settings.json`, apply the `claude-hooks` skill.

- A hook reads the event JSON on **stdin**, prints to **stderr**, and its **exit code** decides: `0` = allow · `2` = BLOCK the tool (PreToolUse) · other non-zero = non-blocking warning.
- **Pick the archetype first:** a **guard** hook blocks bad actions on purpose (exit 2, tight patterns + an explicit override); a **utility/reminder** hook must NEVER break a turn — if its own machinery fails, **exit 0**.
- Read stdin defensively (catch JSON errors → exit 0); be fast (runs on every event); no secrets; prefer read-only.
- **Test with a synthetic payload** before shipping: `echo '{"tool_name":"Bash","tool_input":{"command":"…"}}' | python3 hook.py; echo $?` — run a should-block/allow/warn battery.

Hook scripts live in `coding/hooks/`; examples: `destructive-command-guard.py` (guard, exit 2) and `config-protection.py` (confirmation, exit 1).
