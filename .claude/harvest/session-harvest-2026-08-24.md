# Session Harvest — Resource Backlog

**Window:** 2026-07-26 → 2026-08-24 (30 days)
**Sources:** Claude Code only — 36 main sessions (subagent transcripts excluded); 28 with human turns,
23 with inline Bash calls. 1,720 human turns; 3,475 deduped inline Bash calls.
**Method:** programmatic extraction (jq/grep). Every pattern scored by **distinct-session count**.
Transcripts contain ~1.36× duplicate records, so occurrence counts are deduped; distinct-session counts
are unaffected by that.

> Cursor / Codex / Copilot: no histories on this machine — Claude Code only.

## Ranked backlog (impact ÷ effort)

| # | Resource (type · name) | What it does | Evidence (distinct sessions) | Est. | Effort |
|---|---|---|---|---|---|
| ~~1~~ | ✅ **SHIPPED v0.13.0** — fix · supply-chain-guard false positive | Stop matching install strings inside quoted grep patterns / heredocs | Fires **7/36** sessions; **reproduced 4× live** while writing this report. Root cause pinned to 2 lines | Medium (~5%) | **XS** |
| ~~2~~ | ✅ **SHIPPED v0.13.0** — fix · /ship-pr phase ordering | Move the prek gate after docs-updater — today the gate is stale before the commit | prek Stop-hook failed in **11/36**; **10 of those 11 ran the gate skill** | **High (~15%)** | S |
| 3 | **hook · tool-dispatch-guard (agent classes)** | Reminder when a command with a dedicated agent runs inline | git `diff/log/show` **15/23** (160), git `add/commit/push` **12/23** (113), `gh pr` **10/23** (39), ruff/prek **7/23** (58), docker **7/23** (41) | Medium–High (~10%) | M |
| 4 | **hook · builtin-tool nudge (Grep/Read)** | Reminder when grep/sed reads a source file instead of the `Grep`/`Read` tools | **18/23** sessions, 389 calls that target a source file | Medium (~8%) | S |
| 5 | **skill · prek hook catalog + audit** | Port the proven, portable prek hooks into a per-project selectable catalog | **45 generic hooks** proven in one repo but unshipped | Medium (~8%) | M |
| 6 | **hook · README-row reminder** | Nudge the README row at resource-creation time, not at commit | check-md-links **10/36** sessions | Medium (~5%) | S |
| 7 | **agent · pr-merger** | Own batch PR merging; `gh-runner` is read-only so nothing covers it | **67** PR merges across **6** sessions via hand-rolled shell loops | Low–Med (~4%) | M |
| 8 | **instruction · agent-launch throttle** | Report running-agent count and ask before launching more | "don't start new agents" — **3** sessions | Low (~3%) | S |

**Deduped, bounded total addressable friction reduction: ~30–40%** (patterns overlap; not a naive sum.)
**Do first: #1 and #2** — both are bug fixes with pinned root causes, not new resources to design.


## NEW — found while shipping #1 and #2 (2026-08-24)

### destructive-command-guard has the SAME false-positive bug, and it HARD-BLOCKS

While opening the release PR, `destructive-command-guard` **blocked** a `gh pr create` because the PR
*body text* quoted the phrase `git stash` in a release note. Nothing was stashed. It then blocked a
second time, on the Python heredoc writing THIS entry.

Identical root cause to the supply-chain-guard bug fixed in v0.13.0 — the pattern is matched against
the raw command string with no quoting awareness — but **higher severity**: this guard exits 2 and
hard-blocks the call, where supply-chain-guard only emits a reminder.

- **Evidence:** two live reproductions. Verbatim: `[destructive-guard] BLOCKED — git stash (removes
  changes from a shared working tree ...)`, on commands that merely quoted the phrase as prose.
- **Distinct sessions:** the guard fires in **17/36** sessions (148 hits); the false-positive share
  within that is not yet measured.
- **Fix shape already exists in the codebase:** `executable_text()` was added to
  `supply-chain-guard.py` in v0.13.0 and is exported in its `__all__`. The two guards should SHARE it
  — extract to a common module rather than copy-paste.
- **Effort:** S. **Priority: next.** A hard block that fires on quoted prose is worse than a noisy
  reminder: the only escape is `GUARD_OK=1`, which trains bypassing the guard wholesale.

## Detail on the two that matter most

### #2 — /ship-pr runs its gate too early (the highest-value finding)
The obvious reading of "prek failed in 11 sessions" is *"the gate wasn't run."* The data says the opposite:
**10 of the 11 failing sessions did invoke `/ship-pr` or `verification-loop`.** So this is neither a missing
rule nor a missing trigger — more prose would be the fake fix.

The structural cause: `/ship-pr` runs the **full prek gate in Phase 2**, then **Phase 3 runs `docs-updater`,
which edits files**, and only then commits. Every markdown hook (`markdownlint`, `mdformat`, `typos`,
`check-md-links`) sees content the gate never checked. Failures appear at **both** stages, and this also
explains #6's `check-md-links` cluster.

**Fix:** re-run the gate after `docs-updater`, or move `docs-updater` into Phase 2 ahead of the gate.

### #1 — supply-chain-guard matches unquoted
`supply-chain-guard.py:104-105` — `JS_INSTALL_RE`/`PY_INSTALL_RE` `.search()` the raw command string with no
quoting awareness, so a *grep pattern* or a *heredoc documenting the bug* matches. Reproduced 4× in this
session alone, including once while writing this file. Cheapest win in the backlog.

### #5 — what's actually portable
Of 69 hooks proven in one repo but not shipped, **45 are generic**: `alembic-single-head`, `check-hooks-installed`,
`docs-updated`, `check-merge`, `assertive-sql`, `pydantic-returns`, `no-environ-config`, `orphan-test-file`,
`terraform-validate`, `no-raw-subprocess-import`, `db-session-containment`…
The other 24 are genuinely project-specific (`cognito-iam-drift`, `check-lambda-env-*`, `check-duckdb-scope`) — leave them.
The user asked for exactly this in-session; it is not yet delivered:
> "we need to think about having a prek skill to put all these hooks there and we can think about which one
> we should copy for each project, like an audit or installer."

## INFO — needs more data (not ranked)
- **Resource discoverability** — 45 agents / 39 skills / 19 hooks; only ~2 genuine instances of the user asking
  which resource to use. Most regex matches were false positives.
- **AWS dispatch bypass** — raw `aws dynamodb scan` in `my_banking_transactions`; **1 session only**.
- **Internal-tool leak correction** — high severity, **1 session only**; flagged for awareness.

## Checked and dismissed (with reasons)
- **rtk adoption** — transcripts show 2 `rtk` calls in 4,310, but the `rtk hook claude` hook rewrites at execution
  time, so transcripts log the original command. `rtk gain`: 203,532 commands, **82.1% saved**. Healthy, not a gap.
- **Auto-merge** — 0 uses of `gh pr merge --auto`. Rule honored.
- **"PR merge retry loops"** — withdrawn. 67 distinct (session, PR) pairs vs 75 invocations; only 2 real retries.
  The apparent 10× retry was extract duplication. Restated honestly as #7 (batch-merge volume).
- **Pydantic/dict contract enforcement** — already covered by `check-model-rules` + `pydantic-returns`.
  The gap is portability (folded into #5), not absence.
- **grep/sed as a dispatch violation** — only 389 of 1,974 grep/sed calls target a source file; the rest are
  legitimate analysis pipelines. Counted honestly in #4 rather than inflating #3.

## Prompt-injection scan
Both analysis agents reported **no injection attempts** in the scanned transcripts.
