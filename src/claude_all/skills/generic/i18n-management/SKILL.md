---
name: i18n-management
description: >-
  Add a translation key and audit for locale drift across a project's i18n systems — a project
  commonly has MORE THAN ONE (a frontend framework's JSON locale tree, a backend's own JSON locale
  tree, template-based per-locale files like email HTML) and they rarely share a key set, a locale
  list, or even a locale-code convention (a frontend `pt-BR` vs a backend `pt`, for example). Use
  when: adding a new translation/i18n key, updating copy that needs to propagate to every locale,
  auditing locale files for missing/orphan keys or empty placeholder strings, reviewing email or
  document templates for per-locale drift, or before a release to catch a locale that silently
  fell behind.
disable-model-invocation: false
user-invocable: true
---

# i18n management — add a key, catch drift, across every i18n system in the project

> **The lesson.** A translation key added to the reference locale and forgotten in the others is
> invisible until a user in that locale sees English (or a raw key) in production. It never fails a
> build — JSON parses fine with a missing key, a template renders fine with a stale string — so
> nothing catches it except reading every locale file side by side. Most projects don't have ONE i18n
> system to keep in sync; they have several, each with its own path, its own locale list, and its own
> mechanism (key-based JSON vs whole-file-per-locale templates).

## Step 0: map the project's i18n systems

Before adding a key or auditing drift, identify every i18n system in the project — do not assume
there is only one. Each system is defined by:

- **Path** — where its locale files live.
- **Mechanism** — `key-based` (a nested JSON/YAML tree, one file per locale, e.g. `react-i18next`,
  `next-intl`, backend `gettext`/`babel` catalogs) vs `file-based` (a template rendered per locale —
  email HTML, PDF templates, static pages — where the whole file IS the content, not a key lookup).
- **Locale list** — the exact codes this system supports. **Do not assume these match across
  systems** — a frontend commonly uses a regional code (`pt-BR`, `zh-CN`) while a backend catalog
  uses the base language (`pt`, `zh`); one system may support fewer locales than another (a new
  market added to the frontend before the backend catches up, or vice versa).
- **Reference locale** — almost always `en`/`en-US` — the one every other locale is diffed against.

Example map (illustrative — replace with the project's real systems and paths):

| System | Path | Mechanism | Locales | Reference |
| --- | --- | --- | --- | --- |
| Frontend | `frontend/src/i18n/locales/` | key-based JSON | en, es, pt-BR | en |
| Backend | `src/myapp/i18n/locales/` | key-based JSON | en, es, pt, de, fr | en |
| Email templates | `src/myapp/email/templates/<name>/<locale>.html.j2` | file-based, one dir per template | en, es, pt-BR | en |

Two systems that both call their regional variant `pt` but mean different countries, or a key-based
system whose "locales" are actually per-brand rather than per-language, are the same shape — the map
above generalizes to any set of parallel per-locale trees.

## Adding a key (key-based systems)

1. Determine the correct nesting path for the new key — a consistent convention (camelCase grouped
   by feature area, e.g. `billing.invoiceTitle`) makes drift easier to spot visually.
2. Add the string to the **reference locale** file first.
3. Add the equivalent to **every other locale** in that system, at the identical nesting path.
4. Validate every touched file still parses as valid JSON/YAML.
5. Run the drift check below — a key present in the reference locale but missing from a sibling is
   exactly the bug this whole skill exists to catch, and it's cheap to catch immediately after the
   edit rather than at the next audit.

Repeat per system — a key relevant to more than one system (e.g. a validation error message that
appears in both the frontend and an API response) needs the same propagation in each independently;
they do not share a key namespace.

## Updating a template (file-based systems)

Template locales are NOT key-based — each locale is a complete, independently-rendered file, so
"add a key" doesn't apply; every locale file needs the actual text change.

1. Edit the reference locale's template first (the canonical source).
2. Update every other locale's template with the translated equivalent.
3. If the change is structural (a new CTA button, a new conditional block, a new templating
   variable), verify every locale's file was updated with the same structural element — a locale
   that only got the reference file's variable substituted, without the new block, silently renders
   incomplete.
4. Flag any locale whose file was touched noticeably less recently than the reference locale's, for
   the same template — that's the single strongest drift signal for file-based systems (see the
   git-mtime check below).

