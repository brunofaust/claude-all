---
name: wait-for-ready
description: >-
  Wait for a service, container, port, or database to become healthy by POLLING until ready —
  instead of a fixed `sleep N`. Use whenever you just started something and need to wait before
  the next step: after `docker compose up` / `docker run`, after starting a dev server or API,
  before running smoke tests or `curl` against a just-started endpoint, before connecting to a
  freshly-started Postgres/Redis. Triggers on "wait for the container", "wait until it's up",
  "wait for the server to be ready", "sleep then curl", "poll until healthy", "is the service up
  yet", "give it a few seconds then hit the endpoint". A fixed `sleep` is the wrong tool — too
  short and the probe fails, too long and you waste the wait; poll with a timeout + interval and
  fail fast instead.
disable-model-invocation: false
---

# wait-for-ready

Replace `sleep N && <probe>` with a bounded poll loop: try the probe every
`INTERVAL` seconds up to a `TIMEOUT`, succeed the instant it's ready, and fail
loudly (non-zero) if the timeout is hit. Never block on a fixed delay.

## Generic poller

```bash
# wait_until "<description>" <timeout_s> <interval_s> <probe-command...>
wait_until() {
  local desc="$1" timeout="$2" interval="$3"; shift 3
  local deadline=$(( $(date +%s) + timeout ))
  until "$@" >/dev/null 2>&1; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "wait-for-ready: TIMEOUT after ${timeout}s waiting for ${desc}" >&2
      return 1
    fi
    sleep "$interval"
  done
  echo "wait-for-ready: ${desc} ready"
}
```

## Common probes

```bash
# HTTP endpoint returns 2xx/3xx (curl --fail is non-zero on >=400)
wait_until "API /health" 60 1 curl -fsS http://localhost:8080/health

# TCP port open (no curl needed)
wait_until "port 5432" 30 1 bash -c 'exec 3<>/dev/tcp/localhost/5432'

# Postgres accepting connections
wait_until "postgres" 60 2 pg_isready -h localhost -p 5432 -q

# Docker container reports healthy (needs a HEALTHCHECK in the image)
wait_until "db healthy" 90 2 \
  bash -c '[ "$(docker inspect -f "{{.State.Health.Status}}" mydb 2>/dev/null)" = healthy ]'

# Compose service is up
wait_until "web up" 60 2 bash -c 'docker compose ps web | grep -q "Up\|running"'
```

## Rules

- **Always set a timeout** — an unbounded poll is just a different hang. Pick a
  ceiling generous enough for a cold start (compose stacks: 60–120s).
- **Probe the real readiness signal**, not a proxy: HTTP health route > port
  open > process exists. "Port open" can be true before the app can serve.
- **Fail loud:** return non-zero on timeout and print what you were waiting for,
  so the caller stops instead of charging ahead into a flaky failure.
- **Long genuine waits run in the background**, not blocking the session.
- Prefer the platform's own waiter when it exists (`docker compose up --wait`,
  `kubectl wait --for=condition=ready`, `pg_isready`) over a hand-rolled loop.
