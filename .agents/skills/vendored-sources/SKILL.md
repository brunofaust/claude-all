---
name: vendored-sources
description: >-
  How this repo vendors (copies) third-party skills/agents from upstream GitHub repos, and how to keep
  them updated and properly attributed. Use when: importing/copying an external skill or agent into the
  repo, asked to "update the imported/vendored skills", refreshing a vendored resource from upstream,
  adding attribution/license to a copied resource, or auditing provenance. Covers the central registry
  (vendored.json), the sync script (scripts/vendor_sync.py), the keep-vendored-files-pristine
  discipline, and the MIT/attribution rules. Pairs with research-before-build (reuse) and repo-audit.
disable-model-invocation: false
user-invocable: true
---

# Vendored Sources

Some skills/agents here are **copied from third-party repos** (e.g. Vercel's `agent-skills`,
`humanink`). This skill is the discipline for vendoring them cleanly, attributing them correctly, and
**updating them from upstream on demand**.

## The registry — `vendored.json` (repo root)

One entry per imported resource. The sync script and all provenance derive from it.

| Field | Meaning |
| --- | --- |
| `id` | unique key (used by `--id`) |
| `kind` | `skill` / `agent` |
| `path` | local path in this repo |
| `vendor_mode` | `dir` (copy whole upstream subpath) · `files` (explicit list) · `reference` (live-fetched at runtime — nothing copied, never synced) · `watch` (DERIVED resource — nothing copied; sync only reports upstream movement) |
| `source` | `{ repo, ref, path }` — upstream repo, branch/tag, and subpath (`.` = repo root) |
| `license`, `author` | for attribution |
| `files` | (files mode) the explicit list to copy |
| `local_only` | files that live **only** here (sidecars) — the sync never overwrites or deletes them |
| `frontmatter_inject` | key/values re-applied to the entry's `SKILL.md` after each sync (e.g. Codex-all's `user-invocable`) |
| `last_synced` | `{ date, commit }` — stamped by the sync script (copy modes) |
| `last_reviewed` | `{ date, commit }` — (watch mode) last upstream commit a human reviewed; advanced only by `--ack <id>` |

## Updating — "update the imported skills"

```bash
python scripts/vendor_sync.py --check          # dry-run: report drift for every entry, write nothing
python scripts/vendor_sync.py                  # sync all; refresh files + stamp last_synced
python scripts/vendor_sync.py --id humanink    # sync just one
```

For each entry the script shallow-clones `source.repo` at `source.ref`, refreshes the local files,
**preserves `local_only`**, re-applies `frontmatter_inject` to `SKILL.md`, and records the upstream
commit. It needs `git` + network. **Always review the diff and commit** — the script never commits.
`reference` entries are reported and skipped (they're already always-latest).

## Derived resources — `watch` mode

Some local resources were **synthesized from** upstream repos (rewritten, not byte-copied) — e.g.
`adversarial-verification` and `self-rationalization-guard` from obra/superpowers and others. The
sync must never overwrite them (that would destroy the adaptation), but upstream improvements should
still surface. A `watch` entry solves this: the script clones with history and reports **how many
upstream commits touched `source.path` since `last_reviewed`**, with a GitHub compare URL — and
never writes a local file. Watch reports are informational only: they never flip the `--check` exit
code. Porting is a deliberate human step; after reviewing (and porting what's worth porting), run

```bash
python scripts/vendor_sync.py --ack <id>       # stamp last_reviewed at upstream HEAD
```

One watch entry per (local resource, upstream source) pair — a skill synthesized from two repos gets
two entries (`<skill>@<source>` ids).

## Core discipline — keep vendored files pristine

- **Don't edit vendored files in place.** Byte-identical-to-upstream files mean clean sync diffs. Put
  every local addition (attribution, AGENTS.md snippet, hooks) in a **`local_only`** sidecar so the
  sync preserves it. The only sanctioned in-file change is `frontmatter_inject` (re-applied each sync).
- **Attribution is mandatory.** Each vendored dir gets an `ATTRIBUTION.md` (source repo, path, ref,
  author, license, local changes). If upstream ships a `LICENSE`, **vendor it verbatim** (MIT etc.
  require keeping the copyright + permission notice). If upstream declares a license but ships no
  file (e.g. inline `license: MIT` in frontmatter), record that in `ATTRIBUTION.md` — **never fabricate
  a copyright notice**.
- **Respect the license.** Only vendor permissive licenses (MIT/Apache/BSD/ISC). For anything else or
  unlicensed, stop and ask — a `reference` (live-fetch / link) may be the only safe option.

## Adding a new vendored resource

1. `research-before-build` — confirm it's worth importing and check the license.
1. Copy the files into `skills/<cat>/<name>/` (or `agents/...`); keep them verbatim.
1. Add `ATTRIBUTION.md` (+ vendor the upstream `LICENSE` if it has one).
1. Add a `vendored.json` entry; list sidecars in `local_only` and any patches in `frontmatter_inject`.
1. If the resource ships multilingual / intentional-misspelling content, scope-exclude its path from
   the prek `typos` hook (see the `prek` skill).
1. `python scripts/vendor_sync.py --check --id <id>` to confirm the entry resolves;
   `./Codex-all --list <name>` to verify discovery; run `prek`.

## Anti-patterns

| Anti-pattern | Instead |
| --- | --- |
| Editing a vendored `SKILL.md` to add provenance | sidecar `ATTRIBUTION.md` (`local_only`) + registry |
| Copying without attribution / license | always `ATTRIBUTION.md`; vendor upstream `LICENSE` verbatim |
| Fabricating a copyright line when upstream has none | record the declared license in `ATTRIBUTION.md` only |
| Vendoring a non-permissive / unlicensed repo | stop and ask; consider a `reference` entry |
| Hand-editing vendored files then losing them on sync | put local changes in `local_only` / `frontmatter_inject` |
| No registry entry | add to `vendored.json` so it's tracked + updatable |
