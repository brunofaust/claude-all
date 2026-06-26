## Web security — `web-security` skill
Key rules: `dangerouslySetInnerHTML` only on DOMPurify-sanitized content; `safeUrl()` scheme allowlist (block `javascript:`/`data:`); only framework-prefixed vars (`NEXT_PUBLIC_*`/`VITE_*`) in client code; sessions in `HttpOnly; Secure; SameSite` cookies, never localStorage; CSP with per-request nonce.
