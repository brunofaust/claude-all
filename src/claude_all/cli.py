#!/usr/bin/env python3
"""claude-all installer — interactive TUI for selecting and installing
agents/skills/plugins/mcps to ~/.claude/ (user) or ./.claude/ (project).

Usage:
    claude-all                          # interactive menu (all items)
    claude-all skills aws               # filter to skills/aws
    claude-all --list [filter...]       # list, no install
    claude-all --help

Keys in TUI:
    ↑/↓ or j/k   move
    SPACE        toggle item
    a            select all
    n            select none
    /            filter (incremental search)
    u            update all installed items
    ENTER        proceed (install selected)
    q / ESC      quit
"""

from __future__ import annotations

import argparse
import contextlib
import curses
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["main", "run"]


REPO_ROOT = Path(__file__).resolve().parent
USER_CLAUDE_DIR = Path.home() / ".claude"
STATE_DIR = Path.home() / ".claude-all"
STATE_FILE = STATE_DIR / "state.json"


# ---------------------- state file ----------------------


def state_key(kind: str, name: str) -> str:
    return f"{kind}/{name}"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"version": 1, "installs": {}}
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {"version": 1, "installs": {}}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def record_install(kind: str, name: str, target_path: Path | None) -> None:
    state = load_state()
    state.setdefault("installs", {})
    key = state_key(kind, name)
    prior = state.get("installs", {}).get(key, {})
    state["installs"][key] = {
        "kind": kind,
        "name": name,
        "target": str(target_path) if target_path else None,
        "installed_at": datetime.now(UTC).isoformat(),
        # A re-install replays every artifact-recording call, so start clean each
        # time rather than accumulating duplicates from the previous install.
        "artifacts": [],
    }
    # Preserve nothing from `prior` — record_install runs FIRST in every install
    # path, then the artifact-creating steps (claude_md / hook) append via
    # record_artifact. This reset is what keeps the footprint current, not stale.
    _ = prior
    save_state(state)


def record_artifact(kind: str, name: str, artifact: dict) -> None:
    """Append one concrete side-effect to a resource's recorded footprint.

    The footprint lets ``--prune`` reverse EXACTLY what an install did — a
    ``CLAUDE.md`` block, a ``settings.json`` hook entry, a hook symlink — even
    after the resource's source has been deleted from the repo, without
    re-deriving it from a naming convention that may have drifted.

    Args:
        kind: Resource kind.
        name: Resource name.
        artifact: A ``{"type": ...}`` record. Types: ``"symlink"`` (``path``),
            ``"claude_md"`` (``file`` / ``start`` / ``end``), ``"settings_hook"``
            (``file`` / ``command``).
    """
    state = load_state()
    entry = state.setdefault("installs", {}).get(state_key(kind, name))
    if entry is None:  # record_install always runs first; defensive only
        return
    entry.setdefault("artifacts", []).append(artifact)
    save_state(state)


# ---------------------- stale-install pruning ----------------------
#
# The installer records every install in state.json. When a resource is later
# DELETED from the repo (e.g. skills merged/retired), its install lingers in
# ~/.claude — a dangling symlink, a CLAUDE.md block, a settings hook entry. This
# detects those and can remove them.
#
# Detecting "stale" is "recorded but no longer shipped" — but a naive diff of
# state vs discover() is UNSAFE and would delete live resources. Three guards,
# each closing a real false-positive found against a real state.json:
#   1. Skip companion sub-records (`<name>.claude_md`) — they belong to a PRIMARY
#      resource and are pruned only WITH it; alone they'd strip an installed
#      resource's CLAUDE.md block.
#   2. Never flag a kind for which discover() currently returns ZERO items — a
#      missing/empty enumerator (e.g. no `plugins/` dir in the package) would
#      otherwise mark every recorded plugin stale.
#   3. The candidate list is only ever ADVISORY on a normal run; removal happens
#      only under an explicit `--prune`. The human sees the list first.

COMPANION_SUFFIX = ".claude_md"

# Kinds excluded from pruning: their install is more than a symlink+block+hook
# (a brew binary, a plugin-marketplace entry), so removing only our recorded
# artifacts would leave the real thing half-installed. Prune never touches them.
PRUNE_EXCLUDED_KINDS = frozenset({"tools", "plugins"})


def is_companion_key(name: str) -> bool:
    """True when a state name is a companion sub-record, not a primary resource."""
    return name.endswith(COMPANION_SUFFIX)


def infer_scope(target: str | None) -> str:
    """Infer the install scope from a recorded target path.

    Args:
        target: The recorded target path, or ``None``.

    Returns:
        ``"user"`` when the target is under ``~/.claude`` (or unknown — the
        common, safe default), else ``"project"``.
    """
    if target and str(Path.cwd()) in target and str(Path.home()) not in target:
        return "project"
    return "user"


def scan_stale() -> list[dict]:
    """Every genuinely-stale PRIMARY install — recorded but no longer shipped.

    Applies guard 1 (companion sub-records are skipped — they ride their primary)
    and guard 2 (a kind with zero currently-discovered items is skipped, so a
    missing enumerator can't mark everything of that kind stale — this also means
    a ``plugins`` record is never flagged while the package ships no ``plugins/``
    dir). Callers partition the result by kind.
    """
    discovered = discover([])
    shippable = {state_key(it.kind, it.name) for it in discovered}
    kinds_present = {it.kind for it in discovered}
    stale: list[dict] = []
    for key, entry in load_state().get("installs", {}).items():
        if is_companion_key(entry.get("name", "")):  # guard 1
            continue
        if entry.get("kind") not in kinds_present:  # guard 2
            continue
        if key not in shippable:
            stale.append(entry)
    return stale


def stale_installs() -> list[dict]:
    """Stale installs of PRUNABLE kinds — ``--prune`` fully reverses their footprint."""
    return [e for e in scan_stale() if e.get("kind") not in PRUNE_EXCLUDED_KINDS]


def stale_records() -> list[dict]:
    """Stale RECORDS of tools/plugins — the resource is gone from the repo, but its
    real install (a brew/pipx binary, a marketplace entry) must NOT be uninstalled.
    ``--prune`` forgets the record (and any ``~/.claude`` artifact) and leaves the
    binary in place.
    """
    return [e for e in scan_stale() if e.get("kind") in PRUNE_EXCLUDED_KINDS]


def prune_installs(entries: list[dict]) -> list[str]:
    """Remove each stale install (symlink + CLAUDE.md block + hook entry) and its companions.

    Symlink-guarded: only unlinks a recorded target when it is actually a symlink,
    so a recorded real file (e.g. a CLAUDE.md path) is never deleted. Uses the
    idempotent ``remove_claude_md`` / ``remove_hook`` for the tagged block and the
    settings hook entry. Drops the primary and its companion records from state.

    Args:
        entries: Primary state entries to prune (from :func:`stale_installs`).

    Returns:
        One human-readable line per pruned resource.
    """
    state = load_state()
    installs = state.get("installs", {})
    removed: list[str] = []
    for entry in entries:
        kind, name = entry["kind"], entry["name"]
        actions = reverse_footprint(entry)
        if not (entry.get("artifacts") or []):
            # Legacy entry (recorded before footprints): reconstruct from kind/name.
            item = Item(kind=kind, subcategory="", name=name, src=Path("."))
            scope = infer_scope(entry.get("target"))
            if remove_claude_md(item, scope):
                actions.append("CLAUDE.md block")
            if remove_hook(item, scope):
                actions.append("hook")
        installs.pop(state_key(kind, name), None)
        installs.pop(state_key(kind, name + COMPANION_SUFFIX), None)
        removed.append(f"{kind}/{name} ({', '.join(actions) or 'state only'})")

    save_state(state)
    return removed


def in_install_scope(path: str | Path) -> bool:
    """True when *path* lies inside an install root this invocation owns.

    ``state.json`` records ABSOLUTE target paths. If the state file and ``$HOME``
    ever disagree — a copied state file, a container, a test harness that overrides
    ``HOME`` — an unguarded prune would follow those paths and delete artifacts
    belonging to a DIFFERENT installation. (Observed: a sandboxed prune run against
    a copied ``state.json`` unlinked symlinks in the real home.) Prune only ever
    touches what the current scope owns: ``~/.claude`` or ``./.claude``.

    Args:
        path: The recorded artifact path to check.

    Returns:
        True when the path is under the user or project install root.
    """
    candidate = Path(path).expanduser()
    roots = (USER_CLAUDE_DIR, Path.cwd() / ".claude", claude_md_target("user"))
    return any(candidate == root or root in candidate.parents for root in roots)


def reverse_footprint(entry: dict) -> list[str]:
    """Undo a record's ``~/.claude`` artifacts (symlink-guarded); return action labels.

    The shared core of :func:`prune_installs` and :func:`forget_records`: unlink the
    recorded resource symlink (only when it IS a symlink — a recorded real file is
    never deleted, and only when it is inside this invocation's install scope) and
    reverse each recorded artifact. Touches the filesystem only; does not mutate
    state or uninstall any binary.

    Args:
        entry: A primary state record.

    Returns:
        Non-empty action labels for the reversed artifacts.
    """
    actions: list[str] = []
    target = entry.get("target")
    if target and in_install_scope(target) and Path(target).is_symlink():
        Path(target).unlink()
        actions.append("symlink")
    actions.extend(a for a in (undo_artifact(x) for x in entry.get("artifacts") or []) if a)
    return actions


def undo_artifact(artifact: dict) -> str:
    """Reverse one recorded install artifact. Returns a short label (or "").

    Every branch is scope-guarded via :func:`in_install_scope` — a recorded path
    outside this invocation's install roots belongs to a different installation and
    is left strictly alone.

    Args:
        artifact: A footprint record from :func:`record_artifact`.
    """
    kind = artifact.get("type")
    if kind == "symlink":
        path = Path(artifact["path"])
        # Only unlink a symlink (never a real file), and only inside our own scope.
        if in_install_scope(path) and path.is_symlink():
            path.unlink()
            return "hook symlink"
        return ""
    if kind == "claude_md":
        target = Path(artifact["file"])
        if not in_install_scope(target):
            return ""
        return strip_claude_md_block(target, artifact["start"], artifact["end"])
    if kind == "settings_hook":
        settings_file = Path(artifact["file"])
        if not in_install_scope(settings_file):
            return ""
        return drop_settings_command(settings_file, artifact["command"])
    return ""