## Drift audit

Run after any i18n change, and periodically (e.g. before a release) independent of any specific
edit. Check each system per its mechanism:

### Key-based systems

- Every key present in the reference locale exists, at the same nesting path, in every other
  locale file.
- **Orphan keys**: a key present in a non-reference locale but absent from the reference locale —
  usually stale (removed from the reference but never cleaned up elsewhere), sometimes a locale
  legitimately needing an extra key (regional legal text) — either way, worth a human look.
- **Empty placeholders**: an empty string value (`""`) — the structural key exists but nobody
  filled in the translation. A key existing is not the same as a key being translated.
- **Structural mismatch**: the same key is a string in one locale and a nested object (or array) in
  another — a sign the two files drifted independently rather than being edited together.
- Every locale file is valid JSON/YAML — a syntax error in one locale's file is itself a drift bug
  (the file was hand-edited and broke).

### File-based (template) systems

- Every template "unit" (a directory, a name prefix) has a file for every locale the system
  supports — a template missing one locale's file entirely is the most common finding.
- Templating variables/placeholders (`{{ name }}`, `{% block %}`) present in the reference locale's
  file are present in every other locale's file for the SAME template — a variable dropped in
  translation breaks the render for that locale only, which is exactly why it's easy to miss in
  testing (the reference locale never breaks).
- Structural blocks (`{% extends %}`, `{% block content %}`, `{% import %}`) match across locales
  for the same template.
- **git-mtime staleness**: for each template, compare how recently each locale's file was last
  touched. A locale last modified long before the reference locale, for the same template, is the
  cheapest signal that a content update didn't propagate — it doesn't prove drift by itself (a
  locale might genuinely be unchanged because the reference change was a typo fix), but it is the
  highest-value place to look first.

```bash
# Generic git-mtime staleness check for one file-based template system —
# adjust the glob and locale list to the project's actual layout.
for dir in src/myapp/email/templates/*/; do
  echo "=== $(basename "$dir") ==="
  git log --format="%ar %f" -1 -- "$dir"en.html.j2 "$dir"es.html.j2 "$dir"pt-BR.html.j2 2>/dev/null
done
```

## Output format

Report drift per system, not merged — a frontend finding and a backend finding for the "same"
concept (e.g. a validation message) are two independent bugs with two independent fixes.

```
=== Frontend (3 locales: en, es, pt-BR) ===
DRIFT: key "billing.invoiceTitle" in en.json missing from es.json
ORPHAN: key "old.legacy" in pt-BR.json not in en.json
EMPTY: key "notices.markRead" in es.json is ""
OK: 247 keys consistent across all 3 locales

=== Backend (5 locales: en, es, pt, de, fr) ===
DRIFT: key "pii.person_name" in en.json missing from de.json, fr.json
OK: 12 keys consistent across all 5 locales

=== Email templates (file-based, 3 locales) ===
MISSING: template "account_deleted" has no de.html.j2
DRIFT: "welcome_invite/es.html.j2" last modified 3 days ago, en.html.j2 modified 1 hour ago —
  possible untranslated update
VAR_MISMATCH: "onboarding_completed" — {{ org_name }} in en but missing in pt-BR
OK: password_reset, password_changed consistent
```

## Anti-patterns

| Anti-pattern | Why | Use instead |
| --- | --- | --- |
| Assuming one i18n system covers the whole project | Frontend/backend/templates usually diverge in locale list and mechanism | Map every system independently (Step 0) before adding a key or auditing |
| Assuming locale codes match across systems | `pt-BR` (frontend) vs `pt` (backend) is a common real split | Look up each system's actual locale list; never infer one from another |
| Treating a present-but-empty key as "translated" | An empty string passes a naive "key exists" check | Explicitly check for empty-string placeholders, not just key presence |
| Only checking key existence in JSON systems | A key existing with the WRONG shape (string vs object) still breaks the consumer | Also check structural type match, not just presence |
| Skipping file-based (template) systems in an i18n audit | They have no key system, so a generic "diff the JSON" script misses them entirely | Audit file-based systems on their own terms: file presence, variable/block consistency, mtime staleness |
