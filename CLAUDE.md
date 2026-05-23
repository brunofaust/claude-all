# claude-all — contribution guidelines

## Naming conventions — always use generic placeholders

All examples, agent prompts, skill documentation, and config snippets must use
fictional, generic names. Never embed real project names, company names, domain
names, or internal tool names from any specific codebase.

### Approved placeholder names

| Category            | Use these                                  |
| ------------------- | ------------------------------------------ |
| Project / app       | `myapp`, `my-service`, `my-project`        |
| Company / org       | `mycompany`, `Acme Inc`, `acme`            |
| Domain              | `example.com`, `acme.example.com`          |
| AWS resource prefix | `myapp-dev-`, `myapp-prod-`                |
| GitHub repo         | `myorg/myapp`, `brunofaust/myapp`          |
| Ticket prefix       | `TICK-`, `APP-`                            |
| DB / secret path    | `myapp/dev/db-credentials`                 |
| Lambda functions    | `myapp-dev-dispatcher`, `myapp-dev-worker` |
| DynamoDB tables     | `myapp-dev-tickets`, `myapp-dev-run-locks` |
| Docker images       | `myapp:latest`                             |
| Python modules      | `src/myapp/handlers/`                      |
| Secret values       | `••••••` or `<redacted>`                   |

### Never use

- Real project names from any client or employer codebase
- Real internal tool or hook names (e.g. private GitHub repos used as prek hooks)
    are fine in actual config files (`prek.toml`) but must not appear in skill
    documentation examples — use `myorg/myhook` instead
- Real email addresses in examples — use `user@example.com`
- Real AWS account IDs — use `123456789012`
- Real ARNs — use `arn:aws:lambda:us-east-1:123456789012:function:myapp-dev-worker`

## Skills and agents — keep them generic

Skills and agents in this repo are shared tooling. They must work for any
project without exposing implementation details of any specific one.

- **No project-specific architecture** in skill/agent body copy (flows, table
    schemas, Lambda naming patterns specific to one app)
- **No project-specific ticket IDs** (use `TICK-1`, `TICK-2`)
- **No project-specific AWS resource names** in examples (use the placeholders above)
- If a skill was originally written for a specific project, strip all project
    specifics before committing it here

## prek.toml

Real hook repos (including private ones like `brunofaust/codecongruence`) are
allowed in `prek.toml` because that file is functional config, not documentation.
But their names must not appear in skill documentation examples — use
`myorg/myhook` as the placeholder in SKILL.md files.
