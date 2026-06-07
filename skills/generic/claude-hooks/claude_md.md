## Authoring Claude Code hooks — `claude-hooks` skill
Apply when writing/debugging a Claude Code hook or wiring one into `settings.json`.

Key rules: hook reads event JSON on stdin, prints to stderr, exit `0`=allow / `2`=BLOCK (PreToolUse) / other non-zero=warn. **Pick archetype first**: guard (exit 2, tight patterns) vs utility (NEVER break a turn — if machinery fails, exit 0). Test with synthetic payload before shipping.
