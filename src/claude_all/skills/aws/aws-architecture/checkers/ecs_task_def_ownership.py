#!/usr/bin/env python3
"""Checker: Terraform must own an ECS task definition's container env outright.

`lifecycle { ignore_changes = [container_definitions] }` (or `= all`) freezes the
deployed revision, so every later env-var change is silently dead on arrival.
`terraform validate` AND `fmt` both passed on a change that wired a reserved var into
five Lambda modules: syntax gates do not check intent, so this rule must be a checker.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from lambda_reserved_env import collect_files, line_of, resource_blocks, strip_comments

__all__ = ["FORBIDDEN", "check_file", "main"]

IGNORE_RE = re.compile(
    r"\bignore_changes\s*=\s*(?:\[(?P<items>[^\]]*)\]|(?P<bare>all)\b)", re.DOTALL
)
FORBIDDEN: frozenset[str] = frozenset({"container_definitions", "all"})


def check_file(path: Path) -> list[str]:
    """Return findings for task definitions in path that ignore container_definitions."""
    text = strip_comments(path.read_text(encoding="utf-8"))
    findings: list[str] = []
    for block in resource_blocks(text, "aws_ecs_task_definition"):
        for match in IGNORE_RE.finditer(text, block.start, block.end):
            raw = match.group("items") or ""
            listed = {item.strip().strip('"') for item in raw.split(",")}
            items = {"all"} if match.group("bare") else listed
            if hits := sorted(items & FORBIDDEN):
                findings.append(
                    f"{path.as_posix()}:{line_of(text, match.start())}: "
                    f"aws_ecs_task_definition.{block.name} has ignore_changes = [{', '.join(hits)}]"
                    " — this freezes the container env block; let Terraform own it"
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    """Scan argv roots (files or dirs) for frozen ECS task definitions."""
    parser = argparse.ArgumentParser(description="Ban ignore_changes on ECS container defs.")
    parser.add_argument("roots", nargs="+", type=Path, help="Terraform files or dirs")
    parser.add_argument("--exit-zero", action="store_true", help="report but exit 0")
    args = parser.parse_args(argv)
    try:
        files = collect_files(args.roots, ".tf")
        findings = [line for path in files for line in check_file(path)]
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ecs-task-def-ownership: cannot check — {exc}", file=sys.stderr)
        return 2
    print(f"scanned={len(files)}", file=sys.stderr)
    if not files:
        print("ecs-task-def-ownership: no .tf files found — checked nothing", file=sys.stderr)
        return 2
    for line in findings:
        print(line)
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