def strip_claude_md_block(target: Path, start_tag: str, end_tag: str) -> str:
    """Remove the tagged block between *start_tag* and *end_tag* from *target*.

    Args:
        target: The ``CLAUDE.md`` file.
        start_tag: The block's opening marker.
        end_tag: The block's closing marker.

    Returns:
        ``"CLAUDE.md block"`` when a block was removed, else ``""``.
    """
    if not target.exists():
        return ""
    text = target.read_text()
    if start_tag not in text or end_tag not in text:
        return ""
    before = text.split(start_tag, 1)[0].rstrip()
    after = text.split(end_tag, 1)[1].lstrip("\n")
    target.write_text((before + "\n" + after).rstrip() + "\n")
    return "CLAUDE.md block"


def drop_settings_command(settings_file: Path, command: str) -> str:
    """Remove every hook entry whose ``command`` equals *command* from *settings_file*.

    Args:
        settings_file: The ``settings.json`` to edit.
        command: The exact command string the install wired.

    Returns:
        ``"settings hook"`` when an entry was removed, else ``""``.
    """
    if not settings_file.exists():
        return ""
    try:
        settings = json.loads(settings_file.read_text())
    except json.JSONDecodeError:
        return ""
    removed = False
    for event, blocks in list(settings.get("hooks", {}).items()):
        for block in blocks:
            before = len(block.get("hooks", []))
            block["hooks"] = [h for h in block.get("hooks", []) if h.get("command") != command]
            if len(block.get("hooks", [])) != before:
                removed = True
        settings["hooks"][event] = [b for b in blocks if b.get("hooks")]
        if not settings["hooks"][event]:
            del settings["hooks"][event]
    if not settings.get("hooks"):
        settings.pop("hooks", None)
    if removed:
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        return "settings hook"
    return ""


def forget_records(entries: list[dict]) -> list[str]:
    """Forget stale tool/plugin RECORDS without uninstalling the real binary.

    Removes any ``~/.claude`` artifact the record created (symlink-guarded) and
    drops the state record, but NEVER runs ``brew``/``pipx`` uninstall — the
    resource is no longer shipped by claude-all, so state stops claiming to manage
    it, while its binary is left exactly as the user installed it.

    Args:
        entries: Stale tool/plugin records (from :func:`stale_records`).

    Returns:
        One human-readable line per forgotten record.
    """
    state = load_state()
    installs = state.get("installs", {})
    forgotten: list[str] = []
    for entry in entries:
        kind, name = entry["kind"], entry["name"]
        reverse_footprint(entry)  # remove any ~/.claude artifact; never the binary
        installs.pop(state_key(kind, name), None)
        installs.pop(state_key(kind, name + COMPANION_SUFFIX), None)
        forgotten.append(f"{kind}/{name} (record forgotten; binary left in place)")
    save_state(state)
    return forgotten


# ---------------------- full uninstall ----------------------
#
# `--prune` reverses installs the repo NO LONGER SHIPS. `--uninstall` reverses
# them ALL — same footprint model, same scope guards, same reversal helpers, just
# a different selection. Nothing here re-implements removal: it hands the chosen
# records to `prune_installs` / `forget_records` exactly as prune does, so a
# guard fixed in one path is fixed in both.
#
# Two things it deliberately does NOT do:
#   1. Uninstall the `claude-all` binary. A process cannot reliably delete the
#      package it is executing from; the command prints the one-liner instead.
#   2. Touch hand-written CLAUDE.md content. Only tagged blocks this tool
#      injected are stripped — everything outside the markers survives.


def all_install_records(filters: list[str] | None = None) -> list[dict]:
    """Every PRIMARY install record, optionally narrowed by filter tokens.

    Mirrors :func:`scan_stale`'s guard 1 — companion sub-records ride their
    primary and must never be selected alone, or the uninstall would strip an
    installed resource's CLAUDE.md block while leaving the resource in place.

    Args:
        filters: Tokens that must each appear in ``"<kind>/<name>"``. Empty or
            ``None`` selects every recorded install.

    Returns:
        The matching primary records, in state order.
    """
    records: list[dict] = []
    for entry in load_state().get("installs", {}).values():
        name = entry.get("name", "")
        if is_companion_key(name):
            continue
        if filters and not all(
            token in state_key(entry.get("kind", ""), name) for token in filters
        ):
            continue
        records.append(entry)
    return records


def confirm(prompt: str) -> bool:
    """Ask for an explicit yes on stdin.

    Returns ``False`` when stdin is not a TTY (a piped/CI invocation gets the
    safe answer, never an accidental wipe) and on EOF/interrupt. Callers offer
    ``--yes`` for non-interactive use.

    Args:
        prompt: The question to show, without the ``[y/N]`` suffix.

    Returns:
        True only on an explicit ``y``/``yes``.
    """
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def remove_state_file() -> bool:
    """Delete the state file once nothing is recorded any more.

    Only ever removes the file when :func:`load_state` reports zero installs, so
    a filtered uninstall that left records behind keeps its state.

    Returns:
        True when the state file was removed.
    """
    if load_state().get("installs"):
        return False
    removed = STATE_FILE.exists()
    STATE_FILE.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        STATE_DIR.rmdir()  # only succeeds when empty — never force-removes
    return removed


# ---------------------- leftover-artifact detection ----------------------
#
# Part of the same secret as install/prune: the artifact model — what an install
# owns (a symlink, a settings.json hook entry, a tagged CLAUDE.md block, a state
# record). Install creates them; prune removes them.
#
# `stale_installs` finds artifacts whose RESOURCE stopped shipping. The checks
# here find artifacts that are broken on their own terms — a dangling symlink, a
# settings entry pointing at a deleted script, a CLAUDE.md block with no owner —
# typically left by an OLDER claude-all that created things this version doesn't.
# `stale_installs` structurally cannot see those: a healthy, still-shipped
# resource is never "stale". Both feed one `--prune`.
#
# Each removable finding carries an `artifact` dict in exactly the shape
# `undo_artifact` already accepts, so removal reuses that scope-guarded path
# rather than adding a second way to delete things.

#: Directories holding installed resource symlinks.
LINK_DIRS = ("skills", "agents", "hooks")


def install_root_of(path: Path) -> str:
    """Return the claude-all install root a symlink target belongs to.

    Args:
        path: A symlink target path.

    Returns:
        The path up to the ``claude_all`` package dir, or "" when the target does
        not look like a claude-all resource.
    """
    text = str(path)
    marker = "/claude_all/"
    return text.split(marker)[0] if marker in text else ""


def check_links(scope: str) -> list[dict]:
    """Report symlinks that dangle, or a MIXED install spanning several roots.

    "Outdated" is not "differs from the CLI I'm running" — running a dev build to
    inspect a tool install is normal, and comparing against it produces a finding
    for every link. The real defect is links that disagree with EACH OTHER: a
    partial install where some resources point at one claude-all and the rest at
    another, so upgrading one leaves the others stale.

    Args:
        scope: Install scope — ``'user'`` or ``'project'``.

    Returns:
        One finding per dangling link, plus one summary finding per minority root
        when the install is mixed.
    """
    base = USER_CLAUDE_DIR if scope == "user" else Path.cwd() / ".claude"
    findings: list[dict] = []
    roots: dict[str, list[str]] = {}
    for sub in LINK_DIRS:
        directory = base / sub
        if not directory.is_dir():
            continue
        for link in sorted(directory.iterdir()):
            if not link.is_symlink():
                continue
            if not link.exists():
                findings.append(
                    {
                        "label": f"dangling link  {sub}/{link.name} -> {os.readlink(link)}",
                        "artifact": {"type": "symlink", "path": str(link)},
                    }
                )
                continue
            root = install_root_of(Path(os.readlink(link)))
            if root:
                roots.setdefault(root, []).append(f"{sub}/{link.name}")
    if len(roots) > 1:
        main_root = max(roots, key=lambda r: len(roots[r]))
        for root, names in roots.items():
            if root == main_root:
                continue
            sample = ", ".join(names[:3]) + (" …" if len(names) > 3 else "")
            findings.append(
                {
                    "label": (
                        f"mixed install  {len(names)} link(s) point at {root} while "
                        f"{len(roots[main_root])} point elsewhere ({sample}) "
                        "— re-run the installer for this scope"
                    ),
                    "artifact": None,  # advisory: a reinstall fixes it, deleting does not
                }
            )
    return findings


def check_settings_hooks(scope: str) -> list[dict]:
    """Report settings.json hook entries that are broken or double-wired.

    Args:
        scope: Install scope — ``'user'`` or ``'project'``.

    Returns:
        One finding string per problem entry.
    """
    settings_file = settings_path(scope)
    if not settings_file.exists():
        return []
    try:
        # guard:allow — claude-all is a stdlib-only installer (dependencies = []),
        # so orjson is not available here; stdlib json is mandatory, not a choice.
        settings = json.loads(settings_file.read_text())
    except json.JSONDecodeError:
        return [
            {
                "label": f"unreadable     {settings_file} is not valid JSON — hand-edit it",
                "artifact": None,  # advisory: never rewrite a file we could not parse
            }
        ]
    findings: list[dict] = []
    seen: dict[str, int] = {}
    for event, blocks in settings.get("hooks", {}).items():
        for block in blocks:
            for hook in block.get("hooks", []):
                command = hook.get("command", "")
                basename = command_hook_basename(command)
                if not basename:
                    continue  # not a script command (e.g. an inline shell one-liner)
                seen[basename] = seen.get(basename, 0) + 1
                script = next(
                    (p for p in command.replace('"', " ").split() if p.endswith(".py")), ""
                )
                if script and not Path(script).exists():
                    findings.append(
                        {
                            "label": f"orphan hook    {event}: {basename} — script not found",
                            "artifact": {
                                "type": "settings_hook",
                                "file": str(settings_file),
                                "command": command,
                            },
                        }
                    )
    findings += [
        {
            "label": f"double-wired   {name} in {count} hook entries (may fire twice) "
            "— re-run the installer, it sweeps prior entries",
            "artifact": None,  # advisory: which entry to keep is the installer's call
        }
        for name, count in sorted(seen.items())
        if count > 1
    ]
    return findings


