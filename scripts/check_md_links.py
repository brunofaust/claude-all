#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check; their `local_only` sidecars stay checked.
Exit 1 on any finding, in both modes. `--json` prints one object on stdout:
{passed, counts: {files_scanned, files_skipped_vendored, files_skipped_missing,
links_checked, links_resolved, resources_checked}, broken_links: [{file, line,
target, resolved}], unlinked_resources: [{kind, name, path}]}
"""

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


def repo_relative(path: Path) -> str:
    """Normalised repo-relative POSIX path; `../` segments when the link escapes ROOT."""
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def scan_links(registry: list[dict]) -> dict:
    counts = {
        "files_scanned": 0,
        "files_skipped_vendored": 0,
        "files_skipped_missing": 0,
        "links_checked": 0,
        "links_resolved": 0,
    }
    broken_links: list[dict] = []
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["files_skipped_vendored"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            counts["files_skipped_missing"] += 1
            continue
        counts["files_scanned"] += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                counts["links_checked"] += 1
                if (md.parent / bare).resolve().exists():
                    counts["links_resolved"] += 1
                else:
                    broken_links.append(
                        {
                            "file": md.relative_to(ROOT).as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved": repo_relative(md.parent / bare),
                        }
                    )
    return {"counts": counts, "broken_links": broken_links}


def check_links(registry: list[dict]) -> list[str]:
    return [
        f"{finding['file']}:{finding['line']}: broken-link -> {finding['target']}"
        for finding in scan_links(registry)["broken_links"]
    ]


def scan_readme_coverage() -> tuple[int, list[dict]]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = [
        {"kind": item.kind, "name": item.name, "path": item.src.relative_to(ROOT).as_posix()}
        for item in items
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return len(items), unlinked


def check_readme_coverage() -> list[str]:
    _, unlinked = scan_readme_coverage()
    return [
        f"README.md: undocumented -> {resource['kind']}/{resource['name']} "
        f"(add a row linking {resource['path']})"
        for resource in unlinked
    ]


def load_registry() -> list[dict]:
    return json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])


def main_json() -> int:
    try:
        links = scan_links(load_registry())
        resources_checked, unlinked = scan_readme_coverage()
    except Exception as exc:
        print(json.dumps({"passed": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    counts = {**links["counts"], "resources_checked": resources_checked}
    passed = not links["broken_links"] and not unlinked
    report = {
        "passed": passed,
        "counts": counts,
        "broken_links": links["broken_links"],
        "unlinked_resources": unlinked,
    }
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


def main() -> int:
    if "--json" in sys.argv[1:]:
        return main_json()
    findings = check_links(load_registry()) + check_readme_coverage()
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
