### Command dispatch — HTTP requests → `http-runner` (Haiku)

| Command | Agent |
|---|---|
| `curl ...`, `wget ...`, hit an API endpoint, check a health URL, inspect a response/headers | `http-runner` |

Anti-patterns:

- `Bash(curl ...)` / `Bash(wget ...)` to call an API inline — response bodies (JSON/HTML) + `-v` header noise run to hundreds of lines and burn Opus/Sonnet tokens. Delegate to `http-runner` and act on its status + trimmed body.
- `curl http://localhost:... ` right after starting a service, with a `sleep` in front — don't poll by fixed delay; use the `wait-for-ready` skill, then delegate the request to `http-runner`.

Note: `http-runner` masks credentials, caps the body, and returns status + key headers + relevant fields. NOT for `curl | sh` installs (a shell action) or large file downloads. A trivial one-shot `curl -fsS .../health` you need the raw body of can stay inline.
