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
    ENTER        proceed
    q / ESC      quit
"""
from __future__ import annotations

import argparse
import curses
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
USER_CLAUDE_DIR = Path.home() / ".claude"


@dataclass
class Item:
    kind: str          # agents | skills | plugins | mcps
    category: str      # coding
    subcategory: str   # aws | python | ...
    name: str
    src: Path          # source path (file for agents, SKILL.md for skills)
    selected: bool = False


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

    # Apply filters: every filter token must appear in the relative path.
    if filters:
        def matches(it: Item) -> bool:
            rel = str(it.src.relative_to(REPO_ROOT))
            return all(f in rel for f in filters)
        items = [it for it in items if matches(it)]

    # Sort: kind, then subcategory, then name
    items.sort(key=lambda i: (i.kind, i.subcategory, i.name))
    return items


def install_item(item: Item, target_root: Path) -> str:
    if item.kind == "agents":
        target_dir = target_root / "agents"
        target_path = target_dir / f"{item.name}.md"
        src = item.src
    elif item.kind == "skills":
        target_dir = target_root / "skills"
        target_path = target_dir / item.name
        src = item.src.parent  # link the whole skill dir
    elif item.kind == "plugins":
        target_dir = target_root / "plugins"
        target_path = target_dir / item.name
        src = item.src
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
            import shutil
            shutil.rmtree(target_path)
        replaced = True

    os.symlink(src, target_path)
    return f"{'replaced' if replaced else 'linked'} {item.kind}/{item.name}"


# ----------------------------- TUI -----------------------------

@dataclass
class TuiState:
    items: list[Item]
    cursor: int = 0
    offset: int = 0          # scroll offset
    filter_text: str = ""
    filter_mode: bool = False
    visible: list[int] = field(default_factory=list)  # indices into items

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

    help_line = " ↑/↓ move │ SPACE toggle │ a all │ n none │ / filter │ ENTER install │ q quit "
    stdscr.addstr(1, 0, help_line[:w], curses.A_DIM)

    if state.filter_mode:
        prompt = f" /{state.filter_text}_"
        stdscr.addstr(2, 0, prompt[:w], curses.A_REVERSE)
    elif state.filter_text:
        stdscr.addstr(2, 0, f" filter: {state.filter_text}"[:w], curses.A_DIM)
    else:
        stdscr.addstr(2, 0, "")

    # Compute viewport
    list_top = 4
    list_bottom = h - 2
    page = max(1, list_bottom - list_top)

    # Keep cursor in view
    if state.cursor < state.offset:
        state.offset = state.cursor
    if state.cursor >= state.offset + page:
        state.offset = state.cursor - page + 1

    # Draw items with section headers (only when visible window starts a new group)
    last_kind = None
    last_subcat = None
    row = list_top
    for vi in range(state.offset, min(state.offset + page, len(state.visible))):
        idx = state.visible[vi]
        it = state.items[idx]
        is_cursor = (vi == state.cursor)
        marker = "[x]" if it.selected else "[ ]"
        prefix = "▸ " if is_cursor else "  "
        label = f"{prefix}{marker}  {it.kind}/{it.subcategory}/{it.name}"
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

    # Footer: count + scroll info
    sel = sum(1 for it in state.items if it.selected)
    total = len(state.items)
    shown = len(state.visible)
    scroll_info = f" {state.cursor+1}/{shown}" if shown else " 0/0"
    footer = f" selected {sel}/{total}  │  shown {shown}/{total}  │ {scroll_info}"
    try:
        stdscr.addstr(h - 1, 0, footer[:w].ljust(w), curses.A_REVERSE)
    except curses.error:
        pass

    stdscr.refresh()


def tui_select(items: list[Item]) -> bool:
    """Return True if user pressed ENTER, False if they quit."""
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
                elif ch == 27:  # ESC
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
            elif ch in (curses.KEY_PPAGE,):
                state.cursor = max(0, state.cursor - 10)
            elif ch in (curses.KEY_NPAGE,):
                state.cursor = min(len(state.visible) - 1, state.cursor + 10)
            elif ch in (curses.KEY_HOME,):
                state.cursor = 0
            elif ch in (curses.KEY_END,):
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
            elif ch in (10, 13, curses.KEY_ENTER):
                return True
            elif ch in (ord("q"), 27):  # q or ESC
                return False

    return curses.wrapper(_run)


def choose_level_tui() -> str | None:
    """Return 'user', 'project', or None on cancel."""
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


# ---------------------------- main ----------------------------

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
        print(f"    {it.kind}/{it.name}")


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

    if args.list:
        cmd_list(items)
        return 0

    # Selection
    if args.all:
        for it in items:
            it.selected = True
    else:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("TUI needs a real terminal. Use --all or --list instead.", file=sys.stderr)
            return 1
        if not tui_select(items):
            print("Cancelled.")
            return 0

    chosen = [it for it in items if it.selected]
    if not chosen:
        print("Nothing selected.")
        return 0

    # Level
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

    print(f"\nDone. Symlinks → edits in repo propagate to install location.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
