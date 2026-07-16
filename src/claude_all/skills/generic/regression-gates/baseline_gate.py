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

SCOPE SAFETY — baseline the SAME paths the gate checks
------------------------------------------------------
Baselining a WIDER path than the gate enforces over is SILENT AMNESTY. If you
seed with ``-- checker src/x`` but enforce with ``-- checker src/x/core``, every
finding under ``src/x`` that lives OUTSIDE ``src/x/core`` is grandfathered into
the baseline yet never re-examined by the gate — it is permanent, invisible
forgiveness. This is not hypothetical: a seed over ``src/x`` wrote 618 entries
where the gate only ever checks 281, so **337 findings outside the checked path
became permanent amnesty** and nobody noticed.

To make that a HARD ERROR instead of a silent one, ``--update`` records the exact
checker command (the argv after ``--``) into a header line of the baseline file,
and enforce refuses to run when the current checker command differs from the one
the baseline was seeded with — naming both commands. Seed and enforce MUST use
the same command (as the USAGE below already shows); the guard turns "must" into
"cannot do otherwise". A legacy baseline with no recorded command is tolerated
(the guard simply cannot check it) — re-seed to opt in.

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
import shlex
import subprocess
import sys
from pathlib import Path

__all__ = ["compare", "load_baseline", "load_seed_command", "main", "run_checker"]

#: Header line prefix recording the checker command a baseline was seeded with.
#: It is a ``#`` comment, so :func:`load_baseline` ignores it as an annotation;
#: only :func:`load_seed_command` reads it back for the scope-safety guard.
_SEED_MARKER = "# baseline_gate:seed-command: "


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


def load_seed_command(path: Path) -> list[str] | None:
    """Read the checker command a baseline was seeded with, if recorded.

    ``--update`` writes the seed command into a ``_SEED_MARKER`` header line so
    enforce can detect a scope divergence (seeding a wider path than the gate
    checks — see the SCOPE SAFETY note in the module docstring). Returns the
    parsed argv, or ``None`` for a missing file or a legacy baseline with no
    recorded command (in which case the guard is skipped).

    Args:
        path: Path to the baseline file.
    """
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith(_SEED_MARKER):
            return shlex.split(raw[len(_SEED_MARKER) :])
    return None


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

    # SCOPE SAFETY: enforce over the SAME command the baseline was seeded with.
    # A wider seed path is silent amnesty (see the module docstring). Check before
    # running the checker so a mismatch fails fast and loud.
    if not args.update:
        seed_command = load_seed_command(args.baseline)
        if seed_command is not None and seed_command != command:
            raise SystemExit(
                "baseline_gate: SCOPE MISMATCH — the baseline was seeded with a different "
                "checker command than the one being enforced. Baselining a WIDER path than "
                "the gate checks is SILENT AMNESTY: findings outside the checked path get "
                "grandfathered forever and never re-examined (337 findings once slipped in "
                "this way). Re-seed with --update using the SAME command, or fix the enforce "
                "command so both match.\n"
                f"  seeded with:  {shlex.join(seed_command)}\n"
                f"  enforcing:    {shlex.join(command)}"
            )

    seen = run_checker(command)

    if args.update:
        header = _SEED_MARKER + shlex.join(command) + "\n"
        body = "\n".join(sorted(seen)) + ("\n" if seen else "")
        args.baseline.write_text(header + body, encoding="utf-8")
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
