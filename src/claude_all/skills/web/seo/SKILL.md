---
name: seo
description: >-
  SEO + GEO + AEO audit and optimization. Use when: writing or editing HTML meta / titles / OpenGraph / structured data (JSON-LD), auditing a page for search performance, improving Core Web Vitals, optimizing for generative engines (ChatGPT / Perplexity / Gemini / Google AI Overviews), winning featured snippets, designing programmatic-SEO pages, reviewing sitemaps / robots / canonicals / hreflang, or troubleshooting why a page isn't ranking. Covers classic search-engine SEO, GEO (Generative Engine Optimization), and AEO (Answer Engine Optimization).
disable-model-invocation: false
user-invocable: true
---

# SEO + GEO + AEO Skill

Three pillars — different objectives, different signals:

| Pillar                                   | Goal                              | Engines                                                 | Key signals                                                         |
| ---------------------------------------- | --------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------- |
| **SEO**                                  | Rank on SETPs                     | Google, Bing                                            | Titles, links, Core Web Vitals, canonicals                          |
| **GEO** (Generative Engine Optimization) | Get *cited* by AI engines         | Perplexity, ChatGPT Search, Gemini, Google AI Overviews | E-E-A-T, factual density, entity clarity, `llms.txt`, AI-bot access |
| **AEO** (Answer Engine Optimization)     | Win featured snippets, PAA, voice | Google snippets, Alexa, Siri                            | Question-headings, FAQPage / HowTo schema, direct ≤40-word answers  |

GEO engines **cite sources, they don't rank** — different optimization shape from classic SEO.

______________________________________________________________________

## Skill Contract

**Inputs:** a URL, a local file (HTML / TSX / JSX / Astro / MD), or a folder of pages.

**Tools available:**

- `WebFetch` for fetching live URLs + raw HTML
- `Bash` for `curl -I`, `lighthouse` (if installed), reading sitemap/robots
- `Read` / `Glob` / `Grep` for local files
- Optional MCPs: `muningis/seo-check-mcp` (24 dedicated check tools — read-sitemap, validate-schema, analyze-meta, etc.), DataForSEO / Ahrefs / SEMrush (paid)

**Output modes:**

- **Quick audit** (default) — top issues sorted by severity, < 30 lines
- **Full audit** — all categories below, grouped + actionable, ≤ 300 lines
- **Specific category** — when user names one (e.g. "audit my structured data")

**Handoff:** end the audit with a numbered prioritized fix list. If the fix needs design / copy / accessibility work, suggest the related skill (`web-design-guidelines` for a11y, `react-best-practices` for Next.js metadata API).

______________________________________________________________________

## Severity scale

