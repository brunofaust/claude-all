# Deeper references — when you need more depth

If a finding in this skill needs richer coverage (specific check, edge case, tool integration), consult one of these. They're community Claude skills / MCPs that informed this skill's design — fetch them via `WebFetch` when in doubt:

- **[addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills)** — Lighthouse-backed scoring + modular sub-skills (perf / CWV / a11y / SEO / best-practices). Go here when you need the Lighthouse JSON-to-rule mapping or category-specific deep dives.
- **[AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)** — biggest community SEO skill (25+ sub-skills). Go here for Google API integration patterns (PageSpeed Insights, CrUX, GSC, GA4, Indexing API), large-site drift detection, content audits at scale.
- **[Bhanunamikaze/Agentic-SEO-Skill](https://github.com/Bhanunamikaze/Agentic-SEO-Skill)** — rule-encoding patterns + 89 helper scripts. Go here for: `llms_txt_checker.py`, programmatic-page caps logic, FAQPage / HowTo deprecation enforcement.
- **[aaron-he-zhu/seo-geo-claude-skills](https://github.com/aaron-he-zhu/seo-geo-claude-skills)** — 4-phase pipeline (Research → Build → Optimize → Monitor) + EEAT / CITE cross-cutting auditors. Go here when designing multi-step SEO workflows or content authority scoring.
- **[SNLabat/SEO-GEO-AEO-Skill](https://github.com/SNLabat/SEO-GEO-AEO-Skill)** — concise three-pillar definitions (SEO / GEO / AEO). Go here for the original definitions if a user asks "what's the difference?".
- **[muningis/seo-check-mcp](https://github.com/muningis/seo-check-mcp)** — 24 MCP tools (read-sitemap, validate-schema, analyze-headings, find-broken-links, benchmark-seo, plus `fix-*` actionables). Wire this MCP if you want dedicated audit tooling instead of ad-hoc curl.
- **[coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)** — broader marketing context; go here when SEO crosses into content strategy / programmatic SEO at scale.
- **[seo-skills/seo-audit-skill](https://github.com/seo-skills/seo-audit-skill)** — SEOmator 251-rule ruleset / 20 categories with JSON/HTML/MD/LLM-XML output. Go here for the most exhaustive single check inventory.

### Paid integrations (only if user has access)

- [Ahrefs MCP](https://api.ahrefs.com/mcp/mcp) — backlinks, keyword data
- [SEMrush MCP](https://www.semrush.com/kb/1619-getting-started-with-mcp) — competitive analysis
- [DataForSEO MCP](https://dataforseo.com/help-center/connect-claude-to-dataforseo-mcp-very-simple-guide) — pay-per-use SERP + keyword data

### Skip / known low-signal

- `huifer/claude-code-seo` — Next.js-locked, bilingual, narrow utility.
- `ivankuznetsov/claude-seo` — Ruby readability dep, niche.

### How to use a deeper reference

When the user's question is outside this skill's depth OR they want the latest community wisdom on a specific area, fetch one of the above and quote the relevant section. Don't load the whole repo — target the README or the specific `SKILL.md`. Example:

> "For LLM-XML report format, the `seo-skills/seo-audit-skill` repo has a working example — let me fetch it."
