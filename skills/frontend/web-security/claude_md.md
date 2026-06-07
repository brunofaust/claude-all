## Web security — `web-security` skill
Apply when writing/reviewing any browser-delivered app (React/Next.js/Remix/Vite) — rendering HTML/markdown, Server Actions/route handlers, auth tokens/sessions, env vars, CSP, third-party scripts.

Key rules: `dangerouslySetInnerHTML` only on DOMPurify-sanitized content; `safeUrl()` scheme allowlist (block `javascript:`/`data:`); only framework-prefixed vars (`NEXT_PUBLIC_*`/`VITE_*`) in client code; sessions in `HttpOnly; Secure; SameSite` cookies, never localStorage; CSP with per-request nonce.
