### Command dispatch — CloudWatch Logs/Metrics → `cloudwatch-inspector` (Haiku)

| Command | Agent |
|---|---|
| `aws logs tail/filter-log-events/start-query`, `aws cloudwatch get-metric-statistics/describe-alarms` | `cloudwatch-inspector` |

Anti-patterns:

- `Bash(aws logs tail ...)` / `Bash(aws logs filter-log-events ...)` / `Bash(aws cloudwatch ...)` inline — CloudWatch JSON responses run hundreds to thousands of lines and burn Opus/Sonnet tokens. Delegate to `cloudwatch-inspector` and act on its verbatim-error summary.

Note: `cloudwatch-inspector` returns matched log lines / metric stats / alarm state, with exception text quoted verbatim. Read-only.
