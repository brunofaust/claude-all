#!/usr/bin/env python3
"""Checker: every checker script must be registered as a hook in prek.toml/.pre-commit-config.yaml.

WHY: a checker, its baseline and its tests once landed while the hook registration did not, so
the gate stayed unarmed for days with every test green. A script is registered when its name
appears in some hook's `entry`/`args` (TOML parsed, else text minus comment lines).
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

__all__ = [
    "DEFAULT_CONFIGS",
    "DEFAULT_GLOBS",
    "HookText",
    "collect_hook_text",
    "is_registered",
    "main",
    "toml_hook_strings",
]

DEFAULT_GLOBS: tuple[str, ...] = ("scripts/check_*.py",)
DEFAULT_CONFIGS: tuple[str, ...] = ("prek.toml", ".pre-commit-config.yaml")
HOOK_KEYS = frozenset({"entry", "args"})

type HookText = list[str]


def toml_hook_strings(node: object, under_hook_key: bool = False) -> HookText:
    if isinstance(node, str):
        return [node] if under_hook_key else []
    out: HookText = []
    if isinstance(node, dict):
        for key, value in node.items():
            out.extend(toml_hook_strings(value, under_hook_key or key in HOOK_KEYS))
    elif isinstance(node, list):
        for item in node:
            out.extend(toml_hook_strings(item, under_hook_key))
    return out


def collect_hook_text(config: Path) -> HookText:
    text = config.read_text(encoding="utf-8")
    if config.suffix == ".toml":
        try:
            return toml_hook_strings(tomllib.loads(text))
        except tomllib.TOMLDecodeError:
            pass  # TOML 1.1 multi-line inline tables (prek accepts them) -> text search
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def is_registered(script: Path, hook_text: HookText) -> bool:
    pattern = re.compile(r"(?<!\w)" + re.escape(script.stem) + r"(?:\.py)?(?!\w)")
    return any(pattern.search(chunk) for chunk in hook_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flag checker scripts no hook runs.")
    parser.add_argument("--root", type=Path, default=Path(), help="repo root (default: cwd)")
    parser.add_argument("--glob", action="append", dest="globs", help="script glob (repeatable)")
    parser.add_argument(
        "--config", action="append", dest="configs", type=Path, help="hook config (repeatable)"
    )
    parser.add_argument("--exit-zero", action="store_true", help="report but exit 0")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    configs = [root / c for c in (args.configs or DEFAULT_CONFIGS)]
    present = [c for c in configs if c.is_file()]
    if not present or (args.configs and len(present) != len(configs)):
        print(f"CANNOT CHECK: hook config not found among {configs}", file=sys.stderr)
        return 2
    hook_text: HookText = []
    for config in present:
        try:
            hook_text.extend(collect_hook_text(config))
        except (OSError, UnicodeDecodeError) as exc:
            print(f"CANNOT CHECK: {config}: {exc}", file=sys.stderr)
            return 2
    scripts = sorted(
        {p for g in (args.globs or DEFAULT_GLOBS) for p in root.glob(g) if p.is_file()}
    )
    print(f"scanned={len(scripts)} checker script(s)", file=sys.stderr)
    if not scripts:
        print("CANNOT CHECK: no checker scripts matched — fix the globs", file=sys.stderr)
        return 2
    unregistered = [p for p in scripts if not is_registered(p, hook_text)]
    for path in unregistered:
        print(
            f"{path.relative_to(root).as_posix()}: not referenced by any hook entry/args in "
            f"{', '.join(c.name for c in present)} — the gate exists but never runs"
        )
    return 1 if unregistered and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
