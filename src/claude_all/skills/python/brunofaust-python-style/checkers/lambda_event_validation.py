#!/usr/bin/env python3
"""Checker: every Lambda handler validates its raw ``event`` through a Pydantic model.

WHY
---
A Lambda ``event`` is the most untrusted dict in the codebase: it arrives from SQS,
SNS, EventBridge, Step Functions, or a direct invoke, and nothing in the runtime
checks it. Reading ``event["org_id"]`` straight off that dict means a renamed
producer field surfaces as a ``KeyError`` three frames deep — or worse, an
``event.get("org_id")`` returns ``None`` and the None flows on. The
brunofaust-python-style rule is that the event is parsed into a model AT THE
BOUNDARY, before any logic, so a malformed payload fails loudly at the one place
that knows what the payload should be.

TWO SANCTIONED SHAPES — both are validation, and shape 2 is usually the better one
for an AWS-owned envelope::

    1.  parsed = MyEvent.model_validate(event)
    2.  parsed = MyEvent(org_id=event.get("org_id"), run_id=event.get("run_id"))

Shape 1 is right when the payload IS our shape — an SQS body we produced ourselves
and control end to end. But handing AWS's raw envelope to ``model_validate`` forces
the model to ``extra="ignore"``, because AWS puts fields in there that we neither
own nor read (an EventBridge envelope carries a pile of them), and ``extra="ignore"``
is exactly the setting that stops a typo in one of OUR fields from failing. Shape 2
extracts only the fields we declare, which lets the model stay ``extra="forbid"``:
AWS may add envelope fields freely, while a typo in one of ours fails loud. Both
shapes are accepted here on purpose — a gate that permits every correct shape and
explains the trade-off gets adopted; a one-true-way gate gets ``SKIP=``'d.

POSITIVELY-VERIFIED ALLOWLIST — the important idea in this checker
Some handlers validate through an indirection this AST check cannot see: an ASGI
proxy (``handler = Mangum(app)``, where FastAPI/Pydantic validate per-route), or a
shared factory (``handler = make_lambda_entry(...)``, which validates inside its own
dispatch). ``--allow DIR=CALLABLE`` exempts such a handler dir — but the exemption
NEVER just ``continue``s. It asserts its own stated reason still holds: if the module
does not actually call ``CALLABLE(...)``, that is a finding of a DISTINCT class
(``stale-allowlist``). So the day someone refactors the exempt module away from its
factory, the gate re-arms itself automatically instead of leaving a permanent hole
that outlives the reason it was punched. An allowlist entry is a claim, and this
checker makes the claim carry its own proof.

  missing-validation  A handler module with an entry point but no Pydantic model
                      built at the boundary — neither `Model.model_validate(event)`
                      nor `Model(field=event.get(...))`.
  stale-allowlist     A `--allow DIR=CALLABLE` exemption whose module no longer
                      calls `CALLABLE(...)`, so the reason for the hole is gone.

CONTRACT
--------
Prints one ``path: [rule] symbol — message`` finding per violation to stdout and
**exits 1 when there is any finding**, so wiring it straight into prek/pre-commit
surfaces the findings and fails the commit — no baseline artifact required.

Keys are rule + handler directory name and NEVER a line number, so an unrelated edit
does not churn a baseline. At most one finding of each rule can arise per module, so
no ordinal discriminator is needed.

The checker owns NO state: it writes no baseline, no JSON, no cache. If you want the
regression-only ratchet, compose it with ``regression-gates/baseline_gate.py`` and
pass ``--exit-zero`` — that harness reads a non-zero exit as "the checker crashed"
and fails closed, so the flag is required there and nowhere else.

USAGE
-----
    # direct gate — prints findings, exits 1 (this is the prek/pre-commit wiring)
    python checkers/lambda_event_validation.py src/myapp/lambdas/
    python checkers/lambda_event_validation.py --handler-glob 'lambdas/*/app.py' src/

    # positively-verified exemptions (repeatable)
    python checkers/lambda_event_validation.py \\
        --allow api=Mangum --allow notifier=make_lambda_entry src/myapp/lambdas/

    # regression-only ratchet — the baseline lives in baseline_gate.py, not here
    baseline_gate.py --baseline lambda_event_baseline.txt -- \\
        python checkers/lambda_event_validation.py --exit-zero src/

PARSER NOTE — pin this hook's interpreter
-----------------------------------------
This checker parses with the ``ast`` of the interpreter it RUNS ON, so an interpreter
older than the project's silently fails to parse new syntax (PEP 695 ``type X = int``,
``async def run[**P, T]``, PEP 758 ``except A, B:``). Any Python-AST-based gate shares
this: unpinned, bandit's env resolved to 3.12 and logged "syntax error while parsing
AST" for 25 files, SKIPPED them, and **still exited success** — a security gate
silently not scanning.

So this checker does NOT fail open. An unparsable file exits **2** (a tool error,
distinct from 1 = findings) even under ``--exit-zero``, because a file it could not
read is a file it did not check — and here that file is a Lambda boundary.

Pin ``language_version`` on THIS hook — a repo-level ``default_language_version`` does
NOT reach a hook's isolated env. Gates with their own non-Python parser (ruff,
tree-sitter-based tools) are immune and need no pin.
"""

