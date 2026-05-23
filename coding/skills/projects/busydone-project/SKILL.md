# busydone-project — Project Context Skill

> Invoke this skill when working in the `busydone` repository. It caches domain knowledge
> that would otherwise be re-discovered each session from scratch.

## When to invoke

- Any task in the `busydone` repo
- Debugging dispatcher → steps → invoke-service → post-results flows
- Investigating DDB table state, SQS queues, Lambda logs
- Understanding ticket status transitions or re-engage logic

______________________________________________________________________

## Project Purpose

Autonomous JIRA ticket analysis and implementation SaaS pipeline.
Processes tickets through a state machine using cloud AI SDKs (Anthropic / OpenAI / Bedrock BYOK)
inside a one-shot Fargate container (`invoke-service`).
Full-stack: FastAPI + React, multi-tenant, Stripe billing.
**Production-grade decisions over scaffolding shortcuts.**

______________________________________________________________________

## Lambda Functions

Pattern: `busydone-{env}-<name>` (env = `dev` / `prod`)

| Lambda                | Trigger            | Purpose                                                                 |
| --------------------- | ------------------ | ----------------------------------------------------------------------- |
| `api`                 | API GW             | FastAPI ASGI via Mangum, 20 routers                                     |
| `dispatcher`          | EventBridge 5 min  | Prefetch connectors, fan-out to SQS, run re-engage                      |
| `steps`               | SQS                | Process tickets per step in parallel                                    |
| `connector`           | SQS                | Fetch connector content, run extractor, write execution-state DDB       |
| `connector-doc`       | SQS (`doc-fetch`)  | Fetch + upsert `extracted_documents`                                    |
| `doc-dispatcher`      | EventBridge 15 min | Fan out doc/web/repo connectors to `doc-fetch` queue                    |
| `db-writer`           | SQS                | Drain `ledger-fallback` queue → DDB                                     |
| `embed`               | SQS                | Chunk, embed (Bedrock Titan V2), upsert S3 Vectors                      |
| `post-results`        | SF task + EB       | Post Jira comment, transition status, write `content_hash_processed`    |
| `check-ci-status`     | SF task            | Poll CI status in coding pipeline                                       |
| `build-retry-prompt`  | SF task            | Build retry prompt after CI failure                                     |
| `sf-settle-timeout`   | SF task            | Handle Step Functions timeout settlement                                |
| `downgrade-scheduler` | EventBridge daily  | Apply scheduled plan downgrades from `plan_changes`                     |
| `abuse-detection`     | EventBridge 06+18h | 4-layer free-tier abuse detection                                       |
| `money`               | API GW             | `/reserve`, `/started`, `/checkpoint`, `/finished` — metering + billing |

ECS Fargate: `invoke-service` (`busydone-{env}-invoke-service`) — one-shot AI coding loop.

______________________________________________________________________

## DynamoDB Tables

Pattern: `busydone-{env}-<name>`

| Table              | PK                                                  | SK                                          | Notes                                    |
| ------------------ | --------------------------------------------------- | ------------------------------------------- | ---------------------------------------- |
| `run-locks`        | `ORG#{org_id}#TICKET#{key}#STEP`                    | —                                           | Idempotency guard; TTL-cleared           |
| `execution-state`  | `{execution_guid}#{connector_id}`                   | subject path                                | Pre-loaded config + ticket data; 24h TTL |
| `llm-usage-ledger` | `{org_id}#{call_group_id}`                          | `{turn_number}#{event_type}`                | Permanent billing audit                  |
| `step-progress`    | `step_progress#{org_id}#{conn}#{proj}#{key}#{step}` | `data`                                      | Single-writer gate; 1h TTL safety net    |
| `ticket-errors`    | org_id (N)                                          | `t#{conn}#{key}` / `m#{model}` / `p#{proj}` | Per-org error registry with retry count  |
| `poll-state`       | `{connector_id}`                                    | —                                           | Last extraction timestamp per connector  |
| `onboarding`       | `ORG#{org_id}`                                      | `STATE`                                     | In-flight wizard state; 30d TTL          |
| `onboarded`        | —                                                   | —                                           | Permanent onboarding completion marker   |

