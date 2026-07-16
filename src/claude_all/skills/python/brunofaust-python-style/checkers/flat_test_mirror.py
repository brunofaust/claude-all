#!/usr/bin/env python3
"""Checker: enforce the FLAT source-mirrored unit-test convention.

WHY
---
``tests/unit/`` is ONE flat folder holding one file per source module, named
``test_<source path with '/' -> '_'>.py``::

    src/myapp/core/aws/s3.py                    -> tests/unit/test_core_aws_s3.py
    src/myapp/features/pii_detection/service.py -> tests/unit/test_features_pii_detection_service.py

"Mirror ``src/``" is ambiguous prose — a NESTED tree
(``tests/unit/features/pii_detection/test_service.py``) and a flat one both claim
to comply, so both appear, and the mirror stops being a lookup you can do in your
head. Flat makes the mapping total and mechanical: given a source path there is
exactly ONE legal test path, and given a test file there is exactly one source
module. That is what makes "does this module have tests?" answerable by a glob
instead of a walk.

Three rules, scanned over the whole ``tests/unit/`` tree:

  not-flat        A subdirectory under the unit tier — a topical folder or a
                  stray package dir. It re-introduces the two-spellings problem
                  and hides a mirror where no glob will find it.
  non-test-file   A non-mirror module parked in the unit tier (``helpers.py``,
                  ``factories.py``). Shared test code belongs in ``conftest.py``
                  or a real package — a file here that is not a mirror breaks the
                  one-file-per-module bijection. ``conftest.py`` / ``__init__.py``
                  are the only exemptions.
  grab-bag        A ``*_extra`` / ``*_edges`` / ``*_coverage[N]`` / ``*_boost[N]``
                  / ``*_remaining`` / ``*_near_threshold`` file parallel to a real
                  mirror. This is the file a coverage-chasing agent writes when
                  it would rather append a new module than read the existing one:
                  the module's tests end up split across files nobody knows to
                  open, and the second copy drifts. Add the tests to the module's
                  mirror instead.

CONTRACT
--------
Prints one ``path: [rule] message`` finding per line to stdout and **exits 1 when
there is any finding**, so wiring it straight into prek/pre-commit surfaces the
findings and fails the commit — no baseline artifact required.

Keys are the offending path plus the rule and NEVER a line number. This checker
is filesystem-based — it inspects names and directory shape, never file contents
— so its keys are naturally path-based and an unrelated edit cannot churn them.

The checker owns NO state: it writes no baseline, no JSON, no cache. If you want
the regression-only ratchet, compose it with ``regression-gates/baseline_gate.py``
and pass ``--exit-zero`` — that harness reads a non-zero exit as "the checker
crashed" and fails closed, so the flag is required there and nowhere else.

Because it never parses Python source, it has no interpreter blind spot and needs
no ``language_version`` pin: an AST-based gate silently fails to parse new syntax
on an old interpreter, but a checker that only reads directory entries cannot.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/flat_test_mirror.py
    python checkers/flat_test_mirror.py --root tests/unit
    python checkers/flat_test_mirror.py --select grab-bag

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline flat_mirror_baseline.txt -- \\
        python checkers/flat_test_mirror.py --exit-zero

Wire it with ``pass_filenames: false`` — it walks the tree itself rather than
taking the staged-file list, so a rename that leaves a nested file behind is still
caught on the commit that did not touch it.
"""

# NOTE: this import looks like it violates the very standard this file enforces —
# the skill's baseline is 3.14, where PEP 649 makes annotations lazy and the import
# is dead weight. It stays because this is TOOLING, not an example: it lives in the
# claude-all repo, which is deliberately `requires-python = ">=3.11"` so the
# installer runs anywhere. Delete it only if claude-all's own floor moves to 3.14.
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

__all__ = ["ALLOWED_NON_TEST", "GRAB_BAG", "RULES", "Finding", "find_violations", "main"]

RULES: tuple[str, ...] = (
    "not-flat",
    "non-test-file",
    "grab-bag",
)

