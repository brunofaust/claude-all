#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json flag, emits a machine-readable JSON object to stdout instead of the
human-formatted report. The JSON shape is:
{
  "pass": bool,                    # True if no findings, False otherwise
  "markdown_files_scanned": int,   # Number of .md files scanned for links
  "links_resolved": int,           # Number of relative links resolved
  "files_skipped_as_vendored": int,# Number of .md files skipped due to vendored exemption
  "resources_checked": int,        # Number of resources discovered for README coverage
  "broken_links": [                # Each broken relative link
    {
      "file": str,                 # Path relative to repo root
      "line": int,                 # Line number (1-indexed)
      "target": str,               # Raw link target from markdown
      "resolved": str              # Resolved path that did not exist
    }
  ],
  "unlinked_resources": [          # Each resource not linked from README
    {
      "kind": str,                 # e.g., "skill", "agent"
      "name": str,                 # Resource name
      "path": str                  # Path relative to repo root
    }
  ]
}
Diagnostics, if any, go to stderr. Without --json, output and exit codes are unchanged.
"""

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


def check_links(registry: list[dict], metrics: dict | None = None) -> list[str]:
    findings = []
    for md in tracked_markdown():
        if metrics is not None:
            metrics["markdown_files_scanned"] = metrics.get("markdown_files_scanned", 0) + 1
        if is_vendored(md, registry):
            if metrics is not None:
                metrics["files_skipped_as_vendored"] = (
                    metrics.get("files_skipped_as_vendored", 0) + 1
                )
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                if metrics is not None:
                    metrics["links_resolved"] = metrics.get("links_resolved", 0) + 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
    return findings


def check_readme_coverage(metrics: dict | None = None) -> list[str]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = list(discover([]))
    if metrics is not None:
        metrics["resources_checked"] = len(items)
    findings = [
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in items
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return findings


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check markdown links and README coverage")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable report",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    metrics: dict = {}
    findings = check_links(registry, metrics) + check_readme_coverage(metrics)

    if args.json:
        # Build broken links list from findings
        broken_links = []
        unlinked_resources = []

        for finding in findings:
            if finding.startswith("README.md: undocumented ->"):
                # Parse: "README.md: undocumented -> kind/name (add a row linking path)"
                try:
                    rest = finding[len("README.md: undocumented -> ") :]
                    kind_name_part, path_part = rest.split(" (add a row linking ", 1)
                    path = path_part.rstrip(")")
                    if "/" in kind_name_part:
                        kind, name = kind_name_part.split("/", 1)
                        unlinked_resources.append({"kind": kind, "name": name, "path": path})
                except Exception:
                    pass
            else:
                # Parse: "file:line_no: broken-link -> target"
                try:
                    location_part, rest = finding.split(": ", 1)
                    if ":" in location_part:
                        file_part, line_str = location_part.rsplit(":", 1)
                        line_num = int(line_str)
                        if " -> " in rest:
                            _, target = rest.split(" -> ", 1)
                            # Compute resolved path: (file_parent / target).resolve()
                            file_path = Path(file_part)
                            resolved_path = (file_path.parent / target).resolve()
                            # Make it relative to ROOT for consistency
                            try:
                                resolved_relative = resolved_path.relative_to(ROOT)
                                resolved_str = resolved_relative.as_posix()
                            except ValueError:
                                # If not relative to ROOT, use absolute path
                                resolved_str = resolved_path.as_posix()
                            broken_links.append(
                                {
                                    "file": file_part,
                                    "line": line_num,
                                    "target": target,
                                    "resolved": resolved_str,
                                }
                            )
                except Exception:
                    pass

        # Build JSON output
        result = {
            "pass": len(findings) == 0,
            "markdown_files_scanned": metrics.get("markdown_files_scanned", 0),
            "links_resolved": metrics.get("links_resolved", 0),
            "files_skipped_as_vendored": metrics.get("files_skipped_as_vendored", 0),
            "resources_checked": metrics.get("resources_checked", 0),
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }

        print(json.dumps(result, indent=None))
        return 1 if findings else 0
    else:
        # Original behavior
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
