# Multi-language spell-check — `typos` (code) + CSpell (content)

`typos` (and `codespell`) are **corrections-based** and English: low-noise typo catching on code, but
they don't *catch* typos in other languages (they don't false-positive on them either — they just
ignore unknown words). For multilingual content, add **[CSpell](https://cspell.org/)** — a
**dictionary-based** checker with dictionaries for dozens of human + programming languages — and
**scope it to the content paths**. Keep `typos` for code so you don't drown the codebase in
dictionary false positives.

> **`codespell` is NOT a multi-language alternative** — it's the same English corrections model as
> `typos`. Switching to it gains nothing here; CSpell is the only true multi-language option.

```toml
# prek.toml — typos stays on code; CSpell handles multilingual content only
[[repos]]
repo = "https://github.com/streetsidesoftware/cspell-cli"
rev = "v8.x.x"        # pin to a real tag
hooks = [
  {
    id = "cspell",
    name = "🔤 content · Multi-language spell check",
    # scope to content you author multilingually — NOT the whole repo
    files = "^(src/myapp/i18n|docs|content)/.*\\.(md|mdx|json|po|ts|tsx)$",
    additional_dependencies = [
      "@cspell/dict-pt-pt",   # Portuguese
      "@cspell/dict-es-es",   # Spanish
      "@cspell/dict-fr-fr",   # French
    ]
  }
]
```

```yaml
# cspell.config.yaml (repo root) — check against several language dictionaries
version: "0.2"
language: "en,pt,pt-PT,es"          # words must be valid in AT LEAST one of these
import:
  - "@cspell/dict-pt-pt/cspell-ext.json"
  - "@cspell/dict-es-es/cspell-ext.json"
  - "@cspell/dict-fr-fr/cspell-ext.json"
dictionaries: ["softwareTerms", "filetypes"]
words:                              # project allowlist (real terms/names CSpell won't know)
  - myapp
  - polars
ignorePaths: ["**/*.lock", "node_modules/**", "**/*.min.*"]
flagWords: []                       # words to ALWAYS flag (e.g. banned/forbidden terms)
```

Trade-offs to plan for:

- **Dictionary-based → noisy on code** (every identifier/abbrev/lib name is "unknown"). That's why
  you scope CSpell to content and grow `words:` over time, rather than running it repo-wide.
- Needs **Node** in the hook env (the `cspell-cli` hook provides it). Heavier than `typos` (Rust).
- Rolling it onto an existing repo surfaces many "unknown word" findings at once — apply the
  "Rolling out a new hook without a backlog" discipline (in SKILL.md): scope narrow first, build `words:`,
  expand.
- **Translator-owned i18n dumps** are often NOT worth CI spell-checking (translators own
  correctness; you'd need every locale's dictionary + heavy allowlisting). Reserve CSpell for content
  *you* author in multiple languages, and keep machine/translator output path-excluded.