______________________________________________________________________

## SQS Queues

Pattern: `busydone-{env}-<name>` — every queue has a paired DLQ.

- `steps` / `connector` / `doc-fetch` / `embed` — main processing queues
- `abuse-observations` — API rate-limit events
- `ledger-fallback` — 3-layer LLM usage durability
- `emails` — outbound email generation

______________________________________________________________________

## Key Env Vars

| Var                              | Notes                                   |
| -------------------------------- | --------------------------------------- |
| `BEDROCK_CLASSIFY_MODEL`         | Currently `nvidia.nemotron-nano-3-30b`  |
| `BEDROCK_EMBED_MODEL_ID`         | `amazon.titan-embed-text-v2:0`          |
| `BEDROCK_RERANK_MODEL_ID`        | `amazon.rerank-v1:0`                    |
| `ONBOARDING_LLM_MODEL`           | `claude-sonnet-4-20250514`              |
| `STEP_MAX_CONCURRENT`            | `5`                                     |
| `INVOKE_SERVICE_MAX_TOOL_ROUNDS` | `50`                                    |
| `INVOKE_SERVICE_TIMEOUT_SECONDS` | `3600`                                  |
| `LINT_ENABLED` / `LINT_MAX_ITER` | `true` / `3`                            |
| `BUSYDONE_SECRETS_NAME_PREFIX`   | SSM prefix for per-org customer secrets |

No `.env` files at runtime — all injected by Terraform from `infra/envs/{env}.tfvars`.
Customer secrets → SSM Parameter Store. Platform secrets → Secrets Manager.

______________________________________________________________________

## Make Targets

| Target                                    | What it does                                             |
| ----------------------------------------- | -------------------------------------------------------- |
| `make deploy-lambda ENV=dev`              | Deploy Lambda ZIP (API + workers)                        |
| `make deploy-invoke-service ENV=dev`      | Build + push invoke-service ECS image to ECR             |
| `make deploy-frontend ENV=dev`            | Sync React build to S3, invalidate CloudFront            |
| `make migrate ENV=prod`                   | Run Alembic DB migrations                                |
| `make test-lambdas ENV=dev`               | Cold-start probe for all Lambdas — MUST run after deploy |
| `make status`                             | Show all service statuses                                |
| `make logs ENV=prod`                      | Tail service logs                                        |
| `make validate-ai-model MODEL=42 ENV=dev` | Smoke-test an AI model row before enabling               |

**Lambda deploys → always delegate to `aws-lambda-deployer`, never raw `aws lambda` CLI.**

______________________________________________________________________

## End-to-End Flow

```
EventBridge (5 min) → dispatcher Lambda
  → prefetch: has_updates_since() per connector (skip if no updates)
  → money /reserve (per connector)
  → SQS (connector queue) → connector Lambda
    → extractor: if content_hash changed → SQS (steps queue) → steps Lambda
    → SQS (embed queue) → embed Lambda
  → re-engage: WHERE content_hash IS DISTINCT FROM content_hash_processed
    → SQS (steps queue) → steps Lambda

steps Lambda → Step Functions state machine
  → SDKEcs (invoke-service Fargate one-shot)
  → ReadInvokeResult → ExtractSDKResult → SetSDKOutput → PostResults

invoke-service (Fargate)
  → Workspace.prepare()     # shallow clone + feature branch
  → AI SDK loop             # CompositeToolHandler: file_read, file_write, bash
  → lint loop               # prek up to LINT_MAX_ITER=3 rounds
  → Workspace.commit_and_push()
  → PR opened

post-results Lambda
  → Jira comment + status transition
  → writes content_hash_processed
  → releases step_progress lock
```

______________________________________________________________________

## Key Field Semantics

