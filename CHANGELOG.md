# CHANGELOG


## [Unreleased]

### Changed

- **brunofaust-python-style**: replaced the module-splitting rule. The old rule — *"one file per
  domain concept, the single home for **everything** about that domain"* — is **too coarse an axis**:
  "AI models" is one domain, so the rule actively instructed you to pile orchestration, billing policy,
  vendor routing and request shapes into one file, and a 1,300-line module was the rule working as
  designed. **Domain tells you which FOLDER; it does not tell you where the seams are.**
  The new axis is **reason to change**, subordinate to **dependency ownership**: *a module hides ONE
  SECRET* — one design decision that can change independently. Five operational tests: split when two
  chunks change for different reasons / rates / owners (*would they ever share a PR for the same
  reason?*); keep together when they always change together (**fat is fine given one reason to
  change**); place by dependency ownership (code whose only real dep is a vendor SDK belongs in that
  vendor's owner module); the **false-seam test** (if splitting forces exposing internals, the cohesion
  is real — don't split, which is what stops it degenerating into the linter's "just split it"); and
  **LOC is a smell, never a criterion**. A coordinator/facade may legitimately be large — it is too big
  only when it smuggles in a *different* secret. Includes a worked 4-secret example. Wired into the
  `audit.md` checklist so `/ship` and `/ship-pr` apply it per changed file.
- **code-review-discipline**: reconciled with the above — the **file-length 800-line hard BLOCK is now
  a smell, not a criterion**. A long file prompts the one-secret question; it is a finding only when the
  seam test says so. (A 200-line file holding two unrelated secrets is the real defect; a cohesive
  1,000-line coordinator is not.) Never demand a split to hit a line target.


## v0.5.0 (2026-07-20)

### Bug Fixes

