#!/usr/bin/env python3
"""Reminder hook for seo skill — fires when SEO-relevant content is being written."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

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

    file_path = data.get("tool_input", {}).get("file_path", "")
    new_string = data.get("tool_input", {}).get("new_string", "") or ""

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
    if os.path.exists(flag):
        return 0
    with contextlib.suppress(OSError), open(flag, "w", encoding="utf-8") as f:
        f.write(file_path)

    print(
        "Reminder (seo, first SEO-touching edit this session): "
        "title 50-60 chars; meta description 150-160; one <h1>; canonical on every indexable page; "
        "JSON-LD (Article/BreadcrumbList/Organization/Product) — "
        "SKIP deprecated HowTo and non-authority FAQPage; "
        "Core Web Vitals: LCP ≤ 2.5s, INP ≤ 200ms (not FID), CLS ≤ 0.1; "
        "robots.txt: don't block GPTBot/ClaudeBot/PerplexityBot/Google-Extended"
        " — costs AI citations.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
