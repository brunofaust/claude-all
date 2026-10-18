#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

Usage:
    python scripts/check_md_links.py          human-readable report on stdout
    python scripts/check_md_links.py --json   one machine-readable JSON object on stdout

Exit codes (identical in both modes): 0 when there are no findings, 1 when there
are findings or when --json could not run the checks. The --json object shape is
documented in the comment block below this docstring.
"""

# --json output shape. Stdout carries exactly one object, nothing else;
# diagnostics go to stderr.
#
#     {
#       "ok": bool,                      # true iff broken_links and unlinked_resources are empty
#       "error": null | {                # non-null only when the checker itself failed
#         "type": str,                   # exception class name, e.g. "CalledProcessError"
#         "message": str
#       },
#       "counts": null | {               # null when "error" is set
#         "markdown_files_scanned": int, # tracked .md files, not vendored, present on disk
#         "links_checked": int,          # relative, non-anchor link targets in those files
#         "links_resolved": int,         # the subset of links_checked whose path exists
#         "resources_checked": int,      # len(discover([])): every discovered resource
#         "files_skipped_vendored": int  # tracked .md files exempted as vendored
#       },
#       "broken_links": [                # one per unresolved relative link
#         {"file": str,                  # repo-relative path of the containing markdown file
#          "line": int,                  # 1-based line number in that file
#          "target": str,                # raw link target as written
#          "resolved_path": str}         # repo-relative path that does not exist
#       ],
#       "unlinked_resources": [          # one per resource with no README row
#         {"path": str,                  # repo-relative path of the resource's source file
#          "kind": str,
#          "name": str}
#       ]
#     }
#
# A zero-file scan still exits 0; callers detect a vacuous pass via
# counts.markdown_files_scanned == 0.

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# [label](target) — skip images, absolute URLs, anchors and mailto. A leading `/` is
# a site-absolute URL (the SEO skill's llms.txt examples), never a repo path.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")
FENCE = re.compile(r"^\s*(```|~~~)")
# Inline code spans are not links: `def first[T](...)` reads as [T](...).
CODE_SPAN = re.compile(r"`[^`]*`")


def is_vendored(path: Path, registry: list[dict]) -> bool:
    for entry in registry:
        base = ROOT / entry["path"]
        if base not in path.parents:
            continue
        if path.name in entry.get("local_only", []):
            return False
        # vendor_mode "dir" copies the whole tree and lists no individual files.
        if entry.get("vendor_mode") == "dir" or path.name in entry.get("files", []):
            return True
    return False


def strip_code_blocks(text: str) -> list[tuple[int, str]]:
    lines, inside = [], False
    for line_no, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            lines.append((line_no, line))
    return lines


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / p for p in out.split("\0") if p]


def scan_links(registry: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Structured link check: broken-link records plus the counts behind them."""

    def display_path(path: Path) -> str:
        # A link may climb out of the repo (`../../../x.md`); report it as written, not as a crash.
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return path.as_posix()

    broken: list[dict] = []
    counts = {
        "markdown_files_scanned": 0,
        "links_checked": 0,
        "links_resolved": 0,
        "files_skipped_vendored": 0,
    }
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["files_skipped_vendored"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        counts["markdown_files_scanned"] += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                counts["links_checked"] += 1
                named = md.parent / bare
                if named.resolve().exists():
                    counts["links_resolved"] += 1
                else:
                    broken.append(
                        {
                            "file": md.relative_to(ROOT).as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved_path": display_path(Path(os.path.normpath(named))),
                        }
                    )
    return broken, counts


def check_links(registry: list[dict]) -> list[str]:
    broken, _ = scan_links(registry)
    return [
        f"{record['file']}:{record['line']}: broken-link -> {record['target']}" for record in broken
    ]


def scan_readme_coverage() -> tuple[int, list[dict]]:
    """Structured README check: (resources_checked, unlinked-resource records)."""
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    unlinked = []
    for item in resources:
        rel = item.src.relative_to(ROOT).as_posix()
        if f"]({rel})" not in readme:
            unlinked.append({"path": rel, "kind": item.kind, "name": item.name})
    return len(resources), unlinked


def check_readme_coverage() -> list[str]:
    _, unlinked = scan_readme_coverage()
    return [
        f"README.md: undocumented -> {record['kind']}/{record['name']} "
        f"(add a row linking {record['path']})"
        for record in unlinked
    ]


def load_registry() -> list[dict]:
    return json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])


def main_human() -> int:
    registry = load_registry()
    findings = check_links(registry) + check_readme_coverage()
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


def main_json() -> int:
    # Anything a check prints to stdout is diagnostics here: keep stdout to the one object.
    try:
        with contextlib.redirect_stdout(sys.stderr):
            registry = load_registry()
            broken, counts = scan_links(registry)
            resources_checked, unlinked = scan_readme_coverage()
    except Exception as exc:  # the caller must always get parseable JSON
        print(f"check_md_links: {type(exc).__name__}: {exc}", file=sys.stderr)
        report = {
            "ok": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "counts": None,
            "broken_links": [],
            "unlinked_resources": [],
        }
        print(json.dumps(report, indent=2))
        return 1
    counts["resources_checked"] = resources_checked
    ok = not broken and not unlinked
    report = {
        "ok": ok,
        "error": None,
        "counts": counts,
        "broken_links": broken,
        "unlinked_resources": unlinked,
    }
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON object on stdout instead of the report",
    )
    args = parser.parse_args(argv)
    return main_json() if args.json else main_human()


if __name__ == "__main__":
    raise SystemExit(main())
