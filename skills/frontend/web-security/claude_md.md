## Web / frontend security — web-security skill

When writing or reviewing any browser-delivered app (React / Next.js / Remix / Vite) — rendering HTML/markdown, building Server Actions or route handlers, handling auth tokens/sessions, wiring env vars into client code, setting a CSP, or embedding third-party scripts — apply the `web-security` skill.

- `dangerouslySetInnerHTML` only on sanitized content (DOMPurify); `safeUrl()` scheme allowlist (block `javascript:`/`data:`); `target="_blank"` → `rel="noopener noreferrer"`.
- Secrets: only framework public-prefixed vars (`NEXT_PUBLIC_*` / `VITE_*` / `REACT_APP_*`) ship to the client — never a secret in a Client Component.
- Server Actions / route handlers run with public-API trust → validate every input (zod) + re-check authz server-side.
- Sessions in `HttpOnly; Secure; SameSite` cookies, **never** localStorage. CSP with a per-request nonce (no `unsafe-inline`). Don't ship source maps.

Apply BEFORE shipping any user-facing web surface; pairs with `seo-reviewer`.
