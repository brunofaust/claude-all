### `docker-log-inspector` (Haiku) — Docker container logs + crash diagnosis
| `docker logs`, `docker compose logs`, "why did the container crash", "find errors in the app container", "is it crash-looping", "OOMKilled?" | `docker-log-inspector` |
⛔ `Bash(docker logs ...)`, `Bash(docker compose logs ...)`, `Bash(docker inspect ...)` inline for reading/diagnosing logs
Note: read-only (logs + inspection). For build/run/up/down/restart use `docker-runner`; for logs already in context use `log-filter`.
