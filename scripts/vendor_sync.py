#!/usr/bin/env python3
"""Sync vendored (third-party) skills/agents from their upstream repos.

Reads ``vendored.json`` (repo root) and, for each entry, shallow-clones the
upstream repo at its ref and refreshes the local copy — while preserving
``local_only`` files (our sidecars: ATTRIBUTION.md, claude_md.md, hook.*) and
re-applying ``frontmatter_inject`` keys to the entry's SKILL.md.

Usage::

    python scripts/vendor_sync.py                 # sync every entry, update registry
    python scripts/vendor_sync.py --id humanink   # sync one entry
    python scripts/vendor_sync.py --check         # dry-run: report drift, write nothing
    python scripts/vendor_sync.py --ack <id>      # mark a watch entry as reviewed

`reference` entries (live-fetched at runtime) are reported and skipped.
`watch` entries track upstreams our resources were DERIVED from (synthesized,
not byte-copied): the script never writes their local files — it reports how
many upstream commits touched the watched path since ``last_reviewed`` (with a
compare URL) so the port/review stays a deliberate human step. Watch reports
are informational only and never affect the ``--check`` exit code; after
reviewing, run ``--ack <id>`` to advance ``last_reviewed`` to upstream HEAD.
Requires ``git`` and network access. Review the diff and commit the result.
"""

import argparse
import filecmp
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["main"]

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "vendored.json"


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return its stripped stdout."""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def clone_upstream(repo: str, ref: str, dest: Path) -> str:
    """Shallow-clone ``repo`` at ``ref`` into ``dest``; return the HEAD commit."""
    run_git(["clone", "--depth", "1", "--branch", ref, repo, str(dest)])
    return run_git(["rev-parse", "HEAD"], cwd=dest)


def clone_with_history(repo: str, ref: str, dest: Path) -> str:
    """Blobless single-branch clone (full history, no file contents); return HEAD.

    Watch entries need history to count commits since ``last_reviewed``; a
    ``--filter=blob:none`` clone keeps that cheap.
    """
    run_git(["clone", "--filter=blob:none", "--single-branch", "--branch", ref, repo, str(dest)])
    return run_git(["rev-parse", "HEAD"], cwd=dest)


def compare_url(repo: str, old: str, new: str) -> str:
    """GitHub compare URL for two commits of ``repo``."""
    return f"{repo.removesuffix('.git')}/compare/{old[:12]}...{new[:12]}"


def process_watch(entry: dict[str, Any], *, ack: bool) -> tuple[bool, bool]:
    """Report upstream movement for a derived (watch) entry; never writes local files.

    Returns ``(changed, errored)`` where ``changed`` is always False — watch
    reports are informational and must not flip the ``--check`` exit code.
    With ``ack=True``, advances ``last_reviewed`` to upstream HEAD instead.
    """
    name, src = entry["id"], entry["source"]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            head = clone_with_history(src["repo"], src["ref"], Path(tmp) / "up")
        except subprocess.CalledProcessError as e:
            print(f"  ! {name}: clone failed — {e.stderr.strip()}", file=sys.stderr)
            return False, True

        if ack:
            entry["last_reviewed"] = {
                "date": datetime.now(UTC).date().isoformat(),
                "commit": head,
            }
            print(f"  ✓ {name}: last_reviewed → {head[:8]}")
            return True, False

        last = entry.get("last_reviewed", {}).get("commit")
        if not last:
            print(f"  ? {name}: watch — no last_reviewed recorded (upstream at {head[:8]})")
            print(f"      run --ack {name} after an initial review")
            return False, False
        path_args = [] if src["path"] == "." else ["--", src["path"]]
        try:
            count = int(
                run_git(["rev-list", "--count", f"{last}..HEAD", *path_args], cwd=Path(tmp) / "up")
            )
        except (subprocess.CalledProcessError, ValueError):
            print(
                f"  ! {name}: last_reviewed commit {last[:8]} not found upstream "
                "(history rewritten?) — re-review and --ack",
                file=sys.stderr,
            )
            return False, True

    if count == 0:
        print(f"  = {name}: watch — no upstream changes since last review ({last[:8]})")
    else:
        print(
            f"  ~ {name}: watch — {count} upstream commit(s) touching {src['path']!r} "
            f"since {last[:8]}"
        )
        print(f"      review: {compare_url(src['repo'], last, head)}   then: --ack {name}")
    return False, False


def list_files(root: Path) -> set[Path]:
    """Return all file paths under ``root``, relative to it (skips .git)."""
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}


def frontmatter_additions(skill_md: Path, inject: dict[str, Any]) -> list[str]:
    """Return the ``key: value`` lines from ``inject`` missing in the frontmatter.

    Empty when there is nothing to inject, the file is absent, or it has no
    parseable ``---``-fenced frontmatter. Only reports missing top-level keys;
    an existing value is never considered drift.
    """
    if not inject or not skill_md.exists():
        return []
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    try:
        close = lines.index("---", 1)
    except ValueError:
        return []
    existing = {ln.split(":", 1)[0].strip() for ln in lines[1:close] if ":" in ln}
    return [f"{key}: {yaml_scalar(val)}" for key, val in inject.items() if key not in existing]


def apply_frontmatter(skill_md: Path, inject: dict[str, Any]) -> bool:
    """Ensure each ``inject`` key is present in the SKILL.md YAML frontmatter.

    Returns True if the file was modified. Only inserts missing top-level keys;
    never overwrites an existing value.
    """
    additions = frontmatter_additions(skill_md, inject)
    if not additions:
        return False
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    close = lines.index("---", 1)
    new_lines = [*lines[:close], *additions, *lines[close:]]
    skill_md.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return True


def yaml_scalar(val: Any) -> str:
    """Render a Python value as a YAML scalar."""
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def sync_entry(entry: dict[str, Any], srcroot: Path, *, write: bool) -> list[str]:
    """Refresh one entry's local files from ``srcroot``. Returns a change list."""
    local = REPO_ROOT / entry["path"]
    local_only = set(entry.get("local_only", []))
    mode = entry["vendor_mode"]

    if mode == "files":
        wanted = {Path(f) for f in entry.get("files", [])}
    elif mode == "dir":
        wanted = list_files(srcroot)
    else:
        return [f"skip ({mode})"]

    inject = entry.get("frontmatter_inject", {})
    changes: list[str] = []
    for rel in sorted(wanted):
        if str(rel) in local_only:
            continue
        up, dst = srcroot / rel, local / rel
        if up.is_symlink():
            # A symlink in the untrusted clone can point anywhere on disk;
            # reading/writing through it would escape the temp tree. Vendored
            # files must be regular files — refuse and surface it.
            changes.append(f"REFUSED symlink from upstream: {rel}")
            continue
        if not up.exists():
            changes.append(f"MISSING upstream: {rel}")
            continue
        if inject and rel == Path("SKILL.md"):
            # The local SKILL.md legitimately carries the injected frontmatter
            # keys, so comparing it against pristine upstream reports drift on
            # EVERY run. Normalize: inject into the (temp) upstream copy first,
            # then compare like-for-like.
            apply_frontmatter(up, inject)
        if not dst.exists() or not filecmp.cmp(up, dst, shallow=False):
            changes.append(f"{'add' if not dst.exists() else 'update'}: {rel}")
            if write:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(up, dst)

    if mode == "dir":
        for rel in sorted(list_files(local)):
            if str(rel) not in local_only and rel not in wanted:
                changes.append(f"remove (gone upstream): {rel}")
                if write:
                    (local / rel).unlink()

    skill_md = local / "SKILL.md"
    if write:
        if apply_frontmatter(skill_md, inject):
            changes.append("re-applied frontmatter_inject -> SKILL.md")
    elif frontmatter_additions(skill_md, inject):
        # --check must count a missing injected key as drift too.
        changes.append("frontmatter_inject key(s) missing from SKILL.md")
    return changes


