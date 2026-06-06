# Vulture whitelist — names flagged by `vulture --min-confidence 60` that are
# intentionally retained (real code, not dead). Vulture matches by identifier
# name, so referencing each here marks it "used". Keep this list tight: only add
# entries that are genuinely live/intended, and prefer deleting true dead code.
#
# Run: `vulture` (reads [tool.vulture] in pyproject.toml) or via the prek hook.

# Uninstall API — the README documents a planned uninstall that strips injected
# CLAUDE.md blocks and removes hook symlinks/settings. These implement it; they
# are wired up by that command, not yet referenced. Retain.
remove_hook
remove_claude_md