# NOTE: this import looks like it violates the very standard this file enforces —
# the skill's baseline is 3.14, where PEP 649 makes annotations lazy and the import
# is dead weight. It stays because this is TOOLING, not an example: it lives in the
# claude-all repo, which is deliberately `requires-python = ">=3.11"` so the
# installer runs anywhere. Delete it only if claude-all's own floor moves to 3.14.
from __future__ import annotations

import argparse
import ast
import sys
from fnmatch import fnmatch
from pathlib import Path

__all__ = ["RULES", "Finding", "check_tree", "find_violations", "iter_handler_files", "main"]

RULES: tuple[str, ...] = (
    "missing-validation",
    "stale-allowlist",
)

#: Names AWS Lambda is configured to invoke. A module binding one of these — by
#: `def`, `async def`, or a module-level assignment (`handler = Mangum(app)`) — is a
#: Lambda boundary and owes the event a model.
ENTRY_POINTS = frozenset({"handler", "lambda_handler"})

#: Base classes that make a locally declared class a validated model, so that
#: CONSTRUCTING one (shape 2) counts as validation at the boundary.
MODEL_BASES = frozenset({"BaseModel", "RootModel"})

#: The method name of shape 1. Matched as an attribute call so `MyEvent.model_validate`
#: and `_MODEL.model_validate` both count.
VALIDATE_METHOD = "model_validate"

DEFAULT_HANDLER_GLOB = "**/handler.py"


class Finding(str):
    """A finding key. Subclasses ``str`` so callers can just print it."""

    __slots__ = ()