def check_claude_md(scope: str) -> list[dict]:
    """Report CLAUDE.md blocks that are malformed or have no install record.

    Args:
        scope: Install scope — ``'user'`` or ``'project'``.

    Returns:
        One finding string per problem block.
    """
    target = claude_md_target(scope)
    if not target.exists():
        return []
    text = target.read_text()
    starts = re.findall(r"<!-- claude-all:([^:]+):start -->", text)
    ends = set(re.findall(r"<!-- claude-all:([^:]+):end -->", text))
    installs = load_state().get("installs", {})
    findings: list[dict] = [
        {
            "label": f"unclosed block {k} has a start tag but no end — hand-edit CLAUDE.md",
            "artifact": None,  # advisory: no end tag means no safe slice to remove
        }
        for k in starts
        if k not in ends
    ]
    findings += [
        {
            "label": f"orphan block   {k} — block present but no install record",
            "artifact": {
                "type": "claude_md",
                "file": str(target),
                "start": f"<!-- claude-all:{k}:start -->",
                "end": f"<!-- claude-all:{k}:end -->",
            },
        }
        for k in sorted(set(starts))
        if k not in installs and k in ends
    ]
    findings += [
        {
            "label": f"duplicate block {k} appears {starts.count(k)} times — hand-edit CLAUDE.md",
            "artifact": None,  # advisory: which copy is authoritative is a human call
        }
        for k in sorted({k for k in starts if starts.count(k) > 1})
    ]
    return findings


def scan_leftovers(scope: str) -> tuple[list[dict], list[dict]]:
    """Find broken install artifacts, split into removable and advisory.

    Args:
        scope: Install scope — ``'user'`` or ``'project'``.

    Returns:
        ``(removable, advisory)`` — removable findings carry an ``artifact`` dict
        that ``undo_artifact`` can reverse; advisory ones are fixed by re-running
        the installer or a hand-edit, so ``--prune`` reports without touching them.
    """
    findings = check_links(scope) + check_settings_hooks(scope) + check_claude_md(scope)
    removable = [f for f in findings if f.get("artifact")]
    advisory = [f for f in findings if not f.get("artifact")]
    return removable, advisory


def remove_leftovers(findings: list[dict]) -> list[str]:
    """Reverse each removable leftover artifact.

    Args:
        findings: Removable findings from :func:`scan_leftovers`.

    Returns:
        One human-readable line per artifact actually removed.
    """
    removed: list[str] = []
    for finding in findings:
        if undo_artifact(finding["artifact"]):
            removed.append(finding["label"])
    return removed


def notify_stale(scope: str = "user") -> None:
    """Print the end-of-run notice: everything `--prune` would clean up.

    Covers both kinds of leftover — a resource the repo no longer ships, and an
    artifact that is broken on its own terms (a dangling link, a hook entry whose
    script is gone, an unowned CLAUDE.md block) — plus advisory findings that a
    reinstall or a hand-edit fixes.

    Args:
        scope: Install scope the run targeted — ``'user'`` or ``'project'``.
    """
    stale = stale_installs()
    records = stale_records()
    removable, advisory = scan_leftovers(scope)
    if not (stale or records or removable or advisory):
        return
    count = len(stale) + len(records) + len(removable)
    if count:
        print(
            f"\n⚠  {count} leftover(s) from older resources can be deleted — "
            "run `claude-all --prune`:",
            file=sys.stderr,
        )
        for entry in stale:
            print(f"     - {entry['kind']}/{entry['name']}", file=sys.stderr)
        for entry in records:
            print(
                f"     - {entry['kind']}/{entry['name']}  (stale record; binary left in place)",
                file=sys.stderr,
            )
        for finding in removable:
            print(f"     - {finding['label']}", file=sys.stderr)
    if advisory:
        print(
            f"\nℹ  {len(advisory)} install issue(s) `--prune` cannot fix:",
            file=sys.stderr,
        )
        for finding in advisory:
            print(f"     - {finding['label']}", file=sys.stderr)


# ---------------------- item model ----------------------


@dataclass
class Item:
    kind: str  # agents | skills | plugins | mcps | tools | hooks | instructions
    subcategory: str  # aws | python | ...
    name: str
    src: Path  # source path (file for agents, SKILL.md for skills, plugin.json for plugins)
    selected: bool = False
    installed: bool = False


