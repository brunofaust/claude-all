#!/usr/bin/env python3
"""Gate: relative markdown links resolve, and every resource is linked from the README.

Two failures this repo has actually shipped, now mechanical:

1. **Broken relative links.** Four cross-skill links went out one `../` short —
   one of them in an already-merged PR — because nothing checked them. A link is
   only as good as the last rename.
2. **A resource with no README row.** CLAUDE.md says "a PR without a README update
   is incomplete", but prose does not enforce itself. The README tables link to
   each resource's source file, so "is it linked?" is a proxy for "is it documented?"
   that a checker can actually answer.

Vendored files are exempt from check 1: they are kept byte-identical to upstream,
so their upstream-relative links legitimately do not resolve in this tree. Files
listed under a vendored entry's `local_only` are OURS and stay checked.

By default this script prints a human-readable report to stdout and exits 1 on
any finding. With `--json` it instead emits a single machine-readable object (and
nothing else) to stdout, so a caller can aggregate, trend, or detect a vacuous
pass without re-parsing prose. Exit codes are identical in both modes.

`--json` output shape (all paths are repo-relative POSIX paths):

```json
{
  "pass": true,
  "counts": {
    "markdown_files_scanned": 0,
    "links_resolved": 0,
    "resources_checked": 0,
    "files_skipped_vendored": 0
  },
  "broken_links": [
    {"containing_file": "src/a/b.md", "line_no": 42,
     "target": "refs/audit.md", "resolved_path": "src/a/refs/audit.md"}
  ],
  "unlinked_resources": [
    {"path": "src/a/b/SKILL.md", "kind": "skills", "name": "b"}
  ]
}
```

- `pass` — overall gate result (`false` iff there is any broken link or unlinked
  resource).
- `counts.markdown_files_scanned` — non-vendored tracked `.md` files that existed
  on disk and were actually inspected.
- `counts.links_resolved` — relative link targets that survived filtering
  (images / absolute URLs / anchors / mailto / code spans skipped) and resolved
  to an existing path.
- `counts.resources_checked` — resources `discover()` returned that were matched
  against the README.
- `counts.files_skipped_vendored` — tracked `.md` files exempted as upstream-owned.
- `broken_links` — one entry per relative link that did not resolve:
  `containing_file` (the markdown file holding the link), `line_no`, `target` (the
  raw link text), `resolved_path` (the resolved path that did not exist).
- `unlinked_resources` — one entry per discovered resource with no README row
  linking its source file: `path` (the source file), `kind` and `name` for
  disambiguation.
"""

import argparse
import json
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
    """Upstream-owned files are exempt: kept byte-identical, so their own relative
    links point at an upstream tree we deliberately did not copy. `local_only`
    files live in the same directory but are OURS — they stay checked.

    Args:
        path: The markdown file being considered.
        registry: The `vendored` entries from `vendored.json`.
    """
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
    """Numbered lines with fenced code removed — a regex or an llms.txt sample
    inside a fenced block only looks like a link.

    Args:
        text: Full markdown source of one file.
    """
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


def _repo_relative(path: Path) -> str:
    """POSIX path relative to the repo root, falling back to the absolute path.

    Almost every candidate (a markdown file, a resolved link target) lives under
    ROOT, but a link with `../../` segments can resolve to a path that escapes it
    — the JSON contract wants repo-relative POSIX names, so fall back to the raw
    absolute path rather than crash on `relative_to`.

    Args:
        path: Any filesystem path.
    """
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def check_links(registry: list[dict]) -> dict:
    """Inspect every non-vendored tracked markdown file's relative links.

    Args:
        registry: The `vendored` entries from `vendored.json`.

    Returns:
        ``{"broken_links": [dict], "markdown_files_scanned": int,
        "links_resolved": int, "files_skipped_vendored": int}``. Each broken link
        is ``{"containing_file", "line_no", "target", "resolved_path"}``.
    """
    broken: list[dict] = []
    scanned = 0
    links_resolved = 0
    skipped_vendored = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            skipped_vendored += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                if (md.parent / bare).resolve().exists():
                    links_resolved += 1
                else:
                    broken.append(
                        {
                            "containing_file": md.relative_to(ROOT).as_posix(),
                            "line_no": line_no,
                            "target": target,
                            "resolved_path": _repo_relative(
                                (md.parent / bare).resolve()
                            ),
                        }
                    )
    return {
        "broken_links": broken,
        "markdown_files_scanned": scanned,
        "links_resolved": links_resolved,
        "files_skipped_vendored": skipped_vendored,
    }


def check_readme_coverage() -> dict:
    """Match every discovered resource's source file against the README tables.

    Returns:
        ``{"unlinked_resources": [dict], "resources_checked": int}``. Each
        unlinked resource is ``{"path", "kind", "name"}``.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = [
        {
            "path": item.src.relative_to(ROOT).as_posix(),
            "kind": item.kind,
            "name": item.name,
        }
        for item in items
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return {"unlinked_resources": unlinked, "resources_checked": len(items)}


def format_human(broken: list[dict], unlinked: list[dict]) -> list[str]:
    """Render the structured results as the gate's human-readable findings."""
    lines = [
        f"{item['containing_file']}:{item['line_no']}: "
        f"broken-link -> {item['target']}"
        for item in broken
    ]
    lines += [
        f"README.md: undocumented -> {item['kind']}/{item['name']} "
        f"(add a row linking {item['path']})"
        for item in unlinked
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate: relative markdown links resolve, and every resource is "
        "linked from the README.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a single machine-readable JSON object to stdout instead of the "
        "human-readable report",
    )
    args = parser.parse_args(argv)

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    links = check_links(registry)
    coverage = check_readme_coverage()
    broken = links["broken_links"]
    unlinked = coverage["unlinked_resources"]

    report = {
        "pass": not broken and not unlinked,
        "counts": {
            "markdown_files_scanned": links["markdown_files_scanned"],
            "links_resolved": links["links_resolved"],
            "resources_checked": coverage["resources_checked"],
            "files_skipped_vendored": links["files_skipped_vendored"],
        },
        "broken_links": broken,
        "unlinked_resources": unlinked,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        if not report["pass"]:
            print(f"\n{len(broken) + len(unlinked)} finding(s).", file=sys.stderr)
        return 0 if report["pass"] else 1

    findings = format_human(broken, unlinked)
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())