#: The only non-mirror filenames that may live in the unit tier. `conftest.py` is
#: pytest's own shared-fixture seam; `__init__.py` makes the tier importable.
ALLOWED_NON_TEST: frozenset[str] = frozenset({"__init__.py", "conftest.py"})

#: Suffixes that mark a parallel "somewhere else to put it" file. Deliberately
#: matched on the STEM's tail so `test_core_aws_s3_extra.py` fires while a module
#: legitimately named `test_features_extras_service.py` (mirroring
#: `features/extras/service.py`) does not.
GRAB_BAG: re.Pattern[str] = re.compile(
    r"_(extra|edges|coverage\d*|boost\d*|remaining|near_threshold)\.py$"
)

#: Directory names that are build/tool output, not authored test layout.
IGNORED_DIRS: frozenset[str] = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache"})


class Finding(str):
    """A finding key. Subclasses ``str`` so callers can just print it."""

    __slots__ = ()


def _relative_hint(path: Path, root: Path) -> str:
    """Return the flat path *path* should have been written to.

    Args:
        path: The offending nested test file.
        root: The unit-test root it lives under.

    Returns:
        The POSIX path of the flat location, e.g. ``tests/unit/test_service.py``.
    """
    return (root / path.name).as_posix()


def find_violations(root: Path, select: frozenset[str]) -> list[Finding]:
    """Collect every flat-mirror violation under *root*.

    A missing *root* is not a violation — a project with no unit tier has nothing
    to keep flat, and failing there would make the gate unusable in a fresh repo.

    Args:
        root: The unit-test directory to scan (typically ``tests/unit``).
        select: The rule names to report; others are skipped.

    Returns:
        One finding per violation, in path order.
    """
    if not root.is_dir():
        return []

    findings: list[Finding] = []
    for path in sorted(root.rglob("*.py")):
        if IGNORED_DIRS & set(path.parts):
            continue
        rel = path.relative_to(root)
        key = path.as_posix()

        if len(rel.parts) > 1:
            if "not-flat" in select:
                findings.append(
                    Finding(
                        f"{key}: [not-flat] nested under {root.as_posix()}/ — the unit tier is "
                        f"ONE flat folder. Move it to {_relative_hint(path, root)} (name it "
                        "test_<source path with '/' -> '_'>.py) or merge it into the matching "
                        "mirror."
                    )
                )
            continue

        name = path.name
        if name in ALLOWED_NON_TEST:
            continue

        if not name.startswith("test_"):
            if "non-test-file" in select:
                findings.append(
                    Finding(
                        f"{key}: [non-test-file] not a mirror — only test_<module>.py files "
                        "belong in the unit tier (plus conftest.py / __init__.py). Put shared "
                        "helpers in conftest.py or a real package."
                    )
                )
            continue

        if GRAB_BAG.search(name) and "grab-bag" in select:
            findings.append(
                Finding(
                    f"{key}: [grab-bag] parallel catch-all file — add these tests to the "
                    "module's mirror, not a *_extra/*_edges/*_coverage file. One module, one "
                    "test file; a second file splits the module's tests where nobody looks."
                )
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        0 when clean (or under ``--exit-zero``), 1 when there is any finding.
    """
    parser = argparse.ArgumentParser(
        description="Enforce the flat source-mirrored unit-test convention.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("tests/unit"),
        help="unit-test directory to scan (default: tests/unit)",
    )
    parser.add_argument(
        "--select",
        default=",".join(RULES),
        help=f"comma-separated rules to enforce (default: all). Available: {', '.join(RULES)}",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="print findings but always exit 0 — ONLY for composing behind "
        "baseline_gate.py, whose contract reads a non-zero exit as 'the checker "
        "itself crashed' and fails closed",
    )
    args = parser.parse_args(argv)

    select = frozenset(r.strip() for r in args.select.split(",") if r.strip())
    if unknown := select - set(RULES):
        parser.error(f"unknown rule(s): {', '.join(sorted(unknown))}")

    findings = find_violations(args.root, select)
    for finding in findings:
        print(finding)

    if findings and not args.exit_zero:
        print(
            f"\n{len(findings)} finding(s) — the unit tier is ONE flat folder, one file per "
            "source module, named test_<source path with '/' -> '_'>.py.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
