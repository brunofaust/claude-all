### Command dispatch — email inspection → `email-inspector` (Haiku, read-only)

| Trigger | Agent |
|---|---|
| Check / filter / search / summarize email via any Gmail / Outlook / email MCP | `email-inspector` |

Anti-patterns:

- Calling email MCP tools (`search_threads`, `read_thread`, `get_thread`, …) directly from the main session — message bodies, HTML wrappers, MIME parts and quoted reply chains blow up to hundreds of lines per message. Delegate to `email-inspector`.

Note: `email-inspector` returns a tight summary — count + per-message sender/subject + VERBATIM alarm/error text for CloudWatch / PagerDuty / Sentry / GitHub notification bodies. Read-only — never sends / archives / deletes / labels.
