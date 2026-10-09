#!/usr/bin/env python3
"""claude-all installer: interactive TUI to select and install agents, skills, plugins, MCPs.

Installs to ~/.claude (user) or ./.claude (project); see HELP_EPILOG for usage and keys.
"""

from __future__ import annotations

import argparse
import contextlib
import curses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

__all__ = ["HELP_EPILOG", "main", "run"]

HELP_EPILOG = """claude-all installer — interactive TUI for selecting and installing
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


REPO_ROOT = Path(__file__).resolve().parent
USER_CLAUDE_DIR = Path.home() / ".claude"
STATE_DIR = Path.home() / ".claude-all"
STATE_FILE = STATE_DIR / "state.json"
STATE_VERSION = 2


# ---------------------- state file ----------------------


def state_key(kind: str, name: str) -> str:
    return f"{kind}/{name}"


def state_scope(path: str | Path | None) -> str:
    """Return the installation scope that owns one recorded path."""
    if not path:
        return "user"
    target = Path(os.path.abspath(path))
    cwd = Path.cwd()
    home = Path.home()
    if not target.is_relative_to(cwd):
        return "user"
    if not target.is_relative_to(home):
        return "project"
    return "project" if len(cwd.parts) > len(home.parts) else "user"


def state_host(path: str | Path | None) -> str:
    """Return the host that owns one recorded path."""
    if path and (
        ".codex" in Path(path).parts
        or ".agents" in Path(path).parts
        or Path(path).name == "AGENTS.md"
    ):
        return "codex"
    return "claude"


def migrate_state(state: dict) -> dict:
    if state.get("version") == STATE_VERSION:
        return state
    for entry in state.setdefault("installs", {}).values():
        if "scopes" in entry:
            continue
        target = entry.get("target")
        scope = state_scope(target)
        host = state_host(target)
        entry["scopes"] = {
            scope: {
                "hosts": {
                    host: {
                        "target": target,
                        "installed_at": entry.get("installed_at"),
                        "artifacts": entry.get("artifacts") or [],
                    }
                }
            }
        }
        entry.pop("target", None)
        entry.pop("installed_at", None)
        entry.pop("artifacts", None)
    state["version"] = STATE_VERSION
    return state


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"version": STATE_VERSION, "installs": {}}
    try:
        return migrate_state(json.loads(STATE_FILE.read_text()))
    except json.JSONDecodeError:
        return {"version": STATE_VERSION, "installs": {}}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def symlink_source(path: Path) -> str | None:
    if not path.is_symlink():
        return None
    try:
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError):
        return None


def unlink_recorded_symlink(
    path: Path,
    recorded_source: object,
    *,
    allow_dangling: bool = False,
) -> bool:
    current_source = symlink_source(path)
    is_known_dangling = allow_dangling and path.is_symlink() and not path.exists()
    source_matches = isinstance(recorded_source, str) and current_source == recorded_source
    if not source_matches and not is_known_dangling:
        return False
    path.unlink()
    return True


def record_install(
    kind: str,
    name: str,
    target_path: Path | None,
    *,
    host: str | None = None,
    scope: str | None = None,
) -> None:
    record_footprint(kind, name, target_path, host=host, scope=scope, replace=True)


def record_artifact(
    kind: str,
    name: str,
    artifact: dict,
    *,
    host: str | None = None,
    scope: str | None = None,
) -> None:
    path = artifact.get("path") or artifact.get("file")
    record_footprint(kind, name, path, artifact=artifact, host=host, scope=scope)


def record_footprint(
    kind: str,
    name: str,
    path: Path | str | None,
    *,
    artifact: dict | None = None,
    host: str | None = None,
    scope: str | None = None,
    replace: bool = False,
) -> None:
    record_scope = scope or state_scope(path)
    record_host = host or state_host(path)
    state = load_state()
    entry = state_entry(state, state_key(kind, name), kind, name)
    hosts = host_records(entry, record_scope)
    if replace:
        recorded_source = symlink_source(Path(path)) if path is not None else None
        hosts[record_host] = {
            "target": str(path) if path else None,
            "source": recorded_source,
            "installed_at": datetime.now(UTC).isoformat(),
            "artifacts": [],
        }
    elif artifact is not None:
        recorded_artifact = dict(artifact)
        if recorded_artifact.get("type") == "symlink" and "source" not in recorded_artifact:
            artifact_path = recorded_artifact.get("path")
            if isinstance(artifact_path, str):
                recorded_artifact["source"] = symlink_source(Path(artifact_path))
        hosts.setdefault(
            record_host,
            {
                "target": None,
                "source": None,
                "installed_at": datetime.now(UTC).isoformat(),
                "artifacts": [],
            },
        )["artifacts"].append(recorded_artifact)
    save_state(state)


def state_entry(state: dict, key: str, kind: str, name: str) -> dict:
    return state.setdefault("installs", {}).setdefault(
        key,
        {"kind": kind, "name": name, "scopes": {}},
    )


def host_records(entry: dict, scope: str) -> dict:
    """Return the host records belonging to one scope in a state entry."""
    return entry.setdefault("scopes", {}).setdefault(scope, {"hosts": {}})["hosts"]


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


def scan_stale() -> list[dict]:
    """Every genuinely-stale PRIMARY install — recorded but no longer shipped."""
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
            stale.extend(scoped_records(entry))
    return stale


def stale_installs() -> list[dict]:
    """Stale installs of PRUNABLE kinds — ``--prune`` fully reverses their footprint."""
    return [e for e in scan_stale() if e.get("kind") not in PRUNE_EXCLUDED_KINDS]


def stale_records() -> list[dict]:
    return [e for e in scan_stale() if e.get("kind") in PRUNE_EXCLUDED_KINDS]


def scoped_records(entry: dict) -> list[dict]:
    return [
        {
            "kind": entry["kind"],
            "name": entry["name"],
            "scope": scope,
            "hosts": scope_entry["hosts"],
        }
        for scope, scope_entry in entry.get("scopes", {}).items()
    ]


def remove_scoped_record(installs: dict, entry: dict) -> None:
    key = state_key(entry["kind"], entry["name"])
    parent = installs.get(key)
    if parent is None:
        return
    parent["scopes"].pop(entry["scope"], None)
    if not parent["scopes"]:
        installs.pop(key, None)
        installs.pop(state_key(entry["kind"], entry["name"] + COMPANION_SUFFIX), None)


def reverse_scoped_record(installs: dict, entry: dict) -> list[str]:
    actions = [
        action for host_entry in entry["hosts"].values() for action in reverse_footprint(host_entry)
    ]
    remove_scoped_record(installs, entry)
    return actions


def prune_installs(entries: list[dict]) -> list[str]:
    return reverse_records(
        entries,
        lambda entry, actions: (
            f"{entry['kind']}/{entry['name']} ({', '.join(actions) or 'state only'})"
        ),
    )


def in_install_scope(path: str | Path) -> bool:
    """True when *path* lies inside an install root this invocation owns."""
    candidate = Path(path).expanduser()
    roots = (
        USER_CLAUDE_DIR,
        Path.cwd() / ".claude",
        claude_md_target("user"),
        Path.home() / ".codex",
        Path.cwd() / ".codex",
        agents_md_target("user"),
        agents_md_target("project"),
        Path.home() / ".agents" / "skills",
        Path.cwd() / ".agents" / "skills",
    )
    return any(candidate == root or root in candidate.parents for root in roots)


def reverse_footprint(entry: dict) -> list[str]:
    actions: list[str] = []
    target = entry.get("target")
    if (
        target
        and in_install_scope(target)
        and unlink_recorded_symlink(Path(target), entry.get("source"))
    ):
        actions.append("symlink")
    actions.extend(a for a in (undo_artifact(x) for x in entry.get("artifacts") or []) if a)
    return actions


def remove_install_host(kind: str, name: str, scope: str, host: str) -> list[str]:
    state = load_state()
    installs = state.get("installs", {})
    actions: list[str] = []
    changed = False
    for key in (state_key(kind, name), state_key(kind, name + COMPANION_SUFFIX)):
        parent = installs.get(key)
        if not isinstance(parent, dict):
            continue
        scopes = parent.get("scopes", {})
        scope_entry = scopes.get(scope)
        if not isinstance(scope_entry, dict):
            continue
        hosts = scope_entry.get("hosts", {})
        host_entry = hosts.pop(host, None)
        if not isinstance(host_entry, dict):
            continue
        actions.extend(reverse_footprint(host_entry))
        changed = True
        if not hosts:
            scopes.pop(scope, None)
        if not scopes:
            installs.pop(key, None)
    if changed:
        save_state(state)
    return actions


def undo_artifact(artifact: dict) -> str:
    """Reverse one recorded install artifact."""
    kind = artifact.get("type")
    if kind == "symlink":
        path = Path(artifact["path"])
        # Only unlink the exact link we created, while it remains inside our scope.
        if in_install_scope(path) and unlink_recorded_symlink(
            path,
            artifact.get("source"),
            allow_dangling=artifact.get("dangling") is True,
        ):
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
    if kind == "generated_file":
        path = Path(artifact["path"])
        expected_digest = artifact.get("digest")
        if (
            in_install_scope(path)
            and path.is_file()
            and not path.is_symlink()
            and isinstance(expected_digest, str)
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected_digest
        ):
            path.unlink()
            return "generated file"
        return ""
    if kind == "codex_hook":
        path = Path(artifact["file"])
        if not in_install_scope(path) or not path.exists():
            return ""
        try:
            document = json.loads(path.read_text())
        except json.JSONDecodeError:
            return ""
        if hook_document_error(document) is not None:
            return ""
        removed = False
        for event, blocks in list(document.get("hooks", {}).items()):
            for block in blocks:
                before = len(block.get("hooks", []))
                block["hooks"] = [
                    hook for hook in block["hooks"] if hook.get("command") != artifact["command"]
                ]
                removed = removed or len(block["hooks"]) != before
            document["hooks"][event] = [block for block in blocks if block.get("hooks")]
            if not document["hooks"][event]:
                del document["hooks"][event]
        if removed:
            path.write_text(json.dumps(document, indent=2) + "\n")
            return "Codex hook"
        return ""
    return ""


def strip_claude_md_block(target: Path, start_tag: str, end_tag: str) -> str:
    """Remove the tagged block between *start_tag* and *end_tag* from *target*."""
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
    """Remove every hook entry whose ``command`` equals *command* from *settings_file*."""
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
    return reverse_records(
        entries,
        lambda entry, _actions: (
            f"{entry['kind']}/{entry['name']} (record forgotten; binary left in place)"
        ),
    )


def reverse_records(entries: list[dict], labeler: Callable[[dict, list[str]], str]) -> list[str]:
    state = load_state()
    installs = state.get("installs", {})
    labels = [labeler(entry, reverse_scoped_record(installs, entry)) for entry in entries]
    save_state(state)
    return labels


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


def all_install_records(filters: list[str] | None = None, scope: str | None = None) -> list[dict]:
    records: list[dict] = []
    for entry in load_state().get("installs", {}).values():
        name = entry.get("name", "")
        if is_companion_key(name):
            continue
        if filters and not all(
            token in state_key(entry.get("kind", ""), name) for token in filters
        ):
            continue
        records.extend(
            record for record in scoped_records(entry) if scope is None or scope == record["scope"]
        )
    return records


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def remove_state_file() -> bool:
    """Delete the state file once nothing is recorded any more."""
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
    text = str(path)
    marker = "/claude_all/"
    return text.split(marker)[0] if marker in text else ""


def check_links(scope: str) -> list[dict]:
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
                        "artifact": {"type": "symlink", "path": str(link), "dangling": True},
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
    findings = check_links(scope) + check_settings_hooks(scope) + check_claude_md(scope)
    removable = [f for f in findings if f.get("artifact")]
    advisory = [f for f in findings if not f.get("artifact")]
    return removable, advisory


def remove_leftovers(findings: list[dict]) -> list[str]:
    removed: list[str] = []
    for finding in findings:
        if undo_artifact(finding["artifact"]):
            removed.append(finding["label"])
    return removed


def notify_stale(scope: str = "user") -> None:
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
    src: Path  # source: agent file, SKILL.md, or plugin.json
    selected: bool = False
    installed: bool = False


# ---------------------- Codex artifact rendering ----------------------


CLAUDE_SKILL_NAME = re.compile(r"^[a-z0-9-]{1,64}$")
CLAUDE_SKILL_RESERVED_WORDS = ("anthropic", "claude")


def parse_agent_front_matter(source: Path) -> tuple[dict[str, str], str]:
    text = source.read_text(encoding="utf-8")
    matched = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, flags=re.DOTALL)
    if matched is None:
        raise ValueError(f"agent source has no YAML front matter: {source}")
    raw, body = matched.groups()
    fields: dict[str, str] = {}
    lines = raw.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        scalar = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if scalar is None:
            index += 1
            continue
        key, value = scalar.groups()
        if value in {">-", "|", ">"}:
            index += 1
            folded: list[str] = []
            while index < len(lines) and (lines[index].startswith(" ") or not lines[index]):
                folded.append(lines[index].strip())
                index += 1
            fields[key] = " ".join(part for part in folded if part)
            continue
        fields[key] = value.strip().strip('"')
        index += 1
    return fields, body.strip()


def render_codex_agent(source: Path, name: str | None = None) -> str:
    fields, body = parse_agent_front_matter(source)
    agent_name = name or fields.get("name")
    description = fields.get("description")
    if not agent_name or not description:
        raise ValueError(f"agent needs name and description: {source}")
    values = {
        "name": agent_name,
        "description": description,
        "developer_instructions": body,
    }
    return (
        "\n".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items()
        )
        + "\n"
    )


def hook_document_error(document: object) -> str | None:
    """Return a structural error for a Claude/Codex hook document, if any."""
    if not isinstance(document, dict):
        return "expected a JSON object"
    hooks = document.get("hooks", {})
    if not isinstance(hooks, dict):
        return "'hooks' must be an object"
    for event, blocks in hooks.items():
        if not isinstance(event, str):
            return "hook event names must be strings"
        if not isinstance(blocks, list):
            return f"hook event {event!r} must contain a list of matcher blocks"
        for block in blocks:
            if not isinstance(block, dict):
                return f"hook event {event!r} contains a non-object matcher block"
            entries = block.get("hooks", [])
            if not isinstance(entries, list):
                return f"hook event {event!r} matcher 'hooks' must be a list"
            if any(not isinstance(entry, dict) for entry in entries):
                return f"hook event {event!r} contains a non-object hook entry"
            for entry in entries:
                command = entry.get("command")
                if command is not None and not isinstance(command, str):
                    return f"hook event {event!r} contains a non-string command"
    return None


def validate_claude_skill_name(name: str, source: Path) -> str:
    if CLAUDE_SKILL_NAME.fullmatch(name) is None:
        raise ValueError(
            f"invalid Claude skill name {name!r} in {source}: "
            "use 1-64 lowercase letters, numbers, or hyphens"
        )
    reserved = next((word for word in CLAUDE_SKILL_RESERVED_WORDS if word in name), None)
    if reserved is not None:
        raise ValueError(
            f"invalid Claude skill name {name!r} in {source}: "
            f"reserved word {reserved!r} is not allowed"
        )
    return name


def skill_destination(skill_root: Path, item: Item) -> Path:
    name = validate_claude_skill_name(item.name, item.src)
    destination = skill_root / name
    if destination.parent != skill_root:
        raise ValueError(f"invalid Claude skill name {name!r}: destination escapes {skill_root}")
    return destination


def agents_md_target(scope: str) -> Path:
    """Return the Codex instruction document for one installation scope."""
    return scoped_path(
        scope,
        Path.home() / ".codex" / "AGENTS.md",
        Path.cwd() / "AGENTS.md",
    )


def inject_agents_md(item: Item, scope: str) -> str | None:
    return inject_instruction(item, agents_md_target(scope), "AGENTS.md")


def merge_codex_hook(
    hooks_file: Path, event: str, matcher: str, command: str, timeout_seconds: int
) -> None:
    document = json.loads(hooks_file.read_text(encoding="utf-8")) if hooks_file.exists() else {}
    error = hook_document_error(document)
    if error is not None:
        raise ValueError(f"invalid Codex hook config {hooks_file}: {error}")
    assert isinstance(document, dict)
    hooks = document.setdefault("hooks", {})
    blocks = hooks.setdefault(event, [])
    block = next((candidate for candidate in blocks if candidate.get("matcher") == matcher), None)
    if block is None:
        block = {"matcher": matcher, "hooks": []}
        blocks.append(block)
    entries = block.setdefault("hooks", [])
    entries[:] = [entry for entry in entries if entry.get("command") != command]
    entries.append({"type": "command", "command": command, "timeout": max(1, timeout_seconds)})
    hooks_file.parent.mkdir(parents=True, exist_ok=True)
    hooks_file.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


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
            try:
                fields, _ = parse_agent_front_matter(p)
            except ValueError:
                fields = {}
            name = validate_claude_skill_name(fields.get("name") or parts[2], p)
            items.append(
                Item(
                    kind="skills",
                    subcategory=parts[1],
                    name=name,
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
            identity = f"{rel}\n{it.name}"
            return all(f in identity for f in filters)

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
    if item.kind == "agents" and item.src.name != "agent.md":
        return item.src.parent / f"{item.name}.claude-all.json"
    return item.src.parent / "claude-all.json"


def load_resource_config(item: Item) -> dict:
    path = resource_config_path(item)
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text())  # guard:allow — zero-dependency installer
    except (json.JSONDecodeError, OSError):
        return {}
    return config if isinstance(config, dict) else {}


def load_requires(item: Item) -> list[str]:
    requires = load_resource_config(item).get("requires", [])
    if not isinstance(requires, list):
        return []
    return [dep for dep in requires if isinstance(dep, str)]


def resolve_closure(
    selected: list[Item], universe: list[Item]
) -> tuple[list[Item], list[str], list[str]]:
    """Expand *selected* to its transitive dependency closure over *universe*."""
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
    return "'" + s.replace("'", "'\\''") + "'"


def mcp_metadata(item: Item) -> tuple[dict, str, str | None, list, dict]:
    meta = json.loads(item.src.read_text())
    return (
        meta,
        meta.get("name") or item.name,
        meta.get("command"),
        meta.get("args") or [],
        meta.get("env") or {},
    )


def has_keychain_reference(args: list, env: dict) -> bool:
    values = [*args, *env.values()]
    return any(isinstance(value, str) and value.startswith("keychain:") for value in values)


def install_mcp(item: Item, scope: str) -> str:
    meta, name, command, raw_args, raw_env = mcp_metadata(item)
    transport = meta.get("transport", "stdio")

    if not command:
        return f"skipped mcp {item.name}: missing 'command'"
    if shutil.which("claude") is None:
        return f"skipped mcp {item.name}: 'claude' CLI not in PATH"

    has_keychain = has_keychain_reference(raw_args, raw_env)

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
    record_install(item.kind, item.name, None, scope=scope)

    msg = meta.get("post_install_message")
    if msg:
        print(f"  (i) {item.name}:\n{msg}")

    return f"added mcp {name} (scope: {scope})"


def install_tool(item: Item) -> str:
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


def hook_install_preflight(item: Item, scope: str, host: str) -> str | None:
    files = hook_files(item)
    if files is None:
        return None
    metadata_path, _ = files
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return f"invalid hook.json: {error}"
    if not isinstance(metadata, dict):
        return "invalid hook.json: expected a JSON object"
    if not isinstance(metadata.get("event", "PreToolUse"), str):
        return "invalid hook.json: 'event' must be a string"
    if not isinstance(metadata.get("matcher", "Edit|Write"), str):
        return "invalid hook.json: 'matcher' must be a string"
    try:
        int(metadata.get("timeout", 2))
    except (TypeError, ValueError):
        return "invalid hook.json: 'timeout' must be an integer"

    config_path = settings_path(scope) if host == "claude" else codex_root(scope) / "hooks.json"
    config_name = "settings.json" if host == "claude" else "hooks.json"
    if not config_path.exists():
        return None
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return f"invalid {config_name}: {error}"
    shape_error = hook_document_error(document)
    if shape_error is not None:
        return f"invalid {config_name}: {shape_error}"
    return None


def hook_symlink_dest(scope: str, item: Item) -> Path:
    if scope == "user":
        base = Path.home() / ".claude" / "hooks"
    else:
        base = Path.cwd() / ".claude" / "hooks"
    return base / f"{item.kind}-{item.name}.py"


def inject_hook(item: Item, scope: str) -> str | None:
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
    timeout = int(hook_meta.get("timeout", 2))

    settings_file = settings_path(scope)
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError as e:
            return f"hook skipped (invalid settings.json: {e})"
    else:
        settings = {}
    error = hook_document_error(settings)
    if error is not None:
        return f"hook skipped (invalid settings.json: {error} in {settings_file})"
    assert isinstance(settings, dict)

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
    settings_file.parent.mkdir(parents=True, exist_ok=True)

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


# ---------------------- CLAUDE.md injection ----------------------


def claude_md_snippet_path(item: Item) -> Path | None:
    if item.kind == "agents" and item.src.name != "agent.md":
        # Flat agent: companion is a prefixed sibling `<name>.claude_md.md`.
        candidate = item.src.with_name(f"{item.name}.claude_md.md")
    else:
        # Folder agent (`<name>/agent.md`) / skill / plugin / mcp: `claude_md.md` in the dir.
        candidate = item.src.parent / "claude_md.md"
    return candidate if candidate.exists() else None


def scoped_path(scope: str, user_path: Path, project_path: Path) -> Path:
    return user_path if scope == "user" else project_path


def claude_md_target(scope: str) -> Path:
    """Return the Claude instruction document for one installation scope."""
    return scoped_path(
        scope,
        Path.home() / ".claude" / "CLAUDE.md",
        Path.cwd() / "CLAUDE.md",
    )


def snippet_tags(item: Item) -> tuple[str, str]:
    key = f"{item.kind}/{item.name}"
    return (
        f"<!-- claude-all:{key}:start -->",
        f"<!-- claude-all:{key}:end -->",
    )


def inject_tagged_block(target: Path, item: Item, snippet_path: Path) -> str:
    return write_tagged_block(target, item, snippet_path.read_text())


def inject_instruction(item: Item, target: Path, label: str) -> str | None:
    snippet_path = claude_md_snippet_path(item)
    if snippet_path is None:
        return None
    action = inject_tagged_block(target, item, snippet_path)
    return f"{label} {action} ({target})"


def write_tagged_block(target: Path, item: Item, content: str | None) -> str:
    start_tag, end_tag = snippet_tags(item)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if start_tag not in existing or end_tag not in existing:
        if content is None:
            return "missing"
        target.parent.mkdir(parents=True, exist_ok=True)
        block = f"\n{start_tag}\n{content.rstrip()}\n{end_tag}\n"
        target.write_text((existing.rstrip() + "\n" + block).lstrip("\n"), encoding="utf-8")
        return "appended"
    before = existing.split(start_tag, 1)[0].rstrip()
    after = existing.split(end_tag, 1)[1].lstrip("\n")
    if content is None:
        text = f"{before}\n{after}".strip()
        target.write_text(f"{text}\n" if text else "", encoding="utf-8")
        return "removed"
    block = f"\n{start_tag}\n{content.rstrip()}\n{end_tag}\n"
    updated = f"{before}\n{block}\n{after}".rstrip() + "\n"
    if updated == existing:
        return "current"
    target.write_text(updated, encoding="utf-8")
    return "updated"


def inject_claude_md(item: Item, scope: str) -> str | None:
    target = claude_md_target(scope)
    message = inject_instruction(item, target, "CLAUDE.md")
    if message is None:
        return None
    start_tag, end_tag = snippet_tags(item)
    record_artifact(
        item.kind,
        item.name,
        {"type": "claude_md", "file": str(target), "start": start_tag, "end": end_tag},
    )
    return message


def command_hook_basename(cmd: str) -> str:
    stripped = (cmd or "").strip()
    if not stripped:
        return ""
    token = stripped.split()[-1].strip("\"'")
    name = Path(token).name
    return name if name.endswith(".py") else ""


def command_targets_managed_hook(cmd: str, target_basename: str) -> bool:
    """True if *cmd* runs a script named *target_basename* out of a ``.claude/hooks/`` dir."""
    if command_hook_basename(cmd) != target_basename:
        return False
    token = Path(cmd.strip().split()[-1].strip("\"'"))
    parent = token.parent
    return parent.name == "hooks" and parent.parent.name == ".claude"


def purge_hook_entries(settings: dict, target_basename: str) -> None:
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
    try:
        manifest = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text())
    except (json.JSONDecodeError, OSError):
        manifest = {}
    meta = manifest.get(item.name, {})
    event = meta.get("event", "PreToolUse")
    matcher = meta.get("matcher", "Edit|Write")
    timeout = int(meta.get("timeout", 2))

    settings_file = settings_path(scope)
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError as e:
            return f"hook skipped (invalid settings.json: {e})"
    else:
        settings = {}
    error = hook_document_error(settings)
    if error is not None:
        return f"hook skipped (invalid settings.json: {error} in {settings_file})"
    assert isinstance(settings, dict)

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

    settings_file.parent.mkdir(parents=True, exist_ok=True)
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
    record_install(item.kind, item.name, None, scope=scope)
    record_artifact(item.kind, item.name, {"type": "symlink", "path": str(dest)}, scope=scope)
    record_artifact(
        item.kind,
        item.name,
        {"type": "settings_hook", "file": str(settings_file), "command": cmd_str},
        scope=scope,
    )
    return f"installed hook {item.name} → {dest} ({event}/{matcher or '*'})"


def install_claude_item(item: Item, target_root: Path) -> str:
    scope = "user" if target_root == USER_CLAUDE_DIR else "project"

    if item.kind == "hooks":
        return install_standalone_hook(item, scope)

    if item.kind == "instructions":
        # Snippet-only resource: inject the tagged block, nothing to symlink.
        md = inject_claude_md(item, scope)
        record_install(item.kind, item.name, claude_md_target(scope), scope=scope)
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
        try:
            target_path = skill_destination(target_dir, item)
        except ValueError as error:
            return f"skipped skills/{item.name}: {error}"
        src = item.src.parent
    else:
        return f"unknown kind: {item.kind}"

    preflight_error = hook_install_preflight(item, scope, "claude")
    if preflight_error is not None:
        return f"skipped {item.kind}/{item.name}: {preflight_error}"

    target_dir.mkdir(parents=True, exist_ok=True)

    replaced = target_path.is_symlink() or target_path.exists()
    if not replace_with_symlink(target_path, src, allow_identical_file=False):
        return f"skipped {item.kind}/{item.name}: destination is user-owned"
    record_install(item.kind, item.name, target_path, scope=scope)
    migrate_legacy_skill_host(item, scope, "claude", target_root / "skills")

    md = inject_claude_md(item, scope)
    if md:
        print(f"  ↳ {md}")
    hk = inject_hook(item, scope)
    if hk:
        print(f"  ↳ {hk}")

    return f"{'replaced' if replaced else 'linked'} {item.kind}/{item.name}"


def codex_root(scope: str) -> Path:
    """Return the Codex configuration root for one scope."""
    return scoped_path(scope, Path.home() / ".codex", Path.cwd() / ".codex")


def codex_skill_root(scope: str) -> Path:
    return scoped_path(
        scope,
        Path.home() / ".agents" / "skills",
        Path.cwd() / ".agents" / "skills",
    )


def replace_with_symlink(
    destination: Path,
    source: Path,
    *,
    allow_identical_file: bool = True,
) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        if destination.resolve() != source.resolve():
            return False
        destination.unlink()
    elif destination.exists():
        if (
            not allow_identical_file
            or not destination.is_file()
            or not source.is_file()
            or destination.read_bytes() != source.read_bytes()
        ):
            return False
        destination.unlink()
    os.symlink(source, destination)
    return True


def migrate_legacy_skill_host(item: Item, scope: str, host: str, skill_root: Path) -> None:
    if item.kind != "skills" or item.src.parent.name == item.name:
        return
    legacy_name = item.src.parent.name
    remove_install_host(item.kind, legacy_name, scope, host)
    legacy_destination = skill_root / legacy_name
    if (
        legacy_destination.is_symlink()
        and legacy_destination.resolve() == item.src.parent.resolve()
    ):
        legacy_destination.unlink()


def is_recorded_codex_agent(destination: Path, scope: str) -> bool:
    for entry in load_state().get("installs", {}).values():
        hosts = entry.get("scopes", {}).get(scope, {}).get("hosts", {})
        codex = hosts.get("codex", {})
        for artifact in codex.get("artifacts", []):
            if artifact.get("path") == str(destination) and artifact.get("type") in {
                "generated_file",
                "symlink",
            }:
                return True
    return False


def write_codex_agent(item: Item, scope: str) -> bool:
    destination = codex_root(scope) / "agents" / f"{item.name}.toml"
    rendered = render_codex_agent(item.src, item.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        legacy_cache = STATE_DIR / "codex"
        if legacy_cache not in destination.resolve(strict=False).parents:
            return False
        destination.unlink()
    elif destination.exists() and (
        not destination.is_file()
        or (
            destination.read_text(encoding="utf-8") != rendered
            and not is_recorded_codex_agent(destination, scope)
        )
    ):
        return False
    destination.write_text(rendered, encoding="utf-8")
    return True


def legacy_codex_agent_symlink_exists(legacy_cache: Path) -> bool:
    agents = codex_root("user") / "agents"
    return any(
        legacy_cache in path.resolve(strict=False).parents
        for path in agents.glob("*.toml")
        if path.is_symlink()
    )


def rebuild_codex_agents(items: list[Item]) -> int:
    installed_names = {
        entry["name"]
        for entry in load_state().get("installs", {}).values()
        if entry.get("kind") == "agents"
        and entry.get("scopes", {}).get("user", {}).get("hosts", {}).get("codex")
    }
    written = sum(
        write_codex_agent(item, "user")
        for item in items
        if item.kind == "agents" and item.name in installed_names
    )
    legacy_cache = STATE_DIR / "codex"
    if legacy_cache.exists() and not legacy_codex_agent_symlink_exists(legacy_cache):
        shutil.rmtree(legacy_cache)
    return written


def install_codex_mcp(item: Item, scope: str) -> str:
    meta, name, command, raw_args, raw_env = mcp_metadata(item)
    if not command:
        return f"skipped Codex mcp {item.name}: missing 'command'"
    has_keychain = has_keychain_reference(raw_args, raw_env)
    cmd = ["codex", "mcp", "add", name, "--"]
    if has_keychain:
        env_parts = [
            f"{key}={keychain_subst(value)}"
            if isinstance(value, str) and value.startswith("keychain:")
            else f"{key}={shell_quote(str(value))}"
            for key, value in raw_env.items()
        ]
        exec_parts = [shell_quote(command)]
        for arg in raw_args:
            if isinstance(arg, str) and arg.startswith("keychain:"):
                exec_parts.append(f'"{keychain_subst(arg)}"')
            else:
                exec_parts.append(shell_quote(str(arg)))
        cmd.extend(["sh", "-c", " ".join([*env_parts, "exec", *exec_parts])])
    else:
        for key, value in raw_env.items():
            cmd.extend(["--env", f"{key}={value}"])
        cmd.append(command)
        cmd.extend(str(arg) for arg in raw_args)
    subprocess.run(cmd, check=True)
    record_install(item.kind, item.name, None, host="codex", scope=scope)
    msg = meta.get("post_install_message")
    if msg:
        print(f"  (i) {item.name}:\n{msg}")
    return f"added Codex mcp {name} (scope: {scope})"


def install_codex_hook(item: Item, scope: str) -> str | None:
    if item.kind == "hooks":
        metadata = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text()).get(item.name, {})
    else:
        files = hook_files(item)
        if files is None:
            return None
        metadata_path, source = files
        metadata = json.loads(metadata_path.read_text())
    if item.kind == "hooks":
        source = item.src
    root = codex_root(scope)
    hooks_file = root / "hooks.json"
    if hooks_file.exists():
        try:
            document = json.loads(hooks_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return f"skipped Codex hook {item.name}: invalid hooks.json: {e}"
        error = hook_document_error(document)
        if error is not None:
            return f"skipped Codex hook {item.name}: invalid hooks.json: {error}"
    destination = root / "hooks" / f"{item.kind}-{item.name}.py"
    if metadata.get("codex") is False:
        actions = remove_install_host(item.kind, item.name, scope, "codex")
        fallback = undo_artifact(
            {"type": "codex_hook", "file": str(hooks_file), "command": str(destination)}
        )
        if fallback:
            actions.append(fallback)
        if destination.is_symlink() and destination.resolve() == source.resolve():
            destination.unlink()
            actions.append("hook symlink")
        suffix = "; removed legacy Codex wiring" if actions else ""
        return f"skipped Codex hook {item.name}: Claude-only approval hook{suffix}"
    if not replace_with_symlink(destination, source):
        return f"skipped Codex hook {item.name}: destination is user-owned"
    merge_codex_hook(
        hooks_file,
        metadata.get("event", "PreToolUse"),
        metadata.get("matcher", "Edit|Write"),
        str(destination),
        int(metadata.get("timeout", 2)),
    )
    record_artifact(item.kind, item.name, {"type": "symlink", "path": str(destination)})
    record_artifact(
        item.kind,
        item.name,
        {"type": "codex_hook", "file": str(root / "hooks.json"), "command": str(destination)},
    )
    return f"Codex hook installed → {destination}"


def install_codex_item(item: Item, scope: str) -> str:
    root = codex_root(scope)
    if item.kind == "instructions":
        message = inject_agents_md(item, scope)
        if message:
            start, end = snippet_tags(item)
            record_artifact(
                item.kind,
                item.name,
                {
                    "type": "claude_md",
                    "file": str(agents_md_target(scope)),
                    "start": start,
                    "end": end,
                },
            )
        return message or f"instructions/{item.name}: no Codex companion found"
    if item.kind == "agents":
        destination = root / "agents" / f"{item.name}.toml"
        rendered = render_codex_agent(item.src, item.name)
        if (
            destination.is_file()
            and not destination.is_symlink()
            and destination.read_text(encoding="utf-8") == rendered
            and not is_recorded_codex_agent(destination, scope)
        ):
            return f"skipped Codex agent {item.name}: destination is user-owned"
        if not write_codex_agent(item, scope):
            return f"skipped Codex agent {item.name}: destination is user-owned"
        record_artifact(
            item.kind,
            item.name,
            {
                "type": "generated_file",
                "path": str(destination),
                "digest": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            },
        )
        message = inject_agents_md(item, scope)
        if message:
            start, end = snippet_tags(item)
            record_artifact(
                item.kind,
                item.name,
                {
                    "type": "claude_md",
                    "file": str(agents_md_target(scope)),
                    "start": start,
                    "end": end,
                },
            )
        return f"generated Codex agent {destination}" + (f"; {message}" if message else "")
    if item.kind == "skills":
        preflight_error = hook_install_preflight(item, scope, "codex")
        if preflight_error is not None:
            return f"skipped Codex skill {item.name}: {preflight_error}"
        try:
            destination = skill_destination(codex_skill_root(scope), item)
        except ValueError as error:
            return f"skipped Codex skill {item.name}: {error}"
        if not replace_with_symlink(destination, item.src.parent):
            return f"skipped Codex skill {item.name}: destination is user-owned"
        record_install(item.kind, item.name, destination, host="codex", scope=scope)
        message = inject_agents_md(item, scope)
        if message:
            start, end = snippet_tags(item)
            record_artifact(
                item.kind,
                item.name,
                {
                    "type": "claude_md",
                    "file": str(agents_md_target(scope)),
                    "start": start,
                    "end": end,
                },
            )
        hook = install_codex_hook(item, scope)
        migrate_legacy_skill_host(item, scope, "codex", codex_skill_root(scope))
        return (
            f"linked Codex skill {destination}"
            + (f"; {message}" if message else "")
            + (f"; {hook}" if hook else "")
        )
    if item.kind == "mcps":
        return install_codex_mcp(item, scope)
    if item.kind == "plugins":
        meta = json.loads(item.src.read_text())
        codex = meta.get("codex")
        if not isinstance(codex, dict) or not isinstance(codex.get("command"), list):
            return f"skipped Codex plugin {item.name}: no codex installation metadata"
        subprocess.run(codex["command"], check=True)
        return f"installed Codex plugin {item.name}"
    if item.kind == "tools":
        return f"tool {item.name} is shared; installed once"
    if item.kind == "hooks":
        return install_codex_hook(item, scope) or f"hooks/{item.name}: no Codex hook metadata"
    return f"unknown Codex kind: {item.kind}"


def install_item(item: Item, target_root: Path) -> str:
    scope = "user" if target_root == USER_CLAUDE_DIR else "project"
    messages: list[str] = []
    if shutil.which("claude"):
        messages.append(install_claude_item(item, target_root))
    else:
        messages.append("Claude skipped: CLI not on PATH")
        record_install(item.kind, item.name, codex_root(scope), scope=scope)
    if shutil.which("codex"):
        messages.append(install_codex_item(item, scope))
    else:
        messages.append("Codex skipped: CLI not on PATH")
    return " | ".join(messages)


# ---------------------- update ----------------------


def update_item(kind: str, name: str, all_items: list[Item]) -> str:
    # Find matching item in current repo
    match = next((it for it in all_items if it.kind == kind and it.name == name), None)

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

    return f"  ✗ {kind}/{name}: unknown kind"


def refresh_scoped_record(record: dict, all_items: list[Item]) -> str:
    kind, name, scope = record["kind"], record["name"], record["scope"]
    match = next((it for it in all_items if it.kind == kind and it.name == name), None)
    if match is None:
        return f"  ✗ {kind}/{name}: not found in repo (removed?)"
    target_root = USER_CLAUDE_DIR if scope == "user" else Path.cwd() / ".claude"
    try:
        return f"  ✓ refreshed ({scope}) {install_item(match, target_root)}"
    except subprocess.CalledProcessError as e:
        return f"  ✗ {kind}/{name}: command failed ({e.returncode})"


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
            if rec["kind"] in ("plugins", "tools"):
                msg = update_item(rec["kind"], rec["name"], all_items)
            else:
                msg = "\n".join(
                    refresh_scoped_record(record, all_items) for record in scoped_records(rec)
                )
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
    records = all_install_records(filters, scope)
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
        prog="claude-all",
        description="claude-all installer (interactive TUI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )
    ap.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('claude-all')}",
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
        "--rebuild",
        action="store_true",
        help="Regenerate installed global Codex agent TOML files",
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
        help="Skip the --uninstall / --install-hooks confirmation prompt (non-interactive use)",
    )
    ap.add_argument(
        "--install-hooks",
        action="store_true",
        help="Wire the checkers of your installed skills into this project's prek.toml / "
        ".pre-commit-config.yaml (claude-all as a pinned hook repo). Shows a diff, then asks",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="With --install-hooks: print the diff, write nothing",
    )
    ap.add_argument(
        "--hook",
        action="append",
        default=[],
        metavar="ID",
        help="With --install-hooks: also enable an optional hook (repeatable)",
    )
    ap.add_argument(
        "--rev",
        help="With --install-hooks: pin this claude-all tag instead of the installed version",
    )
    ap.add_argument("filters", nargs="*", help="Filter tokens (each must appear in path)")
    args = ap.parse_args(argv)

    if args.rebuild:
        if args.user or args.project:
            ap.error("--rebuild has no scope; run it without --user or --project")
        all_items = discover([])
        written = rebuild_codex_agents(all_items)
        print(f"Rebuilt {written} installed Codex agent(s): {Path.home() / '.codex' / 'agents'}")
        return 0

    if args.install_hooks:
        from claude_all.prek_hooks import cmd_install_hooks

        return cmd_install_hooks(
            assume_yes=args.yes, dry_run=args.dry_run, rev=args.rev, only=args.hook
        )

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

    print(f"Installing {len(chosen)} item(s) → {target_root}\n")
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
    print("\nDone. Codex agents are generated directly in its agent directory.")
    if any(it.kind == "skills" and "prek_hooks" in load_resource_config(it) for it in chosen):
        print(
            "Some installed skills ship checkers. In each project, run "
            "`claude-all --install-hooks` to wire them into prek/pre-commit."
        )
    notify_stale(scope)
    return 0


def run() -> None:
    """Console-script entry point (`claude-all` on PATH)."""
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    run()
