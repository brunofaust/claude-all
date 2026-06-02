---
name: code-review-discipline
description: >-
  Discipline for any review-style task (code review, security review, SEO review, migration review, architecture review). Enforces a uniform output format, mechanical Approve/Warning/Block verdict rule, PR merge-readiness pre-check, "report-only" rule (no silent refactors), and a "common false positives" pattern. Pair with whatever review skill is doing the actual domain work — this one defines the SHAPE of the output and the discipline. Use when: reviewing a PR, reviewing a diff, performing a security audit, reviewing a migration, reviewing an architecture proposal, or building any new reviewer agent / skill.
user-invocable: true
---

# Code Review Discipline

A meta-skill for review work. Domain skills (security-review, code-review,
migration-reviewer, seo-reviewer) provide WHAT to look for. This skill
provides HOW to report it and HOW to behave during the review.

______________________________________________________________________

## Rule 0 — PR merge-readiness pre-check

**Before opening any file**, check the PR is in a reviewable state.

```bash
gh pr view <number-or-url> --json mergeStateStatus,statusCheckRollup,mergeable
```

Stop and report — do not start the actual review — if:

- `mergeStateStatus` is `BLOCKED`, `BEHIND`, `DIRTY`, or `UNKNOWN`
- `mergeable` is `CONFLICTING`
- `statusCheckRollup` contains any `FAILURE` or `PENDING` required check
- Branch is not synced with base (rebase needed)

Output for early-stop:

```
PR REVIEW SKIPPED
=================
Reason: <one-line: merge conflict / CI red / behind base / required checks pending>
Required action before review: <what the PR author must do first>
```

Why: reviewing a PR that can't merge anyway wastes tokens AND tempts you to
write notes that become stale when the author rebases and force-pushes.

For local-diff reviews (no PR yet), skip this rule. For staged-only reviews,
verify `git diff --staged` is non-empty before continuing.

______________________________________________________________________

## Rule 1 — Report findings only, do not refactor

A reviewer **never** edits source files. Even if the fix is obvious. Even if
it's a one-line change. Even if the user said "fix any issues you find."

You report. The user (or the implementation agent) fixes.

Exceptions — none. If the user wants you to fix as well, they invoke a
separate fix step after the review report.

Rationale:

- Mixing review with fixing makes it impossible to audit what changed and why.
- The review is wrong noticeably often — fixes shipped from a wrong review are
    silently destructive.
- Reviewer and implementer are different cognitive modes. Don't blend.

______________________________________________________________________

## Rule 2 — Standard output format

Every finding follows this exact shape — no exceptions:

```
[SEVERITY] Issue title
File: path/to/file.ext:LINE
Issue: What is wrong and why it matters (1-3 sentences)
Fix:   The exact change to make (code snippet or precise instruction)
```

Severities (mechanical, not opinion-based):

| Severity   | Meaning                                                            | Example                                                    |
| ---------- | ------------------------------------------------------------------ | ---------------------------------------------------------- |
| `CRITICAL` | Security / data-loss / production breakage                         | SQL injection, exposed secret, missing auth check          |
| `HIGH`     | Will cause bugs, broken contracts, or major maintainability harm   | Race condition, unhandled async error, type-erasing `Any`  |
| `MEDIUM`   | Code quality, idiomatic violations, perf opportunities             | Missing docstring on public API, N+1 query, magic constant |
| `LOW`      | Style / nit — would suggest in a code-review comment but not block | Naming, formatting that the formatter didn't catch         |
| `INFO`     | Observation, not a finding                                         | "this module is unusually large", "consider splitting"     |

Group findings under their severity. Within a severity, order by file path.

______________________________________________________________________

## Rule 3 — Mechanical approval verdict

After listing findings, emit ONE verdict line. The rule is:

| Findings present           | Verdict                            |
| -------------------------- | ---------------------------------- |
| Any `CRITICAL` or `HIGH`   | `BLOCK`                            |
| Only `MEDIUM`              | `WARNING — can merge with caution` |
| Only `LOW` / `INFO` / none | `APPROVE`                          |

The verdict is mechanical. You do NOT override it because "the HIGH issue is
not really important" or "the team can fix it later." If you disagree with the
severity assignment, downgrade the finding's severity with a stated reason
BEFORE computing the verdict — never override the verdict itself.

Output format:

```
VERDICT: BLOCK
Reason: 2 CRITICAL findings (file_a.py:10, file_b.py:42), 1 HIGH (file_c.py:7)
Required before merge: address the 3 BLOCK-grade findings above
```

______________________________________________________________________

## Rule 4 — Acknowledge common false positives

Add a "False positives I considered and ruled out" section ONLY if you spent
real effort distinguishing real findings from noise. This builds trust that
the report isn't just regex output.

Common false positives by domain:

| Domain             | Looks like a problem but isn't                                                                                                                                    |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Secrets / security | `.env.example` entries, test credentials clearly marked, public API keys (Stripe publishable key, Mapbox token), SHA256/MD5 used as checksums (not for passwords) |
| Python             | Mutable default in `__init__` of a frozen dataclass, `# noqa: BXXX` with a justification comment, `Any` in a Protocol parameter that's intentionally generic      |
| TypeScript         | `any` in adapter shims for untyped third-party libs, `as const` casts                                                                                             |
| SQL / migrations   | `SELECT *` in a one-off backfill script (not production code), no index on a low-cardinality boolean column                                                       |
| AWS / IaC          | Hardcoded ARNs in test fixtures, `*` in IAM for CloudWatch Logs write-only paths                                                                                  |

Only list ones you actually considered — empty section is fine.

______________________________________________________________________

## Rule 5 — Output template (assemble all rules)

```
REVIEW REPORT
=============
Scope: <files / PR number / commit range>
Domain: <security | code | migration | seo | architecture>

[CRITICAL] <title>
File: <path:line>
Issue: <description>
Fix:   <change>

[CRITICAL] <title>
...

[HIGH] <title>
...

[MEDIUM] <title>
...

[LOW] <title>
...

False positives considered:
- <pattern> at <path:line> — ruled out because <reason>

VERDICT: <APPROVE | WARNING | BLOCK>
Reason: <count and grade summary>
Required before merge: <specific actions, if BLOCK or WARNING>
```

______________________________________________________________________

## Integration with existing review tooling

| Tool                             | This skill's contribution                                                    |
| -------------------------------- | ---------------------------------------------------------------------------- |
| Built-in `code-review` skill     | Apply Rule 0-4 + use the output template                                     |
| Built-in `security-review` skill | Apply Rule 0-4 + use the output template + include "false positives" section |
| `migration-reviewer` agent       | Apply Rule 0-4 + use the output template                                     |
| `seo-reviewer` agent             | Apply Rule 2-4 (skip Rule 0 if reviewing static HTML, not a PR)              |
| Any new reviewer agent/skill     | Wire to this skill instead of inventing a new output format                  |

______________________________________________________________________

## Anti-patterns

- ❌ Skipping the merge-readiness check "to save time" — a 1-second `gh pr view` saves a 5-minute pointless review
- ❌ Fixing a finding "while I'm in there" — separate review from fix
- ❌ Inventing a new severity ("MAJOR", "TRIVIAL") — use CRITICAL/HIGH/MEDIUM/LOW/INFO only
- ❌ Padding the report with INFO findings to look thorough — quality over quantity
- ❌ Manually overriding the verdict — adjust the severity input, not the verdict output
- ❌ Reporting on style issues that the formatter (ruff, prettier) would auto-fix — those aren't review findings, those are unfixed lint
- ❌ Vague findings ("this could be better") — every finding needs a specific Fix
- ❌ Findings without file:line — unactionable
