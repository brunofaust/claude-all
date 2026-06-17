---
name: resource-scaffolder
description: >-
  Turn an APPROVED proposal (from session-harvest / repo-audit / diff-retrospective / friction-analyzer
  / lessons-extractor) into a correctly-scaffolded Claude Code resource — a skill, subagent, hook, or
  CLAUDE.md instruction — following the right conventions for the target (a project's `.claude/`, or a
  contribution back to claude-all). Use when: "create the skill/agent/hook we just proposed", "scaffold
  these into the project", or as the build phase of `/retro`. It is the generation engine those
  propose-only resources lack. Generates files only after the proposal is confirmed; verifies discovery
  + lint before declaring done.
disable-model-invocation: false
user-invocable: true
---

# resource-scaffolder — proposal → a real resource

Most of the analysis resources (`session-harvest`, `repo-audit`, `diff-retrospective`,
`friction-analyzer`, `lessons-extractor`) stop at a **proposal**. This skill is the missing build step:
it takes one approved proposal and writes the correctly-structured file(s).

## Inputs (per resource)

- **type**: `skill` | `agent` | `hook` | `instruction`
- **name**: kebab-case, generic (no project/company names — use `myapp`, `acme`, `example.com`, …)
- **purpose + triggers**: what it does and the exact phrasings/conditions that should invoke it
- **target**: `project` (write into the repo's `.claude/`) or `claude-all` (contribute back)
- **evidence**: the occurrences that justified it (carry into the description / PR body)

## Decide the right type first

| If the proposal is… | Scaffold a… |
| --- | --- |
| reusable knowledge / a multi-step procedure invoked on demand | **skill** |
| a bounded task that produces verbose output and should run in isolation | **subagent** |
| something that must fire automatically on an event (validate, set up, remind) | **hook** |
| a standing rule that belongs in always-loaded context | **instruction** (CLAUDE.md fragment) |

Don't scaffold a hook for what is really a one-shot procedure, or an agent for what is a standing rule.

## Project-level layout (target = `project`)

Write into the repo's own `.claude/` (these are what session-history mining usually produces):

- **skill** → `.claude/skills/<name>/SKILL.md` (frontmatter: `name`, `description` with explicit
  triggers, `disable-model-invocation`, `user-invocable`; add supporting files in the dir as needed).
  A user-invocable skill surfaces as the `/<name>` slash command.
- **subagent** → `.claude/agents/<name>.md` (frontmatter: `name`, `description` with when-to/when-NOT,
  `model` — haiku for mechanical, sonnet for judgment — and a focused `tools` list).
- **hook** → a script in `.claude/hooks/<name>.py` + an entry merged into `.claude/settings.json`
  (`event`, `matcher`, `timeout`). Follow the two archetypes (guard → exit 2; utility → exit 0 + JSON
  `additionalContext`) — see the `claude-hooks` skill.
- **instruction** → a tagged block appended to the project `CLAUDE.md`.

## claude-all layout (target = `claude-all`)

Follow this repo's `CLAUDE.md` exactly: pick the category folder (`generic`/`python`/`aws`/…); flat vs
folder agent; `claude_md.md` naming; add the README table row (§1.x agent / §2.x skill / §3 hook); use
only the approved generic placeholders. Then `./claude-all --all --user <name>` to activate.

## Conventions to honour (both targets)

- **Description = router fuel.** Be explicit about WHEN to trigger AND when not; list real phrasings.
- **Model strategy** (agents): Haiku = read/report/run mechanical; Sonnet = judgment (review, debug,
  refactor). Don't put judgment work on Haiku.
- **Generic + public-safe** — no real project/company/domain/ARN/secret names; scrub evidence snippets.
- **Hooks fail safe** — guards block deliberately; utilities never break a turn.

## Procedure

1. **Confirm the proposal** (type, name, target, purpose) — never generate from a vague idea. If
   underspecified, ask.
2. **Dedup** — check the target doesn't already have a resource covering this (`claude-all --list`,
   the project's `.claude/`, installed `~/.claude/`). Extend rather than duplicate.
3. **Scaffold** the file(s) per the layout above.
4. **Verify before done** — confirm discovery (`claude-all --list <name>` or the skill/agent appears),
   and run the repo's linter/gate on any code you added (it must pass on the tree). For claude-all,
   also add the README row.
5. **Report** what you created + how to activate it. Generating files is state-changing — do it only
   after step 1's confirmation.

Pairs with the propose-only resources (it's their build phase) and with `subagent-prompting` /
`claude-hooks` (authoring detail) and `regression-gates` (when the proposal is a new gate).