def process(entry: dict[str, Any], *, write: bool) -> tuple[bool, bool]:
    """Sync a single registry entry. Returns ``(changed, errored)``."""
    name, mode = entry["id"], entry["vendor_mode"]
    if mode == "reference":
        print(f"  ~ {name}: reference (live-fetched, nothing to sync)")
        return False, False
    if mode == "watch":
        return process_watch(entry, ack=False)

    src = entry["source"]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            commit = clone_upstream(src["repo"], src["ref"], Path(tmp) / "up")
        except subprocess.CalledProcessError as e:
            print(f"  ! {name}: clone failed — {e.stderr.strip()}", file=sys.stderr)
            return False, True
        srcroot = Path(tmp) / "up" / src["path"] if src["path"] != "." else Path(tmp) / "up"
        changes = sync_entry(entry, srcroot, write=write)

    if not changes:
        print(f"  = {name}: up to date ({commit[:8]})")
        return False, False
    verb = "would change" if not write else "synced"
    print(f"  > {name}: {verb} ({len(changes)} file(s), upstream {commit[:8]})")
    for c in changes:
        print(f"      {c}")
    if write:
        entry["last_synced"] = {"date": datetime.now(UTC).date().isoformat(), "commit": commit}
    return True, False


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Sync vendored skills from upstream.")
    parser.add_argument("--id", help="sync only this registry id")
    parser.add_argument("--check", action="store_true", help="dry-run; write nothing")
    parser.add_argument(
        "--ack", metavar="ID", help="mark a watch entry as reviewed at upstream HEAD"
    )
    args = parser.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entries = registry["vendored"]

    if args.ack:
        matches = [e for e in entries if e["id"] == args.ack]
        if not matches or matches[0]["vendor_mode"] != "watch":
            print(f"No watch entry with id {args.ack!r}", file=sys.stderr)
            return 1
        changed, errored = process_watch(matches[0], ack=True)
        if changed:
            REGISTRY.write_text(
                json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print("Updated vendored.json. Review the diff and commit.")
        return 1 if errored else 0

    if args.id:
        entries = [e for e in entries if e["id"] == args.id]
        if not entries:
            print(f"No registry entry with id {args.id!r}", file=sys.stderr)
            return 1

    write = not args.check
    print(f"{'Checking' if args.check else 'Syncing'} {len(entries)} vendored entr(ies)…")
    results = [process(e, write=write) for e in entries]
    changed = any(chg for chg, _ in results)
    errored = any(err for _, err in results)

    if write and changed:
        text = json.dumps(registry, indent=2, ensure_ascii=False) + "\n"
        REGISTRY.write_text(text, encoding="utf-8")
        print("Updated vendored.json. Review the diff and commit.")
    elif args.check and changed:
        print("Drift detected. Run without --check to sync.")
    elif not errored:
        print("Everything up to date.")
    if errored:
        print("One or more entries failed to sync.", file=sys.stderr)
        return 1
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
