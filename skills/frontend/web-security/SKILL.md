---
name: web-security
description: >-
  Frontend / web-app security review + hardening for React, Next.js, Remix, Vite, and any
  browser-delivered app. Use when: writing or reviewing components that render user/HTML content,
  building Server Actions / API routes / route handlers, handling auth tokens or sessions in the
  browser, wiring env vars into client code, setting a Content-Security-Policy, embedding third-party
  scripts, or doing a pre-deploy security pass on frontend code. Covers XSS (dangerouslySetInnerHTML,
  unsafe URL schemes, target=_blank), the per-framework public-env-var leak table, Server-Actions-as-
  public-API input validation, httpOnly cookie sessions (never localStorage), CSP + nonces, prototype
  pollution, SSR injection, third-party SRI, and source-map exposure. Pairs with seo-reviewer (static
  page review) and code-review-discipline (output shape).
disable-model-invocation: false
user-invocable: true
---

# Web / Frontend Security

App-level security for code that runs in (or renders to) the browser. This is **not** HTTP-header
auditing (that's a deploy concern / `seo-runner`) — it's the code patterns that leak data or execute
attacker input. Treat every one of these as 🔴 BLOCK in review.

## XSS — never render untrusted content as HTML

- **`dangerouslySetInnerHTML` is guilty until proven safe.** Only with content you fully control or
  output of a sanitizer (`DOMPurify.sanitize(html)`). Never raw user input, never markdown rendered
  without sanitizing, never an API field you don't own.
- **Unsafe URL schemes** — a user-supplied `href`/`src` of `javascript:` or `data:text/html` executes.
  Allowlist schemes:

  ```ts
  const SAFE = new Set(["http:", "https:", "mailto:", "tel:"]);
  export function safeUrl(raw: string): string {
    try { return SAFE.has(new URL(raw, location.origin).protocol) ? raw : "#"; }
    catch { return "#"; }
  }
  ```

- **`target="_blank"` → always `rel="noopener noreferrer"`** (tabnabbing + referrer leak).
- React auto-escapes `{value}` in JSX — keep it that way; the danger is only the escape hatches above.

## Secrets & env vars — know what ships to the client

Anything imported into client code ends up in the bundle, readable by anyone. Only the framework's
**public-prefixed** vars are safe to expose; everything else stays server-only.

| Framework | Safe in client (public) | Everything else |
| --- | --- | --- |
| Next.js | `NEXT_PUBLIC_*` | server-only (route handlers, Server Components, actions) |
| Vite | `VITE_*` | server-only |
| Create React App | `REACT_APP_*` | server-only |
| Remix | loader/action return values only | never `process.env.X` in a component |

Rule: **a secret (API key, DB URL, signing key) must never be reachable from a Client Component.**
If you `import` it client-side, it's leaked — fetch through a server route instead.

## Server Actions / API routes run with public-API trust

A Server Action or route handler is reachable by anyone with the URL — hidden form fields and
client-side checks mean nothing. So:

- **Validate every input at the boundary** (zod/valibot): `const data = Schema.parse(input)`.
- **Re-check authn + authz on the server** for every action — never rely on the UI having hidden a
  button.
- Don't trust client-sent IDs/roles/prices; look them up server-side.

## Sessions & auth — httpOnly cookies, never localStorage

- **Never store session tokens / JWTs in `localStorage` or `sessionStorage`** — any XSS reads them.
  Use `Set-Cookie: HttpOnly; Secure; SameSite=Lax` (or `Strict`); the browser sends it, JS can't read it.
- CSRF: `SameSite` cookies + a CSRF token for state-changing non-GET requests when applicable.
- Don't put PII / roles / entitlements in a client-readable token and trust them — verify server-side.

## Content-Security-Policy — default-deny + nonces

A real CSP is the backstop when an XSS slips through. Minimum shape, with a **per-request nonce**
(avoid `'unsafe-inline'`):

```
default-src 'self';
script-src 'self' 'nonce-<RANDOM>';
style-src 'self' 'nonce-<RANDOM>';
img-src 'self' data:;
object-src 'none'; base-uri 'self'; frame-ancestors 'none';
```

Generate the nonce per request, pass it to inline `<script nonce>`. `'unsafe-inline'`/`'unsafe-eval'`
in `script-src` defeats the point.

## Other sharp edges

- **Prototype pollution** — spreading untrusted JSON (`{...userInput}`) or deep-merging it can set
  `__proto__`/`constructor`. Guard keys, or build objects with `Object.create(null)`; use a
  pollution-safe merge.
- **SSR injection** — interpolating untrusted data into a server-rendered `<script>`/JSON island
  without escaping (`</script>`, `<!--`) breaks out. Use the framework's serializer.
- **Third-party scripts** — pin + **SRI** (`integrity=` hash); each one runs with full page trust.
- **Source maps** — don't ship `.map` to production (leaks source + paths); upload to your error
  tracker and strip from the public bundle.

## Anti-patterns

| Anti-pattern | Why | Use instead |
| --- | --- | --- |
| `dangerouslySetInnerHTML={{__html: userInput}}` | Stored/reflected XSS | `DOMPurify.sanitize` or don't render as HTML |
| `<a href={userUrl}>` unchecked | `javascript:` URL executes | `safeUrl()` scheme allowlist |
| token in `localStorage` | XSS-readable | `HttpOnly` cookie |
| `process.env.SECRET` in a Client Component | shipped in bundle | server route / Server Component |
| Server Action trusting hidden form fields | it's a public endpoint | `Schema.parse` + server-side authz |
| `{...JSON.parse(untrusted)}` into an object | prototype pollution | key guard / `Object.create(null)` |
| `'unsafe-inline'` in `script-src` | nullifies CSP | per-request nonce |

## Enforcement

- ESLint: `eslint-plugin-security`, `eslint-plugin-no-unsanitized` (flags `innerHTML`/`dangerouslySet…`),
  `eslint-plugin-react` (`jsx-no-target-blank`).
- `semgrep` rulesets (`p/xss`, `p/react`) in CI.
- A CSP smoke check in CI; secret-scanning (gitleaks) so keys never reach client bundles.
- Validate Server Action inputs with a schema lib — make `Schema.parse` the lint-enforced entry.

## References (track for updates)

- Adapted from [affaan-m/ECC](https://github.com/affaan-m/ECC) — [`rules/react/security.md`](https://github.com/affaan-m/ECC/blob/main/rules/react/security.md) and [`rules/common/security.md`](https://github.com/affaan-m/ECC/blob/main/rules/common/security.md).
- [OWASP XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html) · [Content Security Policy Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)
- [MDN: Content-Security-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy)
