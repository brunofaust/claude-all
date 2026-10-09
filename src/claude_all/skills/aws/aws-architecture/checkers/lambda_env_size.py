#!/usr/bin/env python3
"""Checker: an aws_lambda_function env map must stay under AWS's 4096-byte cap.

Size is estimated statically as compact JSON of Environment.Variables. A literal value
counts its bytes; each `${...}` interpolation or a wholly computed value (var.x,
aws_sqs_queue.q.url) counts as --unknown-value-bytes. An opaque map merged in
(merge(local.env, ...)) cannot be sized: it is reported as unknown, never as a finding.
"""

from __future__ import annotations

import argparse
import json  # guard:allow - stdlib-only checker
import re
import sys
from pathlib import Path

from lambda_reserved_env import EnvEntry, EnvMap, collect_files, lambda_env_maps

__all__ = ["HARD_CAP_BYTES", "check_file", "estimate_size", "main"]

HARD_CAP_BYTES = 4096
INTERPOLATION_RE = re.compile(r"\$\{")


def entry_value(entry: EnvEntry, unknown_bytes: int) -> str:
    """Return entry's literal value, or a stand-in sized by unknown_bytes per computed part."""
    if entry.literal is not None:
        return entry.literal
    expr = entry.expr
    if not (expr.startswith('"') and expr.endswith('"')):
        return "X" * unknown_bytes
    parts = INTERPOLATION_RE.split(expr[1:-1])
    literal = parts[0] + "".join(part.split("}", 1)[-1] for part in parts[1:])
    return literal + "X" * (unknown_bytes * (len(parts) - 1))


def estimate_size(env_map: EnvMap, unknown_bytes: int) -> int:
    """Return env_map's compact-JSON byte size, computed values sized by unknown_bytes."""
    payload = {entry.name: entry_value(entry, unknown_bytes) for entry in env_map.entries}
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())


def check_file(path: Path, max_bytes: int, unknown_bytes: int) -> list[str]:
    """Return findings for Lambdas in path whose env exceeds max_bytes (see unknown_bytes)."""
    findings: list[str] = []
    for env_map in lambda_env_maps(path.read_text(encoding="utf-8")):
        size = estimate_size(env_map, unknown_bytes)
        if size <= max_bytes:
            continue
        note = f"; plus {len(env_map.opaque)} unsized opaque map(s)" if env_map.opaque else ""
        findings.append(
            f"{path.as_posix()}:{env_map.line}: aws_lambda_function.{env_map.resource} "
            f"env is ~{size} bytes (limit {max_bytes}{note}) — AWS rejects Environment."
            f"Variables over {HARD_CAP_BYTES} bytes; drop literals that equal the code default"
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    """Scan argv roots (files or dirs) for oversized Lambda env maps."""
    parser = argparse.ArgumentParser(description="Lambda env var JSON size gate.")
    parser.add_argument("roots", nargs="+", type=Path, help="Terraform files or dirs")
    parser.add_argument("--max-bytes", type=int, default=HARD_CAP_BYTES)
    parser.add_argument("--unknown-value-bytes", type=int, default=128)
    parser.add_argument("--exit-zero", action="store_true", help="report but exit 0")
    args = parser.parse_args(argv)
    try:
        files = collect_files(args.roots, ".tf")
        findings = [
            line
            for path in files
            for line in check_file(path, args.max_bytes, args.unknown_value_bytes)
        ]
    except (OSError, UnicodeDecodeError) as exc:
        print(f"lambda-env-size: cannot check — {exc}", file=sys.stderr)
        return 2
    print(f"scanned={len(files)}", file=sys.stderr)
    if not files:
        print("lambda-env-size: no .tf files found — checked nothing", file=sys.stderr)
        return 2
    for line in findings:
        print(line)
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
