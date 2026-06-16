#!/usr/bin/env python3
"""Checker: ban `os.environ.setdefault(...)` of CI-reserved env vars in test bootstrap.

WHY
---
`os.environ.setdefault("X", "...")` is a no-op when X is already set. CI runners
pre-set a reserved namespace (``CI``, ``GITHUB_*``, ``RUNNER_*``, ``GITLAB_*``,
``CIRCLE*``, ``BUILDKITE*``, …). So a test bootstrap that does

    os.environ.setdefault("GITHUB_API_URL", "http://localhost:9999")  # "mock"

silently LOSES to the runner's real value in CI: locally your tests hit the
fake, in CI they hit the real service. The mock evaporates exactly where it
matters most. Use an unconditional assignment (or a fixture/monkeypatch) instead
of `setdefault` for anything a CI provider might own.

The reserved-namespace principle generalises to ANY CI provider — extend
``RESERVED_PREFIXES`` / ``RESERVED_NAMES`` for yours.

CONTRACT
--------
Prints one ``path:line: message`` finding per match to stdout; exits 0 on success
(even with findings) so it composes with ``baseline_gate.py``. Fails open on a
file it cannot parse (a sibling syntax/lint gate owns that). Defaults to scanning
``test``-named files under the given roots.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

__all__ = ["find_violations", "main"]

# A CI-set value wins over setdefault; these namespaces are owned by the runner.
RESERVED_PREFIXES: tuple[str, ...] = (
    "GITHUB_",
    "RUNNER_",
    "GITLAB_",
    "CIRCLE",
    "BUILDKITE",
    "TRAVIS",
    "JENKINS_",
    "TEAMCITY",
    "BITBUCKET_",
    "DRONE_",
)
RESERVED_NAMES: frozenset[str] = frozenset({"CI", "CONTINUOUS_INTEGRATION", "BUILD_NUMBER"})


def is_reserved(name: str) -> bool:
    return name in RESERVED_NAMES or name.startswith(RESERVED_PREFIXES)


def setdefault_key(call: ast.Call) -> str | None:
    """Return the literal env-var name if `call` is `os.environ.setdefault("X", ...)`."""
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "setdefault"):
        return None
    target = func.value
    is_environ = (isinstance(target, ast.Attribute) and target.attr == "environ") or (
        isinstance(target, ast.Name) and target.id == "environ"
    )
    if not is_environ or not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def find_violations(path: Path) -> list[str]:
    """Return ``path:line: message`` findings for one file. Fails open on parse error."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return []  # a sibling syntax gate owns unparseable files
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            key = setdefault_key(node)
            if key is not None and is_reserved(key):
                findings.append(
                    f"{path}:{node.lineno}: os.environ.setdefault of CI-reserved var "
                    f"{key!r} (setdefault loses to the runner's value — assign unconditionally)"
                )
    return findings


def iter_test_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "test" in p.name)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ban setdefault of CI-reserved env vars in tests.")
    parser.add_argument(
        "roots", nargs="+", type=Path, help="files or dirs to scan (dirs → test*.py)"
    )
    args = parser.parse_args(argv)
    for file in iter_test_files(args.roots):
        for finding in find_violations(file):
            print(finding)
    return 0


if __name__ == "__main__":
    sys.exit(main())