def _name_of(node: ast.expr | None) -> str:
    """Resolve the trailing bare name out of *node*.

    Args:
        node: The expression to name, or ``None``.

    Returns:
        The trailing name (``pydantic.BaseModel`` -> ``BaseModel``), or ``""`` when
        *node* carries none.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def calls_named(tree: ast.AST, name: str) -> bool:
    """Return whether any call in *tree* invokes something named *name*.

    Matches both a bare call (``name(...)``) and an attribute call (``obj.name(...)``),
    which covers a direct factory call and a ``Model.model_validate(...)`` method call
    with the same predicate.

    Args:
        tree: The parsed module (or any subtree).
        name: The function/method name to search for.

    Returns:
        True if a matching call is found anywhere in *tree*.
    """
    return any(
        isinstance(node, ast.Call) and _name_of(node.func) == name for node in ast.walk(tree)
    )


def declared_model_names(tree: ast.AST) -> set[str]:
    """Return the names of pydantic models DECLARED in *tree*.

    Only locally declared models count: shape 2 is "build the model this module
    declares out of the raw envelope", and a class defined here is one whose field
    contract this module owns.

    Args:
        tree: The parsed module.

    Returns:
        The class names subclassing a base in :data:`MODEL_BASES`.
    """
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and any(_name_of(b) in MODEL_BASES for b in node.bases)
    }


def constructs_local_model(tree: ast.AST) -> bool:
    """Return whether the module CONSTRUCTS a pydantic model it declares.

    This is sanctioned boundary shape 2 — ``MyEvent(org_id=event.get("org_id"), ...)``
    — and the preferred shape for an AWS-owned envelope, because extracting only our
    own fields lets the model stay ``extra="forbid"`` instead of the ``extra="ignore"``
    that handing AWS's raw dict to ``model_validate`` forces. See the WHY section.

    Args:
        tree: The parsed module.

    Returns:
        True when a class this module declares as a model is also called in it.
    """
    names = declared_model_names(tree)
    if not names:
        return False
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names
        for node in ast.walk(tree)
    )


def has_entry_point(tree: ast.AST) -> bool:
    """Return whether the module binds a Lambda entry-point name.

    Counts a ``def``/``async def`` named in :data:`ENTRY_POINTS` at any depth, and a
    module-level assignment to one of those names — the latter is how a proxy or a
    shared factory exposes a handler (``handler = Mangum(app)``), and a def-only check
    would call those modules "not a handler" and skip them.

    Args:
        tree: The parsed module.

    Returns:
        True when an entry-point name is bound.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in ENTRY_POINTS:
            return True
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id in ENTRY_POINTS for t in targets):
            return True
    return False


def check_tree(
    tree: ast.AST,
    path: str,
    select: frozenset[str],
    allow: dict[str, str],
) -> list[Finding]:
    """Collect every violation in an already-parsed handler module.

    Args:
        tree: The parsed module.
        path: Path string used to key findings.
        select: The rule names to report.
        allow: Mapping of handler directory name -> the callable whose presence
            justifies the exemption.

    Returns:
        One finding per violation.
    """
    symbol = Path(path).parent.name or Path(path).stem
    findings: list[Finding] = []

    def add(rule: str, message: str) -> None:
        """Record a finding under a stable, line-independent key.

        Args:
            rule: The rule name; ignored when not in *select*.
            message: The human-facing explanation.
        """
        if rule in select:
            findings.append(Finding(f"{path}: [{rule}] {symbol} — {message}"))

    if symbol in allow:
        callable_name = allow[symbol]
        # A positively-verified exemption: never a bare `continue`. The allowlist entry
        # states WHY the boundary is safe, and that reason is re-proved on every run.
        if not calls_named(tree, callable_name):
            add(
                "stale-allowlist",
                f"allowlisted because it calls {callable_name}(...), but no "
                f"{callable_name}(...) call found — allowlist stale? Either restore the "
                "validation indirection, or drop the --allow entry so this module must "
                "parse its own event into a model",
            )
        return findings

    if not has_entry_point(tree):
        return findings

    if not (calls_named(tree, VALIDATE_METHOD) or constructs_local_model(tree)):
        add(
            "missing-validation",
            "Lambda entry point does not parse `event` into a Pydantic model — the event "
            "is the most untrusted dict in the process and must be validated at the "
            "boundary, before any logic, via `Model.model_validate(event)` (when the "
            "payload IS our shape) or `Model(field=event.get(...), ...)` (preferred for "
            'an AWS envelope: it keeps the model extra="forbid"). If it validates through '
            "an indirection, exempt it with --allow "
            f"{symbol}=<callable> so the reason stays verified",
        )
    return findings