| Field                    | Meaning                                                                                                                                              |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `content_hash`           | SHA-256 of ticket summary+description+status+comments. Written by connector on any source change. Busydone's own comments excluded to prevent loops. |
| `content_hash_processed` | Written by `post_results_handler` after successful Jira transition. "Work for this version is done."                                                 |
| `content_hash_embedded`  | Written after S3 Vectors upsert. Stale vector detection, NOT a re-engage gate.                                                                       |
| `step_progress` lock     | Acquired before SQS SendMessage to steps. Released by post-results. TTL 1h safety net.                                                               |
| `run_locks`              | Idempotency guard for steps/hooks Lambda invocations.                                                                                                |

**Re-engage condition:** `content_hash IS DISTINCT FROM content_hash_processed` = ticket crashed mid-flight.

______________________________________________________________________

## Jira Status Transitions

| Status          | Phase | What it means                                                                                     |
| --------------- | ----- | ------------------------------------------------------------------------------------------------- |
| `[AI Analysis]` | 1     | Analyzing ticket for ambiguities (SDK Lambda, not SF)                                             |
| `[AI Question]` | 1     | Posted clarifying questions; waiting for human answer                                             |
| `[AI Ready]`    | 1→2   | No more questions; ready to implement                                                             |
| `[AI Coding]`   | 2     | SF pipeline running: invoke-service implementing                                                  |
| `[In Review]`   | done  | PR opened, human review needed                                                                    |
| `[AI Issues]`   | error | Unrecoverable error (any phase). DDB error row deleted on transition → clean slate for re-trigger |

Event types in `project_status_mappings`: `trigger`, `on_start`, `success`, `error`.

______________________________________________________________________

## Model Selection Chain

1. Step model → Persona model → Org model → `""` (empty = internal model)
1. Resolution: `step_logic._resolve_ai_config()`
1. `ai_models.runner` field controls routing: `'anthropic'` / `'openai'` / `'bedrock-*'` → invoke-service ECS; `''` → internal Lambda model
1. BYOK: per-org keys from SSM at point of use (`_CALLER_ACCOUNT` table in `ai_model.py`)
1. `BEDROCK_CLASSIFY_MODEL` env var selects the classifier DB row
1. `is_active`: BOTH `ai_providers.is_active` AND `ai_models.is_active` must be true
1. **`am."type"` must always be quoted** — `type` is a PostgreSQL reserved word

______________________________________________________________________

## Debugging Quick Reference

| Symptom                                | First check                                                              |
| -------------------------------------- | ------------------------------------------------------------------------ |
| Ticket stuck, not re-engaging          | `content_hash != content_hash_processed`? Check `step-progress` lock TTL |
| Dispatcher running but no SQS messages | `has_updates_since()` returning False? Check `poll-state` DDB            |
| invoke-service not starting            | `run-locks` entry exists? Check ECS task definition revision             |
| Post-results not firing                | SF execution status? Check `post-results` Lambda DLQ                     |
| Wrong model being selected             | `ai_models.is_active` both provider + model? `runner` field set?         |

For multi-service investigation → `incident-responder` agent first, not raw `aws` chains.

______________________________________________________________________

## Agent Dispatch Rules (busydone-specific)

| Task                                 | Agent                                           |
| ------------------------------------ | ----------------------------------------------- |
| `make deploy-lambda ENV=*`           | `aws-lambda-deployer`                           |
| `make deploy-invoke-service ENV=*`   | `aws-lambda-deployer`                           |
| `make test-lambdas ENV=*`            | `aws-lambda-deployer`                           |
| CloudWatch logs for any Lambda       | `cloudwatch-inspector`                          |
| DDB reads (run-locks, step-progress) | `dynamodb-inspector`                            |
| DDB writes / deletes                 | `dynamodb-mutator` + explicit user confirmation |
| SQS queue depth / DLQ peek           | `sqs-monitor`                                   |
| SF execution trace                   | `step-functions-tracer`                         |
| "tickets stuck / flow broken"        | `incident-responder`                            |
| "run dispatcher + check" loops       | `e2e-scenario-runner`                           |
