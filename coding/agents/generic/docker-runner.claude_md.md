### Command dispatch — docker / compose → `docker-runner` (Haiku)

| Command | Agent |
|---|---|
| `docker build`, `docker run`, `docker exec`, `docker logs`, `docker ps`, `docker images`, `docker compose up/down/restart/logs` | `docker-runner` |

Anti-patterns:

- `Bash(docker build ...)` / `Bash(docker compose up ...)` / `Bash(docker logs ...)` — build output is hundreds of layer-cache lines and logs run to thousands; both burn Opus/Sonnet tokens. Delegate to `docker-runner` and act on its summary.
- The `docker run ... && sleep N && curl ...` readiness loop — don't hand-roll fixed-delay health waits inline. Delegate the docker part to `docker-runner` and use the `wait-for-ready` skill for the poll.
- `Bash(cd "/path" && docker compose ...)` — the `cd` prefix does NOT exempt it; delegate with the path in the prompt.

Note: `docker-runner` runs the command and returns a tight summary (image id + size on build, last meaningful log lines on logs, container table on ps). `push` only when explicitly asked. A trivial one-shot check (`docker ps -q`, single container name/health) can stay inline.
