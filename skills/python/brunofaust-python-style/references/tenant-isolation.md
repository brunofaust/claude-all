# Database tenant isolation — RLS + audit (optional hardening)

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a
> condensed summary; this file holds the full depth.

**This is optional.** If you want the database itself to guarantee a tenant can
only ever touch its own rows — instead of trusting every `WHERE tenant_id = …` in
the app — this is the menu. It came out of hunting cross-tenant leaks in real test
suites: logical (app-side) isolation can't *prove* a missing filter never leaks; a
database-enforced guard can. Pick the level you want; all of it is env-gated so
prod is unchanged when the switches are off.

Throughout, `tenant_id` is whatever your tenant key is — `org_id`, `account_id`,
`tenant_id`. Examples assume Postgres (RLS is Postgres-specific; on MySQL/Aurora
you'd fall back to the app-side audit instrument).

## Two levels — enforce, or just audit

| Level | What it does | Blocks a leak? | Cost |
| --- | --- | --- | --- |
| **Enforcing RLS** | A row outside the session tenant is invisible / write is rejected | **Yes** — leak becomes empty result or error | per-row policy eval |
| **Non-blocking audit** | Query results unchanged; every foreign-tenant row access is *logged* | No — detector only | per-row log fn / trigger |

They compose: run **enforcing** in prod (real guard) and **audit** in e2e (proof +
a queryable artifact at shutdown), or run audit-only first to find leaks before you
dare turn on enforcement.

## Setting the session tenant — the one thing every option needs

Both levels key off a session value that says "this connection is acting for tenant
X". Set it with `SET LOCAL` / `set_config(..., is_local=true)` so it is
**transaction-scoped** — it evaporates at `COMMIT`/`ROLLBACK` and never leaks to the
next borrower of a pooled connection. (Plain session `SET` would persist on the
pooled connection and leak — never use it for this. `SET LOCAL` is also the form
that survives PgBouncer transaction-mode pooling, because both are txn-scoped.)

```python
# At the top of every handler / unit of work, from the VALIDATED payload (req: data-modeling)
async with conn.transaction():
    await conn.execute("SELECT set_config('app.current_tenant', $1, true)", org_id)
    ...  # every query in this txn is now tenant-scoped
```

This is the recommended prod approach: the handler reads the tenant from its
Pydantic-parsed event and sets `app.current_tenant` once, per request. If you forget
it, the policies below treat the unset value as "deny all" → a loud empty result,
not a silent leak.

## Injecting the tenant — two vectors (work for prod and tests)

How the tenant value *reaches* the session. Offer both; they suit different
constraints:

**Vector A — per-tenant DB role (driver-agnostic).** Connect as a tenant-scoped
role; the policy keys on `current_user`. Needs zero driver/app cooperation — it's
just a username in the DSN — so it's the **no-code-change** option for tests with
real binaries. Downside: many roles, and a shared multi-tenant pool can't multiplex
them (fine when each connection serves one tenant — see e2e below).

```
DATABASE_URL=postgresql://tenant_<A>:pw@host:5432/app
```

**Vector B — session GUC (one role).** One app role; the tenant rides in
`app.current_tenant`, set either by the **app** (`SET LOCAL`, recommended for prod —
this is the busydone plan: set `org_id` on every handler from the payload) or, for
no-code-change tests, baked into the DSN at connect time:

```
DATABASE_URL=postgresql://app:pw@host:5432/app?options=-c%20app.current_tenant%3D<A>
```

> Verify your driver honors DSN `options` / `PGOPTIONS` before relying on the no-code
> form — asyncpg documents `server_settings` (a code change) and does **not**
> clearly honor `PGOPTIONS`; psycopg/libpq do. If unsure, use Vector A for the
> no-code-change case.

## Enforcing RLS — the blocking guard

Single app role (Vector B). The app role must **not** be the table owner, superuser,
or have `BYPASSRLS`; `FORCE` makes even the owner obey.

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON orders
  USING      (tenant_id = current_setting('app.current_tenant', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid);
```

`current_setting('app.current_tenant', true)` returns NULL when unset; `tenant_id =
NULL` matches no row → **unset tenant denies everything** (reads return empty, writes
fail the `WITH CHECK`). A query that forgot its tenant filter can now only ever see
its own tenant's rows — the leak is structurally impossible, not merely discouraged.

Put this in **migrations** so prod *and* the MiniStack DB (provisioned from the same
migrations) carry it — then e2e validates the real guard, not a test-only shim. If
you'd rather start test-only, create the policies in a pytest-init fixture.

## Non-blocking audit — log foreign-tenant access, never block

You asked for a detector that "logs the session tenant and flags if it touched any
other tenant id, on any query." Two ways, trading coverage for simplicity:

**Audit-only RLS policy (covers reads *and* writes).** Instead of filtering, the
policy always returns `true` but logs a mismatch as a side effect. Because RLS
`USING` is evaluated for `SELECT`/`UPDATE`/`DELETE` and `WITH CHECK` for `INSERT`,
this captures **any query**, reads included — which plain triggers cannot do.

```sql
CREATE OR REPLACE FUNCTION audit_tenant_access(row_tenant uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER AS $$
DECLARE declared text := current_setting('app.current_tenant', true);
BEGIN
    IF declared IS NULL OR row_tenant::text IS DISTINCT FROM declared THEN
        INSERT INTO audit.tenant_access (declared_tenant, row_tenant, test_id, at)
        VALUES (declared, row_tenant,
                current_setting('app.test_id', true), clock_timestamp());
    END IF;
    RETURN true;  -- ← never blocks; results are unchanged
END;
$$;

CREATE POLICY tenant_audit ON orders
  USING (audit_tenant_access(tenant_id)) WITH CHECK (audit_tenant_access(tenant_id));
```

Caveats: a function call per scanned row (cost — scope it to suspect tables or run in
e2e/integration, not hot prod paths); keep the `audit` schema RLS-free so it can't
recurse; the audit insert lives in the same transaction, so a rolled-back txn drops
its log (fine for committed e2e flows).

**Trigger audit (writes only, simpler/cheaper).** `AFTER INSERT/UPDATE/DELETE`
triggers record the same row into `audit.tenant_access`. Doesn't see `SELECT`s
(triggers don't fire on reads) — pair with enforcing RLS (which makes read-leaks
impossible) or with `pgaudit` if you need statement-level read logging.

**Stamp the caller.** Set a second GUC the same `SET LOCAL` way —
`set_config('app.test_id', '<nodeid>', true)` (or a request id in prod) — so every
audited row carries *who* caused it. This is the clean answer to "identify the
caller": the caller declares its id into the session; the audit records it.

**Assert at shutdown.** In `pytest_sessionfinish` (or a session-scoped teardown):

```sql
SELECT test_id, declared_tenant, row_tenant
FROM audit.tenant_access
WHERE declared_tenant IS DISTINCT FROM row_tenant;   -- any row = a leak
```

Empty = no session ever touched a foreign tenant. Group by `test_id` for a per-test
leak report.

## e2e with real (unchanged) lambdas in MiniStack

The lambdas in e2e are the **real prod binaries** running in MiniStack — you can't
edit them. Two paths, depending on whether the handler already sets the tenant:

- **Handler sets the tenant from the payload (the busydone plan).** Then the real
  lambda code sets `app.current_tenant` itself from its scoped event — **e2e needs
  nothing extra**. This dovetails with two existing rules: scoped processes
  ([`scoped-processes.md`](scoped-processes.md)) make each invocation single-tenant,
  and `LAMBDA_EXECUTOR=docker` ([`testing.md`](testing.md)) gives a fresh
  container/pool per invoke — so the session tenant is clean every time, no
  multiplexing, no warm-pool bleed.
- **No-code-change fallback.** If the handler does *not* set it, inject the tenant at
  the connection layer through the lambda's **environment** (which the test owns):
  Vector A (a tenant role in `DATABASE_URL`) or Vector B (`options` in the DSN). Set
  it at **function-creation time** in the per-test fixture — the per-test/per-worker
  unique-resource rule already gives each test its own function to stamp:

  ```python
  await mini_lambda.create_function(
      FunctionName=f"rollup-{worker}-{test_id}",          # unique per test/worker
      Environment={"Variables": {"DATABASE_URL": dsn_for(tenant_a)}},
      ...,
  )
  ```

  (A function shared across tenants in one test can't be pinned by env — deploy
  per-test functions, which the isolation rules already push you toward.)

## Coverage audit — don't let the rule rot

Whichever level you run, add one meta-test that asserts **every tenant-scoped table
has RLS enabled and a policy** — it fails CI the moment someone adds a table and
forgets the policy (the real long-term leak source):

```sql
SELECT c.relname
FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
WHERE a.attname = 'tenant_id' AND c.relkind = 'r'
  AND (NOT c.relrowsecurity
       OR NOT EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname));
-- any row = a tenant table with no RLS / no policy
```

## Honest scope

- App-side `WHERE tenant_id` is still your first line; this is **defense in depth**.
- The no-code-change e2e path is a **detector**, not prod enforcement — prod gets the
  guard only when the app sets the tenant (the busydone plan) or you route per-tenant
  connections.
- Everything here is env-gated: roles/policies/audit are created only when the
  isolation switch is on, so prod is byte-for-byte unchanged when you don't opt in.

## Checklist

- [ ] Session tenant set via `SET LOCAL` / `set_config(..., true)` — never plain `SET`.
- [ ] App role is non-owner, non-superuser, no `BYPASSRLS`; tables `FORCE` RLS.
- [ ] Policy treats unset tenant as deny-all (`current_setting(..., true)` → NULL).
- [ ] RLS + audit live in migrations (prod-faithful) or a clearly env-gated fixture.
- [ ] Audit stamps both `app.current_tenant` and a caller id (`app.test_id` / request id).
- [ ] `pytest_sessionfinish` asserts no `declared_tenant <> row_tenant` rows.
- [ ] Coverage test asserts every `tenant_id` table has RLS + a policy.
- [ ] e2e: real handler sets the tenant from the scoped payload, or env-inject as fallback.
</content>