- **installer**: Scope-guard prune so it cannot escape the current install roots
  ([`c11050c`](https://github.com/brunofaust/claude-all/commit/c11050ce97d584c1921e12a5976a0c5dad816e47))

state.json records ABSOLUTE target paths. When the state file and $HOME disagree — a copied state
  file, a container, a harness overriding HOME — an unguarded prune FOLLOWED those paths out of its
  sandbox and deleted another installation's artifacts.

Found the hard way, not hypothetically: testing the installer in an isolated HOME seeded with a COPY
  of the real state.json, --prune unlinked three real symlinks in the actual ~/.claude (restored
  immediately; no data lost — state.json and CLAUDE.md were untouched because those writes correctly
  targeted the sandbox).

in_install_scope() now gates every filesystem reversal: reverse_footprint's target unlink, and all
  three undo_artifact branches (hook symlink / CLAUDE.md block / settings hook entry). A record
  whose path lies outside ~/.claude or ./.claude is reported 'state only' and its files are left
  strictly alone.

Verified by re-running the EXACT scenario that caused the incident: same sandbox, same copied
  state.json — the out-of-scope entry now reports 'state only' and the real symlinks survive. Plus
  three regression tests (out-of-scope symlink not unlinked, out-of-scope CLAUDE.md not rewritten,
  real install roots still in scope so normal pruning works).

### Documentation

- **brunofaust-python-style**: Add YAGNI / minimalism reference
  ([`7a7cf59`](https://github.com/brunofaust/claude-all/commit/7a7cf59beac43d801ab61387ce4d2d15cc6c33f3))

Structure is a cost, not a virtue. references/yagni.md makes minimalism the DEFAULT: name a concrete
  present reason for every function, class, file, and abstraction — 'might need it later' / 'more
  flexible' / 'cleaner' / 'best practice' / 'separation of concerns' are not reasons.

- target shapes: one table = one class + its Pydantic model; called once -> inline; one
  implementation -> no interface/Protocol; one method -> no class - banned by default:
  pass-throughs, a repository wrapping SQLAlchemy,
  factories/strategies/registries/managers/single-subclass bases, config for one-value options,
  defensive handling of type-guaranteed inputs - why: the wrong abstraction costs more than the
  duplication (duplication is easy to see and delete; a bad abstraction is load-bearing) - when a
  boundary is EARNED: Rule of Three, a real second impl today, a genuine test seam — never
  speculation - the architectural exception: foundations expensive to reverse (boundary models,
  schema/DB, security/tenant boundaries, module layout) warrant foresight now. YAGNI governs
  features, not foundations. - the deletion pass: per unit, name the present need or inline/remove

Synthesized from the user's minimalism prompt + the lev-os YAGNI skill.

Also RECONCILES a self-contradiction: architecture.md promoted Service/ Repository layering and
  Protocol-DI, which yagni.md's banned-by-default list rejects. architecture.md now frames those as
  tools for a justified need, not defaults, with 'When to reach for this' caveats. SKILL.md carries
  YAGNI as architectural rule #1.

### Features

- **frontend**: Merge 7 frontend skills into brunofaust-frontend-style
  ([`fccd2db`](https://github.com/brunofaust/claude-all/commit/fccd2db74d831b60886ea3be846def8c66b1f45a))

One entry point for React/browser work — the counterpart to brunofaust-python-style. 7 skills -> 5.

FOLDED IN as references/ (content moved verbatim, frontmatter stripped; git records them as
  renames): react-correctness, react-testing, web-security. Those three skill dirs are deleted.

REFERENCED IN PLACE, not copied: the four vendored skills (react-best-practices,
  composition-patterns, react-view-transitions, web-design-guidelines) stay byte-identical to
  upstream so scripts/vendor_sync.py keeps pulling improvements — Vercel actively updates
  react-best-practices, and folding it would fork it permanently. Verified after the merge:
  vendor_sync.py --check reports 'up to date'; vendored.json needs no change and has no dangling
  paths.

Installing the new skill pulls the four in automatically via its claude-all.json requires — the
  dependency mechanism's first real use, verified (closure = 5).

Companions consolidated: one claude_md.md (was 3 separate always-loaded injections) and one reminder
  hook (was 3). The hook covers source AND test files, so the folded react-testing hook's test-file
  reminder is preserved as an appended line rather than lost; once-per-session, skips
  node_modules/dist/build.

New references/audit.md — the frontend judgment checklist that /ship and /ship-pr now run on every
  changed .tsx/.jsx/.ts/.vue/.svelte file (correctness, composition, security, a11y, tests, perf,
  minimalism), filling the placeholder those pipelines shipped with.

- **hooks**: Edit-time guards for the brunofaust stdlib-library rules
  ([`52e65ad`](https://github.com/brunofaust/claude-all/commit/52e65ada1fac2d86bc0a44749a23e97a56c4f483))

Four PreToolUse guards that BLOCK the Write in Claude Code when an edit introduces a construct the
  brunofaust-python-style skill bans, so generation is steered toward the preferred library before
  the bad import lands:

- python-orjson-guard stdlib json -> orjson - python-structlog-guard stdlib logging -> structlog -
  python-settings-env-guard os.getenv -> the Settings singleton - python-thread-subprocess-guard raw
  asyncio.create_subprocess / to_thread / ThreadPoolExecutor -> the owner wrappers

Ported from the source repo's .claude/hooks. This is the edit-time layer that complements the
  skill's CI layer (the ruff banned-api bans added in v0.4.0): the guard stops it being written, the
  ban stops it being merged. Edit-time guards steer generation better than a review comment after
  the fact.

Each guard: fires on Edit/Write/MultiEdit of a .py file; exempts tests/scripts/migrations/alembic;
  escape hatch is a # guard:allow comment or a per-guard env var (the one owner file that
  legitimately keeps the stdlib adds it); blocks with exit 2 + a stderr message naming the
  replacement. Handles MultiEdit's edits[] array, not just Write/Edit's new_string/content.

Wired via hooks.json (PreToolUse, Edit|Write|MultiEdit); installed at user level they apply in every
  repo. enforcement.md documents the two-layer model. Verified: each guard blocks Write+MultiEdit of
  its banned construct, allows the

preferred library / # guard:allow / env-var / test paths, and no-ops on malformed input.

- **installer**: Annotate dependencies, add first tests, dogfood own checkers
  ([`d19bf25`](https://github.com/brunofaust/claude-all/commit/d19bf250f89021e1b35334b9b1f0a456f86ee5b5))

Three follow-ups to the dependency-resolution mechanism.

1. ANNOTATIONS — 8 more resources declare their hard deps: merge-main, mock-drift-sweep,
  adversarial-verification, verification-loop, repo-audit, prek, python-module-migration,
  brunofaust-python-style. Every target was validated against the installer's own discover() BEFORE
  writing, so the graph is correct by construction rather than by hope. Surface-conditional
  reviewers (terraform-reviewer et al) are deliberately NOT requires — they are runtime-
  conditional, not install-time.

2. TESTS — the repo's first test suite (tests/test_dependency_resolution.py, 11 tests). Covers the
  resolver contract: transitive closure, cycle termination, unknown deps reported external not
  installed, already-selected deps not double-reported, tolerant manifest reading
  (missing/malformed/non-list requires, parametrized), the flat-agent <name>.claude-all.json
  convention, and the REAL shipped graph (every requires target resolves; ship-pr pulls its agents)
  — so a rename that breaks the graph fails here, not at a user's install. pytest>=8 in the dev
  group + [tool.pytest.ini_options].

3. DOGFOODING — claude-all now runs its OWN checkers on its OWN source in prek.toml (module_private,
  junk_drawer). It shipped these gates without ever applying them to itself, which is exactly how a
  module-level _name — banned by the visibility rule this repo publishes — reached cli.py. Both pass
  clean today; the gate keeps it that way.

Also fixes a /ship self-contradiction: its Rules said whole-repo --all-files while its gate step
  (correctly) scopes the fast loop to the changed set; the whole-repo no-amnesty gate belongs to
  /ship-pr.

codecongruence excludes tests/** from duplicate_functions: test cases for one function are
  arrange-act-assert siblings BY DESIGN — deduping them into a shared mega-test would hide which
  case broke. Genuine setup duplication is still extracted (build_universe).

- **installer**: Forget stale tool/plugin records without uninstalling; fix visibility
  ([`682ac51`](https://github.com/brunofaust/claude-all/commit/682ac512acc7824a0986fc75e292f96ebda044c9))

Two follow-ups from review:

1. Module-level visibility. The 5 prune helpers were _-prefixed, which violates this repo's own
  visibility rule (visibility.md: module-level names never start with _ — the prefix blinds
  dead-code tools; use __all__). cli.py's convention is public names + __all__ = ["main", "run"].
  Renamed to public names (is_companion_key, infer_level, undo_artifact, strip_claude_md_block,
  drop_settings_command) — still not exported, per the convention. (It slipped because claude-all
  does not run its own module_private checker on cli.py — a dogfooding gap worth wiring later.)

2. Stale tool/plugin RECORDS are now forgotten, not left forever. --prune must never uninstall a
  brew/pipx binary or a marketplace plugin — but a record for a tool/plugin no longer shipped by the
  repo was lingering in state.json indefinitely (e.g. a dead tools/lean-ctx from June).
  forget_records drops the record + any ~/.claude artifact and LEAVES THE BINARY IN PLACE, so state
  stops claiming to manage something it no longer ships without ever running an uninstall. Plugins
  stay safe via guard 2 (zero discovered -> never flagged).

Refactor: prune_installs and forget_records shared the footprint-reversal loop (codecongruence C003,
  0.92). Extracted reverse_footprint() as the single owner — symlink-guarded unlink + undo each
  artifact — used by both (dogfoods the simplification audit; cleared C003 by dedup, not silencing).

Verified in an isolated HOME: artifact prune, legacy reconstruction fallback, tool-record forget
  (binary untouched), plugin exclusion, CLAUDE.md preservation.

- **installer**: Per-resource dependency resolution via claude-all.json
  ([`d414d5a`](https://github.com/brunofaust/claude-all/commit/d414d5a2db79bf0f2d218c126c26f3cb8f808331))

A resource may ship a claude-all.json companion beside it — an extensible manifest, first key
  requires: ['kind/name', ...] (room to grow). Folder resources use <dir>/claude-all.json; flat
  agents <name>.claude-all.json, mirroring the hook companion convention.

Installing a resource pulls in its transitive, cycle-safe dependency closure: install skills/ship-pr
  and its delegated agents/skills (lint-fixer, test-runner, docs-updater, git-committer,
  verification-loop, code-review-discipline) come with it. Resolution runs over the UNFILTERED
  resource set, so a dependency the user's filter would exclude is still installed; the installer
  reports what it pulled in. A requires entry that resolves to no installable resource (a built-in
  like /code-review) is reported as external and skipped — never fails the install.

Per-resource, not a central manifest: the deps live WITH the resource, so deleting it deletes its
  deps — no central file to orphan (the anti-drift property the prune feature enforces from the
  other direction; central requires.json would reintroduce exactly the stale-record class prune
  exists to kill).

scripts/check_requires.py is the drift gate (wired in prek): every requires entry must resolve to a
  real resource. It imports the installer's own discover()/state_key, so 'what is a resource' is
  defined in ONE place — a rename in cli.py that invalidates a requires fails the check. Proven:
  passes clean on the 2 seeded manifests (ship-pr, ship); bites on an injected dangling dep.

Resolver verified: closure + dedup (ship-pr -> 7), cascade (dep-of-dep), cycle termination
  (ship<->ship-pr), external/unknown deps reported not crashed.

NOTE: prune (PR #91) should consult this graph — never prune a still-required resource. That guard
  lands once #91 is on main (its prune functions don't exist here yet); tracked as the follow-up.

- **installer**: Prune stale installs no longer shipped by the repo
  ([`b8d89da`](https://github.com/brunofaust/claude-all/commit/b8d89daabbb1853f37ae6a4d6ab98da562843811))

The installer records every install in ~/.claude-all/state.json, but nothing removed an install when
  its resource was later deleted from the repo — a skill merged/retired left a dangling symlink,
  CLAUDE.md block, and settings hook entry in ~/.claude forever.

Now every run prints an advisory notice listing installed-but-no-longer-shipped resources, and
  `claude-all --prune` removes each one (symlink + CLAUDE.md block + settings hook entry + state
  record, plus companion records) with no confirmation.

A naive 'recorded minus discovered' diff is UNSAFE — tested against a live state.json it would have
  deleted real data. Three guards, each closing a verified false-positive: 1. Companion sub-records
  (<name>.claude_md) are pruned only WITH their primary; alone they'd strip an installed resource's
  CLAUDE.md block. 2. A kind for which discover() returns ZERO items is never flagged — a missing
  enumerator (no plugins/ dir in the package) would else mark every recorded plugin stale. 3. The
  recorded target symlink is unlinked ONLY when it is actually a symlink, so a recorded real file
  (e.g. a CLAUDE.md path) is never deleted.

Reuses the existing idempotent remove_claude_md / remove_hook. Verified end-to-end in an isolated
  HOME: prune removes symlink + companion hook + CLAUDE.md block + settings entry + state (primary
  and companion), and preserves unrelated CLAUDE.md content. This is the prerequisite for retiring
  the 7 frontend skills into brunofaust-frontend-style — the delete now propagates to existing
  installs.

- **installer**: Record install footprint + exclude tools/plugins from prune
  ([`a8b2e59`](https://github.com/brunofaust/claude-all/commit/a8b2e59825c0aaabfb46efde4a5746032086d312))

Two refinements to stale-pruning:

1. Never prune tools/plugins. Their install is more than a symlink+block+hook (a brew binary, a
  plugin-marketplace entry), so removing only our recorded artifacts would leave the real thing
  half-installed. Excluded from staleness.

2. Record each install's full FOOTPRINT in state.json. record_artifact appends an 'artifacts' list
  per install — the CLAUDE.md block (+ its tags), each settings.json hook command, the hook symlink
  — captured where each side-effect is created (inject_claude_md / inject_hook /
  install_standalone_hook). --prune now reverses EXACTLY what an install did, source-independently,
  even after the resource is deleted from the repo and we've lost its hook.json/claude_md.md.

This closes a real gap the reconstruction approach had: a standalone hook's settings entry + symlink
  use <name>.py, but reconstruction derived the companion <kind>-<name>.py path and would miss them.
  Recording the actual command/path fixes it. Entries recorded before footprints fall back to
  kind/name reconstruction.

Dedup: remove_hook's settings-entry stripping and the new artifact reversal are the same operation,
  so remove_hook now delegates to _drop_settings_command — one owner for 'strip this command from
  settings.json' (dogfoods the simplification audit; cleared the codecongruence C003 by dedup, not
  by silencing).

Verified in an isolated HOME: artifact-path removal (hook symlink + block + settings command + real
  content preserved), legacy reconstruction fallback, tools/plugins exclusion, and
  reinstall-resets-footprint all pass.

- **ship**: Hard full-prek gate on both stages — no pre-existing-issue amnesty
  ([`c08bb95`](https://github.com/brunofaust/claude-all/commit/c08bb95bce4de23839acd76396e8f4f21032d543))

Every ship must be full green across the WHOLE repo, not just the diff. Adds a non-negotiable gate
  to /ship and /ship-pr: before commit, run

prek run --all-files # pre-commit stage prek run --all-files --hook-stage pre-push # pre-push stage

over the entire repo, and require zero Failed on BOTH.

NO pre-existing-issue amnesty: a hook failing on a file OUTSIDE the current diff still blocks the
  ship. 'It was already broken' is not an exception — fix the root cause (route to lint-fixer; never
  # noqa / SKIP= / --no-verify / config-loosen), then re-run both stages until green.

This closes the recurring 'pre-existing issues slipped through' gap: lint-fixer only touches changed
  files, and prek run --all-files alone runs only the pre-commit stage — so neither guaranteed a
  whole-repo both-stage green. Both skills also warn to read per-hook status lines: a '(no files to
  check) Skipped' on input a hook should have inspected is a vacuous pass, not green (per the prek
  skill's vacuous-PASS section).

- **ship**: Skill-audit framework — audit each changed file vs its stack skill
  ([`c3ee324`](https://github.com/brunofaust/claude-all/commit/c3ee32464866b81ebb16086014e35b4d7c44bd39))

Generalizes the standard audit step in /ship and /ship-pr from 'against yagni.md' to 'against the
  stack skill's audit.md', via a file-type map: *.py -> brunofaust-python-style/references/audit.md
  *.tsx/*.jsx/*.ts -> brunofaust-frontend-style/references/audit.md (pending)

New references/audit.md is the skill's master JUDGMENT checklist — minimalism, layering,
  error-handling, async, boundaries, config, tests, ownership — and is explicitly the layer the
  mechanical checkers cannot see. It never restates a checker-gated rule (no-typeddict,
  extra-forbid, masking-default, ...); it catches the judgment calls: pass-through chains,
  speculative abstractions, I/O mixed with logic, a swallowed except, a fixture that restates the
  code, os.getenv outside Settings. Scales to the diff, never strips a hard rule.

/ship-pr also gains: - a surface-scoped SEO review step: fires when the diff renders crawler-visible
  HTML (a frontend page OR a server-rendered template OR sitemap/robots), never a pure JSON API.
  Scoped by surface, not stack — a Django SSR page counts. - security-review promoted from loose
  judgment to standard-when-a-security-surface -is-touched
  (auth/secrets/input/IaC/IAM/shell/tenant). web-security (frontend XSS/CSP) rides the frontend
  skill audit; this step is the cross-stack audit.

Kept /ship and /ship-pr separate on purpose: /ship-pr adds three real layers (code-review, security,
  docs) beyond /ship+PR, and /ship's lightness is what makes commit-early-commit-often work — they
  compose (ship-pr reuses ship's gates), not duplicate.

- **ship-pr**: Scope /ship to changed files; parallel Phase 2 with IaC, migration, dependency
  reviews
  ([`0adb981`](https://github.com/brunofaust/claude-all/commit/0adb981c8a60d01b6aed67b0111fcd49d77d9c7a))

Refines the ship pipelines per review:

/ship — gate the CHANGED files (both stages), not the whole repo. It is the fast commit loop, so it
  gates your changes (prek run + prek --hook-stage pre-push --files ...) and does not block a quick
  WIP commit on an unrelated pre-existing issue elsewhere. The whole-repo, no-pre-existing-amnesty
  full gate stays /ship-pr's job (the outward-facing boundary where shared code must be fully
  green).

/ship-pr — three phases, Phase 2 runs in PARALLEL. Phase 1 (serial, mutating): skill audit +
  /simplify -> lint-fixer. Phase 2 (concurrent subagents, read-only over final code): coverage,
  tests, full prek (--all-files both stages), code-review, and the surface-scoped reviews. Phase 3
  (serial): docs -> commit -> PR. Fanning out the independent reads is what stops ship-pr being a
  30-minute serial crawl; mutators stay serial and first so readers see final code.

Surface-scoped Phase-2 reviews, each firing only on its surface: - architecture-decision-guard —
  structural change (new boundary/layer/interface) - IaC review — *.tf / CloudFormation / CDK:
  cloudformation-reviewer / terraform-reviewer + aws-architecture and aws-cost-optimization lenses
  (arch fitness AND cost) - migration-reviewer — a DB migration file - dependency review —
  pyproject/uv.lock/requirements or package.json/lock: CVE scan gates high/critical;
  version-currency + maintenance + fit (research-before-build + Context7) ADVISES the user without
  blocking. Owns the dep slice of the supply-chain surface.

Skipped when the diff doesn't touch the surface, so the common case stays fast.

- **yagni**: Pass-through-chain anti-pattern + standard simplification audit in ship/ship-pr
  ([`0a298a6`](https://github.com/brunofaust/claude-all/commit/0a298a67472f94c822e64d09da94ae96686dfa63))

Refines the YAGNI reference with the single most common over-engineering — one operation smeared
  across a chain of forwarding methods:

get_by_id -> _get_by_id -> _get_from_database -> _query -> _result_as_pydantic

collapsed to the one method it should be:

get_by_id -> db.fetchrow(...) -> Model.model_validate(...)

A routine ~30% line reduction with zero behaviour change. The rule: a private method must do
  something genuinely distinct AND shared (2+ callers) — a helper with one caller that only forwards
  gets inlined; the whole operation should read top to bottom in one method. Private methods are
  fine; a chain of forwarders is not.

Adds a yagni.md 'Audit checklist' and makes the simplification audit a STANDARD (no longer optional)
  step in BOTH /ship and /ship-pr: every changed file is audited against the checklist before the
  gates, mechanical fixes applied via /simplify, judgment calls reported. It scales to the diff
  (trivial rename -> quick pass; feature code -> full list) but is never skipped, and never strips
  the skill's hard rules (a boundary model / owner class / docstring stay).


## v0.4.0 (2026-07-16)

### Bug Fixes

- **brunofaust-python-style**: Close all_contract's no-__all__ fail-open hole
  ([`59f7b05`](https://github.com/brunofaust/claude-all/commit/59f7b0587a23afb88effe3de4847a70eb7e139fe))

all_contract's `not-in-all` verifies `from x import y` against x.__all__ and SKIPS a target module
  that declares no __all__. So deleting __all__ was the way to opt a module out of the gate entirely
  — remove the thing being validated and the checker stops looking. In the production repo this left
  155 of 291 modules (53%) with zero enforcement while the gate reported green, and one such module
  broke mypy strict's no_implicit_reexport with a real blocking error.

Adds a `missing-all` rule: a module that defines a public module-level def/class but declares no
  __all__ is flagged. It closes the hole from the other side — `not-in-all` still (correctly) can't
  verify an import against an absent __all__, but the target module is now caught directly, so once
  it declares __all__ the import check can enforce. The two rules coexist; not-in-all/private-in-all
  are unchanged.

Exempt BY CONSTRUCTION, not by a path allowlist: the rule fires only when there is a public name to
  export, so a module with nothing public — an empty or docstring-only __init__.py, a private-only
  or constants-only module — is never flagged, and the gate stays incrementally adoptable.

Verified against the source codebase: 156 findings, matching its own count of ~155 no-__all__
  modules — the checker now catches the exact hole its fixed version does.

This is the session's own lesson applied to our own checker: a checker that silently skips its input
  reports a vacuous pass.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **brunofaust-python-style**: Close the opaque-annotation recursion hole
  ([`81fb319`](https://github.com/brunofaust/claude-all/commit/81fb319d0b512e6f1e4ef26833ae19976a4fff04))

The opaque-annotation rule only recursed into mapping containers, so it silently PASSED
  Sequence[Any], list[dict[str, Any]] and Mapping[str, Any] | None — each of which is the untyped
  dict one level down. It now recurses through every subscript argument at any depth.
  Concretely-subscripted containers stay legal: Mapping[str, str] and dict[VectorKey, SearchResult]
  still pass, because the container was never the problem.

Also adds a dict-return rule: a function returning a raw dict leaks a payload across a boundary,
  including a concrete dict[str, str] and an unannotated `return {...}` that dodges every
  annotation-based check. It is checked before opaque-annotation so a `-> dict[str, Any]` reports
  once, not twice.

The checker now exits 1 on any finding, so it wires straight into prek/pre-commit and fails the
  commit with the findings printed — no baseline artifact. It owns no state: no baseline, no JSON,
  no cache. --exit-zero is for composing behind baseline_gate.py, whose contract reads a non-zero
  exit as a crash and fails closed.

Smaller ports from the same idea running in production:

- object joins Any as opaque - RootModel joins BaseModel/BaseSettings as a model base - the splat
  rule exempts the whole structlog surface (.info, .exception, .bind_contextvars) rather than only
  .bind

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **brunofaust-python-style**: Fail closed when a file will not parse
  ([`1daf013`](https://github.com/brunofaust/claude-all/commit/1daf013cf34f0cbcfd8bf88e3a1721ae40723bb9))

The checker parses with the ast of the interpreter it RUNS ON, and swallowed SyntaxError to return
  no findings. An env older than the project therefore skipped files silently and reported them
  clean.

This is not hypothetical. Unpinned, bandit's isolated env resolved to 3.12, could not parse PEP 758
  `except A, B:`, logged "syntax error while parsing AST" for 25 files, skipped them, and still
  exited success — a security gate silently not scanning. Vulture's resolved to 3.11 and dropped 35
  files from dead-code analysis on PEP 695 generics, which is why real dead modules survived. A
  repo-level default_language_version does not reach a hook's isolated env.

An unparsable file now exits 2 — a tool error, distinct from 1 = findings — and does so even under
  --exit-zero, so baseline_gate.py sees a crash and fails closed rather than recording an empty
  finding set. The message names the fix: pin language_version on the hook.

enforcement.md's wiring recipe carried two bugs of its own:

- it omitted --exit-zero, so baseline_gate would read exit-1-on-findings as a crash and fail closed
  on every run - it did not pin language_version, so the gate it documents had the very blind spot
  described above

It also now documents the bare, ratchet-free wiring: the checker exits 1 on findings by itself, so
  neither script is needed once the baseline hits zero.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **claude-md**: Close the escape hatches the gates leave open
  ([`601accd`](https://github.com/brunofaust/claude-all/commit/601accd317c40510f6d3ce9322527bf57e91e096))

Both claude_md.md snippets are injected into the always-loaded ~/.claude/CLAUDE.md, and both
  contradicted the rules they front.

python-style listed TypedDict as a recommended strict-typing tool while the skill now bans it, and
  asked only for "Pydantic at trust boundaries" — too weak now that every payload crossing a
  boundary is a model with extra="forbid".

It now carries a fix vs fake-fix table. Every gate has one real fix and one tempting fake fix that
  makes the message vanish while the bug survives:

- extra-forbid / ValidationError -> relax to extra="ignore" (re-arms the bug: the unknown key
  silently vanishes and you learn nothing) - masking-default -> add a "safe-looking" default ("", 0,
  []) — that IS the bug - opaque-annotation -> widen to Any / drop the annotation - no-typeddict,
  no-cast -> cast() into a TypedDict, the original no-op - select-star -> loosen the model to match
  SELECT * - exit 2 on an unparsable file -> re-add the SyntaxError fail-open - any of them ->
  --select it away, SKIP=, --no-verify, baseline a NEW finding

Agents follow incentives literally: an undocumented escape hatch one keystroke away is the gate's
  real failure mode, so name it and forbid it where the rule lives.

prek asserted "prek run --all-files is the single gate". It is not — that is one stage, over tracked
  files only, and a hook that silently skips its input still exits 0. That instruction produced a
  real vacuous PASS: an untracked new file reported clean across 34 hooks while mypy said "(no files
  to check) Skipped". Now: git add first, run the pre-push stage too, read the per-hook status
  lines, and pin per-hook language_version.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **prek**: Name the vacuous PASS and pin AST hooks per-hook
  ([`a9c2660`](https://github.com/brunofaust/claude-all/commit/a9c2660bac5bddd003a985c329fa0e04bbb29967))

A hook that silently skips its input still exits 0, so the gate reports green while being blind. The
  skill only documented default_language_version, which does NOT reach a hook's isolated env — so
  any hook parsing Python with the interpreter's own ast could resolve an older Python and stop
  seeing files.

Observed, not theorised. Unpinned, bandit's env resolved to 3.12, could not parse PEP 758 `except A,
  B:`, logged "syntax error while parsing AST" for 25 files, skipped them, and exited success — a
  security gate silently not scanning. Vulture's resolved to 3.11 and dropped 35 files on PEP 695
  generics, which is why real dead code survived for months.

- per-hook language_version is the rule; default_language_version cannot carry it - AFFECTED
  (bandit, vulture, interrogate, local AST checkers) vs IMMUNE (ruff and jscpd own non-Python
  parsers, tree-sitter tools, pyright bypasses prek's env) — so the pin lands where it matters
  instead of everywhere - the diagnostic tell: an exit-0 hook is not proof it scanned anything.
  Inspect the cached env under ~/.cache/prek/hooks/, check which Python it resolved to, run that
  interpreter over the tree and count what it cannot parse.

Generalises to two siblings already biting in practice: `prek run --all-files` only inspects
  git-tracked files, so an untracked file is skipped and the gate passes vacuously (tell: "(no files
  to check) Skipped"); and it runs only the pre-commit stage, so pre-push hooks go unexercised.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **release**: Drop [skip ci] from the PSR bump commit
  ([`88bd48b`](https://github.com/brunofaust/claude-all/commit/88bd48bb122e74f536b57999668e8d7b8163a13a))

It reads as harmless — "don't re-run CI for a bot's version bump". But GitHub applies skip-ci to the
  HEAD commit of push AND pull_request events, and that bump commit becomes the release PR's head.
  So it suppressed the `pull_request: closed` run on merge, which is the ONLY trigger for the
  publish job.

That is the whole bug. main was left bumped-but-untagged on BOTH the release/0.2.0 and release/0.3.0
  merges, and 0.2.2 was stranded and skipped entirely. It also meant every release PR merged with
  zero CI.

Diagnosed as a dropped webhook twice. It never was: a normal PR produced two runs (ci + release),
  while the release PR's `[skip ci]` head produced zero runs of any workflow — deterministic, not
  flaky. The prepare job's own idempotency guard (next == current -> exit 0) is what stops the bump
  push from looping, not `[skip ci]`, exactly as release.yml has documented all along. The config
  simply never matched its own comment.

Also raises the docstring gate to 100%. A percentage floor below 100 cannot say WHICH missing
  docstring is acceptable, so it drifts down to whatever today's code happens to score. The noise
  cases are carved out by name instead (ignore-magic, ignore-setters, ignore-overloaded-functions,
  ignore-init-module), so each exemption is a decision someone made rather than slack in a number.
  enforcement.md's bypass column said "raise the floor", which is not a bypass, and
  pyproject-toml.md documented no interrogate config at all — the skill mandated a gate it never
  showed you how to configure.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **release**: Stop uv.lock drifting on every release
  ([`e5b697d`](https://github.com/brunofaust/claude-all/commit/e5b697d1368dd4225999148e9cab7ec2ee873877))

python-semantic-release rewrites ONLY `pyproject.toml:project.version` — that is all `version_toml`
  points at. So the lockfile's record of this package's OWN version goes stale at the moment of
  every bump, and nothing notices: the drift surfaces later when someone's `uv sync` silently
  rewrites the line and dirties an unrelated working tree. That is exactly how it reached
  0.2.0-in-lock vs 0.3.0-in-pyproject.

Fixed at the source. The prepare job now runs `uv lock` right after the bump and folds the result
  into the same commit, because no prek hook runs in CI — the place the drift is created is the one
  place no gate was watching.

Adds the local half too: the astral-sh/uv-pre-commit `uv-lock` hook. It runs at pre-push, NOT
  pre-commit, because it REWRITES uv.lock and a hook that mutates a file fails the run it mutates on
  — deferring to push keeps `git commit` from bouncing on a lockfile refresh mid-work.

Verified the hook bites: desyncing the lockfile's self-version to 0.1.0 produced "uv-lock ... Failed
  / files were modified by this hook / Updated claude-all v0.1.0 -> v0.3.0", and a synced tree
  passes.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

### Build System

- **deps**: Sync uv.lock's self-version to 0.3.0
  ([`bf49046`](https://github.com/brunofaust/claude-all/commit/bf490467ad3f13a441d6d956596325b14a01adf6))

python-semantic-release bumps `version` in pyproject.toml on release but never touches uv.lock, so
  the lockfile's record of this package's OWN version goes stale on every release. The next `uv
  sync` silently rewrites that line and dirties the working tree, which is how it drifted to 0.2.0
  while pyproject.toml said 0.3.0.

This resyncs it. It does not fix the cause: the drift will reappear at the next release unless the
  release pipeline also refreshes the lockfile.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

### Documentation

- **brunofaust-python-style**: Record which ruff groups to reject, and why
  ([`5073843`](https://github.com/brunofaust/claude-all/commit/5073843fa19e8040b50f16f78c7297c1da7155aa))

pyproject-toml.md was a thin template: it listed rule groups to SELECT and said nothing about which
  to reject. Anyone can list selections. Knowing what to reject is what costs a day of measuring,
  and it was living only in one private repo's config comments.

The measured rejections, with their counts:

- DOC (pydoclint) — DOC501/DOC502 cannot trace exceptions through function calls: 196 false
  positives. The D rules already enforce presence, structure, and the Google convention. - blanket
  PLR — lights up ~346 style findings (PLR2004 magic-value, PLR6301 no-self-use, PLR0914
  too-many-locals). Keep only the complexity caps: PLR0911, PLR0912, PLR0913, PLR0915. - umbrella
  TRY — TRY003 alone is ~185 findings and is idiomatic here; TRY300 is ~30 of stylistic churn. Keep
  TRY002, TRY004, TRY201.

The counts are the point. A group that lights up hundreds of findings does not get fixed — it gets
  ignored, or noqa'd into meaninglessness, and the gate stops meaning anything. A number is what
  stops the next person re-enabling it.

Also lands:

- banned-api (TID251) ownership table, which makes "one owner per external system" mechanical rather
  than prose. Includes why botocore is owned by the AWS module: its wrappers TRANSLATE ClientError
  into semantic errors, and consumers catch those, so a caller importing botocore to catch
  ClientError has reached around the translation and re-coupled itself to the SDK's error
  vocabulary. - bandit and vulture skips where every single ignore states its reason — an ignore
  without one rots. - import-linter contracts; "X are mutually independent" is the reusable shape
  that stops sibling modules quietly importing each other.

Deliberately does NOT copy the upstream `exclude = ["tests/"]`. It is tempting (tests trip D, S105,
  S106) and it is wrong: this skill's entire data-modeling standard exists because a TEST FIXTURE
  lied — it matched neither the DB nor its TypedDict while mypy stayed green. Excluding tests from
  lint leaves the least-checked code in exactly the place the incident came from. Relax the
  genuinely test-only rules by name via per-file-ignores instead.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

### Features

- **brunofaust-python-style**: Add pydantic-contract AST gate
  ([`a04b0e2`](https://github.com/brunofaust/claude-all/commit/a04b0e23a2168bcd73a1293f6955fe137fbc3231))

An untyped dict carrying a contract lets a missing, blank, or renamed key slip through silently.
  TypedDict does not fix this — it validates nothing at runtime, so cast(row_dtype, dict(row)) is a
  no-op that only pretends to type. The bug class is not the .get(k, default) spelling; it is a
  default on a field that is required.

Adds checkers/pydantic_contract.py — a stdlib AST gate with eight rules:

- no-typeddict a TypedDict validates nothing at runtime - no-cast cast() asserts a type instead of
  proving one - extra-forbid no exceptions; a schema change needs a code change - masking-default
  optional => `| None = None`, required => no default - opaque-annotation bans the opaque VALUE
  (Any), not the container, so Mapping[str, str] and dict[Key, Model] stay legal - splat logging is
  the only exemption - select-star the rule extra-forbid depends on - secret-repr Field(repr=False)
  on credential/PII fields

Keys are line-independent, with a per-symbol ordinal on the repeatable rules so a second occurrence
  is a new finding rather than collapsing into the first one's baseline entry. Composes with
  regression-gates/baseline_gate.py.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **brunofaust-python-style**: Adopt the model-contract rules, and make gates self-checking
  ([`4a6733a`](https://github.com/brunofaust/claude-all/commit/4a6733adc65a9cdf700a71538ea92e19e4fe4e45))

A production migration proved a stricter set of model rules than this skill shipped, and surfaced
  two ways a gate lies. This adopts the rules, ports the new gate, reverses two now-wrong stances,
  and adds a wiring mandate.

New gate — checkers/model_contract.py (7 rules, no-typeddict stays in pydantic_contract.py, one
  owner per rule): - json-parse-then-validate: model_validate(orjson.loads(raw)) on a strict model
  throws away JSON type-context and REJECTS the UUID/datetime/enum it would coerce from raw bytes. A
  real caller failed open and skipped billing for months; it hid because the fixture list was empty.
  Use model_validate_json. - barrel-init: __init__.py is docstring-ONLY. RUF067 is insufficient — it
  permits the re-exports being banned (a barrel cost 324ms/12 submodules). - pydantic-config,
  verbatim-strip, no-alias, no-dataclass, private-access.

Reversals of guidance shipped earlier in this cycle (the new rules are better): - serialization.md:
  model_validate_json is Rule 0; aliases are now BANNED (an alias maps a renamed key to a default
  instead of failing loud). - data-modeling.md + SKILL.md: Pydantic is the default even internally;
  a @dataclass is the rare allowlisted exception for a proven STRUCTURAL reason, never "already
  validated". model_construct() for the hot path. Validation cost (~1-5us) is stated and accepted:
  robustness first, buy back speed narrowly. - Every model starts from one shared config; verbatim
  fields opt out of str_strip_whitespace.

Two gates that lied, now fixed: - pydantic_contract.py: MODEL_BASES is a --model-base option. A
  migration to a project base class silently blinded the equivalent gate (0 findings in a 285-model
  repo read as clean). The set names symbols and fails toward FALSE CLEAN. - baseline_gate.py
  records the seed command and fails loud when enforce runs a different (wider) path — a wider
  --baseline than the gate checks is silent amnesty (337 findings once slipped in this way).

Enforcement is per-project, and shipped != enforced. Installing the skill copies the checkers as
  FILES; it does not wire them into any project's prek.toml. A shipped-but-unwired checker is prose.
  SKILL.md now mandates: on every invocation, verify each checker is wired, pinned, and green on
  both stages, and auto-search for checkers present as files but absent from the hook config — a
  code change can mint a new gate.

references/incidents.md catalogs the six real failures behind these rules.

codecongruence.toml excludes skills/**/checkers/** and skills/**/scripts/**: the checkers are
  single-file copy-into-your-project templates and share dispatch scaffolding by design — the
  duplication is the portability, not debt.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **brunofaust-python-style**: Enforce the stdlib-library bans via ruff banned-api
  ([`29d9634`](https://github.com/brunofaust/claude-all/commit/29d96349191906f6dca6041de3c885f97ffd9cbd))

The skill's "Preferred libraries" table says orjson over stdlib json and structlog over logging, and
  its config rule says os.getenv goes through the Settings singleton — but only the SDK and thread
  bans were actually wired. These were prose. A rule in prose gets violated; a rule in a checker
  holds.

Adds json, logging, and os.getenv to the ruff banned-api (TID251) block — the same mechanism already
  enforcing aiobotocore/httpx/asyncio.to_thread ownership. Each carries its replacement in the
  message and one documented owner exception: a serde/codec boundary for stdlib json, the
  logging-bootstrap module structlog wraps, and settings.py for os.getenv.

These are the skill's OWN opinions, not generic guards, so they belong with the skill and are
  enforced at its prek/CI layer via ruff — not as default hooks. A project that also wants the
  edit-time layer (block the Write before it lands) can add equivalent PreToolUse guards, but the
  durable enforcement is the ban.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **brunofaust-python-style**: Flat test mirror and __all__ contract gates
  ([`a7aeca9`](https://github.com/brunofaust/claude-all/commit/a7aeca9887730f828a54f251a8f1d913755d3859))

Two more ports from a production gate set, plus the contradiction the first one exposed.

The test layout was contradictory. testing.md and project-structure.md both documented a NESTED
  mirror (tests/unit/features/pii_detection/test_service.py) while the convention actually run in
  production is FLAT. Both called themselves "mirror src/ 1:1" — the phrase is ambiguous, which is
  precisely how the two coexisted unnoticed for so long. Prose cannot arbitrate; the mapping is now
  mechanical: take the module's path under src/<pkg>/, replace every / with _, prefix test_. So
  src/myapp/core/aws/s3.py -> tests/unit/test_core_aws_s3.py.

- flat_test_mirror.py: rules not-flat, non-test-file, grab-bag. The last one kills the *_extra /
  *_coverage2 / *_boost parallel files that coverage-chasing produces — they belong in the module's
  own mirror. It walks the filesystem and never parses source, so unlike the AST gates it needs no
  language_version pin. - all_contract.py: rules not-in-all, private-in-all. `from x import y`
  requires y in x.__all__, and no _private name may be exported. __all__ IS the export contract;
  importing outside it couples you to an implementation detail that can move without notice. Handles
  relative imports, aliases, and dotted attribute access. A module with NO __all__ is skipped by
  design: it declared no contract, so flagging its importers would report the wrong file and would
  fire on every intra-repo import in a codebase that has not adopted the convention. "Every module
  must declare __all__" is a real but different rule needing its own gate.

enforcement.md retires two superseded rules rather than running both: the nested skill_enforcer.py
  rule test_mirrors_src (which contradicted the flat mirror), and the vague "pyright + AST
  __all__-contract hooks" row now that a real checker exists. Two gates for one rule is two sources
  of truth that disagree.

Also documents positively-verified allowlists as a shape to apply to every allowlist, not just the
  Lambda gate.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **brunofaust-python-style**: Gate Lambda event validation at the boundary
  ([`8df7fe1`](https://github.com/brunofaust/claude-all/commit/8df7fe1a509b1bda34dbb8fe560bfd3606ead0c3))

The skill has mandated "every Lambda entry point parses its event into a Pydantic model before any
  logic" since it was written, and nothing checked it. That is the seam where it matters most: the
  event is the most untrusted dict in the process, and a renamed field there ships silently.

Ported from a production gate. Rules: missing-validation, stale-allowlist.

Accepts BOTH sanctioned shapes rather than picking one — Model.model_validate( event) when the
  payload IS our shape, and Model(field=event.get(...)) which is often preferable for an AWS
  envelope, because model_validate on AWS's raw dict forces extra="ignore" (AWS adds fields we do
  not control) while extracting our own fields lets the model stay extra="forbid". A gate that
  permits every correct shape and documents the trade-off gets adopted; a one-true-way gate gets
  SKIP='d.

Also lands the pattern the port exists to steal: positively-verified allowlists. An exemption never
  just skips. `--allow api=Mangum` does not mean "skip api/" — it means "api/ is exempt BECAUSE it
  calls Mangum(...)", and the checker re-proves that predicate on every run. Refactor the proxy into
  a plain handler and the gate re-arms itself with a distinct stale-allowlist finding instead of
  leaving a permanent hole. A name-set allowlist cannot do that: it rots silently and never tells
  you the exemption outlived its reason. enforcement.md documents the shape to apply to every
  allowlist we add.

Same contract as the sibling checker: line-independent keys, exits 1 on findings so it wires
  straight into prek with no baseline artifact, --exit-zero only for composing behind
  baseline_gate.py, and fails CLOSED with exit 2 on a file it cannot parse.

Known gap: a handler.py that binds no entry point at all is silently clean. That is dead code Lambda
  cannot invoke, but it is a hole — the alternative classified every proxy/factory module as "not a
  handler", which is exactly what the allowlist exists to cover.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **brunofaust-python-style**: Pin the pydantic data contract
  ([`f6d2e7a`](https://github.com/brunofaust/claude-all/commit/f6d2e7a1752227f067df57cf10d5edf0040a3b22))

Corrects two rules that were actively harmful. The skill said "TypedDict only for static test data"
  — backwards: test fixtures are where TypedDict lies most, because it is a static annotation that
  validates nothing at runtime. And it said Pydantic was unnecessary for DB rows because "the DB
  schema already enforces" — a lie: one migration breaks everything, and cast(row_dtype, dict(row))
  enforces nothing. TypedDict and cast are now banned, and SKILL.md's *_dtype naming row, which
  taught the very pattern that caused the incident, is gone.

The bug class was never the .get(k, default) spelling; it is a default on a field that is required.
  Model the payload and the decision is forced.

- data-modeling.md: 11 rules — required-vs-optional is the contract, empty string is not a value, no
  opaque model fields, no ** splatting (logging is the only exemption), model our side of a boundary
  not the vendor's wire, extra="forbid" always (a schema change must force a code change; SELECT *
  banned so the row shape is one the code built), model where the shape is fixed, codec-or-nothing
  exemptions, blast radius, frozen-model gotchas, Field(repr=False) verified empirically. -
  serialization.md (new): cross a boundary with a model without changing the bytes on the wire —
  model_dump(mode="json") plus a round-trip proof. - enforcement.md: eight checker rows; retires
  no_dict_any_in_signatures (one gate per rule) and stops recommending cast() as the no-any-return
  escape hatch — model_validate() proves the type instead of asserting it. - merge-main,
  mock-drift-sweep: name dict->model as a semantic-conflict class. New code doing dict-style access
  on a newly-modelled type merges clean and crashes at runtime. A clean textual merge is not a clean
  merge.

Core principle "immutable parameter types" is untouched: only the opaque VALUE (Any) is banned,
  never the container. Mapping[str, str] and dict[Key, Model] stay legal.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **brunofaust-python-style**: Restore the Python 3.14 baseline
  ([`8693fbe`](https://github.com/brunofaust/claude-all/commit/8693fbe9e74245a33738879549f7152bb49d8265))

The skill was 3.14 in its private origin and was downgraded to 3.11+ during the port to this public
  repo. This reverts that. It is not a find-and-replace: a 3.14 floor inverts rules the skill
  stated.

- `from __future__ import annotations` flips from MANDATED to ANTI-PATTERN. PEP 649 makes
  annotations lazy by default, so the import is dead weight — and unlike PEP 563 they still resolve
  to real objects for get_type_hints() / Pydantic / dataclasses. - PEP 695 becomes the baseline
  rather than the upgrade: `type EntityId = str`, `def first[T](...)`, `class Stack[T]`, `async def
  run[**P, T]`. TypeVar / ParamSpec / Generic[...] demote to a read-it-don't-write-it legacy note.
  Alias naming moves snake_case -> PascalCase, forced by `type`: an alias must not read as a
  variable. - PEP 758 paren-less `except ValueError, TypeError:` is available — but ONLY without an
  `as` clause. `except A, B as e:` is a SyntaxError, so the parenthesised form stays required when
  binding. Verified against CPython 3.14.6. - PEP 734 InterpreterPoolExecutor is available on the
  baseline; the when-to-reach-for-it vs run_in_thread() judgement is unchanged.

A 3.14 floor also makes the prek `language_version` pin mandatory rather than advisory: PEP 695 and
  PEP 758 are exactly the syntax an older hook interpreter cannot parse, and such hooks skip the
  file silently and still exit 0.

Two always-injected surfaces were teaching the opposite of the skill and are fixed here:
  claude_md.md and hook.py both still advertised TypedDict as a recommended strict-typing tool after
  the skill banned it.

claude-all itself stays requires-python = ">=3.11" — it is the installer, not a project following
  this skill. The shipped checker keeps its `from __future__ import annotations` for that reason,
  now with a comment explaining why it is not a violation of the standard it enforces.

BREAKING CHANGE: the brunofaust-python-style baseline moves from Python 3.11+ to 3.14+. Projects on
  3.11-3.13 must keep `from __future__ import annotations` and the TypeVar/Generic form, and should
  pin the skill's previous revision.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w


## v0.3.0 (2026-07-15)

### Bug Fixes

- **ship-pr**: Open PR ready for review instead of draft
  ([`5e8074c`](https://github.com/brunofaust/claude-all/commit/5e8074cceea06419253b578a319970943ca6113c))

The draft default forced an undraft step on every PR. /ship-pr now opens the PR ready for review
  (still confirmed, still no auto-merge). Updated SKILL.md, the claude_md.md snippet, the nudge
  hook, and the README row.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

### Chores

- **aws-debug-loop**: Apply ruff-format line wrapping to log_sweep.py
  ([`a4d605d`](https://github.com/brunofaust/claude-all/commit/a4d605d0eed8541d5fb4c44ec7ab8ae3fbd61c9f))

Wrap the long argparse add_argument calls, the sqlite INSERT tuple, and the report() signature so
  every line is <=100 chars. Formatting only, no behavior change (smoke test still green: 3 hits,
  per-stream rowid ordering intact).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

### Documentation

- **brunofaust-python-style**: Document the process-global handled-exception logger
  ([`9456183`](https://github.com/brunofaust/claude-all/commit/9456183d6f6dfc70e70c836a63190119903d2596))

Adds a "Process-global handled-exception logger — the DEBUG safety net" section to
  error-handling.md: register ONE sys.monitoring (PEP 669, 3.12+) EXCEPTION_HANDLED callback that
  DEBUG-logs every handled exception centrally, instead of scattering log.debug across handlers
  (which no_debug_in_except bans). Documents the non-negotiable design points (feature-flag
  default-off so no tool id is claimed = zero overhead; filter control-flow exceptions; per-thread
  reentrancy guard; idempotent install + uninstall for xdist tests; install per entry point) with a
  genericised code sketch. Reconciles the existing "no silent swallow / no log.debug in except" rule
  via a forward-pointer: with the global safety net installed, a benign expected swallow may be left
  clean; reserve an explicit warning/error in the except body for a genuinely notable failure.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

### Features

- **aws-debug-loop**: Add all-groups awslogs log sweep
  ([`8ff093b`](https://github.com/brunofaust/claude-all/commit/8ff093bde3e315121bfc66c8dfcfd520591e8c57))

The highest-yield move when a symptom has no obvious owner: pull EVERY log group for the env with
  `awslogs`, grep a fixed error-signature set, dedupe into a table, and loop (re-sweep to confirm
  each fix). Catches crashes in scheduled/async resources that the happy-path e2e and a
  single-resource probe both miss. Wired into Phase 1 (gather) and Phase 3 (regression gate), plus a
  new rule and README row.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **aws-debug-loop**: Add stdlib log_sweep.py (awslogs -> sqlite, errors only)
  ([`2b95393`](https://github.com/brunofaust/claude-all/commit/2b95393f5dd408fe5906d907def22afd0a250c32))

Token-cheap automated sweep: loads every CloudWatch event into a stdlib sqlite3 DB and prints only a
  deduplicated error table (group, snippet, rowid), so the caller spends tokens on real failures — a
  clean sweep is one line. Fetch degrades boto3 -> aws CLI -> awslogs; if all fail it warns.
  Structlog JSON gets level/event parsed and the object kept in a `fields` column (json_extract);
  rows are ordered per stream so `id +/- N` gives real context. No new deps (installer stays
  stdlib-only). Wired into the skill's sweep section + README row.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **hooks**: Add mock-spec-guard to kill mock drift at edit time
  ([`0c9a506`](https://github.com/brunofaust/claude-all/commit/0c9a5065a5f6901ffa4369c0fae92ac38bdb9181))

Non-blocking PreToolUse reminder that fires when a Python test file gains a bare
  MagicMock()/AsyncMock() (no spec=/autospec=/wraps=). Mock drift is the #1 silent-failure class — a
  bare mock accepts any signature, so a change to the real function won't fail the test; it steers
  generation toward autospec=True / spec=RealClass / create_autospec. Silent unless the pattern is
  present, test files only; opt out with CLAUDE_ALL_MOCK_SPEC_OK=1. hooks.json + README section 3
  updated.

Also fixes two ruff findings that landed on main in secret-leak-guard.py (SIM103, E501) so the gate
  is green.

- **hooks**: Edit-time skill enforcement — test-data guard + fix python-style auto-load
  ([`4f82433`](https://github.com/brunofaust/claude-all/commit/4f82433c1cf1d49c04231ba33b7f86f56581b534))

From the session-harvest of the project's Claude Code history.

New test-data-isolation-guard: a non-blocking PreToolUse Edit/Write/MultiEdit reminder that fires
  when a test file hard-codes a tenant/scope id literal (org_id/tenant_id/project_key =
  <int|string>). Shared/hard-coded ids make tests fight over rows (flaky under xdist) and let an FK
  cross a tenant boundary. The style guide already documents the rule; prose alone kept getting
  violated, so this is the checker. Silent unless the smell is present; deduped per (session, file);
  a fixture/variable value (org_id=org.id) never matches.

Fix python-style reminder auto-load: the SessionStart loader and the edit-time
  brunofaust-python-style hook shared ONE dedup flag, so the session-start nudge suppressed the
  high-signal reminder at the first real .py edit — the skill often never loaded when editing
  Python. Give each its own flag so the first .py edit always reminds (at most one session-start +
  one first-edit reminder per session).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **hooks**: Re-fire the python-style reminder hourly, not once per session
  ([`48a9a68`](https://github.com/brunofaust/claude-all/commit/48a9a68be220b0f147cc3038ac87e5abe6b2deff))

The edit-time brunofaust-python-style reminder deduped once per session, so on a long session it
  reminded only once, hours before later Python edits. Now the flag mtime is the last-fired time and
  the reminder re-fires at most once per hour, so the conventions stay fresh across a long session.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w

- **hooks**: Re-fire the skill reminder hooks hourly, not once per session
  ([`306bb93`](https://github.com/brunofaust/claude-all/commit/306bb9310d217f967c0fbb435948f32a1fe2fd42))

Applies the same hourly-TTL pattern already added to brunofaust-python-style to the other 10
  self-contained skill reminder hooks (react-*, web-design-guidelines, seo, alembic-migration,
  ship-pr, merge-main, aws-architecture). Each stays fully self-contained (only stdlib `time` added,
  no shared import): the per-session flag mtime is the last-fired time and the reminder re-fires at
  most once per hour, so a long session keeps each skill's conventions fresh instead of being
  reminded once, hours earlier. Behaviour-only; message text unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_0193MfC1zoeDxQfjiLoknH1w


## v0.2.1 (2026-07-07)

### Features

- **hooks**: Add worktree-isolation + secret-leak guards and 4 CLAUDE.md snippets
  ([`b3e0cd5`](https://github.com/brunofaust/claude-all/commit/b3e0cd5b4973110a40cf70a809fcc3866f4c0d67))

worktree-isolation-guard pauses an Edit/Write on the primary checkout of a protected branch
  (main/master) — the parallel-session corruption case; opt out via CLAUDE_ALL_ALLOW_MAIN_EDITS.
  secret-leak-guard hard-blocks a git add/commit/push that stages a credential file or embeds a live
  sensitive env-var value in the outgoing diff (the value-in-content gap gitleaks misses), reporting
  only the file/var name. Adds response-style, worktree-isolation, secrets-in-shell and
  commit-cadence instruction snippets. README §3/§7 and hooks.json updated.


## v0.2.0 (2026-07-06)

### Bug Fixes

- **release**: Register release/** as a PSR release-eligible branch group
  ([`5473f52`](https://github.com/brunofaust/claude-all/commit/5473f52f3b4bf1604e5fa45c04ddf6dec8292256))

python-semantic-release>=9 ignores the legacy flat `branch = "main"` key — it only recognizes nested
  `[tool.semantic_release.branches.<name>]` groups. Without one matching `release/.*`, the `prepare`
  job in release.yml (which runs `semantic-release version --print` on the release branch itself,
  before it's merged to main) reported "isn't in any release groups" and computed no version,
  silently no-opping. Verified locally with `uvx --from "python-semantic-release>=9,<10"
  semantic-release version --print`, which now correctly resolves to 0.2.0.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

### Chores

- **ci**: Add workflow_dispatch escape hatch to the release publish job
  ([`965e132`](https://github.com/brunofaust/claude-all/commit/965e1327421e041fe6065ddbc29b56faa0cfef29))

Merging the release/0.2.0 PR (#75) produced no `release` workflow run at all — the `pull_request:
  closed` webhook was never delivered/fired, so main was left bumped to 0.2.0 with no git tag or
  GitHub release. Verified via the Actions API: no run record exists for that merge event, unlike
  prior release-branch merges which fired normally.

Adds `workflow_dispatch` as a trigger and allows the `publish` job to run from it, so a missed
  webhook delivery can be manually recovered with `gh workflow run release.yml --ref main` instead
  of hand-running the tag + release steps. Safe to re-run any time — `publish` already skips
  tagging/releasing when the version is already published.

Also excludes CHANGELOG.md from the typos hook: it's machine-generated by python-semantic-release
  and its commit-hash links occasionally collide with real words (e.g. a hex substring flagged as a
  misspelling).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

### Features

- **tools**: Convert code-review-graph plugin to a uv_tool
  ([`bdc1236`](https://github.com/brunofaust/claude-all/commit/bdc123675dd65b2f59ceb1247289d1485ebcf945))

Installs via `uv tool install "code-review-graph[communities,enrichment] @ git+..."` instead of
  pipx, matching how rtk is installed as an OS-level tool. Adds `type: uv_tool` support to the tools
  installer alongside the existing `brew` type, and drops the now-unneeded pip post_install step for
  igraph since the `communities`/`enrichment` extras already pull in igraph and jedi.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>


## v0.1.1 (2026-07-05)

### Bug Fixes

- **hooks**: Set executable bit on python-style-skill-loader.py
  ([`9ab4734`](https://github.com/brunofaust/claude-all/commit/9ab473458282bc213e253e1cd8a7528da2cd2f8c))

Every other script in src/claude_all/hooks/ is mode 100755; this one was still 100644. The installer
  chmods hooks at symlink time (PR #55), so this didn't break installs, but the repo file itself
  should match its siblings — e.g. running it directly
  (./src/claude_all/hooks/python-style-skill-loader.py) requires the bit.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01L7RCABTvHrKdyHKPxYWQ1a

### Documentation

- **python-style**: Aws owner-translated semantic exceptions pattern
  ([`0669112`](https://github.com/brunofaust/claude-all/commit/0669112046e53f14d08fc9e6f465f97dcbc6e40c))

Documents the pattern where a core/aws wrapper catches botocore ClientError and re-raises a typed
  error it owns (via a translating(code_map, default) context manager), so consumers catch typed
  exceptions (dynamodb. ConditionalCheckFailed, s3.ObjectNotFound, ...) and never import botocore.
  Adds the `botocore` banned-api entry + a "Semantic exceptions" section to
  external-system-ownership.md, and a full worked example (exceptions.py helper, owner, consumer) +
  rules to error-handling.md. Distilled from a real end-to-end migration across 7 AWS services.

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01KCCsDA5Ex6Qc9AFPFtpUY5

- **python-style**: Core/ organize-by-domain + mechanism-vs-policy policy
  ([`7a1727f`](https://github.com/brunofaust/claude-all/commit/7a1727f53196d5cd2717248880cf24c0012bc4d1))

Adds the anti-file-explosion policy to project-structure.md: organize by DOMAIN CONCEPT never per
  business requirement; one file per domain, package only when genuinely large AND has real variant
  seams (containment over layering, decided on post-dedup size); mechanism-vs-policy layering
  (domain code is glue over generic core/ owners; promote a generic on the third copy); and
  enforcement (root-allowlist gate + the measured lesson that a semantic-duplication gate belongs at
  a HIGH threshold, since lowering it surfaces noise not reuse). Distilled from a real core/
  consolidation design.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01KCCsDA5Ex6Qc9AFPFtpUY5


## v0.1.0 (2026-07-03)

### Bug Fixes

- Align docs with reality, add mypy gate, repair broken skill frontmatter
  ([`34c6639`](https://github.com/brunofaust/claude-all/commit/34c6639e01e4447adaae804a4e96fc405d584fd7))

- CLAUDE.md documented a nonexistent CLI (`install <name> --level user`); replace with the real
  syntax (`./claude-all --all --user <name>`) and fix the stale 'hooks not yet active'
  repo-structure row - prek gate claimed to run mypy but had no mypy hook — add mirrors-mypy scoped
  to the installer/scripts/hooks/tools and fix the 4 errors it found in claude-all.py - update_item:
  handle tools and hooks kinds — previously 'update all' failed them with 'missing target path in
  state' - skills/generic/requirements-ears: restore SKILL.md YAML frontmatter that a markdown
  formatter had mangled (skill was undiscoverable metadata-wise) - README: add missing rows for
  repo-cleaner agent and repo-audit / session-harvest / requirements-ears skills - gh-runner:
  replace a real company name in an example with 'Acme Inc' per the repo's placeholder rules

https://claude.ai/code/session_01BnNQt6eW4XcXBf8aVPNmFM

- Remove stray code-review-graph artifacts and correct model labels in 4 agent descriptions
  ([`176b136`](https://github.com/brunofaust/claude-all/commit/176b136e9bc5978ec43a32e28cdb235b0821590a))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Repo-wide review pass — leaks, guard gaps, installer bugs, skill compression
  ([`89c3234`](https://github.com/brunofaust/claude-all/commit/89c3234d935912df455346f5cfcaab2a49c5b40a))

- Sweep real-project names + tool-call artifacts from agents/skills; add banned-project-names prek
  gate (pygrep; vendored dirs excluded) - Guard hooks: block rm -R / rm -rf /*, anchor override
  markers to leading env assignment, config-protection pauses via permissionDecision "ask",
  dev-server bypass honors run_in_background - claude-all.py: exit 1 on failed installs;
  companion-hook purge scoped to .claude/hooks paths across all events (no double-fire, no foreign
  unwiring) - vendor_sync.py: normalize injected frontmatter before drift compare, exit 1 on drift
  in --check, refuse symlinked upstream files - prek-stop-runner: stop_hook_active bail, shared 50s
  budget, loud exit-1 notice when the gate itself can't run - regression-gates checkers: stable keys
  without line numbers, walk excludes, per-dir migration graphs (loose file args = one tree) - Unify
  reviewer severity scales; preview-and-stop confirmation for deployer agents; repair broken fences;
  fix stale vercel-* skill names; SEO bot policy - Compress prek (1060→432), aws-architecture
  (583→366), seo SKILL.md — moved verbatim into references/ - Agent model claude-sonnet-4-6 →
  claude-sonnet-5 (16 agents) - README/CLAUDE.md synced to the new behavior

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01W1NRmDUgFVXuc7ucYh1gAS

- **agents**: Enforce verbatim error output in all log/trace agents
  ([`3b76b64`](https://github.com/brunofaust/claude-all/commit/3b76b643e34e850318a293b0ca2a5596eabca38c))

step-functions-tracer + cloudwatch-inspector: added IAM/permission error anti-pattern with concrete
  before/after (ECS task role missing ssm:GetParameter paraphrase that masked a correct IAM policy).
  log-filter: added full CRITICAL verbatim section. incident-responder: requires sub-agent error
  blocks passed through verbatim into timeline. debugger: Evidence fields must quote exact error
  text, paraphrase-only evidence counts as inconclusive. Root cause: agents were
  interpreting/summarizing error messages instead of quoting them verbatim, sending debugging
  sessions down false trails.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **agents**: Git-cleanup skips dirty items instead of blocking
  ([`b229870`](https://github.com/brunofaust/claude-all/commit/b22987081dfbfadc4dfb959ab1bec7bb3a0c805e))

Dirty worktrees now skip-and-warn instead of blocking all cleanup. Added noise filter (.DS_Store,
  *.pyc, __pycache__, node_modules, etc.) so worktrees with only noise changes are treated as clean.
  Updated classification table labels and removed "stop here" gate from Step 3.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **agents**: Return full verbatim hook output on commit failure
  ([`569dad8`](https://github.com/brunofaust/claude-all/commit/569dad80e65a24b873b76889f2fea04a74fce257))

On hard hook failure (lint, type errors, secrets scan), return the complete untruncated output to
  the caller — never summarise or truncate. Caller needs full text to diagnose and fix. Agent must
  not attempt fixes.

Autofix retry (formatter-rewrote-files pattern) kept: one retry after re-staging hook-modified
  files, then stop if still failing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **content**: Repair agent recipes, skill reference code, and reminder-hook wiring
  ([`75c3465`](https://github.com/brunofaust/claude-all/commit/75c346562e4e2cd242a7e6d3f1eacc31a0fda4f7))

Content-level review of all agents, skills, hooks and instructions (three review sweeps +
  verification). Highlights:

Agents: - secrets-fetcher: repair broken markdown fencing that swallowed the
  allowlist/banlist/redaction/rules sections into code blocks - python-module-migrator (+ companion
  skill): grep -E lookbehind matches nothing — rewrite loop touched zero files and verify gate
  falsely passed; lookbehind now lives only in perl - aws-lambda-deployer: canonical invoke recipe
  read unexported OUT/META (KeyError); profile/region silently defaulted against its own rule -
  terraform-deployer: churn gate read plan.out but the plan is saved as tfplan.out — gate never
  fired; apply errors now returned verbatim - terraform-reviewer: body told a 'never executes
  Terraform' agent to run terraform plan — now static review + read existing plan files -
  ecr-manager: wrong --query paths (imageScanFindingsSummary, scanStatus) — CVE block always
  returned null - env-audit/env-sync: make|tail||fallback chains lacked pipefail — fallbacks were
  dead code and failures read as success - gh-runner: invalid gh --json fields (checks,
  workflowName) - python-deps: 'uv pip audit' doesn't exist → uvx pip-audit -
  e2e-scenario-runner/email-inspector: tools: frontmatter excluded the MCP tools the body requires;
  removed impossible agent-to-agent delegation instructions (also debugger) - rds-postgres-query:
  unqualified 'COPY ... TO is allowed' permitted COPY TO PROGRAM (command exec as DB OS user) — now
  STDOUT-only - test-runner/gh-runner/code-quality/frontend-builder: align error reporting with the
  house verbatim rule (≥3 closest frames, no '+N more' truncation of type errors) - contradictions:
  sqs-monitor read-only vs DLQ redrive, docker-runner -f, test-runner --lf, log-filter traceback
  caps, cloudformation describe-change-set misfiled as a write, BSD-only date, fabricated advisory
  about a real PyPI package replaced with placeholder, etc.

Skills: - 7 reminder hooks never fired on Write (read new_string only; Write sends content) and used
  exit 1 + stderr, which reaches neither Claude nor blocks — now exit 0 + additionalContext JSON,
  firing on both - claude-hooks: Stop hooks CAN block (exit 2); fixed wrong description of
  config-protection - brunofaust-python-style references: NameErrors from half-applied rename,
  invalid except* syntax, smart-quote SyntaxErrors, super() with no base, PEP 695 syntax on a 3.11
  baseline, fail-fast example that didn't exit, boto3 banned in its own designated owner folder,
  escaped code fences, self-contradicting test guidance - aws-architecture: nonexistent 256 MB ZIP
  limit in the always-on claude_md snippet; TransactWriteItems 25→100; SnapStart Python 3.12+;
  reconciled Lambda-chaining contradiction - alembic-migration: ALTER TYPE ADD VALUE transactional
  claim outdated (PG 12+); reconciled the two contradictory ENUM recipes - prek: private hook repo
  name in documentation example → myorg/myhook - code-review-discipline claude_md verdict aligned
  with the skill (HIGH→BLOCK, not WARN) - verification-loop Phase 2 reconciled with the prek skill's
  'never run gate tools directly' rule - wrong installer syntax in
  repo-audit/session-harvest/vendored-sources; vendored skill referenced by wrong (unprefixed) name
  in 3 places

https://claude.ai/code/session_01BnNQt6eW4XcXBf8aVPNmFM

- **content**: Resolve deferred review items — dangling refs, git agent trigger overlap, naming-rule
  exception
  ([`1d40442`](https://github.com/brunofaust/claude-all/commit/1d4044219727058118dc05df90071df76b686a52))

- self-rationalization-guard / subagent-prompting / code-review-discipline / requirements-ears:
  remove or inline references to skills that don't exist in the repo (brainstorming,
  test-driven-development, superpowers-extended-cc:dispatching-parallel-agents) — point at in-file
  sections or upstream Inspiration links instead - git-audit vs git-cleanup: sharpen colliding
  dispatch triggers (audit no longer claims 'clean up branches'; cleanup no longer claims the
  ambiguous 'clean the repo' that also collided with repo-cleaner) and add explicit cross-references
  in both descriptions, the claude_md snippet, and README - CLAUDE.md: codify the functional
  exception for real hook names in agent dispatch triggers (lint-fixer's codecongruence triggers
  stay — dispatch must match real command output; illustrative examples still use myorg/myhook) -
  README: hook-injection section still described the old exit-1/stderr reminder semantics — updated
  to exit 0 + additionalContext JSON - caching.md verified against cachebox 6.1.0 (TTLCache
  global_ttl kwarg, cached(lambda self: ...) on sync+async methods, per-instance isolation) —
  correct as written, no change needed

https://claude.ai/code/session_01BnNQt6eW4XcXBf8aVPNmFM

- **docs**: Add missing Args sections to resolve D006 codecongruence violations
  ([`233a32e`](https://github.com/brunofaust/claude-all/commit/233a32e33332c24d5e7135e691db8defd0faaf80))

Added docstring Args: sections to 11 functions in claude-all.py and 1 function in
  coding/hooks/dev-server-tmux.py to satisfy codecongruence D006 linting rule.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **hooks**: Correct git-clean guard regex and prek failure detection
  ([`f63be1b`](https://github.com/brunofaust/claude-all/commit/f63be1bd1bc8414ab42526396bed8650eddc0d19))

- destructive-command-guard: the git clean pattern's alternation was ungrouped, so ANY command
  containing '--force ... -d' (e.g. 'pip install --force-reinstall -d out') was hard-blocked; anchor
  the pattern to 'git clean' and catch reordered flags like '-df' too - prek-stop-runner:
  is_real_failure could mask a genuine hook failure whenever check-added-large-files noise appeared
  in the same output, and swallowed unrecognized failure output; now every failing line except the
  known-noise hook counts, unknown output is surfaced - stale comment (warn path exits 0, not 1);
  README: suggest-compact counts all tool calls, not edit-class only

https://claude.ai/code/session_01BnNQt6eW4XcXBf8aVPNmFM

- **hooks**: Guard pipe-to-shell warn matches bash/zsh, not only sh
  ([`9c84b44`](https://github.com/brunofaust/claude-all/commit/9c84b4471f113517aa088bb2c26f62bba1752e09))

The curl|wget pipe-to-shell WARN pattern matched only `| sh`, missing `| bash`, `| zsh`, etc. Use
  `\w*sh\b` so all shells are caught. Re-verified: sh/bash/zsh/ sudo-bash/dash all warn; `echo bash`
  does not match; block/allow cases unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **hooks**: Make Stop/Bash-guard hooks executable + enforce +x on install
  ([`c812bfd`](https://github.com/brunofaust/claude-all/commit/c812bfd49bdb92de4681966a043c758d86a25cb8))

prek-stop-runner.py and destructive-command-guard.py were committed as mode 100644. Claude Code
  execs hooks by bare path, so a non-executable script fails with '/bin/sh: ...: Permission denied'
  (seen on a fresh checkout). Set both to 100755 to match the other hooks, and have inject_hook()
  chmod +x the symlink target so a future non-exec hook can't reintroduce the bug.

- **hooks**: Mark supply-chain-guard executable + document params
  ([`d91a28c`](https://github.com/brunofaust/claude-all/commit/d91a28c1c6610e2b35aa09f09ccd1964147374e9))

Set the executable bit on supply-chain-guard.py so it matches every other hook in hooks/ (all
  100755) — it was the lone 100644, which can fail when the hook is run directly. Also add Args:
  docstring sections to nudge, analyze, classify, _uv_upload_time, and cooldown_findings to clear
  pre-existing codecongruence D006 (params_in_docstring) findings that block any commit touching the
  file.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01DbtP1jWDZYUMaZ9USuzRSR

- **hooks**: Prek-stop-runner skips commit-ceremony hooks (no-commit-to-branch)
  ([`0445139`](https://github.com/brunofaust/claude-all/commit/044513918821b6e49f72f0e4f005494511991f7a))

prek-stop-runner runs the pre-commit STAGE as a lint batch on edited files at Stop — which wrongly
  includes `no-commit-to-branch`, failing purely because you're on `main` (no commit is happening).
  Skip commit-ceremony hooks via the SKIP env var (merged with any user SKIP); they still run on a
  real `git commit`. Verified: SKIP=no-commit-to-branch applied, user's SKIP preserved.

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>

- **hooks**: Surface non-blocking reminders via exit-0 JSON, not hook errors
  ([`5af8ec2`](https://github.com/brunofaust/claude-all/commit/5af8ec22d141740eee7f6970e10d6c0f19c8dd32))

Non-blocking hooks exited 1 + stderr, which Claude Code renders as '<hook> hook error: Failed with
  non-blocking status code'. That label is misleading: nothing failed, the hook is just nudging.

Switch the non-blocking paths to exit 0 + structured stdout JSON: - config-protection: all branches
  -> hookSpecificOutput.additionalContext - suggest-compact: -> systemMessage (normal user warning)
  - destructive-command-guard: WARN branch -> additionalContext (the catastrophic BLOCK branch stays
  exit 2 — a real block, not a failure)

Behavior is unchanged (still non-blocking); only the rendering changes: guidance now reaches
  Claude/the user as a reminder/warning instead of an error notice.

- **installer**: Chmod +x standalone hooks on install
  ([`841f2ca`](https://github.com/brunofaust/claude-all/commit/841f2ca7f0c9275a05cb6aabb65b6e8d3ac611c6))

install_standalone_hook symlinked the hook script but never set the executable bit, so hooks under
  hooks/ that weren't already +x in the repo failed at runtime with "Permission denied" (Claude Code
  execs the hook by bare path). Add the same `chmod | 0o111` the companion-hook path (inject_hook)
  already does, right after the symlink.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01DbtP1jWDZYUMaZ9USuzRSR

- **merge-main**: Resolve ruff E501/format + rework flow to auto-resolve
  ([`24edde6`](https://github.com/brunofaust/claude-all/commit/24edde6b344cae3525438b4c3c5062c5629b9b47))

ruff-check flagged two E501 lines in the nudge hook string and ruff-format reflowed the regex; both
  fixed (max line 98, ruff check + format clean).

Reworks the skill flow per the intended use: calling /merge-main IS the decision to merge, so it no
  longer gates on a "should I merge?" decision. New sequence: check incoming changes → check
  semantically → merge → resolve textual conflicts → resolve semantic conflicts (validated by the
  lint/test gates) → summarize. It only stops to ask on huge differences or high-risk impact
  (security contracts, schema/migration, ambiguous either-side resolution). SKILL.md, claude_md.md,
  README, and the hook nudge message all updated to match.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_014KmbE6iNDha5pPL5QshMns

- **python**: Align brunofaust-python-style skill to the repo's 3.11 baseline; add suppress()
  justifications
  ([`6fc3e23`](https://github.com/brunofaust/claude-all/commit/6fc3e234cba79967d4deb3ec88873ab45201e6a5))

Audit of the repo's first-party .py files against the brunofaust-python-style skill. The repo is
  `requires-python >=3.11` (ruff target py311), but the skill asserted Python 3.14+ — so the files
  were flagged for `from __future__ import annotations`, which is in fact CORRECT on 3.11-3.13. Per
  direction, keep the Python version and adapt the skill instead.

Skill adapted 3.14+ -> 3.11+ (keeps features that exist in 3.11: TaskGroup, add_note,
  ExceptionGroup/except*, pipe unions, match): - SKILL.md: version line + idioms header; `from
  __future__ import annotations` flips from "never (PEP 649)" to "use on 3.11-3.13 for deferred
  annotations (PEP 563), redundant on 3.14+"; multi-except uses parenthesised tuple (PEP 758
  paren-less form noted as 3.14+ only). - claude_md.md + reminder hook.py message: 3.14+ -> 3.11+. -
  references/error-handling.md: Pattern 4b -> parenthesised `except (A, B):`. -
  references/type-hints.md: TYPE_CHECKING note reframed for the 3.11 future-import; generics shown
  with TypeVar/Generic baseline, PEP 695 inline as a 3.12+ upgrade. - references/async-patterns.md:
  InterpreterPoolExecutor flagged unavailable < 3.14. - references/pyproject-toml.md: ruff
  target-version py314->py311, mypy 3.14->3.11.

Real .py fix (version-independent): the standard allows narrow `contextlib.suppress(SpecificError)`
  only with a justification comment. Added comments to all 9 sites — 7 skill hooks
  (`suppress(OSError)` best-effort flag write) and claude-all.py (`suppress(curses.error)` x2,
  screen-edge addstr).

Not changed (file-class N/A, documented in the PR): stdlib `json` and `os.environ` in
  zero-dependency hooks (orjson/Pydantic-Settings would break them); async-first/uvloop (hooks are
  sync stdin/stdout filters).

ruff check + format clean; prek clean.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **python-style**: Make skill loading explicit on .py edits
  ([`0247509`](https://github.com/brunofaust/claude-all/commit/0247509040f58d27966cd283cb339e99cff24d65))

The brunofaust-python-style claude_md.md said only "Apply when writing/editing Python files" and
  inlined the key rules, so Claude read the summary and proceeded without ever invoking the Skill
  tool to load the full SKILL.md + references/. The PreToolUse hook likewise only emitted a rule
  reminder, not a load directive.

Make the load explicit in both wiring paths: - claude_md.md: direct invoking the skill (Skill tool)
  before non-trivial .py edits and reading the matching references/<topic>.md; frame the inline
  rules as a reminder, not a substitute. - hook.py: reword the once-per-session reminder to nudge
  invoking the skill + reading references first, rather than just listing rules.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01VEYbYZjWfFXztJCPABvSHv

- **release**: Stop pushing the version bump straight to protected main
  ([`b60bfbd`](https://github.com/brunofaust/claude-all/commit/b60bfbde9f5858bb65af4918edfadd124f3e6b2a))

python-semantic-release's `semantic-release version` tried to commit and push the bump directly to
  main, which GitHub's branch protection rejects (main requires PRs). Split the workflow into
  `prepare` (bumps the version on the release/** branch itself on push — that's unprotected — so the
  bump lands on main through the normal PR merge) and `publish` (on merge, tags the already-bumped
  main and creates the GitHub release; tags aren't branch-protected). Mirrors the fix already
  shipped in brunofaust/codecongruence.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01L7RCABTvHrKdyHKPxYWQ1a

- **skill**: Rename _lookup to lookup_cache — no underscore-prefixed module-level names
  ([`bcd9df2`](https://github.com/brunofaust/claude-all/commit/bcd9df2d4bc1f3654a9f45b5f4f9437759abc662))

- **skills**: Correct "unparseable" -> "unparsable" (typos hook)
  ([`fc28738`](https://github.com/brunofaust/claude-all/commit/fc2873883b807a715ed5f12e33fef5d6334fe54c))

The prek `typos` gate flagged "unparseable" in the regression-gates skill and two example checkers.
  Use the spelling typos accepts.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **style**: Prohibit contextlib.suppress(Exception) as anti-pattern
  ([`10de6ea`](https://github.com/brunofaust/claude-all/commit/10de6eabfb5798a7b8f3e481a5b525c7dc8f87a4))

Updated architectural rule 3 (error handling) to explicitly prohibit contextlib.suppress(Exception)
  — it silences all exceptions including bugs and OOM. Only suppress(SpecificError) allowed with
  inline justification. Updated quick rules section and review checklist to reflect this standard.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **suggest-compact**: Wording reflects all-tools counting
  ([`51d77ef`](https://github.com/brunofaust/claude-all/commit/51d77ef7a7482af732b5f82124fc905cb87c1a1f))

The hook is wired with matcher "" (all tools), but its docstring and message said "edit-class" /
  "Edit|Write", which is why it surfaced on a Bash call. Counting all tool calls is the intended
  behavior for context pressure; update the docstring, comment, and message to say "tool calls".

- **tools**: Harden lean-ctx setup.py TOML serialiser
  ([`b7632e6`](https://github.com/brunofaust/claude-all/commit/b7632e6054b8632a21daa7909919aa046686eec0))

- escape strings via json.dumps (backslashes/quotes corrupted output before) - reject arrays of
  tables explicitly instead of writing Python repr - preserve empty tables on round-trip - validate
  serialised TOML before overwriting the existing config

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Chores

- Compact claude_md snippets and agent descriptions to reduce CLAUDE.md size
  ([`477c89b`](https://github.com/brunofaust/claude-all/commit/477c89b034d0c97d73d8eed5a1fa6824b122b024))

Reduced ~/.claude/CLAUDE.md from 75k to 45k bytes (40% reduction): - Compacted 53 claude_md.md
  snippet files (62% size cut: 53.5k → 20.3k) - Reduced 48 agent descriptions (~17.7k → 4.4k tokens)

No logic changed — only description verbosity and injection size optimized.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Ignore local MCP tool cache dirs (.chunkhound/, .playwright-mcp/)
  ([`f581d7a`](https://github.com/brunofaust/claude-all/commit/f581d7a6fa808d571050592dd9675aeed2fa827a))

These are transient directories created by local MCP tool installations and should not be tracked in
  the repository.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017KRUypgUeNkEsMoZtCiRkt

- Initial clean commit
  ([`fadd793`](https://github.com/brunofaust/claude-all/commit/fadd7936b3dbe7d0a68eb45796510ea5ebf6c1e8))

- Move vendored-sources to .claude/skills (repo-internal); humanink pass on README
  ([`0df918d`](https://github.com/brunofaust/claude-all/commit/0df918dcb74f3670fcba3adf544e8ca07ae2fd43))

vendored-sources is a claude-all maintenance skill (how the repo vendors upstream resources) — it
  should NOT be installed on user machines. Move it out of the distributable catalog
  (skills/generic/) into this repo's own .claude/skills/, so it's active when working ON claude-all
  but never offered by the installer (confirmed gone from `claude-all --list`).

.gitignore ignored all of /.claude/, which would have made the moved skill untracked; re-include
  just .claude/skills/<name> so it stays committed while the rest of .claude/ remains local-only.
  Documented the .claude/skills/ row + the gitignore wrinkle in CLAUDE.md; removed the
  vendored-sources row from README §2.5.

Ran the humanink skill's method over README.md (--general --light): it already scores low (mostly
  human — the em-dash/bold/table density is deliberate technical-doc voice, which humanink says not
  to penalize), so only light fixes — dropped a redundant "Holistic" inflation and de-filler'd the
  closing "feedback loop" line.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- Scrub non-generic data from examples (keep brunofaust identity)
  ([`310d0eb`](https://github.com/brunofaust/claude-all/commit/310d0eb320f9df386c0185b217d60a77ca650aa7))

Repo-wide genericness sweep. Removed real/person-specific data that had leaked into examples and
  sample tool-outputs:

- BusyDone (real product name) -> MyApp (requirements-ears) - AWS account 169728770189
  (real-looking) -> 123456789012 placeholder (dynamodb-mutator, secrets-fetcher) per CLAUDE.md -
  sample commit/PR authors Bruno / Bruno Faust / Juan / Juan Tissone -> generic Alex Kim / Sam Lee
  (gh-runner, git-runner) - bruno@example.com -> user@example.com (email-inspector) - IAM user
  bruno-cli -> deploy-cli (iam-auditor) - "Bruno's stack" -> "Python" (verification-loop) - hook tmp
  flag claude-all-bruno-py -> claude-all-brunofaust-py

Kept (legitimate project identity, not example data): LICENSE / pyproject author "Bruno Faust",
  CODEOWNERS @brunofaust, brunofaust/claude-all URLs, the brunofaust-python-style skill name, and
  brunofaust/codecongruence in prek.toml.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- Standardize example AWS account IDs to 123456789012 placeholder
  ([`9ef6e20`](https://github.com/brunofaust/claude-all/commit/9ef6e2071f68f2c72606dbd6cab4f6c2fe51c88f))

Replace the synthetic illustrative account IDs 111111111111 (cloudformation-reviewer) and
  222222222222 (iam-auditor) with the CLAUDE.md placeholder 123456789012, so every example account
  ID and ARN uses one consistent fake account.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- Stop git-ignoring .claude/
  ([`33ef705`](https://github.com/brunofaust/claude-all/commit/33ef70554aa4042919f8a0dfb47caa2f28429636))

Track .claude/ as part of the repo (it holds repo-internal Claude config: hooks/agents/skills scoped
  to working ON claude-all, e.g. the vendored-sources skill). Removes the /.claude/ ignore + the
  narrow re-include carve-out added in the previous commit. Updated the CLAUDE.md note accordingly.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- Update prek package version to 0.4.4 and sync vendored skills
  ([`65c3e1b`](https://github.com/brunofaust/claude-all/commit/65c3e1be65b673234f502c2541c3e2c38145000e))

- Updated the version of the prek package from 0.4.1 to 0.4.4, including new source and wheel URLs.
  - Modified vendored.json to reflect the latest sync dates and commit hashes for various skills,
  ensuring accurate tracking of dependencies. - Enhanced formatting in AGENTS.md and other
  documentation files for improved readability and consistency. - Adjusted rule files in the
  composition-patterns and react-best-practices directories to follow a standardized frontmatter
  format.

- Use generic Brazilian names for sample authors (gh-runner, git-runner)
  ([`cc5102d`](https://github.com/brunofaust/claude-all/commit/cc5102df3f1346e3c6e7b029203d49858b8db312))

Swap the placeholder sample commit/PR authors to generic Brazilian names: João Silva and Maria Souza
  (short João / Maria) in the gh-runner and git-runner mock outputs. No real-person data; the
  project's own author identity (Bruno Faust / brunofaust) stays in LICENSE / pyproject /
  CODEOWNERS.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **agents**: Use generic placeholder hook name in git-committer skip_hooks example
  ([`39b4786`](https://github.com/brunofaust/claude-all/commit/39b4786b99258966636da1a3dc783d5a5134dca8))

Replace the real private hook id in the skip_hooks examples with `myhook`/`docs-check` placeholders,
  per the repo rule that documentation examples must not embed real hook names.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **gitignore**: Ignore only .claude/settings.local.json
  ([`a836b36`](https://github.com/brunofaust/claude-all/commit/a836b36d145f0e0c6736c972d70c699a5d0317ff))

Keep .claude/ tracked, but exclude the per-user local settings file (machine paths / permission
  grants) that shouldn't be shared.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **plugins**: Remove caveman + claude-mem, ensure igraph installs for code-review-graph
  ([`ddeb22d`](https://github.com/brunofaust/claude-all/commit/ddeb22dd1617a0afe0bbacd0ce487707d5d7d45d))

- remove the caveman and claude-mem plugins (not worth keeping) - code-review-graph: pip-install
  igraph into the plugin's pipx venv via `pipx inject` during post_install (the communities extra
  wasn't reliably pulling it) - drop the now-orphaned "caveman-commit" trigger phrase from
  git-committer - generalize the claude-mem reference in secrets-fetcher to "session-memory /
  indexing plugin" (keep-generic + no dangling reference to a removed plugin) - update README plugin
  table

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **prek**: Remove markdownlint + mdformat hooks
  ([`67ec0d6`](https://github.com/brunofaust/claude-all/commit/67ec0d69028547b54d64482ea13b40a89c52dd49))

Drop the two markdown hooks (markdownlint-cli 'Fix markdown' + mdformat 'Format markdown'). They
  were recurring CI noise — auto-reformatting tables and fences — without catching real defects, and
  the value didn't justify the friction. Other gates (ruff, mypy, typos, gitleaks, codecongruence)
  stay. Also drop 'markdownlint' from the lint-command comment in CLAUDE.md.

- **prek**: Remove markdownlint + mdformat hooks
  ([`327148d`](https://github.com/brunofaust/claude-all/commit/327148d0d1ef9d7e247630f60fa2a80fcbcf3bf9))

Drop the two markdown hooks (markdownlint-cli 'Fix markdown' + mdformat 'Format markdown'). They
  were recurring CI noise — auto-reformatting tables and fences — without catching real defects, and
  the value didn't justify the friction. Other gates (ruff, mypy, typos, gitleaks, codecongruence)
  stay. Also drop 'markdownlint' from the lint-command comment in CLAUDE.md.

- **release**: Prepare release
  ([`8c6608f`](https://github.com/brunofaust/claude-all/commit/8c6608f9170b4583266568ff3d76a912c6d956e4))

- **release**: Prepare v0.1.0
  ([`86de726`](https://github.com/brunofaust/claude-all/commit/86de7261b28057df3280cf3010c429a4881217cc))

- **tools**: Remove lean-ctx, keep only rtk
  ([`f83dd86`](https://github.com/brunofaust/claude-all/commit/f83dd8647ac19c89decc6757d80792e9f7bcca0e))

Drop the lean-ctx tool definition (tool.json + claude_md.md + setup.py) — it is no longer maintained
  in this setup. RTK remains the sole token-killer tool. Update the README §6 Tools table (remove
  the lean-ctx row, drop the "pick one" alternatives note) and the git-runner row (now references
  only the rtk wrapper).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_012gte5q7WgQx7kp2ve8hdss

- **vendor**: Sync Vercel skills to upstream f8a72b96
  ([`8652e6b`](https://github.com/brunofaust/claude-all/commit/8652e6bb3b3c7c58487f305ecf49eef8c4aaebba))

- react-best-practices: 17 files updated; composition-patterns: 2 files - vendored.json last_synced
  bumped - prek.toml: exclude vendored dirs from trailing-whitespace / end-of-file-fixer /
  mixed-line-ending — upstream ships trailing whitespace and vendored files must stay
  byte-identical, else vendor_sync --check reports permanent drift

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01W1NRmDUgFVXuc7ucYh1gAS

### Code Style

- Apply mdformat to delegate_search snippet + CLAUDE.md table
  ([`82448ce`](https://github.com/brunofaust/claude-all/commit/82448cee9be415cbf167bb78a5d12a3335b6e0e9))

mdformat (not excluded for coding/claude_md/**) re-aligns the snippet's tables and re-pads the
  CLAUDE.md structure table after the new row. The snippet has no frontmatter, so mdformat
  formatting is harmless.

- Apply ruff-format to config-protection hook
  ([`f8f3c66`](https://github.com/brunofaust/claude-all/commit/f8f3c6679ea67d2990f4a3ab1a01d434a1913dcd))

- **vendor_sync**: Ruff-format after rename
  ([`9503572`](https://github.com/brunofaust/claude-all/commit/95035727ee66203b5bd3eed5e29ce9d9317d5eaa))

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

### Documentation

- Add lean-ctx tool entry and README update requirement
  ([`f7c8222`](https://github.com/brunofaust/claude-all/commit/f7c8222c0adf80d47c6fb23393448217e73c6102))

Added lean-ctx tool to §6 Tools table in README with config_append.toml companion docs and generic
  placeholders. Updated CLAUDE.md with explicit requirement to update README before raising PRs,
  with section map per resource type.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Clarify repo-audit is the umbrella that runs session-harvest (no double-run)
  ([`0f575f1`](https://github.com/brunofaust/claude-all/commit/0f575f16c9488beb1f0c26e4696c7af4e4d57fa7))

repo-audit dimension 14 already invokes session-harvest, so listing both as the "first run"
  double-ran the history mining. Make repo-audit the single entry point: it runs session-harvest
  (dim 14) + project profiling (dim 15) in one pass. Document running session-harvest standalone
  only outside a repo-audit (history-only mining, or a non-Python repo where the code dimensions
  don't apply). Add reciprocal "no double-run" notes to both skills and rewrite the README first-run
  section accordingly.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **agents**: Add ecs-inspector and env-sync agents to agent registry
  ([`6fd22c6`](https://github.com/brunofaust/claude-all/commit/6fd22c6b2b265593a0a9dbd4f50fd2f37925d838))

Adds documentation for three new agents: - ecs-inspector: read-only ECS inspection (describe task
  definitions, services, tasks) with secret redaction - env-audit: read-only deployment-state diff
  for any environment - env-sync: brings non-prod environments up to date with user confirmation
  gates

Updates codecongruence hook to v0.4.0 for stricter validation.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **agents**: Document skip_hooks (SKIP=) triage mode in code-quality
  ([`8023d49`](https://github.com/brunofaust/claude-all/commit/8023d49bb6748261409624187d3ca800ff0c4626))

Add a "Skip-hooks mode" section to the code-quality agent: pass hook IDs via the SKIP env var
  (`SKIP=mypy prek run --all-files`) to triage past a known-failing/slow hook. Discipline: a skipped
  hook is reported as [SKIPPED], never as passing, and the gate is flagged incomplete; only skip
  when the caller asks; never --no-verify. Generic hook ids only. Mirrors the git-committer
  skip_hooks directive + prek skill.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **claude.md**: Agents must return errors verbatim to main session
  ([`68afa40`](https://github.com/brunofaust/claude-all/commit/68afa4021f479e40620625e39b0b0d27801a37d3))

Test failures, lint errors, hook output, log exceptions, and AWS errors must be returned verbatim —
  the main session needs full text to fix them. Summary is only acceptable for successes or infra
  errors the caller cannot act on from text alone (missing creds, network timeout).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **python-style**: Add e2e/integration testing reference for shared-infra multi-tenant suites
  ([`dec7ed8`](https://github.com/brunofaust/claude-all/commit/dec7ed860bfb77afc891e40d601a546dbf6c2362))

Add references/e2e-testing.md: how to run a parallel e2e/integration suite for a multi-tenant system
  against one shared backing stack without flakiness.

Core principle: isolate data, accept shared infra, never confuse the two — diagnose each failure as
  data contention vs infra contention (the remedies differ). Covers one create_tenant factory (zero
  tenant rows in the seed), edge states as factory params, post-seed sequence randomization,
  concurrency-capable mock servers, drain-to-own shared queues, fail-closed prefetch observability,
  settings-cache timing, and picking the xdist dist mode at parse time.

Headline: a one-pass phased-execution pytest plugin — @pytest.mark.phase(n) ordering, a cross-worker
  file-counter barrier (PYTEST_XDIST_TESTRUNUID-keyed shared dir, expected counts written at
  collection, fail-loud on timeout), and a project-injected {phase: reset_fn} mapping run once per
  phase by a single worker. Includes a minimal working implementation of the barrier helpers.

Also wire the new reference into SKILL.md's reference table and add a cross-link from
  references/testing.md.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01CVJCnh4mg31j4dXVMER49x

- **python-style**: Add optional DB tenant-isolation reference (RLS + non-blocking audit)
  ([`5f07814`](https://github.com/brunofaust/claude-all/commit/5f0781474741ab08363726b18b0baf4c2c701846))

New references/tenant-isolation.md — optional Postgres hardening to make cross-tenant leaks
  structurally impossible (enforcing RLS) or observable (non-blocking audit table queried at
  pytest_sessionfinish):

- Session tenant via SET LOCAL / set_config(is_local=true) — txn-scoped, pool-safe (PgBouncer txn
  mode), never plain session SET. - Two injection vectors for prod AND tests: per-tenant DB role
  (driver-agnostic, no-code-change) vs session GUC (app sets org_id from the validated payload). -
  Enforcing RLS policy with unset-tenant = deny-all. - Non-blocking audit: logging RLS policy
  (covers reads + writes) or AFTER-write triggers, stamping app.current_tenant + a caller id
  (app.test_id) per row. - No-code-change e2e for real lambdas in MiniStack: handler sets tenant
  from the scoped payload (preferred), else inject via the per-test function's env. - Coverage
  meta-test: every tenant_id table must have RLS + a policy. - Env-gated throughout; prod unchanged
  when the switch is off.

Wires into SKILL.md reference table, testing.md tenant-isolation cross-link, and the README skill
  row.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01SiiQomNxj42cCNwwv8oHkp

- **python-style**: Add Pydantic boundary validation, test isolation, scoped-process rules
  ([`16589f3`](https://github.com/brunofaust/claude-all/commit/16589f3bbcc07b64600f5c34c1f03b026863117c))

Harvested from the busydone flaky-test debugging marathon:

1. Lambda payloads + ECS env vars must be Pydantic-validated at the boundary (data-modeling.md
  trust-boundary list + worked example; SKILL.md Lambda handler example now parses the event in
  main()). 2/3/4. Test data isolation as the flaky-test root cause (testing.md): dynamic DB ids
  (never hard-coded), per-test data ownership (nothing shared), foreign keys never cross tenants
  (seed mirrors real cardinality), and pytest-xdist as the concurrency/isolation validator (not just
  a speed-up). Plus anti-pattern table rows and an isolation checklist. 5. New
  references/scoped-processes.md: every all-tenant job accepts an optional scope
  (run-for-one/group), one code path, scope-aware DynamoDB idempotency where a global run supersedes
  a customer-scoped run (the customer claim is blocked when already covered). Enables e2e isolation
  + single-customer production re-runs.

SKILL.md: new reference-table row, architectural one-liners, quick-rule anti-patterns, and
  review-checklist items. README row enriched.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01SiiQomNxj42cCNwwv8oHkp

- **python-style**: Ban xdist_group for co-dependent tests (user-approved exception only)
  ([`cdfb738`](https://github.com/brunofaust/claude-all/commit/cdfb73869d5e2d7583ed4e51e349bbe170ed7fb5))

Tests must be fully isolated, so @pytest.mark.xdist_group — which pins tests to one worker in order
  — is forbidden as a flaky-test workaround: it hides a test-depends-on-test coupling instead of
  fixing it. Rare genuine exceptions require asking the user first and documenting the reason in a
  comment on the marker.

Adds the rule to references/testing.md (Rule 4 + anti-pattern row + checklist) and the SKILL.md
  test-patterns one-liner.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01SiiQomNxj42cCNwwv8oHkp

- **python-style**: Drop phased-test idea; add e2e-verify-requirements principle + SessionStart
  skill loader
  ([`e33ed86`](https://github.com/brunofaust/claude-all/commit/e33ed86522f3baaa71c0e55f6d8c4d4dcdb663a3))

Remove the phased-execution idea — an in-xdist cross-worker phase barrier is not viable under
  pytest-xdist (xdist schedules/steals tests on its own, a conftest can't reliably gate a worker
  mid-run, and a poll-until-others-drain barrier trades contention for deadlock risk).
  references/e2e-testing.md §9 now states that plainly and prescribes the proven split instead: a
  parallel pass for the isolated per-tenant tests + a separate serial pass (`-m all_tenants -p
  no:xdist`, freshly-reset DB) for the un-scopeable global sweeps. Updated §8, the checklist, the
  SKILL.md table row, and the references/testing.md cross-link to match.

Add to claude_md.md (injected into ~/.claude/CLAUDE.md on skill install): "e2e tests verify
  REQUIREMENTS; unit tests verify CODE" — derive every e2e test from the initial prompt +
  brainstorming iterations + the plan/tasks agreed before coding, not from reading the
  implementation.

Add hooks/python-style-skill-loader.py: a SessionStart reminder to invoke the
  brunofaust-python-style skill when the session cwd looks like a Python project. Silent in
  non-Python sessions; shares the edit-time hook's per-session dedup flag so the two never stack a
  reminder. Registered in hooks/hooks.json (SessionStart), documented in README section 3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01CVJCnh4mg31j4dXVMER49x

- **python-style**: Frame xdist_group as an isolation-failure diagnostic
  ([`e3d64ac`](https://github.com/brunofaust/claude-all/commit/e3d64ac6b1db53fda4c823e3e2963a5a5dcb195b))

Reaching for @pytest.mark.xdist_group is itself the signal that tests aren't isolated correctly —
  fix the isolation rather than papering over it by pinning tests to one worker.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01SiiQomNxj42cCNwwv8oHkp

- **python-style**: Make tenant audit policy multi-operation (FOR ALL) + enforce/audit exclusivity
  ([`b6286d6`](https://github.com/brunofaust/claude-all/commit/b6286d6a99bcfc3f21d8b40baa269ccc2adfb657))

The non-blocking audit policy now uses a single FOR ALL policy with the log function in BOTH USING
  (existing rows: SELECT/UPDATE-old/DELETE) and WITH CHECK (new rows: INSERT/UPDATE-new) — covering
  every DML including SELECT and MERGE (decomposed into its INSERT/UPDATE/DELETE actions). Adds an
  operation-coverage table and a phase column to disambiguate UPDATE's double log.

Documents the critical correctness rule: an always-true permissive audit policy is OR-combined and
  defeats an enforcing policy on the same table — so enforce (prod) and audit (e2e) must be selected
  by environment, never stacked. Plus the read-precision caveat (USING is a security-barrier qual;
  may over-report vs the returned set) and the app-side exact-result alternative.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01SiiQomNxj42cCNwwv8oHkp

- **python-style**: Migrate skill to MiniStack + add harvested conventions
  ([`599aff6`](https://github.com/brunofaust/claude-all/commit/599aff6c24e4cc7c55972aa0238db2bf95cb4b1f))

- testing.md: LocalStack->MiniStack (drop-in :4566), executor trade-off (docker + LAMBDA_STRICT=1),
  runtime pinning, post-run CloudWatch log scan, LAMBDA_ACCOUNT_CONCURRENCY heuristic (~cpu/2) -
  async-patterns.md: DynamoDB single-flight lock + idempotency markers; to_thread ban; async-first /
  RUF029-ignored rule - architecture.md: no re-export shim modules (move + repoint) -
  type-hints/visibility/external-system-ownership/project-structure/enforcement: strict-typing
  gates, Protocol conformance, __all__ contract, subprocess ban, RUF067, mined from busydone session
  history - prek skill: ruff commit/push split, dep-CVE audit, interrogate 3.14 pin, pygrep guards,
  regression-only gates (jscpd / raw-SQL / alembic-head)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01PdsjcBHosmNB2fqHP9wJim

- **python-style**: Strip residual phased/barrier wording from e2e-testing.md
  ([`da64d93`](https://github.com/brunofaust/claude-all/commit/da64d93c0c8c8f49e565ce80f5e4f8d0f1d93009))

Remove the leftover "don't try to phase / cross-worker barrier" explanation and the barrier
  reference in the checklist — the section now simply prescribes two separate runs (parallel
  per-tenant pass + serial all-tenants pass) with no mention of the phased/barrier idea at all.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01CVJCnh4mg31j4dXVMER49x

- **repo**: Add repo structure guide and missing skills documentation
  ([`8d10ed7`](https://github.com/brunofaust/claude-all/commit/8d10ed7d5f7c482bb715924697b7de9ff86a0716))

- Add Commands section to CLAUDE.md with setup and linting entry points - Add Repo structure table
  to CLAUDE.md with paths and purposes - Add workflow for adding new agents/skills to CLAUDE.md -
  Update README.md structure diagram to include hooks/, web/, tools/ - Add 4 missing skills to
  README: aws-debug-loop, code-review-discipline, prek, verification-loop - Document all 5 hooks in
  new section 3 of README with descriptions - Renumber Plugins/MCPs/Tools sections to 4/5/6 in
  README - Update prek and brunofaust-python-style skill documentation - Improve prek-stop-runner.py
  with complete docstrings and Args/Returns - Update prek.toml configuration

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **session-harvest**: Add Cursor + Claude Code extraction templates (tmp paths)
  ([`5cf78e0`](https://github.com/brunofaust/claude-all/commit/5cf78e0a6e001c0d23da6ad39e7fe34b24d4d039))

Add concrete, copy-pasteable history-extraction templates for Cursor (cursorDiskKV / bubbleId:
  bubbles) and Claude Code (projects JSONL, outputs stripped). Both write to a tmp file
  (${TMPDIR:-/tmp}) and gzip a compact, shareable artifact. Flag them as version-dependent templates
  — Cursor's schema (table/keys, type enum, createdAt units) varies by version and OS; update the
  "Where the histories live" Cursor row to cover newer cursorDiskKV vs older ItemTable. Note:
  substitute SINCE properly ($SINCE, not literal).

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **session-harvest**: Default extraction templates to last 1 year + period guidance
  ([`17fdc13`](https://github.com/brunofaust/claude-all/commit/17fdc13b5d495064762b0e2d28d2fcc2a4727d95))

Both history-extraction templates now default to a 1-year window instead of a hardcoded date / 60d:
  Claude Code uses -mtime -365; Cursor computes SINCE=1-year-ago portably (BSD `date -v-1y` || GNU
  `date -d '1 year ago'`). Add a "Choosing the period window" note — 1 year is the default (long
  enough for recurring patterns, not ancient noise); widen for sparse usage, narrow to 60-90d for a
  recent-trend pass; flag Claude Code's cleanupPeriodDays (default 30) retention caveat.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **skills**: Add CSpell multi-language spell-check option to prek skill
  ([`1f255b5`](https://github.com/brunofaust/claude-all/commit/1f255b5d6cf6fb0db9ad11ef5b194ee9295f81c7))

- prek skill: document CSpell (dictionary-based, multi-language) scoped to content paths alongside
  typos (corrections-based, English) for code — cspell-cli hook block, cspell.config.yaml,
  trade-offs. Note codespell is NOT a multi-lang alternative. - prek.toml: exclude the prek skill
  from the typos hook (the skill deliberately contains example typos + multi-language sample words).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Add per-hook resolution examples to prek skill
  ([`7a7ba4f`](https://github.com/brunofaust/claude-all/commit/7a7ba4f61f482c8b0bf0d093ee00debfebdbacc2))

Document the three ways to resolve any hook finding — fix it, allowlist narrowly (word/rule/line),
  or scope-exclude a path — with a worked `typos` example (i18n path-exclude vs extend-words
  allowlist vs fix) and a per-hook cheat sheet covering
  ruff/mypy/gitleaks/bandit/interrogate/vulture/markdownlint/mdformat/pyupgrade/
  check-added-large-files/semantic-dedup. Security note: gitleaks is fix-only (rotate the secret);
  allowlist is for false positives only. Generic placeholders throughout.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Add RDS-vs-DynamoDB table-level decision + source references
  ([`1f429da`](https://github.com/brunofaust/claude-all/commit/1f429da9634ab3da84653a7b8e5f06ecd6144b05))

- feat(skills): aws-architecture — add per-table RDS vs DynamoDB decision rubric (DynamoDB for
  no-RDS-Proxy fan-out / insert-only / TTL / idempotency / key-only access; RDS for joins /
  transactions / ad-hoc queries / relational integrity) - docs(skills): add tracked source-reference
  sections (AWS Well-Architected, Compute Optimizer, Trusted Advisor, Cost Optimization Hub, RDS
  Proxy, DynamoDB TTL, FOCUS) + ecosystem repos (OptimNow, zxkane, Cloud Custodian, Infracost,
  Komiser) to aws-cost-optimization, aws-architecture, and cost-audit-runner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Add source references to ECC-derived skills
  ([`2c14c68`](https://github.com/brunofaust/claude-all/commit/2c14c689f9c0a6187771255d42b48fa352b6474b))

Add "References (track for updates)" sections citing the upstream affaan-m/ECC rule files each skill
  was adapted from (rules/react + rules/common), plus key canonical docs (OWASP cheat sheets,
  Testing Library, MSW, react.dev "You Might Not Need an Effect", React 19 notes). Lets us track
  upstream changes in the future.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Document commit-time SKIP=<hook> usage in prek skill
  ([`2fbf07b`](https://github.com/brunofaust/claude-all/commit/2fbf07b82c1f9cda4bf0a038c308bb468e72910e))

The prek skill already showed `SKIP=mypy prek run --all-files`; add the commit-time form (`SKIP=mypy
  git commit -m ...`) for skipping one hook for a single commit when a pre-existing failure is
  unrelated to the change, plus a note to prefer SKIP=<id> over `--no-verify` (which disables every
  hook). Generic hook ids only.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Document import-linter + frontend local hooks in prek skill
  ([`fe94ec8`](https://github.com/brunofaust/claude-all/commit/fe94ec8155e52884035847b81bd6f16b8d465041))

Add the import-linter (architecture boundary) and frontend tsc/eslint/prettier local `language =
  "system"` hooks to the prek skill's annotated prek.toml example, on the pre-push stage. Generic
  placeholders only.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Reframe prek skill to cover both pre-commit and prek
  ([`1133012`](https://github.com/brunofaust/claude-all/commit/1133012515d1460bd7845a6c3e81a57c8867ec92))

prek is a drop-in Rust reimplementation of pre-commit (reads .pre-commit-config.yaml unchanged; adds
  optional prek.toml). The skill knowledge is ~95% shared, so make it explicit it serves both: new
  title, a prek⇄pre-commit equivalence table (install/run/ autoupdate/SKIP/config-file mapping),
  tool-neutral framing, and a note that every `prek`/`prek.toml` example maps to pre-commit +
  .pre-commit-config.yaml. Name kept as `prek` (matches the stack + global config + code-quality
  detection).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

### Features

- Add Cursor-signal resources — runner dispatch rules, http-runner, wait-for-ready skill+hook
  ([`e98eb9f`](https://github.com/brunofaust/claude-all/commit/e98eb9f44315caef6c2436233b98c28feee7d99b))

Derived from analyzing ~8 months of real editor usage (treated as Claude Code signal). Adds the
  resources for the high-volume tool patterns that weren't yet routed off the main session:

Dispatch snippets for existing agents (they had no .claude_md.md, so the main session was never told
  to route to them — same gap test-runner had): - docker-runner (docker/compose — ~1,200 calls;
  build/log output is huge) - python-deps (uv/pip/poetry dependency ops; NOT uv-run tests/lint) -
  postgres-query (psql / read-only SQL) - gh-runner (gh CLI inspection)

New http-runner agent (Haiku) + dispatch snippet — runs curl/HTTP requests and returns status + key
  headers + trimmed body, masks credentials.

New wait-for-ready skill — poll-until-healthy primitive (timeout + interval) to replace fixed 'sleep
  N && curl' loops, with ready-made probes. Ships a bundled PreToolUse hook that catches blocking
  sleep / sleep+curl poll-by-delay loops and points at the skill (exit-0 JSON reminder, not a hook
  error). Hook is coupled to the skill — installed only when the skill is.

- Add requirements-ears skill for business-level acceptance criteria
  ([`21b9bfd`](https://github.com/brunofaust/claude-all/commit/21b9bfd53d1184d4d4980ca4ec358e90825f64e8))

- Supply-chain guard, implement-loop, token-aware compaction + review/spec enhancements
  ([`213be57`](https://github.com/brunofaust/claude-all/commit/213be57d86ca1c043cc0bbe5cfe2d3e9ba6ad9c2))

Insights adapted from dotclaude (and edge-of-chaos), generic + public-safe.

New resources: - hooks/supply-chain-guard.py (+ hooks.json): non-blocking PreToolUse reminder on
  package installs (npm/pnpm/yarn/bun/pip/uv/poetry/pipx) — flags git/URL sources, missing
  --ignore-scripts, bare install with a lockfile present (use ci/frozen), and a new-package cooldown
  reminder. Reinforces research-before-build + security-audit. Bypass CC_SUPPLY_CHAIN_OK=1. -
  skills/generic/implement-loop: the structured "story-by-story" Ralph loop — implement a backlog
  one story per FRESH subagent context, in dependency order, commit with an ac_trace, review
  diff-only (cross-model), feed progress forward.

Enhancements to existing resources: - suggest-compact.py: now TOKEN-aware — reads the latest
  message.usage from the transcript to estimate context occupancy and suggests /compact at a
  threshold (default 160K, env-tunable), amortized + with a tool-call fallback. -
  adversarial-verification: [FACT]/[INFERENCE]/[ASSUMPTION] markers + the observe-before-claim
  corollary (runtime claims cite observed state, not source). - requirements-ears + test-author:
  [bN] behavior ids so every test traces to a criterion (auditable spec coverage). -
  code-review-discipline: cross-model second-opinion section (decorrelate hallucination by reviewing
  with a different model than implemented).

All touched Python passes ruff (check+format), mypy, vulture; hooks.json valid; both hooks
  functionally tested; installer discovers the new resources; typos clean.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- Vendoring registry + sync script; attribute imported frontend skills
  ([`1ff8b9b`](https://github.com/brunofaust/claude-all/commit/1ff8b9b6ca6b17ee47d5d317f0441ddfe2927284))

The frontend skills copied from Vercel now carry explicit provenance, and a registry + updater makes
  all imported resources maintainable.

Attribution (no content edits — vendored files stay byte-identical to upstream): - Add
  ATTRIBUTION.md to the 3 vendored Vercel skills (react-best-practices, composition-patterns,
  react-view-transitions) → vercel-labs/agent-skills, MIT (declared inline upstream; no LICENSE file
  shipped, so attributed by reference, not fabricated). - web-design-guidelines is a local wrapper
  that live-fetches vercel-labs/web-interface-guidelines at runtime → ATTRIBUTION.md notes it's a
  reference (nothing vendored, always latest). - react-correctness / react-testing / web-security
  are originals — untouched.

Registry + updater: - vendored.json (repo root) — one entry per imported resource: source repo/
  ref/path, license, author, local_only sidecars, frontmatter_inject, last_synced. Includes humanink
  + the 3 Vercel skills + the WIG reference. - scripts/vendor_sync.py — shallow-clones each upstream
  at its ref, refreshes files, preserves local_only, re-applies frontmatter_inject, stamps the
  upstream commit. Supports --id and --check (dry-run). Run it to "update the imported skills";
  review the diff and commit. - vendored-sources skill documents the registry, the script, and the
  keep-vendored-files-pristine + attribution discipline. - CLAUDE.md + README note the convention.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **agents**: Add bug-hunter agent + deep-dive lane pattern in repo-audit
  ([`2930af5`](https://github.com/brunofaust/claude-all/commit/2930af56fc12ec4f652410ea124794a2c6e212d4))

Generalize the reusable core of ad-hoc audit subagents into shared tooling:

- agents/generic/bug-hunter: deep correctness review of a named scope against a generic bug-class
  taxonomy (async/concurrency, data handling, storage/transactions, error swallowing,
  off-by-one/boundary). Read-only, severity-tagged, dispatcher inlines scope + hot spots per run. -
  repo-audit skill: document optional parallel deep-dive lanes — hot code lanes route to bug-hunter;
  bespoke infra configs get one-off prompts per subagent-prompting (not canned single-use agents);
  Phase 0 recon stays on the built-in Explore agent. - README: bug-hunter row in § 1.1, repo-audit
  row updated.

https://claude.ai/code/session_017zwJJDVo2Ro8bougEXRTrP

- **agents**: Add claude_md snippets for ecs-inspector, iam-auditor, git-runner
  ([`3622d33`](https://github.com/brunofaust/claude-all/commit/3622d33e5450094e86ad1b82f119b0715efe7157))

Introduce the `<agent>.claude_md.md` pattern for agents that need to inject dispatch rules into
  ~/.claude/CLAUDE.md via `claude-all install`.

- ecs-inspector.claude_md.md — flags describe-task-definition / describe-service / describe-tasks as
  large-output delegates; list-* calls are fine in main session - iam-auditor.claude_md.md — flags
  get-role-policy / get-policy-version / simulate-principal-policy (verbose JSON); list-* calls are
  fine in main session - git-runner.claude_md.md — flags git log/diff/blame/show including the `cd
  "worktree" && git ...` bypass pattern; single-line commands ok in main

Update CLAUDE.md: document that ~/.claude/CLAUDE.md must never be edited directly — changes belong
  in agent claude_md.md files and land via install.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **agents**: Add dispatch rule for cloudformation-reviewer (read-only)
  ([`f65a257`](https://github.com/brunofaust/claude-all/commit/f65a2575fafca4d7e5d610a55d65879cecbdd1da))

Routes CloudFormation template / change-set REVIEW tasks to the cloudformation-reviewer agent
  (Sonnet, read-only — security/cost/IAM assessment), while explicitly NOT routing deploys
  (create/update-stack, execute-change-set stay deliberately invoked via cloudformation-deployer).

Surfaced by a colleague's Cursor history (heavy CloudFormation/ECS/OpenSearch infra work). Migrated
  to the folder layout (agent.md + claude_md.md).

Verified: discovers as a folder agent, injects its dispatch block, symlink resolves to agent.md.

- **agents**: Add dispatch rules for 8 read-only inspector/builder agents
  ([`786803b`](https://github.com/brunofaust/claude-all/commit/786803bebcfd354e1b4d12dd7b920bdd3ec588f9))

Audit found 17 router-type agents (their own description says 'delegate / use FIRST / main session
  must NOT run directly') with no claude_md.md dispatch rule — so nothing told the main session to
  route to them. Adds the rules for the 8 clear read-only / output-heavy ones, each migrated to the
  folder layout (agent.md + claude_md.md):

- frontend-builder (npm/vite/next build — bundler output) - rds-postgres-query (psql on RDS/Aurora —
  also stops credential leaks) - cloudwatch-inspector (aws logs/metrics — huge JSON) -
  dynamodb-inspector (aws dynamodb reads — verbose AttributeValue maps) - sqs-monitor (aws sqs
  inspection) - step-functions-tracer (aws stepfunctions history — 1000s of lines) - secrets-fetcher
  (secretsmanager — stops secret values in transcript) - email-inspector (email MCP — message
  bodies)

Skipped code-quality (already routed by lint-fixer's snippet). Deliberately NOT routing the
  write/deploy/mutate agents (terraform-deployer, aws-lambda-deployer, dynamodb-mutator,
  aws-events-scheduler) or workflow agents — those are invoked deliberately, not auto-delegated.

Verified: all 8 install in folder form, inject dispatch blocks, 0 broken symlinks.

- **agents**: Add docker-log-inspector — read-only container log reader + bug hunter
  ([`13d7947`](https://github.com/brunofaust/claude-all/commit/13d79477357313fdc8c0fca8de834ca6af29026e))

Haiku agent modeled on cloudwatch-inspector but for local Docker containers: pulls logs (docker logs
  / compose logs, bounded --tail/--since, never -f) from running or exited containers, filters for
  errors/exceptions, returns verbatim error blocks + crash diagnosis via docker inspect (exit code,
  OOMKilled, restart-count). Read-only — refuses build/run/up/down and points at docker-runner.
  Ships companion claude_md.md dispatch row; README §1.1 updated.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01DbtP1jWDZYUMaZ9USuzRSR

- **agents**: Add ecs-inspector + strengthen iam-auditor trigger phrases
  ([`9c41dd3`](https://github.com/brunofaust/claude-all/commit/9c41dd361e891c4ced3ef39ed52f8120fa15580b))

Add `ecs-inspector` (Haiku) — covers aws ecs describe-task-definition, describe-service,
  describe-cluster, list-tasks, describe-tasks, list-services. Previously the main session had no
  agent to delegate to for ECS reads, so Opus ran them directly.

Update `iam-auditor` description to include explicit CLI trigger phrases: aws iam get-role-policy,
  list-role-policies, list-attached-role-policies, simulate-principal-policy. The body already
  handled these commands but the description (what the auto-router reads) was missing them.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **agents**: Add git-cleanup end-of-session cleanup agent
  ([`45594a5`](https://github.com/brunofaust/claude-all/commit/45594a5b672808d184f603b596b25b865106aa85))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **agents**: Add repo-cleaner agent for safe filesystem cleanup
  ([`2b5c5eb`](https://github.com/brunofaust/claude-all/commit/2b5c5eb1b604d16ccfb75b2e93a71319381ff208))

Adds a focused Haiku agent that detects repo languages, removes build artifacts/cache/bytecode/noise
  safely, handles ignore-file-referenced dirs with per-directory prompts, and manages git-tracked
  dirs that exist in origin via git rm --cached.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **agents**: Add test-author + lint-fixer (Sonnet doing-agents)
  ([`7f43d28`](https://github.com/brunofaust/claude-all/commit/7f43d28c9c8258dfe60ff364076c88b0aebdbafa))

Two Sonnet agents for work that was wrongly falling to the main Opus session:

- test-author — coverage-driven unit-test writer. Measures gaps via pytest --cov, writes
  behavior-asserting tests per brunofaust conventions (factories, DI not module-patching, tests
  mirror src/), loops to the gate. No coverage-gaming, never edits source to fudge. Pairs with
  test-runner. - lint-fixer — fixes ruff/mypy/eslint/tsc/codecongruence findings at root cause.
  Clears the mechanical tier with ruff --fix/format, then judgment findings one category at a time.
  No silencing (ignore/noqa/config-loosening/--no-verify); verifies with the gate + tests after
  each. Pairs with code-quality + test-runner.

Both ship .claude_md.md dispatch snippets; README catalog updated.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **agents**: Add test-runner dispatch snippet + route inline linter runs to code-quality
  ([`da24c4d`](https://github.com/brunofaust/claude-all/commit/da24c4d8e6c4ed93e44c480fa88a160fa7a165c5))

Analysis of 30 days of real session history surfaced two delegation gaps where routine commands ran
  inline in the main (Opus) session:

- 45x full `uv run pytest tests` runs inline. The test-runner agent exists but had NO .claude_md.md,
  so no dispatch rule was injected into ~/.claude/CLAUDE.md telling the main session to route tests
  to it. Add test-runner.claude_md.md (pytest/npm test/vitest/jest/go test -> test-runner, Haiku) so
  test runs stop burning Opus tokens on full tracebacks + coverage tables.

- Inline `uv run mypy` / `ruff check` / `eslint` / `tsc` runs to *see* findings. Extend
  lint-fixer.claude_md.md so running a linter/type-checker to inspect findings routes to
  code-quality (the read-only Haiku finder), then fix via lint-fixer.

- **agents**: Handle pre-commit hook output in git-committer
  ([`7a29786`](https://github.com/brunofaust/claude-all/commit/7a2978641df0814112aea6865d5ea01239609281))

Add hook-detection and autofix-retry logic to git-committer: - Detect .git/hooks/pre-commit before
  committing - On hook autofix (files modified, exit != 0): re-stage + retry once - Summarize hook
  output as pass/fail counts, never dump raw lines - Surface verbatim first error line per failing
  hook on hard failure

Add git-committer.claude_md.md flagging Bash(git commit ...) in hook-enabled repos as a main-session
  anti-pattern.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **agents,skills**: Add cost-audit-runner + architecture-decision-guard, document core/ containment
  ([`9479a36`](https://github.com/brunofaust/claude-all/commit/9479a365e9e8bf17ce9b370ad2961de002a94083))

Second batch of busydone-derived generic improvements.

- feat(agents): add cost-audit-runner (Sonnet, read-only) — multi-service AWS waste hunt emitting
  prioritized findings + non-executed fix_commands - feat(skills): add architecture-decision-guard —
  containment-over-layering guardrails, smell tests, revert-the-split guidance - docs(skills):
  brunofaust-python-style — redefine core/ as a settings-free extractable library (config/settings
  moves to package root), document the per-service AWS SDK-owner layout (core/aws/<service>.py +
  base.py), add the core-independence import-linter contract and TID251 core/aws ignore -
  docs(skills): aws-architecture — add "AWS client wrappers (core/aws containment)" section (one
  owner per service, shared aiobotocore session in base.py) - docs(repo): list the new agent + skill
  in README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **agents,skills**: Add module-migrator + fix skill frontmatter + agent/skill improvements
  ([`9c252e2`](https://github.com/brunofaust/claude-all/commit/9c252e2aacde5859dd0508389de29c3d808c7b57))

Derived from a review of the last 48h of session history.

- fix(skills): exclude coding/skills + plugin folders from mdformat (it was mangling every
  SKILL.md's YAML frontmatter into a thematic break + heading, breaking skill model-invocation) and
  restore --- frontmatter on all 15 skills - feat(agents): add python-module-migrator (Haiku) —
  mechanical git mv + import-repoint + collect-only verify loop with finish discipline -
  feat(skills): add python-module-migration skill (the recipe + foot-guns) - feat(agents):
  git-committer gains skip_hooks + no-restage directives - fix(agents): code-quality now detects
  prek.toml (not just .prek.yaml) - feat(agents): test-runner recognizes pyleak/xdist harness noise;
  runs critical-path tests serially - fix(agents): python-refactorer no longer endorses
  contextlib.suppress(Exception) - docs(skills): enrich prek (complexity-cap rollout),
  aws-architecture (relational->DynamoDB decision), brunofaust-python-style (import-alias rule),
  alembic-migration (op-functions-over-raw-SQL anti-pattern)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **agents,skills**: Friction-analyzer + ECC-agents prompt patterns
  ([`9637195`](https://github.com/brunofaust/claude-all/commit/963719544b8d6e9b404ee96eb4dfe726fa8f0d8a))

Adopted the genuinely-novel patterns from the ECC agents/ folder (most of which overlaps our set or
  is runtime-specific):

- friction-analyzer agent (Sonnet) — mines a session transcript for friction (reverts, repeated
  corrections, command thrash, a guard firing repeatedly, raw-command dispatch leaks, re-derived
  gotchas) and proposes a preventative rule per pattern (guard hook / CLAUDE.md rule /
  agent-or-skill improvement) with verbatim evidence. Read-only. Automates the manual session-mining
  pattern. - subagent-prompting: add a "prompt-defense baseline" (anti-prompt-injection preamble) +
  list the untrusted-input agents that should carry it. - code-review-discipline: add Rule 4.5
  report discipline — >=80% confidence to report, Pre-Report Gate (defensible severity),
  zero-findings=APPROVE, skip unchanged code unless CRITICAL, HIGH/CRITICAL need proof. -
  adversarial-verification: add "judge the artifact, not the effort" (anti-sycophancy — no cope
  phrases, no points for effort). - README catalog updated.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **hooks**: Companion reminder hooks for alembic-migration + react-testing; document the standard
  ([`6d81ff9`](https://github.com/brunofaust/claude-all/commit/6d81ff9294d73e374fc2f0e08c27cc5fc6730c46))

Add once-per-session PreToolUse/Edit|Write reminder hooks to two more skills: - alembic-migration:
  fires when editing a migration file (path under versions/ / alembic/ / migrations/) with the
  migration safety rules. - react-testing: fires when editing a frontend test file
  (*.test.*/*.spec.* or __tests__/). Matcher is narrower than react-best-practices (test files only)
  so the two don't stack on the same component edit.

Both follow the reminder-hook standard: once-per-session /tmp-flag dedup, stdout additionalContext
  addressed to Claude (never stderr), return 0 on any non-match/error so a turn is never broken.

Document the standard in CLAUDE.md (new "Authoring companion hooks" section): the reminder-vs-guard
  archetypes, the once-per-session rule and when to go once-ever, the Claude-facing
  additionalContext channel, narrow matching, the no-overlapping-reminders rule, and the hook.json
  schema. Audit result: all existing reminder hooks already dedup once-per-session; guard/utility
  hooks (destructive-command-guard, supply-chain-guard, accumulator, ...) fire per occurrence by
  design.

README: note the new companion hook on both skill rows.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01VEYbYZjWfFXztJCPABvSHv

- **hooks**: Supply-chain-guard — add Python-specific index / trusted-host checks
  ([`bccc46a`](https://github.com/brunofaust/claude-all/commit/bccc46ab11395183894973003e6e10ee864da1b3))

The npm side had specific hardening (--ignore-scripts, lockfile steering) but the Python side only
  got the generic advisory. Add pip/uv/poetry-specific checks: - --index-url / --extra-index-url →
  dependency-confusion warning (a custom index can shadow public names; pin versions+hashes, prefer
  one trusted index). - --trusted-host → flags disabled TLS/cert verification.

git/URL-source + provenance/cooldown already applied to Python installs. Updated the docstring +
  README to spell out which checks are ecosystem-agnostic vs npm-only vs pip/uv/poetry-only.
  ruff/format/mypy clean; functionally tested.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **hooks**: Supply-chain-guard — real release-date cooldown check (npm + PyPI)
  ([`b38d3b4`](https://github.com/brunofaust/claude-all/commit/b38d3b48ab699403f31e2386c21f2355f7125a92))

Replaces the advisory-only cooldown with a real one: for every package being installed — named on
  the command line OR resolved from the lockfile for `uv sync` / `poetry install` / `npm ci` / `pip
  -r` — query the npm/PyPI registry for the version's publish date and ALERT if it's within the
  cooldown window (default 7d, env CC_SUPPLY_CHAIN_COOLDOWN_DAYS). Both modes, as requested.

Safe-by-construction: pinned-version dates are disk-cached (immutable, so the cache never goes stale
  and lockfile syncs only re-query newly-bumped deps); the whole lookup runs under a wall-clock
  budget with a short per-request timeout and FAILS OPEN — an unreachable/blocked registry never
  blocks the install (verified: returns in ~0.18s with the registry unreachable). Bumped the hook
  timeout to 15s.

Env: CC_SUPPLY_CHAIN_NO_NETWORK=1 skips the lookup (static checks only), CC_SUPPLY_CHAIN_OK=1
  silences the hook. ruff/format/mypy/vulture clean; classify, spec/lockfile parsing, cooldown
  findings, and fail-open all functionally tested.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **hooks,skills**: Destructive-command guard + security-audit (gstack-inspired)
  ([`18bf9bc`](https://github.com/brunofaust/claude-all/commit/18bf9bca6177e418e2c329ab642c9bd783403b57))

Adopt the strongest gstack ideas that we lacked:

- coding/hooks/destructive-command-guard.py — PreToolUse(Bash) hook that HARD-BLOCKS (exit 2)
  catastrophic/irreversible commands (rm -rf /, disk wipes, DROP/TRUNCATE, git push --force / reset
  --hard, docker/kubectl/volume destruction, terraform destroy, aws ...delete-*, fork bombs) with a
  safe build-dir allowlist and an explicit GUARD_OK=1 / # guard:allow override; warns on
  risky-but-routine ops. Mechanically enforces the prose "STOP — destructive" guardrails. Tested
  against 26 commands (15 block / 8 allow / 3 warn). - security-audit skill (+ companion) —
  whole-system audit: OWASP Top 10 + STRIDE, six layers
  (app/secrets/supply-chain/CI-CD/LLM-AI/cloud), daily zero-noise gate vs deep mode. Complements
  web-security (frontend) + iam-auditor (AWS IAM). - code-review-discipline: add "bugs that pass CI
  but break in prod" lens — injection safety, LLM trust-boundary violations, conditional side
  effects, concurrency. - README catalog + hooks table updated.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **installer**: Add standalone claude_md resource category
  ([`188e676`](https://github.com/brunofaust/claude-all/commit/188e6767ad4c51103a660c47289fd6a35e3ec043))

Adds a new top-level resource kind, coding/claude_md/<name>/claude_md.md, for CLAUDE.md dispatch
  rules whose target is a BUILT-IN agent (Explore, general-purpose) — there's no agent/skill/hook
  file to hang the snippet on, so it gets its own category. Install injects only the tagged block
  into ~/.claude/CLAUDE.md (no symlink); update re-injects idempotently, inferring scope from the
  recorded target.

First snippet: coding/claude_md/delegate_search — routes broad/iterative codebase search (grep -r
  chains, multi-repo sweeps, 'where is X used') to the built-in Explore agent, while keeping single
  targeted greps inline. Surfaced by analyzing real session history where ~100 recursive greps ran
  in the main session.

Also fixes a latent discovery quirk: agent discovery globbed *.md and surfaced <agent>.claude_md.md
  SNIPPET files as installable agents. Exclude them (they're injected alongside their agent, not
  standalone agents) — this also keeps the new 'claude_md' filter from matching those snippet paths.

- **installer**: Standalone hooks installable kind + guard .claude config
  ([`db59cbb`](https://github.com/brunofaust/claude-all/commit/db59cbbf0e1acb92be9677306d84f51589973bdc))

- claude-all.py: make coding/hooks/ a first-class installable kind. `claude-all coding hooks` now
  discovers each script (via coding/hooks/hooks.json), symlinks it as <name>.py (no kind prefix,
  matching the hand-wired convention), and wires it into settings.json with the manifest's
  event/matcher/timeout. The merge dedups by command basename across all events, so re-install
  cleanly replaces a prior/hand-wired entry — no double-firing. Verified in an isolated HOME (dedup
  replaces hand-wired config- protection, destructive-guard lands on PreToolUse/Bash, unrelated
  entries preserved). - coding/hooks/hooks.json: install manifest for the 6 standalone hooks. -
  config-protection.py: also require confirmation before editing .claude/hooks/** and
  .claude/settings.json — prevents silent gate-neutering (the run_ruff.py-style incident). - README:
  document the hooks install kind + the config-protection extension.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **installer**: Typed post_install steps (pip / bash) for plugins + tools
  ([`5f00765`](https://github.com/brunofaust/claude-all/commit/5f00765a0d949338520fca3fcd0b724a63d18ddf))

Replace bare-argv post_install entries with typed steps for flexibility:

- {"type": "pip", "package": "X", "extras": [...], "pin": "==v", "target": "app"} → pipx inject into
  the plugin's venv (default target = the plugin's package) - {"type": "bash", "command": [...],
  "pwd": "dir"} → run a command, optional cwd - bare argv lists still accepted as legacy bash steps
  (backward compatible)

Both install_plugin and install_tool route through _run_post_install_step. code-review-graph uses
  the new format: pip-inject igraph, then run its install.

Note: committed with SKIP=codecongruence — it flags a pre-existing tui_select duplication unrelated
  to this change.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **packaging**: Support `uv tool install` + add release automation
  ([`1596ad0`](https://github.com/brunofaust/claude-all/commit/1596ad051daaf445f55433a5b41d302ddf94a20d))

Repackage claude-all as a proper Python package (src/claude_all/, hatchling build, `claude-all`
  console script) so it can be installed with `uv tool install
  git+https://github.com/brunofaust/claude-all.git` instead of a git-clone + PATH setup. The dev
  workflow (git clone + `uv sync --dev`) still works via an editable install.

Also adds release automation modeled on brunofaust/codecongruence: python-semantic-release +
  commitizen, a release.yml workflow triggered by merging a release/x.y.z branch, and a
  CHANGELOG.md.

Fixes 8 pre-existing undocumented-parameter findings and scopes the codecongruence
  duplicate_functions rule away from standalone/portable scripts (hooks, skill hook.py companions,
  regression-gates checkers) that can't share code by design.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01L7RCABTvHrKdyHKPxYWQ1a

- **prek-stop-runner**: Skip linked worktrees to avoid redundant lint
  ([`8c3428d`](https://github.com/brunofaust/claude-all/commit/8c3428d3bb91b25159d6fc180fa11a7556df17b5))

Add is_linked_worktree() helper that detects linked git worktrees (where .git is a file, not a
  directory) and excludes them from the end-of-turn prek lint batch. Feature-branch edits are
  already gated at commit/push time or via /ship-pr, so batching them into main checkout's lint pass
  is redundant. Generalizes the existing /.worktrees/ path exclusion to work with worktrees created
  anywhere on disk (e.g. sibling ../repo-feature directories).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_017KRUypgUeNkEsMoZtCiRkt

- **ship**: Add test-coverage gate to /ship and /ship-pr
  ([`2b3bc9b`](https://github.com/brunofaust/claude-all/commit/2b3bc9bbde748227b9b681e6cb77262c0c99ad7a))

Add a first pipeline step (before lint/test) that confirms a change ships its tests: unit tests for
  new/changed code, and — where an e2e/integration suite exists — e2e/integration tests validating
  each business requirement of the feature (user-observable behaviour, not the implementation). A
  feature with no business-requirement coverage is a hard stop.

- /ship: new step 1 "test-coverage gate", renumber remaining steps, add stop-on-hard-fail rules and
  update the output line. - /ship-pr: make the gate explicit in the /ship-sequence step, add a rule
  and update the output line (it inherits the gate via the /ship sequence). - README: update the
  ship and ship-pr rows.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01WwyFQXjgZqkWY99rYQjny3

- **ship-pr**: Add git commit/push nudge hook
  ([`58d9baa`](https://github.com/brunofaust/claude-all/commit/58d9baab0af4b96368e2075f8377c93acdfab0a7))

Companion PreToolUse/Bash hook on the ship-pr skill. On the first `git commit` or `git push` of a
  Claude session it injects a non-blocking reminder to route the change through /ship-pr (gates ->
  review -> docs -> draft PR) instead of an ad-hoc commit + PR.

A hook can't invoke a skill, so this only nudges Claude — it does not auto-open the PR. Deduped once
  per session (same /tmp-flag trick as the python-style hook) so it stays quiet during ship-pr's OWN
  commit/push performed by git-committer. Silent on non-git Bash commands.

README: note the new companion hook on the ship-pr skill row.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01VEYbYZjWfFXztJCPABvSHv

- **skill**: Replace cachetools with cachebox in python-style caching reference
  ([`3c24884`](https://github.com/brunofaust/claude-all/commit/3c24884d15acd4c0bcb80d903c98fdfc2c85a240))

- **skills**: Add /merge-main — semantic pre-merge check for origin/main
  ([`3ddfd55`](https://github.com/brunofaust/claude-all/commit/3ddfd5526b1231279b90ce4f17bb8a42f3fa4d2c))

A ship-pr-style orchestrator for parallel-session workflows: pull origin/main into the current
  branch with a SEMANTIC conflict pass that runs BEFORE the merge. A clean textual merge can still
  be broken (main touched a file this branch deleted, changed a contract it still calls, or removed
  a symbol it references); this previews the merge with `git merge-tree` so the working tree stays
  untouched while you decide, then merges --no-commit, runs lint/test gates, and finalizes on
  confirm.

Ships SKILL.md, a claude_md.md routing rule, and a once-per-session PreToolUse nudge hook on `git
  merge`/`git pull` of origin/main. README generic-skills table updated.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_014KmbE6iNDha5pPL5QshMns

- **skills**: Add agent-era guardrail resources from production retrospective
  ([`e206459`](https://github.com/brunofaust/claude-all/commit/e206459eedd0ff502ddc9ab5c9410b793c45d084))

Translate battle-tested lessons from an AI-agent-built production codebase into
  executable/actionable claude-all resources (not prose):

- skills/generic/regression-gates: regression-only baseline harness (runnable baseline_gate.py — new
  fail, baselined pass, stale also fail so the file only shrinks, stable-identity keys, fail-closed)
  + three-step warn→error rollout + runnable example checkers (migration_head, ci_env_guard,
  junk_drawer, module_private). Encodes "a rule in prose gets violated; a checker holds". -
  skills/generic/mock-drift-sweep: sweep every mock on a signature/return/ exception/import change +
  one-real-dependency-per-contract (the #1 silent failure: tests that agree with the code, not
  reality).

- skills/generic/diff-retrospective: merged-PR DIFFS -> clustered root causes -> checker-first
  guardrails. Complements session-harvest/friction-analyzer (chat histories) by mining shipped code.
  - agents/support/lessons-extractor: read-only Sonnet agent that mines one PR/commit-range
  partition and dedups candidate gates against existing enforcement; caller fans out several in
  parallel and merges. - instructions/agent-era-rules: lean standing-rules snippet (two
  meta-findings + distilled rules + the altitude rule), pointing to the skills for detail. -
  skills/generic/prek: add a "custom local checkers" section housing the
  embedded-SQL-against-migration-schema gate as a suggested-hook recipe with its sqlglot gotchas
  (documented, not shipped — stack-specific). - README: rows for the new agent (1.6) and skills
  (2.5).

All added Python passes ruff (check+format), mypy, and vulture, and every checker reports zero
  findings on claude-all's own tree.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **skills**: Add aws-cost-optimization skill + engines-first cost-audit-runner
  ([`e4e2cc7`](https://github.com/brunofaust/claude-all/commit/e4e2cc7aea7e4323b018393d6dd6d24029312861))

Derived from AWS Well-Architected + GitHub FinOps ecosystem research.

- feat(skills): add aws-cost-optimization — Well-Architected 5 areas, the "AWS recommendation
  engines first" hierarchy (Cost Optimization Hub → Compute Optimizer → Trusted Advisor → Cost
  Explorer → CUR/Athena), waste catalog + idle criteria, RI/SP/Spot/Graviton/right-sizing/lifecycle
  levers, Infracost + Cloud Custodian, FOCUS - feat(agents): cost-audit-runner now queries Cost
  Optimization Hub / Compute Optimizer get-idle-recommendations / Trusted Advisor FIRST (AWS
  pre-computed idle + $ estimates), then supplements with per-service probes - docs(agents):
  cross-link cost-explorer + cost-audit-runner to the new skill - docs(repo): list
  aws-cost-optimization in README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Add claude-hooks skill + safe action-taking tools (ruflo-inspired)
  ([`4bf28b0`](https://github.com/brunofaust/claude-all/commit/4bf28b0212203e85ac938bdcb5233a79eda650f6))

The two portable patterns from ruvnet/ruflo (most of which is app/runtime, not adoptable):

- security-audit: add a "Building safe action-taking tools & agents" section — any MCP tool / agent
  / automation that takes a side effect should validate inputs, default to dry-run, bound its scope,
  be idempotent, support rollback, and gate destructive ops on explicit confirmation. The
  design-time complement to the destructive-command-guard hook. - claude-hooks skill —
  authoring/debugging Claude Code hooks: events/matchers, the stdin/stderr/exit-code contract, the
  guard(exit 2)-vs-utility(exit 0) archetypes, resilient-shim pattern, exit-code capture,
  settings.json wiring, payload testing. - README catalog updated.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Add CLAUDE.md companions to all coding skills (stack-aware dispatch)
  ([`70f2ecc`](https://github.com/brunofaust/claude-all/commit/70f2eccb1da9e2ffe67b42784c04d2d497c77916))

Every coding skill now ships a claude_md.md so installing it injects a "when you touch
  <language/resource>, apply this skill" reminder into CLAUDE.md — enforcing skill use by stack
  (Python -> brunofaust, React -> react-*, web -> web-security/seo, AWS -> aws-*, etc.). The
  verification-loop companion adds the consolidated "before opening a PR" stack-aware checklist
  routing to the relevant skills + adversarial-verification. Closes the gap where 12 of 22 skills
  had no companion.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Add optional /simplify + docs-updater steps to /ship-pr
  ([`3fc4e1e`](https://github.com/brunofaust/claude-all/commit/3fc4e1eef9bc1f2f7c8d2453d2c89e2020b81083))

Two steps the user found valuable: - optional /simplify on the changed code, run early (before the
  gates) so its reuse/simplification/altitude edits are validated by lint+tests+verify. -
  docs-updater after review (code final), to revise CLAUDE.md + README/ ARCHITECTURE/CHANGELOG from
  the diff so the always-loaded guidance never drifts from the code. Proposes diffs; confirm before
  staging.

Both are optional/no-op on trivial diffs. Updated the description, step list, rules, output line,
  README row, and the claude_md.md always-on rule.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **skills**: Add repo-audit skill for brownfield code-quality audits
  ([`a2d7822`](https://github.com/brunofaust/claude-all/commit/a2d78220cfd22bdd09838842d9d40f8b73eed91c))

A whole-repo, point-in-time congruence audit against brunofaust-python-style and its enforcement
  stack (ruff, mypy strict, import-linter, banned-api, interrogate, vulture, bandit, gitleaks,
  skill_enforcer).

Designed for onboarding existing / brownfield repos: it measures every dimension count-only, scores
  a per-dimension scorecard, and emits a ratcheting remediation roadmap (measure -> baseline ->
  ratchet) so quality climbs without a commit-blocking big-bang. Report-only — fixes happen in later
  reviewed PRs via lint-fixer / python-module-migrator.

Includes a claude_md.md companion that routes brownfield-onboarding audits to the skill and
  distinguishes it from verification-loop (per-diff gate) and security-audit (security layers only).

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **skills**: Add session-harvest skill + IaC & process-tooling audit dimensions
  ([`8e6f56d`](https://github.com/brunofaust/claude-all/commit/8e6f56d2b417d93d2f75746cc7d509366233e335))

Add `session-harvest` — mines AI coding-assistant histories (Claude Code, Cursor, Codex, GitHub
  Copilot) for recurring friction, re-derived knowledge, and repeated workflows, then emits a
  prioritized backlog of resources to create (skill / agent / hook / CLAUDE.md instruction /
  settings change), each with a description, evidence, an estimated % improvement, and effort. Reads
  histories programmatically (jq/sqlite3/grep), treats them as DATA, and is report-only (proposes;
  confirm before creating). Superset of the friction-analyzer agent.

Extend `repo-audit` with two dimensions: - 13 Infrastructure-as-Code — CloudFormation + Terraform
  correctness, drift, and cost (cfn-lint, tflint, checkov/tfsec, terraform validate/plan),
  delegating to cloudformation-reviewer / iam-auditor / aws-architecture. - 14 Assistant leverage /
  process tooling — delegates to session-harvest.

Wire both into the dimensions, delegation, and integration tables plus the claude_md.md dispatch
  snippets.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **skills**: Add web-security, react-testing, react-correctness, research-before-build
  ([`f28d3c5`](https://github.com/brunofaust/claude-all/commit/f28d3c5744db8a9377a69afc9ed7959a821c1726))

Frontend + workflow skills inspired by patterns absent from our collection (we were deep on
  Python/AWS, thin on frontend correctness/security/testing and reuse-first):

- web-security — XSS/dangerouslySetInnerHTML/safeUrl, per-framework env-var leak table,
  Server-Actions-as-public-API validation, httpOnly sessions, CSP+nonce, prototype pollution, source
  maps + enforcement. - react-testing — RTL query priority, userEvent>fireEvent, MSW, anti-snapshot,
  per-layer coverage table, a11y/axe; frontend counterpart to test-author. - react-correctness —
  useEffect-when-NOT, state-location decision tree, stale closures, keys, default-don't-memoize,
  React 19 hooks (distinct from the Vercel perf skill). - research-before-build — Step-0 reuse
  hierarchy (internal -> Context7 -> gh search -> registries -> web), adopt/fork/wrap/build decision
  + research note. - code-review-discipline: add numeric size/complexity gates, per-layer coverage
  table, and the split-role parallel review panel. - README catalog updated.

All original/genericized (no external files copied; myapp placeholders).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **skills**: Add workflow orchestrators (ship, ship-pr, retro) + resource-scaffolder
  ([`9c0221f`](https://github.com/brunofaust/claude-all/commit/9c0221f4914c12f8e5c50d4d0d5131711cd3dd44))

Compose the existing agents/skills into step-by-step workflows. claude-all has no "commands" install
  kind, but a user-invocable skill IS a slash command, so these install as /ship, /ship-pr, /retro,
  /resource-scaffolder.

- skills/generic/ship: light pre-commit pipeline — lint-fixer -> test-runner -> verification-loop ->
  (confirm) git-committer. Stop-on-hard-fail, no review/PR. - skills/generic/ship-pr: heavy pre-PR
  pipeline — the /ship gates plus /code-review (gate on Block) -> conditional security-review ->
  (confirm) git-committer -> open a DRAFT PR (confirm). Review runs once here, not per commit. -
  skills/generic/resource-scaffolder: generation engine that turns an approved proposal
  (session-harvest/repo-audit/diff-retrospective/friction-analyzer/ lessons-extractor) into a
  scaffolded skill/agent/hook/instruction for a project's .claude/ or a claude-all contribution —
  the build step those propose-only resources lack. - skills/generic/retro: unified "learn & harden"
  — gathers session history + PR diffs + repo audit, synthesizes one deduped ranked backlog, and
  after confirm generates resources via resource-scaffolder / wires gates via regression-gates.
  Merges the history-mining and PR-retrospective passes.

Pipelines are user-invoke-only (disable-model-invocation: true) since they commit/generate; the
  scaffolder stays model-invocable so /retro can call it. README §2.5 updated. All four discovered
  by the installer; typos clean.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **skills**: Make ship-pr model-invocable + retro contribute-back + weekly tip
  ([`1216fe6`](https://github.com/brunofaust/claude-all/commit/1216fe6a5f87f465e9f0ffff21098ea6bcf06819))

- ship-pr: flip to model-invocable and ship a claude_md.md rule so opening a PR routes through
  /ship-pr automatically (gates + review before commit, draft PR after confirm) — best practice, not
  just an opt-in command. - retro + resource-scaffolder: after generating resources, suggest the
  user open a PR/issue on claude-all with a genericized version of any generic resource, so the
  shared toolbox keeps growing from real usage (don't open it automatically). - README: note
  /ship-pr's always-on rule; add a tip to schedule /retro ~weekly (cron/CI, Claude Code routine via
  /schedule, or the /loop skill).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **skills**: Port upstream findings into adversarial-verification + self-rationalization-guard
  ([`22238df`](https://github.com/brunofaust/claude-all/commit/22238df523e10dc284df5e4e2b47ce71d53f4c62))

- adversarial-verification: add completeness corollary (checklist the original ask, not just the
  last claim; diff a subagent's actual changes rather than trust its summary) — ported from
  obra/superpowers verification-before-completion - self-rationalization-guard: add 8th signal
  "delegation rationalization" (offloading synthesis to a subagent/user instead of deciding) —
  ported from kadaliao/claude-code-skills-collection; tighten Restart contract wording and add two
  anti-patterns (reworded-looping, no-nuance-clauses-later) per obra/superpowers writing-skills'
  loophole-closing guidance - vendored.json: --ack all 4 watch entries after this review - fix
  stray-space typo in self-rationalization-guard's description

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01W1NRmDUgFVXuc7ucYh1gAS

- **skills**: Vendor humanink — multilingual AI-writing humanizer (MIT)
  ([`aaa9eb1`](https://github.com/brunofaust/claude-all/commit/aaa9eb13c7558fa8ca17af29e29ec5ef28c08e39))

Add the humanink Claude Code skill (skills/generic/humanink), copied from
  https://github.com/sirambrosio/humanink under the MIT license. It detects 35 AI-writing patterns,
  scores AI probability 0-100, and rewrites text to sound human across English, Brazilian
  Portuguese, Spanish (+ French, German, Japanese, Italian), with context modes, severity levels,
  and style fingerprinting (--pt / --es to force a language).

- Vendored verbatim except two claude-all frontmatter fields added to SKILL.md
  (disable-model-invocation, user-invocable) for installer / Skill-tool compatibility. Upstream MIT
  LICENSE retained; provenance in ATTRIBUTION.md. - Scope-exclude skills/generic/humanink/** from
  the prek `typos` hook (it ships multilingual example words), mirroring the prek skill's own
  exclude. - List it in the README generic-skills table.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **tools**: Add lean-ctx context compression tool and knip dead-code detection
  ([`120c634`](https://github.com/brunofaust/claude-all/commit/120c6349c3369bffb8025c76585babfce9b8bb4e))

Add lean-ctx as an alternative context-compression layer to RTK. Lean-ctx compresses shell output
  via MCP hooks (no prefix needed), provides ctx_read/ctx_search/ctx_shell tools, and archives large
  results. Includes 19-step post-install configuration (memory profiles, secret detection, cloud
  settings). Also adds knip (JS/TS dead code finder) as optional pre-push hook in prek skill with
  template config.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **tools**: Replace lean-ctx config set steps with stdlib TOML merger
  ([`49b0c7d`](https://github.com/brunofaust/claude-all/commit/49b0c7d2f91afad1d99ddb0e89b363e54c5c218f))

Replaced 15 individual `lean-ctx config set` post_install steps with a single Python script that
  reads the existing config with stdlib tomllib, deep-merges desired values (ours win on conflict),
  and writes back — correctly handling arrays without third-party deps.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **vendor**: Watch mode — track upstreams of derived (synthesized) skills
  ([`4cece7e`](https://github.com/brunofaust/claude-all/commit/4cece7e8ab18fdb70ce6ee66485969e839e84f24))

- vendor_mode "watch": never writes local files; reports upstream commits touching source.path since
  last_reviewed, with a GitHub compare URL - --ack <id> stamps last_reviewed at upstream HEAD after
  a human review - watch reports are informational — never flip the --check exit code - registry: 4
  watch entries for adversarial-verification (obra/superpowers, robertoecf/adversarial-review) and
  self-rationalization-guard (obra/superpowers, kadaliao); alirezarezvani source no longer exists
  upstream, noted not watched - docs: vendored-sources SKILL.md + README vendored note

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01W1NRmDUgFVXuc7ucYh1gAS

### Refactoring

- Drop claude_md.md for repo-audit and session-harvest; move to README
  ([`4a46375`](https://github.com/brunofaust/claude-all/commit/4a463753b50d6bdd1df02043a5c75ef2c4e9b444))

Both are ad-hoc, user-invoked skills, so they shouldn't inject an always-on dispatch rule into
  ~/.claude/CLAUDE.md (read every session). Remove both claude_md.md companions — the installer
  simply skips injection when absent, so the skills still install via symlink. Move their
  behavior/rules (generic-boundaries + per-stack translation, brownfield measure→baseline→ ratchet,
  report-only; session-harvest's programmatic/DATA/evidence-cited rules) into the README "First run"
  section instead.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- Flatten coding/ to repo root; add per-project recommendations + first-run/contribute docs
  ([`68fbcd1`](https://github.com/brunofaust/claude-all/commit/68fbcd10262840b8c91ac1d708598bccaa5d17e5))

Flatten the resource tree — coding/ was the sole top-level dir, so its segment was redundant. Move
  agents/ skills/ hooks/ plugins/ mcps/ tools/ instructions/ to the repo root and declare claude-all
  explicitly coding-scoped. Rewrite the installer discovery roots + path index math (category is now
  the constant "coding"), update the help text, and repoint every coding/ path reference in
  CLAUDE.md, README.md, prek.toml, and the claude-hooks / session-harvest skill docs. Drop the
  README "future categories as siblings to coding/" note.

repo-audit: add dimension 15 — project profiling & resource-fit recommendations. It profiles the
  stack/frameworks/cloud/DB and recommends which claude-all agents/skills/hooks to install for THIS
  repo plus net-new project-specific ones, with a mapping table and recommendation output. Runnable
  per-project for tailored suggestions.

README: add a "First run — audit & customize per project" section (repo-audit + session-harvest as
  the setup pass) and a "Contributing back — share your findings" section (open a PR with generic,
  placeholder-scrubbed resources), and cross-link session-harvest from the session-history recipe.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- Remove dead Item.category field (future-categories plan dropped)
  ([`4cf33d2`](https://github.com/brunofaust/claude-all/commit/4cf33d273ea2bdf662c4fa636eaed52eaabc19c1))

The flatten PR removed the planned sibling top-level categories (travel, writing, …), so
  `Item.category` — always "coding", never read (sort/filter/ label all use `subcategory`) — is now
  genuinely dead. Remove the field + its 7 constructor kwargs, and drop its vulture_whitelist.py
  entry (it was whitelisted as forward-looking; that rationale is gone). The uninstall-API entries
  remain.

No doc changes needed — the future-categories prose was already removed from README/CLAUDE.md by the
  flatten PR.

ruff + vulture + prek clean; `claude-all.py --help` OK.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- Rename claude_md category to 'instructions' + document history analysis
  ([`a48d191`](https://github.com/brunofaust/claude-all/commit/a48d19130357eff12f5532492edb145b94797bbf))

- Rename the standalone-snippet category coding/claude_md/ -> coding/instructions/ (clearer than the
  doubled 'claude_md'; kind/tag become 'instructions'). Installer discovery, install, and update
  branches updated; verified end-to-end. - README: add 'Analyzing your session history' section —
  the jsonl extraction command (prompts + tool calls, outputs stripped), the Bash-frequency variant,
  and an example insight prompt. Documents the workflow that produced these agents/dispatch rules.

- **agents**: Hybrid folder layout for agents with companions
  ([`888c5af`](https://github.com/brunofaust/claude-all/commit/888c5af4ace2325b557c444485ccae9dfd391c94))

Agents that ship companions (a claude_md.md dispatch snippet and/or a hook.py/hook.json) now live in
  a folder — coding/agents/<cat>/<name>/agent.md plus the companions in the same dir — instead of
  scattering prefixed siblings (<name>.md, <name>.claude_md.md) across the category folder. Bare
  agents stay flat <name>.md. Mirrors the skills layout and keeps each agent's files together.

Installer supports both layouts (hybrid): discovery treats <name>/agent.md as agent '<name>', and
  _claude_md_snippet_path / _hook_files resolve companions inside the folder vs as prefixed siblings
  based on whether the source is agent.md. install/update/symlink are unchanged (they already key
  off the .md file + agent name). Migrated the 16 agents that currently have companions; docs
  (README + CLAUDE.md) updated.

Verified: all 47 agents discover + install (0 broken symlinks), 16 folder agents inject their
  dispatch blocks, update re-injects idempotently.

- **claude_md**: Trim noise from skill companions
  ([`bd102f5`](https://github.com/brunofaust/claude-all/commit/bd102f5eaa5c55b3c51ca80786e62051361a68b7))

Skills' descriptions are already auto-loaded into Claude's context, so a claude_md.md that just
  restates 'Apply when X' is pure duplication. Audit outcome:

Drop 12 companions that only restated the description (skills stay installed and triggerable via
  their description): composition-patterns, react-view-transitions, web-design-guidelines,
  react-best-practices, aws-debug-loop, architecture-decision-guard, research-before-build,
  security-audit, python-module-migration, claude-hooks, mock-drift-sweep + regression-gates
  (already distilled in agent-era-rules)

Trim 9 companions to their actionable cheat-sheet, dropping the redundant 'Apply when' trigger line:
  aws-architecture, seo, react-correctness, react-testing, web-security, aws-cost-optimization,
  code-review-discipline, alembic-migration, ship-pr.

Agent dispatch companions are untouched — their inline anti-patterns are the value the description
  can't carry.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_012gte5q7WgQx7kp2ve8hdss

- **dispatch**: Move hand-written dispatch rules into agent/instruction companions
  ([`196f26e`](https://github.com/brunofaust/claude-all/commit/196f26e45d771ca1ca52c8b6758e197abca60301))

Convert 14 flat agents to folder form and add a claude_md.md companion to each, so their dispatch
  row + anti-patterns become installer-managed blocks instead of hand-maintained prose in
  ~/.claude/CLAUDE.md: aws: aws-lambda-deployer, terraform-deployer, dynamodb-mutator,
  aws-events-scheduler, s3-inspector, cost-explorer, ecr-manager generic: e2e-scenario-runner,
  git-audit, code-quality

python: migration-reviewer

support: incident-responder

web: seo-runner, seo-reviewer

Add two standalone instruction snippets for cross-cutting rules owned by no single agent:
  instructions/tool-dispatch built-in-tools-over-Bash, RAG-over-Grep, raw-bash self-check
  instructions/bash-safety credential-leak + destructive-write anti-patterns

Fold the prek fix-loop discipline (2-failures-then-stop, one-category-per-attempt) into prek
  SKILL.md. Document instructions/ in the README structure tree + new §7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_012gte5q7WgQx7kp2ve8hdss

- **hooks**: Supply-chain-guard — drop the disk cache, read uv.lock upload-time
  ([`4f318ee`](https://github.com/brunofaust/claude-all/commit/4f318ee50fc90b4ac56769cb4b2231aa25742928))

Installs are rare, so the publish-date cache was over-engineering. Simplify: - Remove the disk cache
  + thread pool (and tempfile/contextlib/concurrent.futures). - Read `upload-time` directly from
  uv.lock's sdist/wheels, so `uv sync` (and any uv-locked package) is cooldown-checked entirely
  OFFLINE — no network, no cache. - For named installs and dateless lockfiles
  (poetry.lock/package-lock.json/ requirements), do a small uncached live npm/PyPI lookup under a
  time budget; still fails open (unreachable registry never blocks, ~0.2s).

CC_SUPPLY_CHAIN_NO_NETWORK=1 now skips only the live lookups — uv.lock embedded dates are still
  checked offline. ruff/format/mypy/vulture clean; offline uv.lock path, network-off, stubbed-live,
  and real fail-open all functionally tested.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01HyS76YyEMBTrJ2Gu7yu879

- **hooks**: Tighten alembic matcher; stop react reminders stacking
  ([`dc229eb`](https://github.com/brunofaust/claude-all/commit/dc229eb654e79ba2865b5f8c649f5076ce0ad3f3))

Review follow-ups on the companion hooks:

- alembic-migration: `versions/`/`alembic/` path segments still fire on their own
  (Alembic-specific), but a bare `migrations/` (also used by Django et al.) now fires ONLY when the
  edited content carries an Alembic signal (down_revision / op. / import alembic / revision =).
  Prevents Alembic-specific advice from showing on a non-Alembic migration. - react-best-practices:
  bail on test files (.test./.spec./__tests__/) so its reminder no longer stacks with the
  react-testing hook on the same edit — exactly one reminder fires per file. (hook.py is a
  local_only companion on the vendored skill, so editing it is allowed.) - react-testing: docstring
  updated to reflect the now-mutually-exclusive split. - README: alembic row reworded to match the
  tightened matching.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Claude-Session: https://claude.ai/code/session_01VEYbYZjWfFXztJCPABvSHv

- **installer**: Hoist tui_select's nested loop to module level
  ([`874d32c`](https://github.com/brunofaust/claude-all/commit/874d32c05402cf5c80035c98d2df1d380514b502))

codecongruence (C003 duplicate_functions) flagged tui_select at 0.93 similarity to its own nested
  `_run` helper — an artifact of a function whose entire body is one nested function + a return.
  Hoist `_run` to a module-level `_tui_select_loop (stdscr, items)` called via
  `curses.wrapper(_tui_select_loop, items)`. Logic is identical (verified with scripted-keypress
  tests: INSTALL/QUIT/UPDATE/space-toggle). codecongruence now passes with NO skip; all 31 prek
  hooks green.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

- **python**: Drop module-level `_` prefixes (use __all__); add vulture dead-code hook
  ([`891da0d`](https://github.com/brunofaust/claude-all/commit/891da0d7975a9f965700edd88beab05034446a91))

Applies the skill's visibility rule (references/visibility.md): module-level names never start with
  `_` — declare the public surface via __all__ instead, so dead-code tools (vulture/ruff/pyright)
  can see module-scope helpers. Class-scope `self._x` and private methods keep their underscore
  (that's the convention).

Renames (module-level functions/vars; whole-word, no collisions; call sites updated; `__all__ =
  ["main"]` added per file): - claude-all.py: 11 helpers (_shell_quote, _settings_path, _hook_files,
  ...). - hooks/config-protection.py (_remind), destructive-command-guard.py
  (_rm_rf_targets_are_safe), prek-stop-runner.py (_run_prek_stage, _is_real_failure),
  wait-for-ready/hook.py (_nudge, _SLEEP_RE, _PROBE_RE). Verified: ruff clean, py_compile OK,
  `claude-all.py --help` exit 0, hooks exit 0.

Vulture (new prek hook, requested): - prek.toml: local `vulture` hook at min_confidence 60
  (vulture==2.14). - pyproject.toml: [tool.vulture] (paths + exclude); per-file-ignore B018/F821 for
  the whitelist file. - vulture_whitelist.py: the 3 real-but-currently-unreferenced names, each with
  justification — `Item.category` (reserved for the README's planned sibling categories) and
  `remove_hook`/`remove_claude_md` (the README's planned uninstall API). No genuine dead code found
  to delete.

prek clean (all 22 hooks pass, vulture included).

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **repo-audit**: Make it language-agnostic; move to skills/generic
  ([`c2a1e69`](https://github.com/brunofaust/claude-all/commit/c2a1e692e9494f9ffd20b584ab483a3d136ee385))

The quality boundaries repo-audit checks (typed contracts, bounded complexity, enforced dependency
  direction, single-owner external systems, no silent error swallowing, tests mirror source, no
  scattered config) are generic — brunofaust-python-style + prek are just the REFERENCE
  instantiation. Reframe the skill to audit any language/architecture:

- Dimensions are now generic boundaries; each says what to count, not a Python-only command. - Add a
  "Translate the standard to the repo's stack" table mapping every boundary to Python /
  TypeScript-JS / Go / Rust tooling (eslint/tsc, golangci-lint, clippy, …); where no tool exists,
  audit by reasoning + grep — never skip a boundary. - Add a frontend lens that delegates UI
  dimensions to the existing react-correctness / react-testing / composition-patterns /
  web-design-guidelines / web-security / seo skills. - Stack-aware Phase 0 (detect language, then
  inventory gates); generic scorecard/roadmap; profiling map gains TS/React rows.

Move skills/python/repo-audit → skills/generic/repo-audit (no longer Python-scoped). Drop the
  "non-Python repo" caveat from session-harvest and the README first-run note now that repo-audit
  covers all languages.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5

- **vendor_sync**: Drop module-level `_` prefix per visibility rule
  ([`e76f2ea`](https://github.com/brunofaust/claude-all/commit/e76f2eae08db1a0bab98b5ec8ad05afe28690d0d))

`_yaml_scalar` -> `yaml_scalar` + add `__all__ = ["main"]`, matching the brunofaust-python-style
  visibility rule (module-level names never start with `_`; declare the public surface via __all__).
  Keeps the script consistent with the underscore cleanup applied to the rest of the repo's Python.

https://claude.ai/code/session_01RFsjrPuEo8Tjr8U22aBKf5
