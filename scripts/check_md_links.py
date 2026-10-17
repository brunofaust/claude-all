#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

Usage:
    python3 scripts/check_md_links.py          human-readable findings on stdout
    python3 scripts/check_md_links.py --json   one JSON object on stdout, nothing else

Exit code is 1 when there is any finding (or, with --json, an internal error), else 0.
The exit code is identical in both modes. Unknown arguments are ignored, as before.

JSON shape (`--json`), printed with indent=2:

    {
      "ok": false,                       # bool: no broken links and no unlinked resources
      "error": null,                     # null, or a string when the gate could not run
      "counts": {
        "markdown_scanned": 12,          # tracked *.md read from disk (not vendored/missing)
        "links_checked": 40,             # relative link targets that resolved to an existing path
        "resources_checked": 9,          # len(discover([])): the resources the README must link
        "vendored_skipped": 3            # tracked *.md files exempt as vendored
      },
      "broken_links": [
        {
          "file": "src/a/b.md",          # file containing the link, repo-relative, posix
          "line": 7,                     # 1-based line number in that file
          "target": "../gone.md",        # raw link target as written
          "resolved": "src/gone.md"      # missing resolved path, relative to repo root
        }
      ],
      "unlinked_resources": [
        {
          "kind": "skill",               # resource kind from discover()
          "name": "my-skill",            # resource name from discover()
          "path": "src/x/my-skill/SKILL.md"  # source file, repo-relative, posix
        }
      ]
    }

Not counted as "scanned": tracked markdown files missing from the working tree.
Not counted as "links_checked": broken links (they appear in `broken_links`), external URLs,
mailto/tel, site-absolute `/` links, and pure `#anchor` links. Vendored files appear only in
`vendored_skipped`.

If the gate cannot run at all under `--json`, stdout is
`{"ok": false, "error": "<ExcType>: <message>"}` and the exit code is 1; a one-line
`check_md_links: <ExcType>: <message>` diagnostic goes to stderr.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
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


@dataclass
class BrokenLink:
    file: Path
    line: int
    target: str
    resolved: Path


@dataclass
class LinkReport:
    scanned: int = 0
    links_checked: int = 0
    vendored_skipped: int = 0
    broken: list[BrokenLink] = field(default_factory=list)


@dataclass
class UnlinkedResource:
    kind: str
    name: str
    src: Path


def display_path(path: Path) -> str:
    """Posix path relative to the repo root; `../` segments when it escapes the repo."""
    return Path(os.path.relpath(path, ROOT)).as_posix()


def check_links(registry: list[dict]) -> LinkReport:
    report = LinkReport()
    for md in tracked_markdown():
        if is_vendored(md, registry):
            report.vendored_skipped += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        report.scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                resolved = (md.parent / bare).resolve()
                if resolved.exists():
                    report.links_checked += 1
                else:
                    report.broken.append(
                        BrokenLink(md.relative_to(ROOT), line_no, target, resolved)
                    )
    return report


def check_readme_coverage() -> tuple[list[UnlinkedResource], int]:
    """Return (unlinked resources, number of resources checked)."""
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = [
        UnlinkedResource(item.kind, item.name, item.src)
        for item in items
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return unlinked, len(items)


def load_registry() -> list[dict]:
    return json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])


def json_report() -> dict:
    links = check_links(load_registry())
    unlinked, resources_checked = check_readme_coverage()
    return {
        "ok": not links.broken and not unlinked,
        "error": None,
        "counts": {
            "markdown_scanned": links.scanned,
            "links_checked": links.links_checked,
            "resources_checked": resources_checked,
            "vendored_skipped": links.vendored_skipped,
        },
        "broken_links": [
            {
                "file": b.file.as_posix(),
                "line": b.line,
                "target": b.target,
                "resolved": display_path(b.resolved),
            }
            for b in links.broken
        ],
        "unlinked_resources": [
            {
                "kind": u.kind,
                "name": u.name,
                "path": u.src.relative_to(ROOT).as_posix(),
            }
            for u in unlinked
        ],
    }


def main() -> int:
    if "--json" in sys.argv[1:]:
        try:
            report = json_report()
        except Exception as exc:  # the gate could not run; report it as JSON
            message = f"{type(exc).__name__}: {exc}"
            print(f"check_md_links: {message}", file=sys.stderr)
            print(json.dumps({"ok": False, "error": message}, indent=2))
            return 1
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    links = check_links(load_registry())
    unlinked, _ = check_readme_coverage()
    findings = [f"{b.file}:{b.line}: broken-link -> {b.target}" for b in links.broken] + [
        f"README.md: undocumented -> {u.kind}/{u.name} "
        f"(add a row linking {u.src.relative_to(ROOT).as_posix()})"
        for u in unlinked
    ]
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
