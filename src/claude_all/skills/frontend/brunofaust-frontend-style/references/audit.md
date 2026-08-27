# Audit checklist — the judgment gate for a changed frontend file

> Reference page for the `brunofaust-frontend-style` skill. `/ship` and `/ship-pr`
> run this against **every changed `.tsx` / `.jsx` / `.ts` / `.vue` / `.svelte`
> file** as a standard step — the frontend counterpart to
> `brunofaust-python-style`'s `references/audit.md`.

This is the **judgment** layer. Anything eslint / `tsc` / prettier / biome already
catches mechanically is NOT restated here — the gate is for what a linter cannot
see. For each item: it's clean, or you fix it (mechanical simplifications via
`/simplify`; the rest reported).

Scales to the diff: a style/copy tweak gets a quick pass; a new component or hook
gets the whole list.

## Correctness → [`react-correctness.md`](react-correctness.md)

- [ ] **No `useEffect` that isn't syncing with an external system** — not derived state (compute during render), not reset-on-prop-change (`key={id}`), not "run once on mount" for something the render or an event handler owns.
- [ ] **State is at the lowest level that works** — local → lift → URL → server-state → context → global. A new context/global store has a named reason it couldn't be local.
- [ ] **Keys are stable and identity-based** — never the array index on a list that can reorder, filter, or splice.
- [ ] **No stale closure** — an effect/callback capturing a value it should read fresh (deps complete, or a ref where genuinely needed).
- [ ] **No memoization without a measured reason** — React 19's compiler handles the common case; `useMemo`/`useCallback`/`memo` added "to be safe" is noise.

## Module seams — one module, one secret → [`project-structure.md`](../../../python/brunofaust-python-style/references/project-structure.md)

The rule is language-agnostic: a 1,000-line component holding orchestration *and*
data fetching *and* formatting *and* a third-party widget's config is four secrets
in one file, exactly like its backend equivalent.

- [ ] **The file hides ONE secret** — one design decision that can change independently. Rendering, data fetching, business rules and a vendor widget's shape each change for their own reason.
- [ ] **Seam test on anything long:** would these chunks ever appear in the same PR, for the same reason? Different reasons / rates / owners ⇒ split. Always change together ⇒ keep together (**a big component with one reason to change is fine**).
- [ ] **Placed by dependency ownership** — code whose only real dependency is a third-party SDK/widget belongs in that integration's module, not inline in the component that renders it.
- [ ] **No false seam** — if splitting would force lifting shared state or exporting internals just to satisfy the split, the cohesion is real: don't.
- [ ] **LOC drove no decision** — length prompted the question, never answered it. (A container/page component may legitimately be large.)

## Composition & API shape → the `vercel-composition-patterns` skill

- [ ] **No boolean-prop proliferation** — a component sprouting `isX`/`hasY`/`showZ` flags wants composition (children/slots/compound components), not another flag.
- [ ] **No prop drilling past ~2 levels** without a deliberate decision (composition first, context only when it earns it).
- [ ] **No wrapper component that only forwards props** and adds nothing — inline it (the frontend form of the pass-through chain).

## Security → [`web-security.md`](web-security.md)

- [ ] **No `dangerouslySetInnerHTML`** on anything not DOMPurify-sanitized.
- [ ] **User-supplied URLs scheme-allowlisted** (`javascript:` / `data:` blocked) on every `href`/`src`.
- [ ] **No token/session in `localStorage`/`sessionStorage`** — `HttpOnly; Secure; SameSite` cookies.
- [ ] **Only framework-prefixed env vars in client code** (`NEXT_PUBLIC_*` / `VITE_*`) — no secret reachable from the bundle.
- [ ] **Server Actions / route handlers validate their input** — they are public endpoints, not internal functions.

## Accessibility → the `web-design-guidelines` skill

- [ ] **Semantic element for the job** — a `<div onClick>` where `<button>`/`<a>` belongs is a keyboard and screen-reader bug.
- [ ] **Every interactive control has an accessible name**; every input a real label.
- [ ] **Keyboard path works** — focus order, focus visible, focus moved/trapped for dialogs, ESC closes.

## Tests → [`react-testing.md`](react-testing.md)

- [ ] **Queries follow priority** — `getByRole` → `getByLabelText` → text → `getByTestId` last.
- [ ] **`userEvent`, not `fireEvent`**; async via `findBy*`/`waitFor`, never a sleep.
- [ ] **Network mocked at the network layer** (MSW) — not by stubbing the component's own module.
- [ ] **Assertions are behavioural** — what the user sees/does, not internal state or a snapshot blob.

## Performance → the `vercel-react-best-practices` skill

- [ ] **No obvious waterfall** — sequential awaits that could be parallel; data fetched in a child that the parent should have started.
- [ ] **Nothing heavy imported eagerly** that a dynamic import would defer (charting, editors, markdown).
- [ ] **Client bundle isn't carrying server-only code** (Server Components / `server-only` where the framework supports it).

## Minimalism → [`yagni.md`](../../../python/brunofaust-python-style/references/yagni.md)

- [ ] **Every new component/hook/prop/context serves a concrete PRESENT need** — "might need it later", "more flexible", "cleaner" are not reasons. Run the deletion pass: name the need or delete it.

---

**This audit never strips a hard rule.** Sanitization, input validation on a
Server Action, an accessible name, a behaviour-asserting test — these stay. The
goal is removing *speculative structure* and catching *judgment* violations, not
thinning the code.
