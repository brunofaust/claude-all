# Multi-tenant isolation — the tenant id, honored across every wall

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a
> condensed summary; this file holds the full depth.

A multi-tenant app leaks when one tenant's request touches another tenant's data,
process memory, scratch files, or cloud resources. Every `WHERE org_id = …` in the
app is the **first wall** — and a single missing filter, warm-process bleed, or bare
`/tmp` write puts it on the floor. This page is the **second wall** for each plane:
make a forgotten filter *structurally impossible* instead of merely discouraged.

**This is not optional and not "prod-only" hardening.** Two-layer isolation
(app-side filter + a wall that enforces it) is the baseline for a product where one
customer's data reaching another is an incident. What *is* tunable is how many walls
you build today; skip one and write down which failure you are accepting.

The spine: the tenant id **enters at exactly one boundary** (§0), and every plane
below must honor that same id — **data / RLS** (§1), **process memory** (§2),
**ephemeral disk** (§3), **AWS resources** (§4). §5 is how you *prove* it holds and
keep the rule from rotting.

Throughout, `org_id` is whatever your tenant key is — `org_id`, `account_id`,
`tenant_id`. A reserved sentinel value (`0` here) means "platform / cross-org
scope"; reserve it in the schema (`CHECK (org_id > 0)`) so no real tenant can ever
collide with it.

______________________________________________________________________

## §0 Boundary contracts — the tenant id has ONE source

Isolation is only as trustworthy as the moment the tenant id is *decided*. Decide it
once, at the entrypoint, from a source the caller cannot forge — then carry a
**typed proof** of that decision down every layer.

**Every entrypoint parses one typed context model as its first statement.** A Lambda
`event`, an SQS/SNS record, a Step Functions input, an HTTP request — all are
untrusted shape. Parse into a Pydantic model at line one of `main()`, before any
logic (→ [`data-modeling.md`](data-modeling.md)). Give each entrypoint an explicit
`org_required` declaration so the set of **platform-scope** handlers is a greppable
inventory, not folklore:

```python
class WorkerEvent(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    org_id: int
    execution_id: str


async def main(event: dict[str, Any]) -> None:
    parsed = WorkerEvent.model_validate(event)      # boundary parse — first line
    row = await load_execution(parsed.execution_id)
    if row.org_id != parsed.org_id:                 # integrity check vs loaded state
        raise TenantMismatchError(payload=parsed.org_id, stored=row.org_id)
    scope = TenantScope.for_org(parsed.org_id, source="worker-event")
    ...
```

