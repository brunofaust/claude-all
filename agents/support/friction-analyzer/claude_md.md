### Command dispatch — turn session friction into rules → `friction-analyzer` (Sonnet)

| Goal | Agent |
|---|---|
| "analyze this transcript for friction", "what went wrong this session", "turn my mistakes into rules", "what guard hook would have helped", "mine my sessions for improvements" | `friction-analyzer` |

Anti-patterns:
- Reading raw session JSONL into the main session to figure out "what went wrong" — transcripts are
  megabytes; delegate to `friction-analyzer`, which extracts the signal with jq and returns a tight
  report (patterns + verbatim evidence + a proposed rule per pattern).
- Hand-writing a guard hook from a vague memory of "you kept doing X" — let `friction-analyzer` find
  the actual recurrences + propose the rule in `claude-hooks` shape, grounded in evidence.

`friction-analyzer` is READ-ONLY: it PROPOSES a guard hook / CLAUDE.md rule / agent-or-skill
improvement per recurring friction pattern (reverts, repeated corrections, command thrash, a guard
firing repeatedly, raw-command dispatch leaks, re-derived gotchas) — it never edits hooks, settings,
or CLAUDE.md (those need your confirmation). Pairs with the `claude-hooks` skill (implements the
proposed hook) and `subagent-prompting`.
