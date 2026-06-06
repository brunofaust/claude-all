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

`reference` entries (live-fetched at runtime) are reported and skipped.
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


def list_files(root: Path) -> set[Path]:
    """Return all file paths under ``root``, relative to it (skips .git)."""
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}


def apply_frontmatter(skill_md: Path, inject: dict[str, Any]) -> bool:
    """Ensure each ``inject`` key is present in the SKILL.md YAML frontmatter.

    Returns True if the file was modified. Only inserts missing top-level keys;
    never overwrites an existing value.
    """
    if not inject or not skill_md.exists():
        return False
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    try:
        close = lines.index("---", 1)
    except ValueError:
        return False
    existing = {ln.split(":", 1)[0].strip() for ln in lines[1:close] if ":" in ln}
    additions = [
        f"{key}: {yaml_scalar(val)}" for key, val in inject.items() if key not in existing
    ]
    if not additions:
        return False
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

    changes: list[str] = []
    for rel in sorted(wanted):
        if str(rel) in local_only:
            continue
        up, dst = srcroot / rel, local / rel
        if not up.exists():
            changes.append(f"MISSING upstream: {rel}")
            continue
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

    if write and apply_frontmatter(local / "SKILL.md", entry.get("frontmatter_inject", {})):
        changes.append("re-applied frontmatter_inject -> SKILL.md")
    return changes


def process(entry: dict[str, Any], *, write: bool) -> bool:
    """Sync a single registry entry. Returns True if anything changed."""
    name, mode = entry["id"], entry["vendor_mode"]
    if mode == "reference":
        print(f"  ~ {name}: reference (live-fetched, nothing to sync)")
        return False

    src = entry["source"]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            commit = clone_upstream(src["repo"], src["ref"], Path(tmp) / "up")
        except subprocess.CalledProcessError as e:
            print(f"  ! {name}: clone failed — {e.stderr.strip()}", file=sys.stderr)
            return False
        srcroot = Path(tmp) / "up" / src["path"] if src["path"] != "." else Path(tmp) / "up"
        changes = sync_entry(entry, srcroot, write=write)

    if not changes:
        print(f"  = {name}: up to date ({commit[:8]})")
        return False
    verb = "would change" if not write else "synced"
    print(f"  > {name}: {verb} ({len(changes)} file(s), upstream {commit[:8]})")
    for c in changes:
        print(f"      {c}")
    if write:
        entry["last_synced"] = {"date": datetime.now(UTC).date().isoformat(), "commit": commit}
    return True


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Sync vendored skills from upstream.")
    parser.add_argument("--id", help="sync only this registry id")
    parser.add_argument("--check", action="store_true", help="dry-run; write nothing")
    args = parser.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entries = registry["vendored"]
    if args.id:
        entries = [e for e in entries if e["id"] == args.id]
        if not entries:
            print(f"No registry entry with id {args.id!r}", file=sys.stderr)
            return 1

    write = not args.check
    print(f"{'Checking' if args.check else 'Syncing'} {len(entries)} vendored entr(ies)…")
    results = [process(e, write=write) for e in entries]
    changed = any(results)

    if write and changed:
        text = json.dumps(registry, indent=2, ensure_ascii=False) + "\n"
        REGISTRY.write_text(text, encoding="utf-8")
        print("Updated vendored.json. Review the diff and commit.")
    elif args.check and changed:
        print("Drift detected. Run without --check to sync.")
    else:
        print("Everything up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