**At the API, the ONLY org source is the authenticated token claim.** Never a path
param, query string, or body field — trusting a client-supplied `org_id` is the
textbook IDOR (a caller edits `?org_id=` and reads a stranger's data). The token is
the boundary; the claim is the id.

**In worker payloads the org is explicit AND integrity-checked.** A job carries its
`org_id` in the validated payload, and the handler re-checks it against the row/state
it loads (as above). A mismatch is a **named error that stops the run** — never a
silent "proceed with one of the two values".

**Carry a provenance-typed `TenantScope`, not a bare `org_id`.** A bare integer
flowing into the data layer cannot say *where it came from* — so a filter can be
invented mid-stack from an unvalidated value and nobody notices. Wrap it in a scope
with **blessed constructors** only:

```python
class TenantScope(BaseModel):
    """Proof that an org filter originated at a trust boundary.

    Data-layer functions accept a TenantScope, never a bare org_id, so a filter
    can never be conjured mid-stack from an unvalidated value. Construct only via
    the three classmethods.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    org_id: int
    origin: Literal["boundary", "explicit", "platform"]
    reason: str | None = None  # set when origin == "platform" (names the cross-org read)

    @classmethod
    def from_context(cls, ctx: RequestContext) -> "TenantScope":
        """The org came from the authenticated token claim (the API path)."""
        return cls(org_id=ctx.org_id, origin="boundary")

    @classmethod
    def for_org(cls, org_id: int, *, source: str) -> "TenantScope":
        """A worker acting for the org carried in its validated payload."""
        return cls(org_id=org_id, origin="explicit", reason=source)

    @classmethod
    def platform_scan(cls, *, reason: str) -> "TenantScope":
        """A deliberate cross-org read; `reason` documents why (greppable)."""
        return cls(org_id=0, origin="platform", reason=reason)
```

A checker bans bare `org_id: int` parameters on the data-owner modules (the ones that
build SQL / call the store) — they must take a `TenantScope`. That makes "this filter
came from the boundary" a type the reviewer can see, not a claim they must trust.

______________________________________________________________________

## §1 Data plane — Postgres RLS as the second wall

The app's `WHERE org_id = :org` is the first wall. Row-Level Security is the second:
even a query that *forgot* the filter can only ever see its own tenant's rows. RLS is
Postgres-specific; on MySQL/Aurora-MySQL you fall back to the app-side audit
instrument in §5. Examples assume Postgres.

### The facade owns every query and sets the session tenant

One data facade owns **all** tenant-scoped SQL. Each call opens a transaction and
stamps the session tenant with `set_config(..., is_local => true)` so it is
**transaction-scoped** — it evaporates at `COMMIT`/`ROLLBACK` and never leaks to the
next borrower of a pooled connection. (Plain session `SET` persists on the pooled
connection and leaks — never use it. `set_config(..., true)` is also the form that
survives PgBouncer transaction-mode pooling, since both are txn-scoped.)

```python
async def query(scope: TenantScope, stmt: Select | Insert | Update | Delete) -> ...:
    """Every tenant-scoped statement. Sets app.current_tenant for this txn only."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant', $1, true)", str(scope.org_id))
        ...  # run stmt — RLS now scopes it


async def query_system(stmt: ..., *, platform_scan: bool) -> ...:
    """Cross-org / platform reads. The kwarg is mandatory and greppable."""
    if not platform_scan:
        raise ValueError("query_system requires platform_scan=True — name the cross-org read")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant', '0', true)")  # sentinel
        ...
```

`query_system(..., platform_scan=True)` at **every** cross-org call site turns "who
reads across tenants?" into a `grep platform_scan=True` burn-down list — a small,
reviewable set instead of an invisible blanket.

### The reader function RAISES on unset — silent-empty is the trap

The dangerous default is `current_setting('app.current_tenant', true)` returning
`NULL` when unset, which makes `org_id = NULL` match nothing → a **silent empty
result**. Silent-empty hides the bug (a handler that forgot to set the tenant looks
like "no rows", not "misconfigured"). Opt out: a `STABLE` function that **raises**.

```sql
CREATE FUNCTION app_current_org_id() RETURNS bigint
LANGUAGE plpgsql STABLE AS $$
DECLARE v text := current_setting('app.current_tenant', true);
BEGIN
    IF v IS NULL OR v = '' THEN
        RAISE EXCEPTION 'app.current_tenant is not set — connection has no tenant scope';
    END IF;
    RETURN v::bigint;
END;
$$;
```

`STABLE`, not `VOLATILE`: the planner evaluates a `STABLE` function **once per
statement**, not once per row, so RLS stays cheap on large scans. (Only the
*audit/logging* function in §5 needs `VOLATILE`, because it writes a row.)

### ENABLE + FORCE + the sentinel policy

```sql
ALTER TABLE orders ADD CONSTRAINT orders_org_positive CHECK (org_id > 0);  -- reserves 0
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON orders
  USING      (org_id = app_current_org_id() OR app_current_org_id() = 0)
  WITH CHECK (org_id = app_current_org_id() OR app_current_org_id() = 0);
```

- **`FORCE`, not just `ENABLE`.** `ENABLE` exempts the table *owner*; a managed
  Postgres (RDS/Aurora/Cloud SQL) master user has no `BYPASSRLS` but frequently **is**
  the owner, so `ENABLE` alone would let your own app connection bypass the policy.
  `FORCE` makes even the owner obey.
- **`0` is the reserved platform sentinel.** `app_current_org_id() = 0` is the escape
  hatch used only by `query_system`. Reserve `0` at the schema level —
  `CHECK (org_id > 0)` on every tenant table, `CHECK (id > 0)` on the `orgs` PK — so
  no real tenant can ever equal the sentinel.
- **Fails closed on unset.** Because `app_current_org_id()` *raises* when the tenant
  is unset, a query on an unscoped connection errors loudly — it never silently
  matches the sentinel branch or returns empty.

Put policies + function in **migrations**, so prod and every test/LocalStack DB
(provisioned from the same migrations) carry the identical guard — then integration
tests validate the real wall, not a test-only shim.

### Coverage guard — fail CI when a new table ships without a policy

The real long-term leak source is someone adding an `org_id` table and forgetting the
policy. One meta-test closes it — it belongs in the suite so it runs in CI:

```sql
SELECT c.relname
FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
WHERE a.attname = 'org_id' AND c.relkind = 'r'
  AND (NOT c.relrowsecurity
       OR NOT c.relforcerowsecurity
       OR NOT EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname));
-- any row = an org_id table with RLS not ENABLEd, not FORCEd, or no policy
```

### Future hardenings to name (so they are a decision, not an oversight)

- **A non-owner app role.** Connect the app as a role that is neither the table owner
  nor a superuser nor `BYPASSRLS`. Then `FORCE` is belt-and-braces and no future
  `ENABLE`-only table can leak through ownership.
- **A separate platform DB principal.** Route the sentinel-`0` (`query_system`) path
  through a *distinct* database role, so a bug in ordinary tenant code physically
  cannot reach the cross-org escape hatch — only the platform principal can set `0`.

______________________________________________________________________

## §2 Process memory — the warm-start singleton/cache leak class

A process-global captures an org-bound value at **first construction** on a warm
worker, then serves it to a **different tenant** on the next (warm) reuse. This is the
subtlest leak because tests on a cold process never see it — it needs a warm reuse
across two tenants.

**One-shot containers are safe by construction; warm workers are the risk surface.**
A per-task Fargate container (one invocation, then it dies) cannot bleed — nothing
survives to serve the next tenant. A warm Lambda, an ECS *service*, or any long-lived
process is where this bites.

Rules:

- **Never a global cache on tenant-bound state.** A module-level singleton or
  `@cached` value that closes over one org's config/credentials/data is a leak
  waiting for the second tenant.
- **Key caches with the tenant id as a key *component* — and make it
  positional-only** so it can never be dropped from the signature:

  ```python
  @cached_async(...)
  async def get_persona(org_id: int, /, name: str) -> Persona:
      """org_id is positional-only (before the `/`) — it cannot be omitted, so the
      cache key always includes the tenant."""
      ...
  ```

- **Construct org-bound handlers per invocation**, from the parsed boundary context —
  never at module scope. The scope object from §0 is the input.
- **Credential-scoped client instances.** Build a *fresh* client wrapping explicit
  per-org credentials, rather than mutating a shared singleton's credentials in place
  (mutation races under concurrency and outlives the request).
- **Clear log contextvars before per-record bind.** `structlog.contextvars`
  (and any `logging` context) persists across invocations on a warm process; a prior
  request's `org_id` label sticks and **mislabels** the next tenant's logs. Call
  `structlog.contextvars.clear_contextvars()` at the top of each unit of work, then
  bind fresh.

**The audit taxonomy — re-run it periodically over every process-global.** Walk each
module-level singleton / cache / contextvar and classify it:

| Verdict            | Meaning                                                      | Action        |
| ------------------ | ----------------------------------------------------------- | ------------- |
| **SAFE-platform**  | holds only org-free platform config                         | leave         |
| **SAFE-org-keyed** | a cache whose key includes the tenant id                    | leave         |
| **SAFE-per-task**  | constructed per invocation; dies with it                    | leave         |
| **SAFE-stateless** | captures no state                                           | leave         |
| **LEAK**           | captures one org's value, serves it to another on reuse     | **fix now**   |

The sweep is cheap and catches the regression a new singleton introduces. Schedule it
like the coverage guard — a periodic, written audit, not a one-time cleanup.

______________________________________________________________________

## §3 Ephemeral disk — `/tmp` isolation

Scratch disk (`/tmp` on Lambda, the task's ephemeral volume on Fargate) is shared
across invocations on a warm container. Two failure classes live here:

1. **Cross-org content at rest** — org A writes `/tmp/work.parquet`, org B's warm
   invocation reads it. The obvious one.
2. **Same-tenant collisions between executions** — two runs *of the same org* both
   write `/tmp/work.parquet` and clobber each other. Nobody audits this one, and it
   corrupts results without ever crossing a tenant boundary.

**Org-first layout for ALL scratch, through ONE path-owner module.** Nothing writes a
bare `/tmp` path (checker-enforced: ban the literal `/tmp/` string outside the path
owner). The layout kills both classes at once:

```
/tmp/{org_id}/{execution_id}/   ← all per-run scratch, org- AND execution-scoped
/tmp/_cache/                    ← deliberately warm-shared org caches (bounded LRU)
/tmp/_platform/                 ← org-free platform scratch
```

`_cache/` is the *only* deliberately-shared area; it holds bounded LRU caches with
size watermarks (a warm cache is a feature there, sharing is intentional and keyed).
`_platform/` is org-free scratch. Everything else is `{org_id}/{execution_id}/`.

```python
def scratch_dir(scope: TenantScope, execution_id: str) -> Path:
    """The ONLY place a scratch path is built. Org-first, execution-scoped."""
    return Path("/tmp") / str(scope.org_id) / execution_id


def cold_start_sweep(own_execution_id: str) -> None:
    """SIGKILL (timeout / OOM) bypasses `finally`, so a prior run's scratch leaks.
    There is exactly ONE invocation per container, so any execution-dir that is not
    ours is an orphan of a killed prior run — delete them at handler init."""
    for org_dir in Path("/tmp").iterdir():
        if org_dir.name in {"_cache", "_platform"} or not org_dir.is_dir():
            continue
        for exec_dir in org_dir.iterdir():
            if exec_dir.name != own_execution_id:
                shutil.rmtree(exec_dir, ignore_errors=True)
```

**Cold-start sweep, because `finally` is not guaranteed.** A timeout or OOM
`SIGKILL`s the process mid-run — your `try/finally` cleanup never executes, so scratch
accumulates across warm reuses. Since one container serves one invocation at a time,
the invariant is simple: at cold start, **every execution-dir that isn't your own is
an orphan** — delete it. This bounds disk regardless of how the previous run died.

**Size the disk against the cache watermarks.** Lambda's default `/tmp` is 512 MB. A
400 MB `_cache/` watermark leaves 112 MB for live scratch → `ENOSPC` under load. Set
ephemeral storage explicitly to **sum(watermarks) + working scratch headroom**, and
treat the watermark and the provisioned size as a single wired pair (change one,
re-check the other).

______________________________________________________________________

## §4 AWS resources — ABAC with STS session tags ("RLS for AWS resources")

RLS scopes *rows*; ABAC scopes *cloud resources*. **One** customer IAM role, with
every grant conditioned on `${aws:PrincipalTag/org_id}`. The worker assumes that role
with a session tag `org_id=<n>`, and every grant self-scopes to that tenant. No
per-org roles to provision; the tag is the scope.

### SPIKE FIRST, per service — the support matrix is learned, not documented

Whether session tags actually scope a given service is **service-specific and often
documented incorrectly**. Run a live spike per service before you rely on it; do not
trust the docs. What real spikes have found:

| Service                          | Session-tag scoping | How / caveat                                                                                                   |
| -------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------- |
| **S3**                           | **YES**             | prefix policies keyed on `${aws:PrincipalTag/org_id}`                                                          |
| **Vector store (per-org index)** | **YES**             | grant scoped to the org's index ARN(s)                                                                          |
| **DynamoDB**                     | **YES — carefully** | `dynamodb:LeadingKeys` works **only where the partition key LEADS with the tenant id**. Audit pk shapes: scope-prefixed keys need explicit key patterns; keys with no org component stay **platform** (not tenant-scopable this way). |
| **Catalog / table store (Iceberg-style)** | **often NO** | session tags are engine **trust lists**, not row selectors. Row filters bind to **principal + grant** → mint a **per-org filter + grant** (automatable at org-creation), or front it with a **trusted query layer** (the app injects `WHERE org_id` from the authenticated `TenantScope`). |

The takeaway: a service that stores rows behind a query engine (catalog/table stores)
usually can't be row-scoped by a session tag at all — the tag gates *access to the
engine*, not *which rows come back*. Fall back to per-org grants or a trusted query
layer that carries the boundary scope.

### Operational rules

- **Lazy minting.** Assume the tagged role only where tenant AWS is actually touched —
  not on every invocation.
- **Org-keyed credential cache with expiry refresh.** Call STS `AssumeRole` **once per
  org per session lifetime**, not per request, and cache the credentials keyed by org
  with an expiry-aware refresh. This is throttle math: `AssumeRole` is rate-limited, so
  per-call minting throttles at scale. Bound the cache (LRU) and use the **regional**
  STS endpoint (the global endpoint adds latency and a shared throttle).
- **FAIL-CLOSED on mint failure.** If `AssumeRole` fails, **error** — never silently
  fall back to the platform role. The silent fallback is simultaneously a cross-tenant
  data path *and* a platform-billing leak.
- **Never pass STS creds through orchestration payloads.** Role-chaining caps the
  session at 1 hour *and* puts live tokens in transit (Step Functions input, SQS body,
  logs). Instead, the worker assumes the tagged role **itself**, from the `org_id` in
  its own validated payload. Tokens are minted at the point of use and never serialized.

### The structural win — billing isolation as IAM, not code review

Give the customer role **no ai-model (Bedrock/LLM) permissions at all**. Then "never
bill the platform for a tenant's LLM call" stops being a rule a reviewer has to
remember and becomes an **IAM boundary**: tenant-scoped work physically cannot invoke
the model, and the (deliberately platform-billed) LLM call runs under the platform
role by construction. Push every "must never happen" you can into the *shape of the
role* — a permission the tenant role lacks can't be misused.

______________________________________________________________________

## §5 Proving it holds — audit, e2e, and keeping the rule alive

Enforcement (§1–§4) makes leaks impossible; this section makes leaks **visible in
tests** and keeps the walls from rotting. The RLS enforcing policy and the
non-blocking audit policy below are alternatives selected by **environment** — run
enforcing in prod, audit in e2e — never stacked on the same table.

### Non-blocking audit — log foreign-tenant access without blocking

An audit-only RLS policy leaves results unchanged but **logs** any foreign-tenant row
access. One `FOR ALL` policy with the log function in **both** `USING` and
`WITH CHECK` fires across every DML — including `SELECT`, which plain triggers can't
see:

```sql
CREATE FUNCTION audit_tenant_access(row_org bigint, phase text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER AS $$
DECLARE declared text := current_setting('app.current_tenant', true);
BEGIN
    IF declared IS NULL OR row_org::text IS DISTINCT FROM declared THEN
        INSERT INTO audit.tenant_access (declared_org, row_org, phase, caller_id, at)
        VALUES (declared, row_org, phase, current_setting('app.caller_id', true), clock_timestamp());
    END IF;
    RETURN true;  -- audit-only: never blocks, results unchanged
END;
$$;

CREATE POLICY tenant_audit ON orders
  FOR ALL
  USING      (audit_tenant_access(org_id, 'read'))    -- existing rows: SELECT/UPDATE/DELETE
  WITH CHECK (audit_tenant_access(org_id, 'write'));   -- new rows: INSERT/UPDATE
```

`USING` evaluates existing rows, `WITH CHECK` new-row values; `UPDATE` logs twice
(old via `read`, new via `write`) — catching both *reading* a foreign row and
*writing* a foreign org value. `MERGE` is covered because Postgres decomposes it into
its INSERT/UPDATE/DELETE actions.

**Never stack audit on enforcement.** The audit policy is *permissive* and always
returns `true`; permissive policies are **OR-combined**, so beside an enforcing policy
it makes every row visible and **defeats enforcement**. Separate them by environment.
(A `RESTRICTIVE` audit policy AND-short-circuits and skips exactly the foreign rows
you want logged — so keep them apart, not layered.)

**Read-precision caveat.** RLS `USING` quals are security-barrier expressions;
Postgres may evaluate them on more rows than the query returns, and the exact set is
plan-dependent. Read an audit row as *"this session reached into another tenant's
data,"* not a byte-exact returned-row count. For an exact "the rows the app **got**
contained foreign rows" check, inspect returned rows app-side in the **test**
connection (a SQLAlchemy `after_cursor_execute` hook), never in product code.

**Stamp the caller.** Set a second txn-local GUC —
`set_config('app.caller_id', '<request/test id>', true)` — so every audited row records
*who* caused it. **Assert at shutdown** (session teardown / `pytest_sessionfinish`):

```sql
SELECT caller_id, declared_org, row_org
FROM audit.tenant_access
WHERE declared_org IS DISTINCT FROM row_org;   -- any row = a leak; group by caller_id
```

### e2e with real (unchanged) workers

When e2e runs the **real** binaries (in LocalStack or equivalent), you cannot edit
them — but you don't need to if the handler already sets the tenant from its scoped
payload (§0). Then the real worker stamps `app.current_tenant` itself and e2e needs
nothing extra; this dovetails with scoped processes
([`scoped-processes.md`](scoped-processes.md)) and the multi-tenant e2e isolation
rules ([`e2e-testing.md`](e2e-testing.md)). If the handler does *not* set it, inject
the tenant at the connection layer via the function's **environment** (a tenant role
in `DATABASE_URL`, or `app.current_tenant` in the DSN `options`) at
function-creation time in the per-test fixture — the per-test unique-resource rule
already gives each test its own function to stamp.

### Sweeps that keep every wall honest

Re-run these on a schedule (and wire the mechanical ones into CI):

- **RLS coverage guard** (§1) — every `org_id` table has ENABLE + FORCE + a policy.
- **`platform_scan=True` inventory** (§0/§1) — the full, reviewed list of cross-org
  readers; anything new is a deliberate decision.
- **Warm-start taxonomy sweep** (§2) — classify every process-global; any `LEAK`
  verdict is a fix-now.
- **Bare-`/tmp` checker** (§3) — nothing builds a scratch path outside the path owner.
- **Bare-`org_id` checker** (§0) — data-owner functions take a `TenantScope`, not a
  loose int.

______________________________________________________________________

## Honest scope

- App-side `WHERE org_id` remains the **first** wall; everything here is the second —
  **defense in depth**, and both layers are expected in a real product.
- A wall you skip is a failure you are *accepting* — write down which one and why (the
  audit-only path is a *detector*, not prod enforcement; per-org grants may lag behind
  a trusted query layer for catalog stores; a warm service without a taxonomy sweep is
  a standing risk). Name the gap; don't let it be silent.

## Checklist

- [ ] Every entrypoint parses one typed context model first; `org_required` is an explicit, greppable per-handler declaration.
- [ ] API org id comes **only** from the auth token claim — never a client param (IDOR).
- [ ] Worker payload org is explicit AND integrity-checked against loaded state; mismatch = named error, stop.
- [ ] Data-layer functions take a provenance-typed `TenantScope` (blessed constructors), not a bare `org_id`; checker enforces it.
- [ ] Facade owns all queries; session tenant via `set_config(..., true)` — never plain `SET`.
- [ ] `app_current_org_id()` is `STABLE` and **RAISES** on unset (no silent-empty).
- [ ] Tables `ENABLE` **and** `FORCE` RLS; policy is `USING/WITH CHECK (org_id = fn() OR fn() = 0)`.
- [ ] `0` reserved as the platform sentinel via `CHECK (org_id > 0)`; `query_system` requires `platform_scan=True` per call site.
- [ ] Coverage guard test fails CI on any `org_id` table lacking ENABLE/FORCE/policy.
- [ ] No global cache on tenant-bound state; caches key the tenant id (positional-only in the signature).
- [ ] Org-bound handlers built per invocation; credential-scoped client instances, not mutated singletons.
- [ ] Log contextvars cleared before per-record bind; warm-start taxonomy sweep run periodically (no `LEAK`).
- [ ] All scratch via the one path owner: `/tmp/{org_id}/{execution_id}/`; `_cache/`, `_platform/` are the only shared dirs; bare `/tmp` checker on.
- [ ] Cold-start sweep deletes every non-own execution-dir (SIGKILL bypasses `finally`); ephemeral disk sized above cache watermarks.
- [ ] AWS: one tag-conditioned customer role; per-service support **spiked live**; STS minted lazily, org-keyed cache, regional endpoint, FAIL-CLOSED, never chained through payloads.
- [ ] Customer role has **no** ai-model permissions (billing isolation as IAM).
- [ ] Enforce vs audit kept on separate environments; audit stamps a caller id; shutdown asserts no `declared_org <> row_org`.
