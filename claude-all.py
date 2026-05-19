#!/usr/bin/env python3
"""
claude-all installer — interactive TUI for selecting and installing
agents/skills/plugins/mcps to ~/.claude/ (user) or ./.claude/ (project).

Usage:
    claude-all.py                       # interactive menu (all items)
    claude-all.py coding aws            # filter to coding/aws
    claude-all.py --list [filter...]    # list, no install
    claude-all.py --help

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
import curses
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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
    state["installs"][state_key(kind, name)] = {
        "kind": kind,
        "name": name,
        "target": str(target_path) if target_path else None,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_state(state)


# ---------------------- item model ----------------------

@dataclass
class Item:
    kind: str          # agents | skills | plugins | mcps
    category: str      # coding
    subcategory: str   # aws | python | ...
    name: str
    src: Path          # source path (file for agents, SKILL.md for skills, plugin.json for plugins)
    selected: bool = False
    installed: bool = False


def discover(filters: list[str]) -> list[Item]:
    items: list[Item] = []

    agent_root = REPO_ROOT / "coding" / "agents"
    if agent_root.exists():
        for p in sorted(agent_root.rglob("*.md")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            if len(parts) < 4:
                continue
            items.append(Item(
                kind="agents",
                category=parts[0],
                subcategory=parts[2],
                name=p.stem,
                src=p,
            ))

    skill_root = REPO_ROOT / "coding" / "skills"
    if skill_root.exists():
        for p in sorted(skill_root.rglob("SKILL.md")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            if len(parts) < 4:
                continue
            items.append(Item(
                kind="skills",
                category=parts[0],
                subcategory=parts[2],
                name=parts[3],
                src=p,
            ))

    plugin_root = REPO_ROOT / "coding" / "plugins"
    if plugin_root.exists():
        for p in sorted(plugin_root.glob("*/plugin.json")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            items.append(Item(
                kind="plugins",
                category=parts[0],
                subcategory="marketplace",
                name=parts[2],
                src=p,
            ))

    mcp_root = REPO_ROOT / "coding" / "mcps"
    if mcp_root.exists():
        for p in sorted(mcp_root.glob("*/mcp.json")):
            rel = p.relative_to(REPO_ROOT)
            parts = rel.parts
            items.append(Item(
                kind="mcps",
                category=parts[0],
                subcategory="stdio",
                name=parts[2],
                src=p,
            ))

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


# ---------------------- install ----------------------

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

    # Post-install hooks
    for cmd in meta.get("post_install") or []:
        if not isinstance(cmd, list) or not cmd:
            print(f"  ! {item.name}: skipping invalid post_install entry: {cmd!r}", file=sys.stderr)
            continue
        if shutil.which(cmd[0]) is None:
            print(f"  ! {item.name}: post_install '{cmd[0]}' not on PATH — open a new shell and run: {' '.join(cmd)}", file=sys.stderr)
            continue
        print(f"  → post_install: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

    msg = meta.get("post_install_message")
    if msg:
        print(f"  ℹ  {item.name}: {msg}")

    # Record state (plugins are global — no target path)
    record_install(item.kind, item.name, None)
    return result_msg


def _keychain_subst(value: str) -> str:
    """Return a shell command substitution for a keychain ref, else the literal value."""
    if isinstance(value, str) and value.startswith("keychain:"):
        service = value[len("keychain:"):]
        # Quote the service name so spaces/specials are safe inside $(...)
        safe_service = service.replace('"', '\\"')
        return f"$(security find-generic-password -a \"$USER\" -s \"{safe_service}\" -w)"
    return value


def _shell_quote(s: str) -> str:
    """POSIX shell single-quote a literal. Preserves any inner $(...) only when not wrapped here."""
    return "'" + s.replace("'", "'\\''") + "'"


def install_mcp(item: Item, level: str) -> str:
    """Install MCP via `claude mcp add`. level = 'user' or 'project'.

    Secrets stay in macOS keychain. Any `keychain:NAME` in env or args is
    converted into a runtime `sh -c '...$(security find-generic-password ...)'`
    wrapper so the secret is resolved on every MCP launch — never stored
    plaintext in .claude.json / .mcp.json.
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
    ) or any(
        isinstance(a, str) and a.startswith("keychain:") for a in raw_args
    )

    scope = "user" if level == "user" else "project"
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
            substituted = _keychain_subst(v) if isinstance(v, str) else str(v)
            # If it's a keychain subst we keep $(...) unquoted (must expand in shell).
            # If literal value, single-quote it.
            if isinstance(v, str) and v.startswith("keychain:"):
                env_inline_parts.append(f"{k}={substituted}")
            else:
                env_inline_parts.append(f"{k}={_shell_quote(str(v))}")

        # Build the exec'd command + args. Single-quote literals; leave keychain
        # subst unquoted so the shell evaluates $(...).
        exec_parts = [_shell_quote(command)]
        for a in raw_args:
            if isinstance(a, str) and a.startswith("keychain:"):
                # Wrap the subst in double quotes so spaces in the secret are safe as one arg.
                exec_parts.append(f"\"{_keychain_subst(a)}\"")
            else:
                exec_parts.append(_shell_quote(str(a)))

        shell_line = (
            " ".join(env_inline_parts) + (" " if env_inline_parts else "") +
            "exec " + " ".join(exec_parts)
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
    subprocess.run(["claude", "mcp", "remove", name, "--scope", scope],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    subprocess.run(cmd, check=True)
    record_install(item.kind, item.name, None)

    msg = meta.get("post_install_message")
    if msg:
        print(f"  ℹ  {item.name}:\n{msg}")

    return f"added mcp {name} (scope: {scope})"


def install_item(item: Item, target_root: Path) -> str:
    if item.kind == "plugins":
        return install_plugin(item)

    if item.kind == "mcps":
        # target_root encodes level via its parent: USER_CLAUDE_DIR vs cwd/.claude
        level = "user" if target_root == USER_CLAUDE_DIR else "project"
        return install_mcp(item, level)

    if item.kind == "agents":
        target_dir = target_root / "agents"
        target_path = target_dir / f"{item.name}.md"
        src = item.src
    elif item.kind == "skills":
        target_dir = target_root / "skills"
        target_path = target_dir / item.name
        src = item.src.parent
    elif item.kind == "mcps":
        target_dir = target_root / "mcps"
        target_path = target_dir / item.name
        src = item.src
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
    return f"{'replaced' if replaced else 'linked'} {item.kind}/{item.name}"


# ---------------------- update ----------------------

def update_item(kind: str, name: str, install_record: dict, all_items: list[Item]) -> str:
    """Update a single installed item. Looks up live meta from repo."""
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

    # agents / skills / mcps — re-create symlink at recorded target
    target = install_record.get("target")
    if not target:
        return f"  ✗ {kind}/{name}: missing target path in state"
    target_path = Path(target)
    if match is None:
        return f"  ✗ {kind}/{name}: not found in repo (removed?)"

    if kind == "skills":
        src = match.src.parent
    else:
        src = match.src

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.is_symlink() or target_path.exists():
        if target_path.is_symlink() or target_path.is_file():
            target_path.unlink()
        else:
            shutil.rmtree(target_path)
    os.symlink(src, target_path)
    # Refresh timestamp
    record_install(kind, name, target_path)
    return f"  ✓ refreshed {kind}/{name} ({target_path})"


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
            print(f"  ✗ {rec['kind']}/{rec['name']}: command failed ({e.returncode})", file=sys.stderr)
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
                i for i, it in enumerate(self.items)
                if ft in it.name.lower()
                or ft in it.subcategory.lower()
                or ft in it.kind.lower()
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

    help_line = " ↑/↓ │ SPACE toggle │ a all │ n none │ / filter │ u update │ ENTER install │ q quit "
    stdscr.addstr(1, 0, help_line[:w], curses.A_DIM)

    if state.filter_mode:
        prompt = f" /{state.filter_text}_"
        stdscr.addstr(2, 0, prompt[:w], curses.A_REVERSE)
    elif state.filter_text:
        stdscr.addstr(2, 0, f" filter: {state.filter_text}"[:w], curses.A_DIM)

    list_top = 4
    list_bottom = h - 2
    page = max(1, list_bottom - list_top)

    if state.cursor < state.offset:
        state.offset = state.cursor
    if state.cursor >= state.offset + page:
        state.offset = state.cursor - page + 1

    row = list_top
    for vi in range(state.offset, min(state.offset + page, len(state.visible))):
        idx = state.visible[vi]
        it = state.items[idx]
        is_cursor = (vi == state.cursor)
        marker = "[x]" if it.selected else "[ ]"
        prefix = "▸ " if is_cursor else "  "
        installed_tag = "  (installed)" if it.installed else ""
        label = f"{prefix}{marker}  {it.kind}/{it.subcategory}/{it.name}{installed_tag}"
        attr = curses.A_REVERSE if is_cursor else curses.A_NORMAL
        if it.selected and not is_cursor:
            attr |= curses.A_BOLD
        try:
            stdscr.addstr(row, 0, label[:w].ljust(min(w, len(label[:w]))), attr)
        except curses.error:
            pass
        row += 1
        if row >= list_bottom:
            break

    sel = sum(1 for it in state.items if it.selected)
    inst = sum(1 for it in state.items if it.installed)
    total = len(state.items)
    shown = len(state.visible)
    scroll_info = f" {state.cursor+1}/{shown}" if shown else " 0/0"
    footer = f" selected {sel}/{total}  │  installed {inst}/{total}  │  shown {shown}/{total}  │ {scroll_info}"
    try:
        stdscr.addstr(h - 1, 0, footer[:w].ljust(w), curses.A_REVERSE)
    except curses.error:
        pass

    stdscr.refresh()


# Action returned by TUI
TUI_INSTALL = "install"
TUI_UPDATE = "update"
TUI_QUIT = "quit"


def tui_select(items: list[Item]) -> str:
    """Return TUI_INSTALL, TUI_UPDATE, or TUI_QUIT."""
    def _run(stdscr):
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

    return curses.wrapper(_run)


def choose_level_tui() -> str | None:
    def _run(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        choices = [
            ("user",    f"User level    →  {USER_CLAUDE_DIR}"),
            ("project", f"Project level →  {Path.cwd() / '.claude'}"),
        ]
        cursor = 0
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
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
    ap.add_argument("--user", action="store_true", help="Install to ~/.claude (skip level prompt)")
    ap.add_argument("--project", action="store_true", help="Install to ./.claude (skip level prompt)")
    ap.add_argument("filters", nargs="*", help="Filter tokens (each must appear in path)")
    args = ap.parse_args(argv)

    items = discover(args.filters)
    if not items:
        filt = " ".join(args.filters) if args.filters else "(none)"
        print(f"No items match filters: {filt}", file=sys.stderr)
        return 1

    annotate_installed(items)

    if args.list:
        cmd_list(items)
        return 0

    # Selection
    if args.all:
        for it in items:
            it.selected = True
        action = TUI_INSTALL
    else:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("TUI needs a real terminal. Use --all or --list instead.", file=sys.stderr)
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

    if args.user:
        level = "user"
    elif args.project:
        level = "project"
    else:
        level = choose_level_tui()
        if level is None:
            print("Cancelled.")
            return 0

    target_root = USER_CLAUDE_DIR if level == "user" else (Path.cwd() / ".claude")

    print(f"\nInstalling {len(chosen)} item(s) → {target_root}\n")
    for it in chosen:
        try:
            msg = install_item(it, target_root)
            print(f"  ✓ {msg}")
        except OSError as e:
            print(f"  ✗ {it.kind}/{it.name}: {e}", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"  ✗ {it.kind}/{it.name}: command failed ({e.returncode})", file=sys.stderr)

    print("\nDone. Symlinks → edits in repo propagate to install location.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
