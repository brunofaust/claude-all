## SEO / GEO / AEO — seo skill

When writing or editing page metadata (`<title>`, `<meta>`, OG tags, JSON-LD), auditing pages for search performance, optimizing for AI engines (Perplexity / ChatGPT / Gemini / Google AI Overviews), or designing programmatic-SEO pages, apply the `seo` skill.

Three pillars:

- **SEO** — classic SERP ranking (titles, links, Core Web Vitals).
- **GEO** — get cited by generative engines (E-E-A-T, factual density, entity clarity, `llms.txt`, AI-bot access).
- **AEO** — win featured snippets, PAA, voice (question-headings, ≤40-word direct answers, FAQPage only on authority sites).

Key quick checks:

- Title 50-60 chars, meta description 150-160 chars, exactly one `<h1>`.
- Canonical tag on every indexable page.
- JSON-LD (not Microdata). Skip deprecated types: `HowTo`, `FAQPage` on non-authority sites.
- Core Web Vitals: LCP ≤ 2.5s, INP ≤ 200ms (replaced FID), CLS ≤ 0.1.
- robots.txt should NOT block `GPTBot`, `ClaudeBot`, `PerplexityBot`, `Google-Extended`, `CCBot` — they feed AI citations.
- Programmatic pages: hard cap (warn ≥ 30 pages, block ≥ 50).
