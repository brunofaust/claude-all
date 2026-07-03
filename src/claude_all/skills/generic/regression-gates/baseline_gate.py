#!/usr/bin/env python3
"""Regression-only baseline harness — introduce ANY new gate without a big-bang cleanup.

This is the reusable meta-pattern: a checker emits findings, this wrapper compares
them against a grandfathered `<gate>_baseline.txt` so that

  * NEW findings (seen, not baselined)  -> FAIL  (the gate bites on regressions)
  * BASELINED findings still present     -> PASS  (legacy debt is tolerated)
  * STALE findings (baselined, no longer seen) -> FAIL  (the baseline can only
        shrink toward empty; you must delete the line when you fix the finding)

The stale-entry rule is what makes the file a ratchet instead of a dumping ground:
every fix forces a baseline edit, so the debt is visible and monotonically
decreasing. Burn it down one notch per PR.

CONTRACT WITH THE CHECKER COMMAND
---------------------------------
The wrapped checker prints ONE finding per line on stdout, each line a STABLE
IDENTITY KEY — e.g. ``path/to/file.py: message`` — keyed by content, NOT by line
number, so an unrelated edit elsewhere in the file does not churn the baseline.
The checker exits 0 when it RAN SUCCESSFULLY (regardless of how many findings it
printed) and exits non-zero ONLY on an internal error (missing dependency, bad
args, crash). This wrapper FAILS CLOSED on a non-zero checker exit: a gate whose
tool is missing must never pass vacuously.

USAGE
-----
    # seed the baseline from today's findings (run once, commit the file)
    baseline_gate.py --baseline private_names_baseline.txt --update -- \\
        python checkers/module_private.py src/

    # enforce in pre-commit AND CI (same command both places)
    baseline_gate.py --baseline private_names_baseline.txt -- \\
        python checkers/module_private.py src/

Copy this file per gate (or call it N times with different --baseline files).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

__all__ = ["compare", "load_baseline", "main", "run_checker"]


def load_baseline(path: Path) -> set[str]:
    """Read a baseline file into a set of finding keys.

    Blank lines and ``#`` comments are ignored, so a baseline can be annotated
    (e.g. ``# TICK-1: remove after the auth refactor``). A missing file is an
    empty baseline — a brand-new gate with zero findings then passes, and any
    finding shows up as NEW.

    Args:
        path: Path to the baseline file.
    """
    if not path.exists():
        return set()
    findings: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            findings.add(line)
    return findings


def run_checker(command: list[str]) -> set[str]:
    """Run the checker command and collect its stdout findings.

    Fails closed: a missing executable or a non-zero exit (internal checker
    error) raises, so the gate errors out rather than reporting a false clean.
    """
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise SystemExit(f"baseline_gate: checker not found: {exc}") from exc
    if proc.returncode != 0:
        raise SystemExit(
            f"baseline_gate: checker exited {proc.returncode} (tool error — failing "
            f"closed, NOT passing vacuously)\n{proc.stderr.strip()}"
        )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def compare(seen: set[str], baseline: set[str]) -> tuple[set[str], set[str]]:
    """Return ``(new, stale)`` findings relative to the baseline.

    Args:
        seen: Finding keys reported by the checker on this run.
        baseline: Finding keys already accepted in the baseline file.
    """
    return seen - baseline, baseline - seen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--baseline", required=True, type=Path, help="path to the <gate>_baseline.txt file"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the baseline from the current findings (seed / re-seed), then exit 0",
    )
    parser.add_argument(
        "checker",
        nargs=argparse.REMAINDER,
        help="-- followed by the checker command (prints one stable finding key per line)",
    )
    args = parser.parse_args(argv)

    command = args.checker[1:] if args.checker and args.checker[0] == "--" else args.checker
    if not command:
        parser.error("provide the checker command after `--`")

    seen = run_checker(command)

    if args.update:
        args.baseline.write_text("\n".join(sorted(seen)) + ("\n" if seen else ""), encoding="utf-8")
        print(f"baseline_gate: wrote {len(seen)} finding(s) to {args.baseline}")
        return 0

    baseline = load_baseline(args.baseline)
    new, stale = compare(seen, baseline)

    for finding in sorted(new):
        print(f"NEW    {finding}")
    for finding in sorted(stale):
        print(f"STALE  {finding}  (fixed? delete this line from {args.baseline.name})")

    if new or stale:
        print(
            f"\nbaseline_gate: {len(new)} new, {len(stale)} stale "
            f"(baseline holds {len(baseline)}). New findings must be fixed; "
            "stale entries must be deleted so the baseline only shrinks.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