- **🔴 BLOCK** — visible / measurable harm (missing title, broken canonical, AI bots blocked unintentionally, deprecated schema in use)
- **🟠 HIGH** — known ranking hit (oversize meta, missing structured data on indexable page, INP > 200ms, missing alt on content images)
- **🟡 MEDIUM** — best-practice gap (no OG image, no breadcrumb schema, thin internal linking)
- **🔵 INFO** — improvement opportunity (no `llms.txt`, no FAQPage where it'd help)

______________________________________________________________________

## 1. On-page SEO checks

### Title

- Exists. Unique per page. **50–60 chars** (longer truncates in SERP).
- Includes primary keyword near the start where natural.
- Brand suffix only on home / category pages, not every article.

### Meta description

- Exists. **150–160 chars** (mobile truncates earlier).
- Action-oriented sentence — Google may rewrite if poor.

### Canonical

- `<link rel="canonical" href="...">` on every indexable page.
- Self-referential allowed. Cross-domain only when content is genuinely syndicated.
- **Anti-pattern:** canonical pointing to a 404 / 301'd URL / paginated parent on every page.

### Headings

- Exactly one `<h1>`. Match (or echo) the title.
- Logical H2 → H3 → H4 hierarchy. **Don't skip levels.**
- For AEO: phrase H2s as questions where natural.

### URL

- Lowercase, hyphens not underscores, no trailing IDs unless meaningful.
- Short. Keyword + descriptor.

### Internal linking

- Every indexable page should be reachable in ≤ 3 clicks from home.
- Anchor text descriptive (`How to deploy Lambda` — not `click here`).
- Orphaned pages (no incoming internal link) → fix or noindex.

______________________________________________________________________

## 2. Structured data (JSON-LD)

Use **JSON-LD in `<head>`**, not Microdata / RDFa.

### Core types (ship for matching content)

- `Article` (blog posts) — `headline`, `datePublished`, `dateModified`, `author`, `publisher`
- `BreadcrumbList` — every non-home page
- `Organization` — site root, with `sameAs` social profiles
- `Product` — e-commerce + pricing + `availability` + `aggregateRating`
- `LocalBusiness` — physical locations, with NAP + opening hours
- `VideoObject` — for any embedded video

### Deprecated / restricted (DO NOT add)

- `HowTo` — Google removed rich-result support (2023). Plain article markup is fine, schema is wasted.
- `FAQPage` — **only on official/government/authority sites since 2023.** Marketing pages stuffing FAQPage get filtered. Audit existing FAQPage on non-authority sites and remove.

### Validation

- Run through Google's [Rich Results Test](https://search.google.com/test/rich-results) or `validator.schema.org`.
- Use `@graph` for multiple types on one page. Cross-reference via `@id`.

______________________________________________________________________

## 3. Core Web Vitals

Current thresholds (June 2024+):

| Metric                                                            | Good    | Needs improvement | Poor    |
| ----------------------------------------------------------------- | ------- | ----------------- | ------- |
| **LCP** (Largest Contentful Paint)                                | ≤ 2.5s  | ≤ 4.0s            | > 4.0s  |
| **INP** (Interaction to Next Paint) — **replaced FID March 2024** | ≤ 200ms | ≤ 500ms           | > 500ms |
| **CLS** (Cumulative Layout Shift)                                 | ≤ 0.1   | ≤ 0.25            | > 0.25  |

Supporting metrics (not ranking but useful):

- **TTFB** ≤ 800ms
- **FCP** ≤ 1.8s

### Common LCP fixes

- Preload the LCP image (`<link rel="preload" as="image">`).
- Modern formats: AVIF > WebP > JPEG.
- `loading="eager"` on above-the-fold image; `loading="lazy"` everywhere else.
- Self-host critical fonts; use `font-display: swap`.
- Server-side render the LCP element (no client-side hydration delay).

### Common INP fixes

- Break long tasks (> 50ms) with `scheduler.yield()` or `requestIdleCallback`.
- Defer non-critical JS (`<script defer>` or `<script type="module">`).
- Avoid synchronous third-party scripts (chat widgets, analytics) in the critical path.

### Common CLS fixes

- Always set `width` + `height` on images and iframes.
- Reserve space for ads / embeds.
- Avoid injecting content above existing content (banners pushing down the page).

### Measurement

- **Lab**: `npx lighthouse <url> --output=json --only-categories=performance,seo`
- **Field**: PageSpeed Insights + CrUX (real user data) — the metric Google actually uses.

______________________________________________________________________

## 4. Technical SEO

### robots.txt

- Exists at `/robots.txt`.
- Allow indexing of important paths. **Block** admin, search, faceted-filter URLs.
- Reference the sitemap: `Sitemap: https://example.com/sitemap.xml`.
- **AI bot access** — for GEO, you usually WANT these allowed:
    - `GPTBot` (OpenAI), `ChatGPT-User` (ChatGPT browse), `OAI-SearchBot` (ChatGPT Search)
    - `ClaudeBot` (Anthropic crawler), `Claude-Web` (interactive), `anthropic-ai`
    - `PerplexityBot`, `Perplexity-User`
    - `Google-Extended` (Bard/Gemini training — separate from Googlebot)
    - `CCBot` (Common Crawl, feeds many models)
        Blocking these by accident is a common GEO killer.

### Sitemap

- Exists, listed in robots, < 50 MB and < 50,000 URLs (use sitemap index for larger).
- Includes `<lastmod>`. Auto-regenerated on content changes (most static-site frameworks do this).
- Only includes canonical, indexable URLs (no redirects, no noindex pages).

### hreflang

For multi-language sites:

- Self-reference required (each page lists itself + its alternates).
- ISO 639-1 language codes + optional ISO 3166-1 alpha-2 region (`en`, `en-US`, `pt-BR`).
- `x-default` for the language picker.

### Redirects

- 301 (permanent), not 302 / 307 unless temporary.
- **No chains** — A → B → C should be flattened to A → C.

### HTTPS / HSTS

- HTTPS everywhere. Mixed-content (`http://` resources on `https://` pages) breaks ranking + browser security.
- HSTS header recommended for production.

______________________________________________________________________

## 5. Mobile + accessibility

- `<meta name="viewport" content="width=device-width, initial-scale=1">` — required for mobile-first indexing.
- Same content + structured data + links served to mobile and desktop (parity).
- For a11y review, hand off to `web-design-guidelines` skill — but tap targets ≥ 44×44px, contrast ≥ 4.5:1 normal, and `prefers-reduced-motion` are SEO-adjacent.

### Image SEO

- `alt` on every content image (decorative → empty `alt=""`).
- File names descriptive (`alpine-lake-summer.jpg`, not `IMG_4823.jpg`).
- Modern format (AVIF/WebP) with fallback.
- `srcset` + `sizes` for responsive.
- `loading="lazy"` below the fold.

______________________________________________________________________

## 6. Social meta (OpenGraph + Twitter)

Required on shareable pages:

```html
<meta property="og:title" content="...">
<meta property="og:description" content="...">
<meta property="og:image" content="...">  <!-- 1200×630, < 5 MB -->
<meta property="og:url" content="...">
<meta property="og:type" content="article">  <!-- or website -->
<meta name="twitter:card" content="summary_large_image">
```

Validate with Facebook Sharing Debugger + Twitter Card Validator.

______________________________________________________________________

## 7. GEO — Generative Engine Optimization

For AI engines that cite sources instead of ranking pages.

### Key signals

1. **E-E-A-T** (Experience, Expertise, Authoritativeness, Trustworthiness) — per Google's Sep 2025 Quality Rater Guidelines, but generative engines apply similar weighting.

    - Author bylines with credentials, photo, social profiles.
    - "About" page + clear ownership.
    - Citations to primary sources, not other content marketing.

1. **Factual density** — concrete numbers, dates, percentages, specific names. Generative engines preferentially cite content with verifiable facts.

1. **Entity clarity** — Use Wikipedia-style consistent naming. Define key entities up front (`The Lambda Powertools library …`). Crisp definitions get extracted.

1. **Answer-first format** — Lead each section with a direct answer (1–3 sentences), then expand. Generative engines extract the lead.

1. **Statistics integration** — Pages with original data / surveys / proprietary stats get disproportionate AI citations.

### `llms.txt`

Optional file at `/llms.txt` (analogous to robots.txt for LLMs). Markdown index of your site's most authoritative pages. Helps AI engines understand the site structure.

```
# Example /llms.txt
# > example.com — what we do
> Example Inc. — observability for serverless

## Docs
- [Getting Started](/docs/getting-started): tldr install + first event
- [API Reference](/docs/api): all endpoints, parameters, examples

## Blog
- [Why we chose DynamoDB](/blog/dynamodb): full design write-up
```

Not yet a confirmed ranking factor anywhere, but cheap to add.

### AI-bot crawl access

Verify these are NOT blocked in robots.txt (see §4 robots.txt).

______________________________________________________________________

## 8. AEO — Answer Engine Optimization

For featured snippets, People-Also-Ask, voice assistants.

### Patterns

- **Question-phrased headings** — H2 / H3 as a question that matches search intent (`How does S3 versioning work?`).
- **Direct-answer paragraph** — first paragraph after the heading: a single, ≤ 40-word direct answer. Bullet list or numbered list immediately after for snippet eligibility.
- **Definition pattern** — for "what is X" queries: H1/H2 = "What is X?", answer = first sentence is a noun-phrase definition.
- **HowTo** schema is deprecated; structure plain prose with numbered list instead.
- **FAQPage** schema only if you're an authority site for the topic. Otherwise skip.

### Snippet-friendly markup

- Numbered list = step-by-step snippets
- Bulleted list = list snippets
- `<table>` = table snippets
- ≤ 50 words per answer = paragraph snippet

______________________________________________________________________

## 9. Programmatic SEO (template-driven pages)

If you generate pages from a template + data (location pages, comparison pages, glossary terms):

| Page count | Risk             | Action                                                                |
| ---------- | ---------------- | --------------------------------------------------------------------- |
| ≤ 30       | Low              | Ship if each page has unique value                                    |
| 30–50      | Medium           | Each page must have ≥ 300 words of unique content + unique data point |
| 50+        | **High — block** | Cannibalisation likely. Consolidate or skip programmatic strategy.    |

### Avoid

- Identical templates filled with `[CITY]` + boilerplate
- Faceted-filter URLs indexed (`/products?color=red&size=l&brand=acme` × 10,000)
- Thin "vs" comparison pages with no original analysis
- Doorway pages (multiple URLs targeting the same keyword)

### Do

- Each programmatic page = unique combo of (entity, data, perspective)
- Canonical to the highest-value variant when overlap is unavoidable
- Block faceted filters in robots.txt or noindex them

______________________________________________________________________

## 10. Audit workflow

### Quick audit (`audit seo for <url>`)

1. Fetch the page (`WebFetch` for live, `Read` for local).
1. Extract: `<title>`, `<meta description>`, canonical, h1, JSON-LD blocks, OG tags, `lang`, viewport.
1. Check sitemap + robots if you can reach them.
1. Run Lighthouse if available locally.
1. Return top 5–10 issues by severity.

Output template:

```
**SEO audit:** example.com/blog/post   •   Quick

🔴 BLOCK (2)
- Missing `<link rel="canonical">` — head:14
- robots.txt blocks GPTBot, ClaudeBot, PerplexityBot — losing AI engine visibility

🟠 HIGH (3)
- Title 73 chars (target 50-60) — will truncate in SERP
- LCP 4.8s (poor) — preload hero image, switch to WebP
- No JSON-LD Article markup on blog post

🟡 MEDIUM (2)
- No OG image — share previews will be ugly
- No internal links to related posts

🔵 INFO (1)
- No `llms.txt` — consider adding for GEO

**Top 3 fixes (impact-ordered):**
1. Add canonical + unblock AI bots (5-min, high impact)
2. Preload + WebP hero image (1 hr, fixes LCP)
3. Add Article + BreadcrumbList JSON-LD (30 min, snippet eligibility)
```

### Full audit

Same shape but with all 10 sections covered, all findings listed (not just top-N).

### Category-specific

When user asks about one slice ("review my structured data", "check Core Web Vitals"), do only that section in depth.

______________________________________________________________________

## Related skills

Hand off to these when their domain is more specific:

- `web-design-guidelines` — a11y, contrast, focus, motion (overlaps with mobile SEO)
- `react-best-practices` — Next.js metadata API, performance for CWV
- `react-view-transitions` — animation patterns (CLS-friendly transitions)
- Agents: static SEO review of page source (HTML/JSX/TSX, robots, sitemap) → `seo-reviewer`; live-URL audits (PageSpeed, Observatory, on-page scrape) → `seo-runner`

______________________________________________________________________

## References — primary sources

- [Google Search Central docs](https://developers.google.com/search)
- [Google Search Quality Rater Guidelines (Sept 2025)](https://services.google.com/fh/files/misc/hsw-sqrg.pdf)
- [Schema.org](https://schema.org/)
- [web.dev Core Web Vitals](https://web.dev/vitals/)
- [PageSpeed Insights](https://pagespeed.web.dev/)
- [llms.txt proposal](https://llmstxt.org/)
- AI bot identifiers: [OpenAI](https://platform.openai.com/docs/bots), [Anthropic crawler docs](https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler), [Perplexity](https://docs.perplexity.ai/guides/bots), [Google AI](https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers)

## Deeper references

Community Claude skills / MCPs that informed this skill, paid integrations (Ahrefs / SEMrush / DataForSEO), known low-signal repos to skip, and how to fetch one →
[`references/community-sources.md`](references/community-sources.md). Consult it when a finding needs richer coverage than this skill carries.