def find_violations(
    path: Path,
    select: frozenset[str],
    allow: dict[str, str],
) -> list[Finding]:
    """Parse *path* and return its findings.

    Args:
        path: The handler module to scan.
        select: The rule names to report.
        allow: Mapping of handler directory name -> justifying callable.

    Returns:
        One finding per violation.

    Raises:
        SyntaxError: When the RUNNING interpreter cannot parse *path*. This is
            deliberately NOT swallowed — see the PARSER NOTE in the module docstring.
            A file the checker could not read is a file it did not check; returning
            ``[]`` would report a Lambda boundary clean.
        ValueError: On a null byte or similar unreadable source.
        UnicodeDecodeError: When the file is not valid UTF-8.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return check_tree(tree, path.as_posix(), select, allow)


def iter_handler_files(roots: list[Path], glob: str) -> list[Path]:
    """Return every handler module under *roots* matching *glob*.

    A directory root is expanded with *glob*. A FILE root is matched against the
    glob's last component only: naming a file explicitly (as prek does when it passes
    staged paths) means the caller meant that file, while a path-shaped pattern would
    depend on the caller's cwd.

    Args:
        roots: Files or directories to scan.
        glob: Handler pattern, e.g. ``**/handler.py`` or ``lambdas/*/app.py``.

    Returns:
        Matching files, deduplicated and sorted.
    """
    basename = glob.rsplit("/", 1)[-1]
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            if fnmatch(root.name, basename):
                files.add(root)
        elif root.is_dir():
            files.update(p for p in root.glob(glob) if p.is_file())
    return sorted(files)


def parse_allow(entries: list[str] | None) -> dict[str, str]:
    """Parse repeated ``--allow DIR=CALLABLE`` options into a mapping.

    Args:
        entries: The raw ``DIR=CALLABLE`` strings, or ``None``.

    Returns:
        Mapping of handler directory name -> the callable whose presence justifies
        the exemption.

    Raises:
        ValueError: When an entry is not of the form ``DIR=CALLABLE``.
    """
    allow: dict[str, str] = {}
    for entry in entries or []:
        name, sep, callable_name = entry.partition("=")
        if not sep or not name.strip() or not callable_name.strip():
            raise ValueError(f"--allow must be DIR=CALLABLE, got: {entry!r}")
        allow[name.strip()] = callable_name.strip()
    return allow


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        0 when clean, 1 when there are findings (unless ``--exit-zero``), 2 when a
        file could not be parsed.
    """
    parser = argparse.ArgumentParser(
        description="Enforce Pydantic validation of the Lambda event at the boundary.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("roots", nargs="+", type=Path, help="files or dirs to scan")
    parser.add_argument(
        "--handler-glob",
        default=DEFAULT_HANDLER_GLOB,
        help=f"pattern identifying Lambda handler modules (default: {DEFAULT_HANDLER_GLOB})",
    )
    parser.add_argument(
        "--allow",
        action="append",
        metavar="DIR=CALLABLE",
        help="exempt handler dir DIR because its module calls CALLABLE(...) — the reason "
        "is re-verified every run, and a module that stops calling CALLABLE reports "
        "stale-allowlist instead of passing (repeatable)",
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
        "itself crashed' and fails closed. An unparsable file still exits 2.",
    )
    args = parser.parse_args(argv)

    select = frozenset(r.strip() for r in args.select.split(",") if r.strip())
    if unknown := select - set(RULES):
        parser.error(f"unknown rule(s): {', '.join(sorted(unknown))}")
    try:
        allow = parse_allow(args.allow)
    except ValueError as exc:
        parser.error(str(exc))

    count = 0
    unparsable: list[str] = []
    for file in iter_handler_files(args.roots, args.handler_glob):
        try:
            findings = find_violations(file, select, allow)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            unparsable.append(f"{file}: {exc}")
            continue
        for finding in findings:
            print(finding)
            count += 1

    # Fail CLOSED on an unparsable file, and do it even under --exit-zero: this is a
    # TOOL error, not a finding, and baseline_gate.py must see it as one.
    if unparsable:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(
            f"\nERROR: {len(unparsable)} file(s) could not be parsed by the running "
            f"interpreter (python {version}). A file this checker could not read is a "
            "file it did NOT check — skipping it silently would report a Lambda "
            "boundary clean.\n"
            "If the syntax is valid on the project's Python, this hook's interpreter is "
            "too old: pin `language_version` on THIS hook. A repo-level "
            "`default_language_version` does NOT reach a hook's isolated env.",
            file=sys.stderr,
        )
        for item in unparsable:
            print(f"  {item}", file=sys.stderr)
        return 2

    if count and not args.exit_zero:
        print(
            f"\n{count} finding(s) — a Lambda event must be a model before it is logic.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
