## Secrets in the shell — fetch at point of use, never print

For an ad-hoc secret needed in a shell command (NOT app config — app env vars belong in `.env` / your config system, read via the app's config layer), fetch it from a secret store at the point of use. Prefer the OS keychain or a secrets manager over a plaintext `.env` for single values.

- **macOS Keychain — store once** (the user runs this, not the agent): `security add-generic-password -a "$USER" -s "MY_SECRET_KEY" -w` — prompts for the value; add `-U` to overwrite an existing key.
- **Read ONLY inside command substitution** feeding the consumer, so the value is never printed: `SOME_TOKEN="$(security find-generic-password -a "$USER" -s "MY_SECRET_KEY" -w)" one-shot-cmd …`
- **🔴 NEVER run `security find-generic-password … -w` (or any secret read) bare / on its own line.** The value prints to stdout and lands in the transcript verbatim — same leak class as `aws … --output text`. Only ever `$(…)`-captured into the same command.
- A one-shot env var the user exports in their own shell is also fine — read it as `$VAR` / from the process environment, never echo it.
- **Dedicated agents win** for their command class (cloud secrets managers, DB queries, GitHub via `gh`). The keychain path is the fallback for the long tail with no agent.