def discover(filters: list[str]) -> list[Item]:
    items: list[Item] = []

    agent_root = REPO_ROOT / "agents"
    if agent_root.exists():
        for p in sorted(agent_root.rglob("*.md")):
            # CLAUDE.md snippets (flat `<name>.claude_md.md` or folder `claude_md.md`)
            # are companions injected alongside their agent, NOT standalone agents.
            if p.name.endswith(".claude_md.md") or p.name == "claude_md.md":
                continue
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            # Two layouts (hybrid): a flat `agents/<category>/<name>.md`, or a folder
            # `agents/<category>/<name>/agent.md` (used when the agent ships companions —
            # claude_md.md / hook.py — so they group in one directory).
            if p.name == "agent.md":
                name = p.parent.name
            elif len(parts) == 3:
                name = p.stem
            else:
                continue  # stray nested .md (e.g. a reference) — not an agent
            items.append(
                Item(
                    kind="agents",
                    subcategory=parts[1],
                    name=name,
                    src=p,
                )
            )

    skill_root = REPO_ROOT / "skills"
    if skill_root.exists():
        for p in sorted(skill_root.rglob("SKILL.md")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            if len(parts) < 3:
                continue
            items.append(
                Item(
                    kind="skills",
                    subcategory=parts[1],
                    name=parts[2],
                    src=p,
                )
            )

    plugin_root = REPO_ROOT / "plugins"
    if plugin_root.exists():
        for p in sorted(plugin_root.glob("*/plugin.json")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            items.append(
                Item(
                    kind="plugins",
                    subcategory="marketplace",
                    name=parts[1],
                    src=p,
                )
            )

    mcp_root = REPO_ROOT / "mcps"
    if mcp_root.exists():
        for p in sorted(mcp_root.glob("*/mcp.json")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            items.append(
                Item(
                    kind="mcps",
                    subcategory="stdio",
                    name=parts[1],
                    src=p,
                )
            )

    tool_root = REPO_ROOT / "tools"
    if tool_root.exists():
        for p in sorted(tool_root.glob("*/tool.json")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            try:
                meta = json.loads(p.read_text())
                subcategory = meta.get("type", "brew")
            except (json.JSONDecodeError, OSError):
                subcategory = "brew"
            items.append(
                Item(
                    kind="tools",
                    subcategory=subcategory,
                    name=parts[1],
                    src=p,
                )
            )

    # Standalone CLAUDE.md snippets ("instructions"): a resource whose ONLY effect
    # is to inject a tagged block into ~/.claude/CLAUDE.md (no agent/skill/hook to
    # install). Used for main-session dispatch rules that target built-in agents
    # (e.g. Explore). The snippet file is `claude_md.md` inside each named dir.
    instructions_root = REPO_ROOT / "instructions"
    if instructions_root.exists():
        for p in sorted(instructions_root.glob("*/claude_md.md")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            items.append(
                Item(
                    kind="instructions",
                    subcategory="instructions",
                    name=parts[1],
                    src=p,
                )
            )

    hook_root = REPO_ROOT / "hooks"
    hook_manifest = hook_root / "hooks.json"
    if hook_manifest.exists():
        try:
            manifest = json.loads(hook_manifest.read_text())
        except (json.JSONDecodeError, OSError):
            manifest = {}
        for name in sorted(k for k in manifest if not k.startswith("_")):
            py = hook_root / f"{name}.py"
            if py.exists():
                items.append(
                    Item(
                        kind="hooks",
                        subcategory="hooks",
                        name=name,
                        src=py,
                    )
                )

    if filters:

        def matches(it: Item) -> bool:
            rel = str(it.src.relative_to(REPO_ROOT))
            return all(f in rel for f in filters)

        items = [it for it in items if matches(it)]

    items.sort(key=lambda i: (i.kind, i.subcategory, i.name))
    return items


def annotate_installed(items: list[Item]) -> None:
    """Mark items as installed based on state file."""
    state = load_state()
    installs = state.get("installs", {})
    for it in items:
        it.installed = state_key(it.kind, it.name) in installs


# ---------------------- dependency resolution ----------------------
#
# A resource may ship a per-resource `claude-all.json` companion — an extensible
# manifest (today: `{"requires": ["kind/name", ...]}`, room to grow). Installing a
# resource pulls in its dependency CLOSURE (transitive, cycle-safe), so e.g.
# installing the ship-pr skill also installs the agents it delegates to. The
# manifest lives BESIDE the resource (like hook.json / claude_md.md), so deleting
# the resource deletes its deps too — no central manifest to drift, the same
# anti-orphan property the prune feature enforces from the other direction.


def resource_config_path(item: Item) -> Path:
    """Return the resource's ``claude-all.json`` companion path (folder or flat).

    Args:
        item: The resource whose companion manifest to locate.

    Returns:
        ``<dir>/claude-all.json`` for a folder resource (skill, folder-agent, …),
        or the flat sibling ``<name>.claude-all.json`` for a flat agent — mirroring
        the hook-companion naming convention.
    """
    if item.kind == "agents" and item.src.name != "agent.md":
        return item.src.parent / f"{item.name}.claude-all.json"
    return item.src.parent / "claude-all.json"


def load_requires(item: Item) -> list[str]:
    """Return the ``requires`` list from a resource's ``claude-all.json``, or ``[]``.

    Tolerant: a missing/malformed manifest, or one without a list ``requires``,
    yields no dependencies rather than raising — a resource without the companion
    simply has no declared deps.

    Args:
        item: The resource whose dependencies to read.
    """
    path = resource_config_path(item)
    if not path.exists():
        return []
    try:
        config = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    requires = config.get("requires", [])
    if not isinstance(requires, list):
        return []
    return [dep for dep in requires if isinstance(dep, str)]


def resolve_closure(
    selected: list[Item], universe: list[Item]
) -> tuple[list[Item], list[str], list[str]]:
    """Expand *selected* to its transitive dependency closure over *universe*.

    Cycle-safe (a resource already visited is not re-entered). A ``requires`` entry
    that resolves to no known resource is returned as *external* (a built-in skill
    like ``/code-review``, or a typo the drift-checker will catch) and never
    installed — resolution reports it rather than failing.

    Args:
        selected: The resources the user chose to install.
        universe: Every discovered resource (pass ``discover([])`` — the UNFILTERED
            set, so a dependency excluded by the user's filter is still resolvable).

    Returns:
        ``(closure, pulled_in, external)`` — the full install list (selected + deps,
        deduped), the dep keys pulled in that were NOT originally selected, and the
        unresolved (external/built-in) dep keys.
    """
    index = {state_key(it.kind, it.name): it for it in universe}
    selected_keys = {state_key(it.kind, it.name) for it in selected}
    closure: dict[str, Item] = {}
    pulled_in: set[str] = set()
    external: set[str] = set()
    stack = list(selected)
    while stack:
        item = stack.pop()
        key = state_key(item.kind, item.name)
        if key in closure:
            continue
        closure[key] = item
        for dep in load_requires(item):
            if dep in index:
                if dep not in selected_keys:
                    pulled_in.add(dep)
                if dep not in closure:
                    stack.append(index[dep])
            else:
                external.add(dep)
    return list(closure.values()), sorted(pulled_in), sorted(external)


# ---------------------- install ----------------------


def run_post_install_step(name: str, pip_package: str | None, step: object) -> None:
    """Execute one post_install step.

    A step is either a typed dict or a legacy bare argv list (kept for
    backward compatibility — treated as a ``bash`` step).

    Typed forms::

        {"type": "pip",  "package": "igraph", "extras": ["x"]}   # optional: "target", "pin"
        {"type": "bash", "command": ["foo", "install"], "pwd": "sub/dir"}  # "pwd" optional

    - ``pip`` injects the package into a pipx venv via ``pipx inject``. The
      target venv defaults to the plugin's own ``package`` (``pip_package``);
      override with ``target`` when injecting into a different app.
    - ``bash`` runs ``command`` (an argv list) optionally in ``pwd``.

    Args:
        name: Plugin name (for log messages).
        pip_package: The plugin's pip package — default pipx inject target.
        step: The raw step from ``post_install`` (dict or legacy list).
    """
    # Legacy form: a bare argv list → behave like a bash step.
    if isinstance(step, list):
        step = {"type": "bash", "command": step}
    if not isinstance(step, dict):
        print(f"  ! {name}: skipping invalid post_install entry: {step!r}", file=sys.stderr)
        return

    stype = step.get("type", "bash")

    if stype == "pip":
        pkg = step.get("package")
        if not pkg:
            print(f"  ! {name}: pip post_install step missing 'package'", file=sys.stderr)
            return
        extras = step.get("extras") or []
        spec = f"{pkg}[{','.join(extras)}]" if extras else pkg
        pin = step.get("pin") or ""
        if pin:
            spec = f"{spec}{pin}"
        target = step.get("target") or pip_package
        if not target:
            print(
                f"  ! {name}: pip post_install step needs a pipx 'target' "
                "(plugin is not pip-type, so there's no default venv)",
                file=sys.stderr,
            )
            return
        if shutil.which("pipx") is None:
            print(
                f"  ! {name}: pipx not on PATH — run later: pipx inject {target} {spec}",
                file=sys.stderr,
            )
            return
        cmd = ["pipx", "inject", target, spec]
        print(f"  → post_install (pip): {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        return

    if stype == "bash":
        cmd = step.get("command", [])
        if not isinstance(cmd, list) or not cmd:
            print(f"  ! {name}: bash post_install step missing 'command' list", file=sys.stderr)
            return
        if shutil.which(cmd[0]) is None:
            print(
                f"  ! {name}: post_install '{cmd[0]}' not on PATH — "
                f"open a new shell and run: {' '.join(cmd)}",
                file=sys.stderr,
            )
            return
        cwd = step.get("pwd") or None
        suffix = f"  (cwd={cwd})" if cwd else ""
        print(f"  → post_install (bash): {' '.join(cmd)}{suffix}")
        subprocess.run(cmd, check=True, cwd=cwd)
        return

    print(f"  ! {name}: unknown post_install step type {stype!r}", file=sys.stderr)


def install_plugin(item: Item) -> str:
    meta = json.loads(item.src.read_text())
    ptype = meta.get("type", "claude-marketplace")
    result_msg = ""

    if ptype == "claude-marketplace":
        marketplace = meta.get("marketplace")
        plugin_ref = meta.get("plugin")
        if not marketplace or not plugin_ref:
            return f"skipped plugin {item.name}: missing 'marketplace' or 'plugin'"
        if shutil.which("claude") is None:
            return f"skipped plugin {item.name}: 'claude' CLI not in PATH"
        subprocess.run(["claude", "plugin", "marketplace", "add", marketplace], check=True)
        subprocess.run(["claude", "plugin", "install", plugin_ref], check=True)
        result_msg = f"installed plugin {item.name} ({plugin_ref})"

    elif ptype == "pip":
        package = meta.get("package")
        if not package:
            return f"skipped plugin {item.name}: missing 'package'"
        if shutil.which("pipx") is None:
            return (
                f"skipped plugin {item.name}: 'pipx' not in PATH. "
                "Install with: brew install pipx && pipx ensurepath"
            )
        extras = meta.get("extras") or []
        pin = meta.get("pin", "")
        spec = package
        if extras:
            spec = f"{package}[{','.join(extras)}]"
        if pin:
            spec = f"{spec}{pin}"
        subprocess.run(["pipx", "install", "--force", spec], check=True)
        result_msg = f"installed plugin {item.name} via pipx ({spec})"

    else:
        return f"skipped plugin {item.name}: unknown type '{ptype}'"

    # Post-install hooks (typed steps; legacy argv lists still accepted)
    for step in meta.get("post_install") or []:
        run_post_install_step(item.name, meta.get("package"), step)

    msg = meta.get("post_install_message")
    if msg:
        print(f"  (i) {item.name}: {msg}")

    # Record state (plugins are global — no target path)
    record_install(item.kind, item.name, None)
    return result_msg


def keychain_subst(value: str) -> str:
    """Return a shell command substitution for a keychain ref, else the literal value."""
    if isinstance(value, str) and value.startswith("keychain:"):
        service = value[len("keychain:") :]
        # Quote the service name so spaces/specials are safe inside $(...)
        safe_service = service.replace('"', '\\"')
        return f'$(security find-generic-password -a "$USER" -s "{safe_service}" -w)'
    return value


def shell_quote(s: str) -> str:
    """POSIX shell single-quote a literal. Preserves any inner $(...) only when not wrapped here.

    Args:
        s: The string to quote.
    """
    return "'" + s.replace("'", "'\\''") + "'"


def install_mcp(item: Item, scope: str) -> str:
    """Install MCP via `claude mcp add`.

    Secrets stay in macOS keychain. Any `keychain:NAME` in env or args is
    converted into a runtime `sh -c '...$(security find-generic-password ...)'`
    wrapper so the secret is resolved on every MCP launch — never stored
    plaintext in .claude.json / .mcp.json.

    Args:
        item: The MCP item to install (reads mcp.json for name, command, args, env).
        scope: Installation scope — ``'user'`` or ``'project'``.
    """
    meta = json.loads(item.src.read_text())
    name = meta.get("name") or item.name
    command = meta.get("command")
    raw_args = meta.get("args") or []
    raw_env = meta.get("env") or {}
    transport = meta.get("transport", "stdio")

    if not command:
        return f"skipped mcp {item.name}: missing 'command'"
    if shutil.which("claude") is None:
        return f"skipped mcp {item.name}: 'claude' CLI not in PATH"

    has_keychain = any(
        isinstance(v, str) and v.startswith("keychain:") for v in raw_env.values()
    ) or any(isinstance(a, str) and a.startswith("keychain:") for a in raw_args)

    scope = "user" if scope == "user" else "project"
    cmd = ["claude", "mcp", "add", name, "--scope", scope]
    if transport and transport != "stdio":
        cmd += ["--transport", transport]

    if has_keychain:
        # Build single sh -c '...' command. Env vars are inline, then exec the real command.
        # Note: we intentionally DO NOT pass keychain env via -e because that
        # would store plaintext in the config. Inline `KEY=$(...) exec cmd args` keeps
        # secrets in keychain only.
        env_inline_parts = []
        for k, v in raw_env.items():
            substituted = keychain_subst(v) if isinstance(v, str) else str(v)
            # If it's a keychain subst we keep $(...) unquoted (must expand in shell).
            # If literal value, single-quote it.
            if isinstance(v, str) and v.startswith("keychain:"):
                env_inline_parts.append(f"{k}={substituted}")
            else:
                env_inline_parts.append(f"{k}={shell_quote(str(v))}")

        # Build the exec'd command + args. Single-quote literals; leave keychain
        # subst unquoted so the shell evaluates $(...).
        exec_parts = [shell_quote(command)]
        for a in raw_args:
            if isinstance(a, str) and a.startswith("keychain:"):
                # Wrap the subst in double quotes so spaces in the secret are safe as one arg.
                exec_parts.append(f'"{keychain_subst(a)}"')
            else:
                exec_parts.append(shell_quote(str(a)))

        shell_line = (
            " ".join(env_inline_parts)
            + (" " if env_inline_parts else "")
            + "exec "
            + " ".join(exec_parts)
        )

        cmd += ["--", "sh", "-c", shell_line]

    else:
        # No secrets — straightforward path. Plain env via -e, args verbatim.
        for k, v in raw_env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append("--")
        cmd.append(command)
        cmd.extend(str(a) for a in raw_args)

    # Remove first if exists — idempotent re-install
    subprocess.run(
        ["claude", "mcp", "remove", name, "--scope", scope],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    subprocess.run(cmd, check=True)
    record_install(item.kind, item.name, None)

    msg = meta.get("post_install_message")
    if msg:
        print(f"  (i) {item.name}:\n{msg}")

    return f"added mcp {name} (scope: {scope})"


def install_tool(item: Item) -> str:
    """Install a CLI tool. Dispatches on tool.json `type` (brew, uv_tool, etc.).

    Tools are GLOBAL (user-machine-wide) — `--user` vs `--project` doesn't apply.
    The optional `claude_md.md` snippet still gets injected at the scope the
    caller chose, so anti-pattern rules can be per-user or per-project.

    Args:
        item: The tool item to install (reads tool.json for type and install config).
    """
    meta = json.loads(item.src.read_text())
    ttype = meta.get("type", "brew")
    if ttype == "brew":
        if shutil.which("brew") is None:
            return (
                f"skipped tool {item.name}: 'brew' not in PATH. "
                "Install Homebrew first: https://brew.sh/"
            )
        package = meta.get("package")
        tap = meta.get("tap")
        if not package:
            return f"skipped tool {item.name}: tool.json missing 'package'"

        # Tap first if specified + not already tapped
        if tap:
            tapped = subprocess.run(
                ["brew", "tap"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            if tap not in tapped.split():
                print(f"  → brew tap {tap}")
                subprocess.run(["brew", "tap", tap], check=True)

        # Check if already installed
        installed = subprocess.run(
            ["brew", "list", "--formula", package],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if installed.returncode == 0:
            print(f"  → {package} already installed via brew (skipping install)")
        else:
            print(f"  → brew install {package}")
            subprocess.run(["brew", "install", package], check=True)

        # Post-install hooks (typed steps; legacy argv lists still accepted; e.g. `rtk init -g`)
        for step in meta.get("post_install") or []:
            run_post_install_step(item.name, meta.get("package"), step)

        record_install(item.kind, item.name, None)

        msg = meta.get("post_install_message")
        if msg:
            print(f"  (i) {item.name}:\n{msg}")

        return f"installed tool {item.name} via brew ({package})"

    if ttype == "uv_tool":
        if shutil.which("uv") is None:
            return (
                f"skipped tool {item.name}: 'uv' not in PATH. "
                "Install with: https://docs.astral.sh/uv/getting-started/installation/"
            )
        package = meta.get("package")
        git_url = meta.get("git")
        if not package or not git_url:
            return f"skipped tool {item.name}: tool.json missing 'package' or 'git'"

        extras = meta.get("extras") or []
        pkg_spec = f"{package}[{','.join(extras)}]" if extras else package
        spec = f"{pkg_spec} @ git+{git_url}"

        cmd = ["uv", "tool", "install", "--force", spec]
        print(f"  → {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

        # Post-install hooks (typed steps; legacy argv lists still accepted)
        for step in meta.get("post_install") or []:
            run_post_install_step(item.name, package, step)

        record_install(item.kind, item.name, None)

        msg = meta.get("post_install_message")
        if msg:
            print(f"  (i) {item.name}:\n{msg}")

        return f"installed tool {item.name} via uv tool install ({pkg_spec})"

    return f"skipped tool {item.name}: unknown type '{ttype}'"


# ---------------------- hook injection ----------------------


def hook_files(item: Item) -> tuple[Path, Path] | None:
    """Return (hook.json, hook.py) paths if both exist next to the resource.

    Args:
        item: The resource item whose sibling hook files to locate.
    """
    if item.kind == "agents" and item.src.name != "agent.md":
        # Flat agent: companions are prefixed siblings `<name>.hook.{py,json}`.
        base = item.src.parent
        json_path = base / f"{item.name}.hook.json"
        py_path = base / f"{item.name}.hook.py"
    else:
        # Folder agent (`<name>/agent.md`) / SKILL.md / plugin.json / mcp.json parent.
        base = item.src.parent
        json_path = base / "hook.json"
        py_path = base / "hook.py"
    if json_path.exists() and py_path.exists():
        return json_path, py_path
    return None


def settings_path(scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    return Path.cwd() / ".claude" / "settings.json"


def hook_symlink_dest(scope: str, item: Item) -> Path:
    if scope == "user":
        base = Path.home() / ".claude" / "hooks"
    else:
        base = Path.cwd() / ".claude" / "hooks"
    return base / f"{item.kind}-{item.name}.py"


def inject_hook(item: Item, scope: str) -> str | None:
    """Install hook: symlink script to .claude/hooks/, merge into settings.json.

    Idempotent — re-install sweeps ALL events for entries whose command basename
    matches this hook and replaces them, so an event/matcher change in hook.json
    never leaves a stale double-firing entry behind.

    Args:
        item: The resource item whose hook files to install.
        scope: Installation scope — ``'user'`` or ``'project'``.
    """
    files = hook_files(item)
    if files is None:
        return None
    json_path, py_path = files

    try:
        hook_meta = json.loads(json_path.read_text())
    except json.JSONDecodeError as e:
        return f"hook skipped (invalid hook.json: {e})"

    event = hook_meta.get("event", "PreToolUse")
    matcher = hook_meta.get("matcher", "Edit|Write")
    timeout = int(hook_meta.get("timeout", 2000))

    # Symlink hook script
    dest = hook_symlink_dest(scope, item)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.exists():
        dest.unlink()
    os.symlink(py_path, dest)

    # Claude Code execs the hook by bare path (the registered command is the
    # script path), so the script MUST be executable or the shell fails with
    # "Permission denied". Ensure the bit is set on the symlink target.
    mode = py_path.stat().st_mode
    py_path.chmod(mode | 0o111)

    # Merge into settings.json
    settings_file = settings_path(scope)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            settings = {}
    else:
        settings = {}

    settings.setdefault("hooks", {})
    # Drop any prior entry for this hook anywhere — the hook.json's event or
    # matcher may have changed between versions, so a same-block dedup would
    # leave a stale entry double-firing. Sweep ALL events by command basename
    # (same semantics as install_standalone_hook).
    purge_hook_entries(settings, dest.name)
    event_blocks = settings["hooks"].setdefault(event, [])

    # Find or create a block with the matching matcher
    target_block = None
    for block in event_blocks:
        if block.get("matcher") == matcher:
            target_block = block
            break
    if target_block is None:
        target_block = {"matcher": matcher, "hooks": []}
        event_blocks.append(target_block)

    target_block.setdefault("hooks", [])
    cmd_str = str(dest)
    target_block["hooks"].append(
        {
            "type": "command",
            "command": cmd_str,
            "timeout": timeout,
        }
    )

    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    record_artifact(item.kind, item.name, {"type": "symlink", "path": str(dest)})
    record_artifact(
        item.kind,
        item.name,
        {"type": "settings_hook", "file": str(settings_file), "command": cmd_str},
    )
    return f"hook installed → {dest}, registered in {settings_file}"


def remove_hook(item: Item, scope: str) -> str | None:
    """Remove hook entry from settings.json + delete symlink. Idempotent.

    Args:
        item: The resource item whose hook to remove.
        scope: Installation scope — ``'user'`` or ``'project'``.
    """
    dest = hook_symlink_dest(scope, item)
    # The settings-entry removal IS `drop_settings_command` — one owner for
    # "strip this command from settings.json", used by both remove_hook and the
    # artifact-based prune path.
    removed_any = bool(drop_settings_command(settings_path(scope), str(dest)))

    if dest.is_symlink() or dest.exists():
        dest.unlink()
        removed_any = True

    return "hook removed" if removed_any else None


# ---------------------- CLAUDE.md injection ----------------------


def claude_md_snippet_path(item: Item) -> Path | None:
    """Return path to the optional ``claude_md.md`` snippet next to the resource.

    For agents (single-file): same dir as the agent .md, named ``<agent>.claude_md.md``.
    For skills/plugins/mcps (dir-based): ``claude_md.md`` inside the dir.

    Args:
        item: The resource item whose claude_md snippet path to resolve.
    """
    if item.kind == "agents" and item.src.name != "agent.md":
        # Flat agent: companion is a prefixed sibling `<name>.claude_md.md`.
        candidate = item.src.with_name(f"{item.name}.claude_md.md")
    else:
        # Folder agent (`<name>/agent.md`) / skill / plugin / mcp: `claude_md.md` in the dir.
        candidate = item.src.parent / "claude_md.md"
    return candidate if candidate.exists() else None


def claude_md_target(scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "CLAUDE.md"
    return Path.cwd() / "CLAUDE.md"


def snippet_tags(item: Item) -> tuple[str, str]:
    key = f"{item.kind}/{item.name}"
    return (
        f"<!-- claude-all:{key}:start -->",
        f"<!-- claude-all:{key}:end -->",
    )


def inject_claude_md(item: Item, scope: str) -> str | None:
    """Inject the resource's claude_md.md snippet into the target CLAUDE.md.

    Idempotent: re-install replaces the existing tagged block.
    Returns a short status string, or None if no snippet exists.

    Args:
        item: The resource item whose claude_md snippet to inject.
        scope: Target CLAUDE.md scope — ``'user'`` or ``'project'``.
    """
    snippet_path = claude_md_snippet_path(item)
    if snippet_path is None:
        return None

    target = claude_md_target(scope)
    target.parent.mkdir(parents=True, exist_ok=True)

    start_tag, end_tag = snippet_tags(item)
    snippet_body = snippet_path.read_text().rstrip()
    block = f"\n{start_tag}\n{snippet_body}\n{end_tag}\n"

    existing = target.read_text() if target.exists() else ""

    if start_tag in existing and end_tag in existing:
        before = existing.split(start_tag, 1)[0].rstrip()
        after = existing.split(end_tag, 1)[1].lstrip("\n")
        new_text = f"{before}\n{block}\n{after}".rstrip() + "\n"
        action = "updated"
    else:
        # Append, ensuring single blank line separator
        new_text = (existing.rstrip() + "\n" + block).lstrip("\n")
        action = "appended"

    target.write_text(new_text)
    record_artifact(
        item.kind,
        item.name,
        {"type": "claude_md", "file": str(target), "start": start_tag, "end": end_tag},
    )
    return f"CLAUDE.md {action} ({target})"


def remove_claude_md(item: Item, scope: str) -> str | None:
    """Strip the resource's tagged block from the target CLAUDE.md.

    Args:
        item: The resource item whose tagged block to remove.
        scope: Target CLAUDE.md scope — ``'user'`` or ``'project'``.
    """
    target = claude_md_target(scope)
    if not target.exists():
        return None
    start_tag, end_tag = snippet_tags(item)
    text = target.read_text()
    if start_tag not in text or end_tag not in text:
        return None
    before = text.split(start_tag, 1)[0].rstrip()
    after = text.split(end_tag, 1)[1].lstrip("\n")
    target.write_text((before + "\n" + after).rstrip() + "\n")
    return f"CLAUDE.md stripped ({target})"


def command_hook_basename(cmd: str) -> str:
    """Best-effort basename of the script a hook command runs (for dedup).

    Handles `"/abs/x.py"`, `$VAR/.claude/hooks/x.py`, and `python3 /abs/x.py`.
    Returns "" for non-script commands (e.g. `rtk hook claude`, shell one-liners).

    Args:
        cmd: The hook's ``command`` string from settings.json.
    """
    stripped = (cmd or "").strip()
    if not stripped:
        return ""
    token = stripped.split()[-1].strip("\"'")
    name = Path(token).name
    return name if name.endswith(".py") else ""


def command_targets_managed_hook(cmd: str, target_basename: str) -> bool:
    """True if *cmd* runs a script named *target_basename* out of a ``.claude/hooks/`` dir.

    Only entries claude-all itself could have wired (any scope, any prior path
    style — absolute or ``$CLAUDE_PROJECT_DIR/.claude/hooks/…``) qualify. A
    user's own hook that merely shares the filename but lives elsewhere (e.g.
    ``~/dotfiles/hooks/x.py``) is NOT matched and never unwired.

    Args:
        cmd: The hook's ``command`` string from settings.json.
        target_basename: Script filename of the hook being (re)installed.
    """
    if command_hook_basename(cmd) != target_basename:
        return False
    token = Path(cmd.strip().split()[-1].strip("\"'"))
    parent = token.parent
    return parent.name == "hooks" and parent.parent.name == ".claude"


def purge_hook_entries(settings: dict, target_basename: str) -> None:
    """Drop every managed hook entry (across ALL events/matchers) for this script.

    A hook's ``hook.json`` may change event or matcher between versions — a
    same-event/same-matcher dedup would leave the stale entry behind and the
    hook would double-fire. Sweeping across the whole ``hooks`` mapping makes
    re-install cleanly replace any prior claude-all wiring. Matching requires
    BOTH the command basename AND a ``.claude/hooks/`` path (see
    ``command_targets_managed_hook``) so a foreign hook sharing the filename is
    never touched. Entries/blocks with unexpected shapes (written by other
    tools or by hand) are left untouched rather than crashing the install.
    Mutates ``settings`` in place; empty managed blocks and events are pruned.

    Args:
        settings: The ``.claude/settings.json`` contents, mutated in place.
        target_basename: The hook script's filename (e.g. ``foo.py``) to sweep.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    for ev, blocks in list(hooks.items()):
        if not isinstance(blocks, list):
            continue  # foreign shape — leave untouched
        for block in blocks:
            if not isinstance(block, dict) or not isinstance(block.get("hooks"), list):
                continue
            block["hooks"] = [
                h
                for h in block["hooks"]
                if not (
                    isinstance(h, dict)
                    and command_targets_managed_hook(h.get("command", ""), target_basename)
                )
            ]
        hooks[ev] = [b for b in blocks if not isinstance(b, dict) or b.get("hooks")]
        if not hooks[ev]:
            del hooks[ev]


def install_standalone_hook(item: Item, scope: str) -> str:
    """Install a standalone ``hooks/`` script: symlink + wire into settings.json.

    Metadata (event / matcher / timeout) comes from ``hooks/hooks.json``. The
    symlink uses NO kind-prefix (``<name>.py``) to match the hand-wired convention, and
    the settings merge dedups by command basename across ALL events — so re-install
    cleanly replaces any prior entry for the same hook (incl. a hand-wired one) instead
    of double-firing.

    Args:
        item: The hook item (``kind="hooks"``).
        scope: Installation scope — ``'user'`` or ``'project'``.
    """
    try:
        manifest = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text())
    except (json.JSONDecodeError, OSError):
        manifest = {}
    meta = manifest.get(item.name, {})
    event = meta.get("event", "PreToolUse")
    matcher = meta.get("matcher", "Edit|Write")
    timeout = int(meta.get("timeout", 2000))

    base = (USER_CLAUDE_DIR if scope == "user" else Path.cwd() / ".claude") / "hooks"
    base.mkdir(parents=True, exist_ok=True)
    dest = base / f"{item.name}.py"
    if dest.is_symlink() or dest.exists():
        dest.unlink()
    os.symlink(item.src, dest)

    # Claude Code execs the hook by bare path, so the script MUST be executable
    # or the shell fails with "Permission denied". Ensure the bit is set on the
    # symlink target (mirrors inject_hook for companion hooks).
    mode = item.src.stat().st_mode
    item.src.chmod(mode | 0o111)

    cmd_str = str(dest)
    target_basename = f"{item.name}.py"

    settings_file = settings_path(scope)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings: dict = {}
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            settings = {}
    settings.setdefault("hooks", {})

    # Drop any prior entry for this hook anywhere (basename match), then re-add fresh.
    purge_hook_entries(settings, target_basename)

    event_blocks = settings.setdefault("hooks", {}).setdefault(event, [])
    target_block = next((b for b in event_blocks if b.get("matcher") == matcher), None)
    if target_block is None:
        target_block = {"matcher": matcher, "hooks": []}
        event_blocks.append(target_block)
    target_block.setdefault("hooks", []).append(
        {"type": "command", "command": cmd_str, "timeout": timeout}
    )

    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    record_install(item.kind, item.name, None)
    record_artifact(item.kind, item.name, {"type": "symlink", "path": str(dest)})
    record_artifact(
        item.kind,
        item.name,
        {"type": "settings_hook", "file": str(settings_file), "command": cmd_str},
    )
    return f"installed hook {item.name} → {dest} ({event}/{matcher or '*'})"


def install_item(item: Item, target_root: Path) -> str:
    scope = "user" if target_root == USER_CLAUDE_DIR else "project"

    if item.kind == "hooks":
        return install_standalone_hook(item, scope)

    if item.kind == "instructions":
        # Snippet-only resource: inject the tagged block, nothing to symlink.
        md = inject_claude_md(item, scope)
        record_install(item.kind, item.name, claude_md_target(scope))
        return md or f"instructions/{item.name}: no snippet found"

    if item.kind == "plugins":
        result = install_plugin(item)
        md = inject_claude_md(item, scope)
        if md:
            print(f"  ↳ {md}")
        return result

    if item.kind == "mcps":
        result = install_mcp(item, scope)
        md = inject_claude_md(item, scope)
        if md:
            print(f"  ↳ {md}")
        return result

    if item.kind == "tools":
        result = install_tool(item)
        md = inject_claude_md(item, scope)
        if md:
            print(f"  ↳ {md}")
        return result

    if item.kind == "agents":
        target_dir = target_root / "agents"
        target_path = target_dir / f"{item.name}.md"
        src = item.src
    elif item.kind == "skills":
        target_dir = target_root / "skills"
        target_path = target_dir / item.name
        src = item.src.parent
    else:
        return f"unknown kind: {item.kind}"

    target_dir.mkdir(parents=True, exist_ok=True)

    replaced = False
    if target_path.is_symlink() or target_path.exists():
        if target_path.is_symlink() or target_path.is_file():
            target_path.unlink()
        else:
            shutil.rmtree(target_path)
        replaced = True

    os.symlink(src, target_path)
    record_install(item.kind, item.name, target_path)

    md = inject_claude_md(item, scope)
    if md:
        print(f"  ↳ {md}")
    hk = inject_hook(item, scope)
    if hk:
        print(f"  ↳ {hk}")

    return f"{'replaced' if replaced else 'linked'} {item.kind}/{item.name}"


# ---------------------- update ----------------------


def update_item(kind: str, name: str, install_record: dict, all_items: list[Item]) -> str:
    """Update a single installed item. Looks up live meta from repo.

    Args:
        kind: Item category — ``'mcps'``, ``'plugins'``, ``'agents'``, ``'skills'``, or ``'tools'``.
        name: Item name within its kind.
        install_record: The entry from the install state file for this item.
        all_items: Full list of available items from the current repo.
    """
    # Find matching item in current repo
    match = next((it for it in all_items if it.kind == kind and it.name == name), None)

    if kind == "mcps":
        if match is None:
            return f"  ✗ mcps/{name}: not found in repo (removed?)"
        # Re-install at user scope by default (mcps don't track scope in state)
        try:
            msg = install_mcp(match, "user")
            return f"  ✓ refreshed {msg}"
        except subprocess.CalledProcessError as e:
            return f"  ✗ mcps/{name}: claude mcp add failed ({e.returncode})"

    if kind == "plugins":
        if match is None:
            return f"  ✗ plugins/{name}: not found in repo (removed?)"
        meta = json.loads(match.src.read_text())
        # If plugin.json declares explicit update_command, use it.
        update_cmd = meta.get("update_command")
        if update_cmd and isinstance(update_cmd, list) and update_cmd:
            if shutil.which(update_cmd[0]) is None:
                return f"  ✗ plugins/{name}: update_command '{update_cmd[0]}' not on PATH"
            print(f"  → update: {' '.join(update_cmd)}")
            subprocess.run(update_cmd, check=True)
            return f"  ✓ updated plugins/{name}"

        ptype = meta.get("type", "claude-marketplace")
        if ptype == "pip":
            package = meta.get("package")
            if not package:
                return f"  ✗ plugins/{name}: missing 'package'"
            if shutil.which("pipx") is None:
                return f"  ✗ plugins/{name}: pipx not on PATH"
            print(f"  → pipx upgrade {package}")
            subprocess.run(["pipx", "upgrade", package], check=True)
            return f"  ✓ updated plugins/{name}"
        if ptype == "claude-marketplace":
            plugin_ref = meta.get("plugin")
            if not plugin_ref:
                return f"  ✗ plugins/{name}: missing 'plugin'"
            if shutil.which("claude") is None:
                return f"  ✗ plugins/{name}: claude CLI not on PATH"
            print(f"  → claude plugin install {plugin_ref} (refresh)")
            subprocess.run(["claude", "plugin", "install", plugin_ref], check=True)
            return f"  ✓ updated plugins/{name}"
        return f"  ✗ plugins/{name}: unknown type '{ptype}'"

    if kind == "tools":
        if match is None:
            return f"  ✗ tools/{name}: not found in repo (removed?)"
        try:
            msg = install_tool(match)
            return f"  ✓ refreshed {msg}"
        except subprocess.CalledProcessError as e:
            return f"  ✗ tools/{name}: install command failed ({e.returncode})"

    if kind == "hooks":
        if match is None:
            return f"  ✗ hooks/{name}: not found in repo (removed?)"
        # Re-install at user scope by default (hooks don't track scope in state)
        return f"  ✓ refreshed {install_standalone_hook(match, 'user')}"

    if kind == "instructions":
        if match is None:
            return f"  ✗ instructions/{name}: not found in repo (removed?)"
        # No symlink — re-inject the snippet. Infer scope from the recorded
        # CLAUDE.md target path (falls back to user).
        recorded = install_record.get("target") or ""
        scope = "project" if recorded.startswith(str(Path.cwd())) else "user"
        md = inject_claude_md(match, scope)
        return f"  ✓ refreshed instructions/{name}" + (f"\n    ↳ {md}" if md else "")

    # agents / skills — re-create symlink at recorded target
    target = install_record.get("target")
    if not target:
        return f"  ✗ {kind}/{name}: missing target path in state"
    target_path = Path(target)
    if match is None:
        return f"  ✗ {kind}/{name}: not found in repo (removed?)"

    src = match.src.parent if kind == "skills" else match.src

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.is_symlink() or target_path.exists():
        if target_path.is_symlink() or target_path.is_file():
            target_path.unlink()
        else:
            shutil.rmtree(target_path)
    os.symlink(src, target_path)
    # Refresh timestamp
    record_install(kind, name, target_path)

    # Infer scope from target path so claude_md + hook re-injection lands in the right scope
    scope = "user" if str(target_path).startswith(str(USER_CLAUDE_DIR)) else "project"

    extras = []
    md = inject_claude_md(match, scope)
    if md:
        extras.append(md)
    hk = inject_hook(match, scope)
    if hk:
        extras.append(hk)

    msg = f"  ✓ refreshed {kind}/{name} ({target_path})"
    for extra in extras:
        msg += f"\n    ↳ {extra}"
    return msg


def run_update_all() -> None:
    state = load_state()
    installs = state.get("installs", {})
    if not installs:
        print("Nothing recorded as installed. State file empty.")
        return
    all_items = discover([])  # full repo, no filter
    print(f"Updating {len(installs)} installed item(s)...\n")
    for _, rec in sorted(installs.items()):
        try:
            msg = update_item(rec["kind"], rec["name"], rec, all_items)
            print(msg)
        except subprocess.CalledProcessError as e:
            print(
                f"  ✗ {rec['kind']}/{rec['name']}: command failed ({e.returncode})",
                file=sys.stderr,
            )
        except OSError as e:
            print(f"  ✗ {rec['kind']}/{rec['name']}: {e}", file=sys.stderr)
    print("\nUpdate complete.")


# ---------------------- TUI ----------------------


@dataclass
class TuiState:
    items: list[Item]
    cursor: int = 0
    offset: int = 0
    filter_text: str = ""
    filter_mode: bool = False
    visible: list[int] = field(default_factory=list)

    def rebuild_visible(self):
        if self.filter_text:
            ft = self.filter_text.lower()
            self.visible = [
                i
                for i, it in enumerate(self.items)
                if ft in it.name.lower() or ft in it.subcategory.lower() or ft in it.kind.lower()
            ]
        else:
            self.visible = list(range(len(self.items)))
        if self.cursor >= len(self.visible):
            self.cursor = max(0, len(self.visible) - 1)


def draw(stdscr, state: TuiState):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    title = " claude-all — select items to install "
    stdscr.addstr(0, 0, title.center(w, "─")[:w], curses.A_BOLD)

    help_line = (
        " ↑/↓ │ SPACE toggle │ a all │ n none │ / filter │ u update │ ENTER install │ q quit "
    )
    stdscr.addstr(1, 0, help_line[:w], curses.A_DIM)

    if state.filter_mode:
        prompt = f" /{state.filter_text}_"
        stdscr.addstr(2, 0, prompt[:w], curses.A_REVERSE)
    elif state.filter_text:
        stdscr.addstr(2, 0, f" filter: {state.filter_text}"[:w], curses.A_DIM)

    list_top = 4
    list_bottom = h - 2
    page = max(1, list_bottom - list_top)

    state.offset = min(state.offset, state.cursor)
    if state.cursor >= state.offset + page:
        state.offset = state.cursor - page + 1

    row = list_top
    for vi in range(state.offset, min(state.offset + page, len(state.visible))):
        idx = state.visible[vi]
        it = state.items[idx]
        is_cursor = vi == state.cursor
        marker = "[x]" if it.selected else "[ ]"
        prefix = "▸ " if is_cursor else "  "
        installed_tag = "  (installed)" if it.installed else ""
        label = f"{prefix}{marker}  {it.kind}/{it.subcategory}/{it.name}{installed_tag}"
        attr = curses.A_REVERSE if is_cursor else curses.A_NORMAL
        if it.selected and not is_cursor:
            attr |= curses.A_BOLD
        # curses.addstr raises curses.error when writing to the last cell / past
        # the screen edge; ignore — the clipped row is cosmetic, not an error.
        with contextlib.suppress(curses.error):
            stdscr.addstr(row, 0, label[:w].ljust(min(w, len(label[:w]))), attr)
        row += 1
        if row >= list_bottom:
            break

    sel = sum(1 for it in state.items if it.selected)
    inst = sum(1 for it in state.items if it.installed)
    total = len(state.items)
    shown = len(state.visible)
    scroll_info = f" {state.cursor + 1}/{shown}" if shown else " 0/0"
    footer = (
        f" selected {sel}/{total}  │  installed {inst}/{total}"
        f"  │  shown {shown}/{total}  │{scroll_info}"
    )
    # Writing the footer to the bottom-right cell raises curses.error; ignore —
    # it's the standard curses idiom for the last visible cell.
    with contextlib.suppress(curses.error):
        stdscr.addstr(h - 1, 0, footer[:w].ljust(w), curses.A_REVERSE)

    stdscr.refresh()


# Action returned by TUI
TUI_INSTALL = "install"
TUI_UPDATE = "update"
TUI_QUIT = "quit"


def tui_select_loop(stdscr, items: list[Item]) -> str:
    """Curses event loop for `tui_select` (run inside `curses.wrapper`).

    Returns TUI_INSTALL, TUI_UPDATE, or TUI_QUIT.

    Args:
        stdscr: The curses standard screen, supplied by `curses.wrapper`.
        items: All available items to display in the selection UI.
    """
    curses.curs_set(0)
    stdscr.keypad(True)
    state = TuiState(items=items)
    state.rebuild_visible()

    while True:
        draw(stdscr, state)
        ch = stdscr.getch()

        if state.filter_mode:
            if ch in (10, 13, curses.KEY_ENTER):
                state.filter_mode = False
            elif ch == 27:
                state.filter_mode = False
                state.filter_text = ""
                state.rebuild_visible()
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                state.filter_text = state.filter_text[:-1]
                state.rebuild_visible()
            elif 32 <= ch < 127:
                state.filter_text += chr(ch)
                state.rebuild_visible()
            continue

        if ch in (curses.KEY_UP, ord("k")):
            if state.cursor > 0:
                state.cursor -= 1
        elif ch in (curses.KEY_DOWN, ord("j")):
            if state.cursor < len(state.visible) - 1:
                state.cursor += 1
        elif ch == curses.KEY_PPAGE:
            state.cursor = max(0, state.cursor - 10)
        elif ch == curses.KEY_NPAGE:
            state.cursor = min(len(state.visible) - 1, state.cursor + 10)
        elif ch == curses.KEY_HOME:
            state.cursor = 0
        elif ch == curses.KEY_END:
            state.cursor = max(0, len(state.visible) - 1)
        elif ch == ord(" "):
            if state.visible:
                idx = state.visible[state.cursor]
                items[idx].selected = not items[idx].selected
        elif ch == ord("a"):
            for vi in state.visible:
                items[vi].selected = True
        elif ch == ord("n"):
            for vi in state.visible:
                items[vi].selected = False
        elif ch == ord("/"):
            state.filter_mode = True
        elif ch == ord("u"):
            return TUI_UPDATE
        elif ch in (10, 13, curses.KEY_ENTER):
            return TUI_INSTALL
        elif ch in (ord("q"), 27):
            return TUI_QUIT


def tui_select(items: list[Item]) -> str:
    """Return TUI_INSTALL, TUI_UPDATE, or TUI_QUIT.

    Args:
        items: All available items to display in the selection UI.
    """
    return curses.wrapper(tui_select_loop, items)


def choose_scope_tui() -> str | None:
    def _run(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        choices = [
            ("user", f"User scope    →  {USER_CLAUDE_DIR}"),
            ("project", f"Project scope →  {Path.cwd() / '.claude'}"),
        ]
        cursor = 0
        while True:
            stdscr.erase()
            _, w = stdscr.getmaxyx()
            stdscr.addstr(0, 0, " Where to install? ".center(w, "─")[:w], curses.A_BOLD)
            stdscr.addstr(1, 0, " ↑/↓ move │ ENTER confirm │ q cancel ", curses.A_DIM)
            for i, (_, label) in enumerate(choices):
                attr = curses.A_REVERSE if i == cursor else curses.A_NORMAL
                prefix = "▸ " if i == cursor else "  "
                stdscr.addstr(3 + i, 0, f"{prefix}{label}"[:w], attr)
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (curses.KEY_UP, ord("k")) and cursor > 0:
                cursor -= 1
            elif ch in (curses.KEY_DOWN, ord("j")) and cursor < len(choices) - 1:
                cursor += 1
            elif ch in (10, 13, curses.KEY_ENTER):
                return choices[cursor][0]
            elif ch in (ord("q"), 27):
                return None

    return curses.wrapper(_run)


# ---------------------- main ----------------------


def cmd_uninstall(*, filters: list[str], scope: str, assume_yes: bool) -> int:
    """Reverse every recorded install: symlinks, CLAUDE.md blocks, hook entries.

    Shows the full plan BEFORE touching anything — this removes a user's whole
    setup, so it must never be a surprise. Reversal itself is delegated to the
    same :func:`prune_installs` / :func:`forget_records` used by ``--prune``, so
    both paths share one set of scope and symlink guards.

    Args:
        filters: Tokens narrowing which records to remove (empty = everything).
        scope: ``"user"`` or ``"project"`` — which install root to clean.
        assume_yes: Skip the confirmation prompt.

    Returns:
        0 on success or a no-op, 1 when the user declined.
    """
    records = all_install_records(filters)
    if not records:
        target = f" matching {' '.join(filters)}" if filters else ""
        print(f"Nothing to uninstall — no claude-all installs recorded{target}.")
        return 0

    prunable = [e for e in records if e.get("kind") not in PRUNE_EXCLUDED_KINDS]
    external = [e for e in records if e.get("kind") in PRUNE_EXCLUDED_KINDS]

    print(f"claude-all --uninstall — {len(records)} recorded install(s), {scope} scope:\n")
    for entry in prunable:
        print(f"  - {entry.get('kind')}/{entry.get('name')}")
    for entry in external:
        print(f"  - {entry.get('kind')}/{entry.get('name')}  [record only — binary left in place]")
    print(
        "\nRemoves the resource symlinks, the CLAUDE.md blocks this tool injected, "
        "and its settings.json hook entries.\nHand-written CLAUDE.md content outside "
        "those markers is NOT touched."
    )
    if external:
        print(
            f"{len(external)} tool/plugin record(s) are forgotten only — their real "
            "install (brew/pipx/marketplace) stays; remove those yourself."
        )

    if not assume_yes and not confirm("\nProceed?"):
        print("Aborted — nothing was removed. (Use --yes for non-interactive runs.)")
        return 1

    removed = prune_installs(prunable)
    forgotten = forget_records(external)
    leftovers, advisory = scan_leftovers(scope)
    cleaned = remove_leftovers(leftovers)

    for line in removed:
        print(f"  ✓ {line}")
    for line in forgotten:
        print(f"  ✓ {line}")
    for line in cleaned:
        print(f"  ✓ leftover: {line}")
    if remove_state_file():
        print("  ✓ removed state file (nothing recorded any more)")
    if advisory:
        print(f"\nℹ  {len(advisory)} issue(s) --uninstall cannot fix:")
        for finding in advisory:
            print(f"  - {finding['label']}")

    print(
        f"\nRemoved {len(removed) + len(forgotten)} install(s). The claude-all CLI itself "
        "is still installed — remove it with:\n  uv tool uninstall claude-all"
    )
    return 0


def cmd_list(items: list[Item]):
    last_kind = None
    last_subcat = None
    for it in items:
        if it.kind != last_kind:
            print(f"\n━━ {it.kind.upper()} ━━")
            last_kind = it.kind
            last_subcat = None
        if it.subcategory != last_subcat:
            print(f"  [{it.subcategory}]")
            last_subcat = it.subcategory
        tag = "  (installed)" if it.installed else ""
        print(f"    {it.kind}/{it.name}{tag}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="claude-all installer (interactive TUI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--list", action="store_true", help="List items without installing")
    ap.add_argument("--all", action="store_true", help="Select everything (skip TUI)")
    ap.add_argument("--user", action="store_true", help="Install to ~/.claude (skip scope prompt)")
    ap.add_argument(
        "--project",
        action="store_true",
        help="Install to ./.claude (skip scope prompt)",
    )
    ap.add_argument(
        "--prune",
        action="store_true",
        help="Remove installs that are no longer shipped by the repo (no confirmation)",
    )
    ap.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove EVERY recorded install (symlinks, CLAUDE.md blocks, hook entries). "
        "Shows a plan and asks before removing anything; narrow it with filters",
    )
    ap.add_argument(
        "--yes",
        action="store_true",
        help="Skip the --uninstall confirmation prompt (for non-interactive use)",
    )
    ap.add_argument("filters", nargs="*", help="Filter tokens (each must appear in path)")
    args = ap.parse_args(argv)

    if args.uninstall:
        return cmd_uninstall(
            filters=args.filters,
            scope="project" if args.project else "user",
            assume_yes=args.yes,
        )

    if args.prune:
        prune_scope = "project" if args.project else "user"
        removed = prune_installs(stale_installs())
        forgotten = forget_records(stale_records())
        leftovers, advisory = scan_leftovers(prune_scope)
        cleaned = remove_leftovers(leftovers)
        if removed:
            print(f"Pruned {len(removed)} stale install(s):")
            for line in removed:
                print(f"  ✓ {line}")
        if forgotten:
            print(f"Forgot {len(forgotten)} stale record(s) (binary left in place):")
            for line in forgotten:
                print(f"  ✓ {line}")
        if cleaned:
            print(f"Removed {len(cleaned)} leftover artifact(s) from an older claude-all:")
            for line in cleaned:
                print(f"  ✓ {line}")
        if not (removed or forgotten or cleaned):
            print("Nothing to prune — no stale installs or leftover artifacts.")
        if advisory:
            print(f"\nℹ  {len(advisory)} issue(s) --prune cannot fix:")
            for finding in advisory:
                print(f"  - {finding['label']}")
        return 0

    items = discover(args.filters)
    if not items:
        filt = " ".join(args.filters) if args.filters else "(none)"
        print(f"No items match filters: {filt}", file=sys.stderr)
        return 1

    annotate_installed(items)

    if args.list:
        cmd_list(items)
        notify_stale("project" if args.project else "user")
        return 0

    # Selection
    if args.all:
        for it in items:
            it.selected = True
        action = TUI_INSTALL
    else:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print(
                "TUI needs a real terminal. Use --all or --list instead.",
                file=sys.stderr,
            )
            return 1
        action = tui_select(items)

    if action == TUI_QUIT:
        print("Cancelled.")
        return 0

    if action == TUI_UPDATE:
        run_update_all()
        return 0

    # action == TUI_INSTALL
    chosen = [it for it in items if it.selected]
    if not chosen:
        print("Nothing selected.")
        return 0

    # Pull in each chosen resource's dependency closure. Resolve over the UNFILTERED
    # universe so a dependency excluded by the user's filter is still installed.
    chosen, pulled_in, external = resolve_closure(chosen, discover([]))
    if pulled_in:
        print(f"+ pulled in {len(pulled_in)} dependency(ies): {', '.join(pulled_in)}")
    if external:
        print(
            f"  (note: {len(external)} required dep(s) are external/built-in, not installed here: "
            f"{', '.join(external)})",
            file=sys.stderr,
        )

    scope: str | None
    if args.user:
        scope = "user"
    elif args.project:
        scope = "project"
    else:
        scope = choose_scope_tui()
        if scope is None:
            print("Cancelled.")
            return 0

    target_root = USER_CLAUDE_DIR if scope == "user" else (Path.cwd() / ".claude")

    print(f"\nInstalling {len(chosen)} item(s) → {target_root}\n")
    failures = 0
    for it in chosen:
        try:
            msg = install_item(it, target_root)
            print(f"  ✓ {msg}")
        except OSError as e:
            print(f"  ✗ {it.kind}/{it.name}: {e}", file=sys.stderr)
            failures += 1
        except subprocess.CalledProcessError as e:
            print(
                f"  ✗ {it.kind}/{it.name}: command failed ({e.returncode})",
                file=sys.stderr,
            )
            failures += 1

    if failures:
        print(f"\nDone with {failures} failure(s) — see errors above.", file=sys.stderr)
        notify_stale(scope)
        return 1
    print("\nDone. Symlinks → edits in repo propagate to install location.")
    notify_stale(scope)
    return 0


def run() -> None:
    """Console-script entry point (`claude-all` on PATH)."""
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    run()
