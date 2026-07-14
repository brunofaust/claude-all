#!/usr/bin/env python3
"""Reminder hook for seo skill — fires when SEO-relevant content is being written."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time

# File types where SEO-meaningful edits live
WEB_EXTS = (
    ".html",
    ".htm",
    ".tsx",
    ".jsx",
    ".astro",
    ".vue",
    ".svelte",
    ".md",
    ".mdx",
    ".xml",
    ".txt",
)

SEO_MARKERS = (
    "<title",
    "</title",
    '<meta name="description"',
    "<meta name='description'",
    '<meta property="og:',
    "<meta property='og:",
    '<meta name="twitter:',
    '<link rel="canonical"',
    "<link rel='canonical'",
    "application/ld+json",
    "@context",
    "schema.org",
    "hreflang",
    "robots.txt",
    "sitemap.xml",
    "llms.txt",
    "Article",
    "BreadcrumbList",
    "Organization",
    "FAQPage",
    "HowTo",
    "Product",
    # Next.js metadata API
    "export const metadata",
    "generateMetadata",
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    # Edit sends `new_string`; Write sends `content` — cover both.
    new_string = tool_input.get("new_string") or tool_input.get("content") or ""

    # Always fire for robots.txt / sitemap.xml / llms.txt files
    name_fire = file_path.endswith(("robots.txt", "sitemap.xml", "llms.txt"))

    if not name_fire:
        if not file_path.endswith(WEB_EXTS):
            return 0
        if "/node_modules/" in file_path or "/dist/" in file_path:
            return 0
        if not any(m in new_string for m in SEO_MARKERS):
            return 0

    session_id = data.get("session_id") or "no-session"
    flag = os.path.join(tempfile.gettempdir(), f"claude-all-seo-{session_id}.flag")
    # re-fire at most once per hour (flag mtime = last-fired time), so a long
    # session keeps the conventions fresh instead of being reminded only once.
    with contextlib.suppress(OSError):
        if os.path.exists(flag) and (time.time() - os.path.getmtime(flag)) < 3600:
            return 0  # reminded within the last hour
    # best-effort flag write: if the FS is unwritable, skip the once-per-session dedup
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(file_path)

    # exit 0 + JSON additionalContext: exit 1 stderr is shown to the USER as a hook
    # error, never to Claude — this reminder is addressed to Claude.
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "Reminder (seo, first SEO-touching edit this session): "
                    "title 50-60 chars; meta description 150-160; one <h1>; canonical on every "
                    "indexable page; JSON-LD (Article/BreadcrumbList/Organization/Product) — "
                    "SKIP deprecated HowTo and non-authority FAQPage; "
                    "Core Web Vitals: LCP ≤ 2.5s, INP ≤ 200ms (not FID), CLS ≤ 0.1; "
                    "robots.txt: don't block GPTBot/ClaudeBot/PerplexityBot/Google-Extended"
                    " — costs AI citations."
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
