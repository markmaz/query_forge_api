# QueryForge API

## Start Here: Local Runtime Servers

Run these from `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api` with the virtual environment activated:

```bash
source .venv/bin/activate
```

Start the Flask API:

```bash
python app/main.py
```

Start the Celery worker in a separate terminal:

```bash
celery -A app.celery_app worker --loglevel=INFO
```

Start Celery Beat in a separate terminal:

```bash
celery -A app.celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
```

Start the standalone MCP server in a separate terminal:

```bash
python -m mcp_server
```

Local default URLs:

- Flask API: `http://127.0.0.1:5000`
- MCP server: `http://127.0.0.1:8001/mcp`

Keep both the Celery worker and Celery Beat running for Skills scheduling and Workflow Studio runtime work such as due timeouts, notification dispatch, schedule dispatch, dataset artifact expiration, and raw webhook payload cleanup.

QueryForge API is the Python backend for QueryForge. It serves three related runtime surfaces:

- the primary Flask REST API behind Gunicorn
- Celery workers for async/background jobs
- the standalone QueryForge MCP server for governed AI access

This README is the operational source of truth for backend development, configuration, Docker, and runtime behavior.

## Runtime Components

### Flask API

- entrypoint: `wsgi:app`
- factory: `app/factory.py:create_app`
- default local port: `5000` when running with `python app/main.py`
- default container port: `8000`

### Celery worker

- app: `app.celery_app`
- purpose: async tasks, ingestion, scheduled/background jobs

### Celery Beat

- app: `app.celery_app`
- purpose: scheduled dispatch for Skills and FlowForge runtime maintenance
- required for FlowForge production runtime because it dispatches due human-task timeouts, pending notification delivery, and raw webhook payload retention cleanup

### QueryForge MCP server

- module: `mcp_server`
- entrypoint: `python -m mcp_server`
- default local/container port: `8001`
- streamable HTTP path: `/mcp`
- auth model: bearer token only
- execution model: preview-only governed query execution, no raw SQL input from clients

### FlowForge module

- backend package: `app/features/flowforge`
- frontend route: `/automation/flowforge`
- API namespace: `/api/v1/flowforge`
- feature gate: workspace feature `flowforge` plus `flowforge:user` or higher effective access
- initial behavior: seeded Therapist Intake Routing workflow, graph validation, persisted integration intake, durable run creation, Celery-backed basic runtime dispatch, runtime matching evaluation persistence, pending notification email dispatch, run/event visibility, operator timeline notes, run-scoped human task reads, signed public action tokens, no-match notification audit rows, report summaries, workflow version publish controls, and initial MCP FlowForge tools
- runtime direction: event-first state-machine execution that supports loops, human decisions, wait states, timeouts, retries, and audit capture
- LLM-assisted matching-rule drafting uses the workspace LLM role `flowforge_rule_drafting`; do not configure FlowForge rule drafting through standalone env vars

Backend package layout:

- `app/features/flowforge/routes/` keeps endpoint-family modules for workflows, integrations, resources, matching policies, runs, and webhooks while preserving `flowforge_ns` as the public route import.
- `app/features/flowforge/service/` keeps the public `FlowForgeService` facade and splits orchestration into workflow, integration, webhook, trigger-evaluation, resource, run, signed-action, notification, report, and matching-policy mixins.
- `app/features/flowforge/schemas/` groups Swagger models by payload family and preserves `register_models(namespace)` as the public schema import.
- `app/features/flowforge/repositories/` groups persistence by settings, workflows, integrations/intake, resources, matching, and runtime. Runtime persistence is split into run, event, human-task, signed-action, and notification mixins behind the stable `FlowForgeRuntimeRepository` import.

Initial FlowForge endpoints:

- `GET /api/v1/flowforge/workflows`
- `GET /api/v1/flowforge/workflows/<workflow_id>`
- `POST /api/v1/flowforge/workflows/validate`
- `GET /api/v1/flowforge/workflows/<workflow_id>/run-inspector`
- `GET /api/v1/flowforge/integrations`
- `POST /api/v1/flowforge/integrations/jotform`
- `GET /api/v1/flowforge/integrations/<integration_config_id>/triggers`
- `POST /api/v1/flowforge/integrations/<integration_config_id>/triggers`
- `POST /api/v1/flowforge/webhooks/jotform/<webhook_public_id>`
- `GET /api/v1/flowforge/runs`
- `GET /api/v1/flowforge/runs/<run_id>`
- `GET /api/v1/flowforge/runs/<run_id>/events`
- `GET /api/v1/flowforge/runs/<run_id>/human-tasks`
- `GET /api/v1/flowforge/runs/<run_id>/notifications`
- `POST /api/v1/flowforge/runs/<run_id>/no-match-escalations`
- `POST /api/v1/flowforge/runs/<run_id>/notes`
- `POST /api/v1/flowforge/human-tasks/<human_task_id>/signed-actions`
- `GET /api/v1/flowforge/public/actions/<token>`
- `POST /api/v1/flowforge/public/actions/<token>/accept`
- `POST /api/v1/flowforge/public/actions/<token>/decline`
- `GET /api/v1/flowforge/reports/domains`
- `GET /api/v1/flowforge/reports/summary`
- `GET /api/v1/flowforge/matching-policies`
- `POST /api/v1/flowforge/matching-policies`
- `POST /api/v1/flowforge/matching-policies/<matching_policy_id>/llm-drafts`
- `POST /api/v1/flowforge/matching-policies/<matching_policy_id>/llm-drafts/<draft_id>/accept`
- `GET /api/v1/flowforge/workflows/<workflow_definition_id>/versions`
- `POST /api/v1/flowforge/workflows/<workflow_definition_id>/versions/<version_id>/publish`

The first seeded workflow intentionally contains a loop from decline/timeout handling back to the offer node. Validation returns loops as warnings rather than errors because FlowForge is graph-oriented in the editor but must not be constrained to strict DAG runtime semantics.

Jotform webhook intake:

- production setup starts with `POST /api/v1/flowforge/integrations/jotform`, which creates a persisted integration, opaque `webhook_public_id`, relative `webhook_path`, and one-time `webhook_secret`
- only the SHA-256 webhook secret hash is stored; the plaintext secret is returned once at creation time
- integration configs support `production` and `test` modes; test mode is intended for setup validation and should be excluded from production reporting
- persisted integration webhooks POST to `/api/v1/flowforge/webhooks/jotform/<webhook_public_id>` where the public id starts with `ffj_`; the supplied token is hashed and compared to the stored integration secret hash
- persisted webhooks store an idempotent `flowforge_intake_events` record with normalized payload, raw payload, headers, source IP, mode, and raw-payload retention expiration
- duplicate Jotform deliveries return the existing intake event id instead of creating a second event
- configure Jotform to POST to `/api/v1/flowforge/webhooks/jotform/<webhook_public_id>?token=<webhook_secret>` when custom headers are unavailable
- prefer `X-FlowForge-Webhook-Token` or `X-Jotform-Webhook-Token` for the per-integration `webhook_secret` if the sender can provide custom headers
- the receiver accepts JSON and form-encoded payloads, including Jotform's `rawRequest` field
- current behavior persists the intake event, evaluates configured integration triggers, stores `trigger_evaluation_json`, creates durable `flowforge_runs` for selected pinned triggers, appends initial `workflow.run.created` events, and returns `202 Accepted`; node execution and side effects are later FlowForge runtime phases

Integration triggers:

- persisted triggers live under `GET/POST /api/v1/flowforge/integrations/<integration_config_id>/triggers`
- triggers connect an integration event to a workflow definition and either a pinned workflow version or the latest published version
- `version_strategy=pinned` requires `workflow_version_id`; `version_strategy=latest_published` resolves the version during future runtime evaluation
- `trigger_mode=always` creates an always-on trigger; `trigger_mode=conditional` requires a non-empty `condition` object
- `trigger_policy=all_matching` can start every matching workflow trigger for an event; `trigger_policy=first_matching` is designed to use `priority` order once runtime evaluation is implemented
- conditional triggers currently support simple payload-path equality maps such as `{"fields.caseType":"new"}` and explicit condition checks using `all`, `any`, `field`, `operator`, and `value`; supported trigger operators are `equals`, `not_equals`, `exists`, `not_exists`, `in`, and `contains`
- trigger records also store provider-to-workflow `field_mapping` and `no_match_config`; webhook intake uses these values in the initial run context
- selected pinned triggers create idempotent `flowforge_runs` using `intake:<intake_event_id>:trigger:<trigger_id>`; duplicate run creation reuses the existing run
- selected `latest_published` triggers without a resolved workflow version are skipped with `workflow_version_unresolved` until published-version resolution is implemented

FlowForge Celery runtime:

- `qf.flowforge.dispatch_run` advances a persisted run through supported node types outside the webhook request path
- supported runtime node types are `intake`, `decision`, `notification`, `matching`, `wait`, and `end`
- `intake`, `decision`, and `notification` are deterministic transition nodes in this slice; `notification` records queue intent but does not create rich node-specific side effects yet
- `matching` resolves a published matching policy version, loads the active resource snapshot batch, executes the deterministic matching engine, persists `flowforge_matching_evaluations` and candidate rows, and branches on `matched` or `no_match` edges
- when runtime matching selects a candidate, it persists the matching queue into run context, creates an offer human task, creates a signed action token, queues a minimal offer email notification, and increments resource active-offer state
- offer human tasks now use deterministic idempotency keys; the hardening migration `20260505_flowforge_runtime_hardening.sql` adds the backing unique key and durable assignment rows
- `wait` pauses the run by returning it to `waiting` at the current node; signed accept/decline responses and timeout sweeps can advance the run onto matching response branches
- `assignment` and `end` mark the run completed and append dispatch-completed events; `event_capture` and `iterator` are explicit pass-through runtime primitives for decline/timeout capture and next-candidate loops
- runtime dispatch uses idempotency keys for dispatch and node events so duplicate dispatch does not duplicate timeline rows
- `qf.flowforge.dispatch_notifications` sends pending email notifications using summary-level content only, then marks rows sent or failed and appends notification timeline events
- `qf.flowforge.purge_expired_raw_payloads` removes expired raw webhook payloads, headers, and sensitive field snapshots while preserving normalized/reporting metadata
- signed accept actions mark the resource assigned, decrement active-offer state, create a durable assignment record, advance the run along an `accept`/`accepted` branch, and enqueue normal dispatch
- signed decline actions and timeout sweeps mark the resource declined/timed out, move to the next queued candidate when one exists, or advance the run along a `no_match` branch when the candidate pool is exhausted
- `qf.flowforge.dispatch_due_timeouts` marks due human tasks timed out, appends timeout events, offers the next candidate or advances no-match, and enqueues normal dispatch when the graph advances

Runtime visibility:

- persisted runs are available through `GET /api/v1/flowforge/runs` with optional `status`, `mode`, `limit`, and `offset` query parameters
- run details are available through `GET /api/v1/flowforge/runs/<run_id>` and are workspace-scoped
- run timelines are available through `GET /api/v1/flowforge/runs/<run_id>/events` with a capped `limit`
- run-scoped human tasks are available through `GET /api/v1/flowforge/runs/<run_id>/human-tasks`; this is the foundation for offer history, signed-response tasks, and needs-attention views
- signed public action tokens are created through `POST /api/v1/flowforge/human-tasks/<human_task_id>/signed-actions`; only the token hash is stored, and the plaintext token is returned once
- public signed action pages can inspect and complete accept/decline actions without bearer auth through `/api/v1/flowforge/public/actions/<token>` routes; responses update the human task, append redacted timeline events, advance the waiting run along an `accept`/`decline` branch, and enqueue normal dispatch
- no-match escalation queues pending email notification audit rows through `POST /api/v1/flowforge/runs/<run_id>/no-match-escalations`; `qf.flowforge.dispatch_notifications` now sends those pending email rows with minimal content and delivery status tracking
- report summaries are available through `GET /api/v1/flowforge/reports/summary` and reporting-domain metadata through `GET /api/v1/flowforge/reports/domains`
- workflow versions can be listed and published through the workflow version routes; publishing requires `flowforge:admin` by default
- run and event reads require `flowforge:user` and return redacted runtime context/event payloads only; sensitive payload JSON is not exposed
- operator notes are appended through `POST /api/v1/flowforge/runs/<run_id>/notes` as `workflow.operator.note` events; until FlowForge-specific operator roles are added, note creation requires `flowforge:admin`
- these endpoints support operator/run-inspector UI work before retries, assignment automation, richer workflow authoring, and production operator/admin UI are implemented

FlowForge operational health:

- System Health includes a `FlowForge Runtime` check.
- The check reads worker heartbeat key `flowforge:worker:last_dispatch` from Valkey.
- The check reports pending notification backlog, failed notification side effects, stuck queued/waiting/running runs older than 30 minutes, and failed runs in the last 24 hours.
- Docker and traditional deployments must run both Celery worker and Celery Beat for the FlowForge health check to stay green.
- Full operations guidance lives in `/Users/mmaslak/Local Documents/projects/query_forge/docs/flowforge-production-runbook.md`.

FlowForge MCP tools:

- `flowforge_list_runs` lists redacted workspace workflow runs with optional status/mode filters.
- `flowforge_get_run` returns one redacted run by id.
- `flowforge_get_run_timeline` returns the redacted append-only event timeline for a run.
- `flowforge_list_human_tasks` returns redacted human tasks for a run.
- `flowforge_get_needs_attention` lists runs currently marked `needs_attention`.
- `flowforge_get_resource_profile` returns a redacted resource snapshot profile by resource set, snapshot batch, and source record key.
- `flowforge_get_matching_summary` returns matching-policy metadata only; it does not publish or mutate policies.
- `flowforge_get_report_summary` returns concise run-count metrics.
- `flowforge_add_operator_note` appends a redacted operator note and requires `flowforge:admin` for human principals.
- All FlowForge MCP tools run through the existing MCP OAuth, workspace enablement, app-principal grant, audit, and rate-limit boundary. Human read tools require `flowforge:user` or `flowforge:admin`; human operator-note mutation requires `flowforge:admin`.

## Local Development

### Prerequisites

- Python `3.12`
- MySQL-compatible metadata database
- Qdrant
- Valkey or Redis-compatible broker/cache
- optional: Docker Desktop for container-first local runtime

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements/requirements.txt
```

### Run the Flask API

```bash
python app/main.py
```

### Run the Celery worker

```bash
celery -A app.celery_app worker --loglevel=INFO
```

### Run Celery Beat

```bash
celery -A app.celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
```

Run Beat alongside the worker for Skills schedules and FlowForge runtime maintenance.

### Run the MCP server

```bash
python -m mcp_server
```

The MCP server is standalone. It does not run inside the Flask app process.

## Docker

QueryForge is expected to run in Docker.

Use the root-level Compose stack from the workspace root:

```bash
cd "/Users/mmaslak/Local Documents/projects/query_forge"
cp .env.docker.example .env
mkdir -p docker
cp docker/customer.env.example docker/customer.env
docker compose up --build
```

Relevant container ports:

- API: `5000 -> 8000`
- MCP: `8001 -> 8001`
- UI: `3000 -> 80`

The backend image in this directory is used for:

- `api`
- `worker`
- `celerybeat`
- `mcp`

The runtime command determines which process starts.

Start the background runtime profile with:

```bash
docker compose --profile worker up --build
```

That profile starts both the Celery worker and Celery Beat. FlowForge runtime dispatch, notification delivery, timeout sweeps, and raw-payload retention cleanup depend on it.

## Configuration

### Traditional backend env

`query-forge-api/.env` is for traditional or direct backend deployments.

Use it for:

- local non-Docker backend runs
- systemd or VM-based deployments
- direct Gunicorn or Celery launches

Do not use it as the source of truth for Docker customer deployments.

### Docker customer env

The Docker stack reads customer-specific runtime settings from:

- `/Users/mmaslak/Local Documents/projects/query_forge/docker/customer.env`

That file is intended for:

- container-safe hostnames
- customer-specific DB credentials
- MCP-specific runtime settings
- container-local service wiring

### Important env groups

#### Core backend runtime

- `JWT_SECRET`
- `DB_HOST`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `DB_PORT`
- `VALKEY_ADDRESS`
- `VALKEY_PORT`
- `QDRANT_URL`
- `QDRANT_API_KEY`

#### Model / AI runtime

- `LLM_INSTANCE_ID`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `SEMANTIC_LLM_ENDPOINT`
- `SEMANTIC_LLM_API_KEY`
- `SEMANTIC_LLM_MODEL`

#### Browser/API integration

- `FRONTEND_BASE_URL`
- `FRONTEND_ALLOWED_ORIGINS`
- `COOKIE_SECURE`
- `COOKIE_SAMESITE`

#### MCP runtime

- `MCP_SERVER_NAME`
- `MCP_SERVER_VERSION`
- `MCP_HOST`
- `MCP_PORT`
- `MCP_STREAMABLE_HTTP_PATH`
- `MCP_ALLOWED_ORIGINS`
- `MCP_RESOURCE_URL`
- `MCP_AUTHORIZATION_SERVER_URL`
- `MCP_OAUTH_SCOPES_SUPPORTED`
- `MCP_INCLUDE_RAW_SQL`
- `MCP_ENABLE_RESOURCES`
- `MCP_ENABLE_SAVED_QUERIES`
- `MCP_PREVIEW_DEFAULT_LIMIT`
- `MCP_PREVIEW_HARD_LIMIT`
- `MCP_PREVIEW_TIMEOUT_SECONDS`
- `MCP_AUDIT_LOGGING`
- `MCP_DEBUG`

#### MCP OAuth wrapper foundation

- `MCP_ENABLED`
- `MCP_REQUIRE_WORKSPACE_ENABLEMENT`
- `MCP_REQUIRE_CHANNEL_GRANT`
- `MCP_REQUIRE_QUERY_STUDIO_FOR_PREVIEW`
- `MCP_DEFAULT_PREVIEW_ROW_LIMIT`
- `MCP_MAX_PREVIEW_ROW_LIMIT`
- `MCP_RATE_LIMIT_PER_USER_PER_MINUTE`
- `MCP_RATE_LIMIT_PER_CLIENT_PER_MINUTE`
- `MCP_RATE_LIMIT_PREVIEW_PER_USER_PER_MINUTE`
- `MCP_BLOCK_SENSITIVE_DOMAINS`
- `OAUTH_ISSUER_URL`
- `OAUTH_ACCESS_TOKEN_TTL_SECONDS`
- `OAUTH_AUTH_CODE_TTL_SECONDS`
- `OAUTH_REFRESH_TOKEN_TTL_SECONDS`
- `OAUTH_CLIENT_TTL_SECONDS`
- `OAUTH_ALLOWED_REDIRECT_HOSTS`
- `OAUTH_ALLOW_LOOPBACK_REDIRECTS`
- `OAUTH_REQUIRE_PKCE`
- `OAUTH_ALLOWED_CODE_CHALLENGE_METHODS`
- `OAUTH_ENABLE_DYNAMIC_CLIENT_REGISTRATION`
- `OAUTH_ENABLE_REFRESH_TOKENS`
- `OAUTH_CONSENT_EXPIRES_WITH_REFRESH_TOKEN`
- `OAUTH_ENABLE_APP_CLIENT_AUTH`

#### Feedback learning foundation

- `FEEDBACK_AUTO_APPLY_ENABLED`
- `FEEDBACK_CONFIDENCE_THRESHOLD`
- `FEEDBACK_EVIDENCE_THRESHOLD`
- `FEEDBACK_EVALUATOR_MAX_RETRIES`
- `FEEDBACK_WORKSPACE_OVERRIDES_ENABLED`
- `FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD`

### MCP behavior defaults

Operational defaults in the MCP layer are:

- raw SQL excluded from `compile_query` unless `MCP_INCLUDE_RAW_SQL=true`
- preview execution only
- no arbitrary SQL execution
- resources enabled by default
- saved queries enabled by default

### MCP OAuth discovery and token flow

The MCP OAuth wrapper exposes standards-shaped discovery metadata and the first production OAuth grant paths for remote MCP clients.

- Flask API: `GET /.well-known/oauth-authorization-server`
- Documented Flask API alias: `GET /api/v1/mcp-oauth/authorization-server-metadata`
- Standalone MCP server: `GET /.well-known/oauth-protected-resource`
- Dynamic client registration: `POST /oauth/register`
- Authorization-code start/consent: `GET /oauth/authorize`
- Authorization-code approval: `POST /oauth/authorize`
- Token exchange and refresh rotation: `POST /oauth/token`
- Refresh-token revocation: `POST /oauth/revoke`
- App-principal admin list/create: `GET/POST /api/v1/workspaces/<workspace_id>/mcp/app-principals`
- App-principal admin revoke: `DELETE /api/v1/workspaces/<workspace_id>/mcp/app-principals/<client_id>`

`MCP_RESOURCE_URL` must match the public origin of the MCP resource server, for example `https://mcp.query-forge.com`. MCP access tokens are accepted only when `typ=mcp_access` and the token audience matches this resource URL. `MCP_AUTHORIZATION_SERVER_URL` should point at the QueryForge API OAuth issuer, usually `https://api.query-forge.com`. When `MCP_AUTHORIZATION_SERVER_URL` is omitted, the MCP server falls back to `OAUTH_ISSUER_URL`.

Unauthenticated MCP requests return `401` with a `WWW-Authenticate` challenge that includes the protected-resource metadata URL so remote MCP clients can rediscover the resource metadata.

`POST /oauth/register` is unauthenticated by design because remote MCP clients register before user login/consent. QueryForge restricts this endpoint by `OAUTH_ALLOWED_REDIRECT_HOSTS`, supported grant types, supported response types, supported scopes, and token endpoint auth method. Public PKCE clients should send `token_endpoint_auth_method=none`; confidential registrations using `client_secret_basic` or `client_secret_post` receive a one-time plaintext `client_secret`, while only its SHA-256 hash is stored.

For local developer clients such as Codex, set `OAUTH_ALLOW_LOOPBACK_REDIRECTS=true` to allow registered redirect URIs on loopback hosts (`localhost`, `127.0.0.1`, and `::1`) over `http` or `https`. Leave this disabled in production so remote clients remain constrained to HTTPS URLs under `OAUTH_ALLOWED_REDIRECT_HOSTS`.

`GET /oauth/authorize` validates the registered client, redirect URI, requested scopes, and PKCE challenge, then renders a backend-hosted QueryForge login/consent form. When the optional OAuth `resource` parameter is omitted by a local client, QueryForge defaults it to `MCP_RESOURCE_URL`; when present, it must exactly match `MCP_RESOURCE_URL`. `POST /oauth/authorize` validates the same OAuth parameters plus QueryForge credentials and TOTP when enabled for the user, stores a short-lived hashed authorization code, and redirects back to the registered redirect URI with `code`, `state`, and `resource`. Authorization codes are one-time-use and are consumed by `POST /oauth/token`.

`POST /oauth/token` supports `authorization_code`, `refresh_token`, and `client_credentials` grants. Authorization-code exchange requires the original `redirect_uri`, matching `resource`, and a valid PKCE `code_verifier`. Issued access tokens are QueryForge MCP-only JWTs with `typ=mcp_access`, issuer `OAUTH_ISSUER_URL`, audience `MCP_RESOURCE_URL`, client id, principal type/id, resource, and authorized MCP scopes. When `OAUTH_ENABLE_REFRESH_TOKENS=true` and the registered client allows `refresh_token`, the token response includes an opaque refresh token stored only by SHA-256 hash. Refresh-token grant use rotates the token every time and rejects replayed or revoked refresh tokens.

`client_credentials` is for non-human MCP app principals when `OAUTH_ENABLE_APP_CLIENT_AUTH=true`. The client id and secret are checked against active `mcp_app_clients` rows, secrets are compared by SHA-256 hash, and successful exchange issues an MCP access token with `principal_type=app`. App-principal runtime access still requires an active `mcp_principal_grants` row for the requested workspace.

Workspace admins manage non-human MCP app principals in the UI at `/admin/mcp/app-principals`. Creating a principal creates both the `mcp_app_clients` credential row and the initial `mcp_principal_grants` workspace grant. The API returns the plaintext client secret only in the create response; after that only the SHA-256 hash is stored, so admins must copy the secret immediately. App principals can be narrowed by allowed MCP tools, allowed domain keys, preview permission, preview row limit, and optional expiration. Revocation disables the grant and revokes the app client so future `client_credentials` exchanges fail.

`POST /oauth/revoke` revokes persisted refresh tokens by hash and is intentionally idempotent for unknown tokens. Access-token revocation requests are accepted as a v1 no-op because MCP access tokens are short-lived JWTs; durable revocation is enforced for refresh tokens.

MCP tool/resource execution enforces the runtime channel policy after token verification. `MCP_ENABLED` must be true, workspace MCP settings must be enabled when `MCP_REQUIRE_WORKSPACE_ENABLEMENT=true`, human users must have `queryforge_mcp:user`, preview tools require `queryforge_mcp:preview` plus Query Studio access by default, and app principals are constrained by explicit grant rows for workspace, tool, domain, preview flag, and preview row limit.

MCP runtime calls also apply coarse rate limits before adapter execution. `MCP_RATE_LIMIT_PER_USER_PER_MINUTE` limits each principal, `MCP_RATE_LIMIT_PER_CLIENT_PER_MINUTE` limits the OAuth/app client id when present, and `MCP_RATE_LIMIT_PREVIEW_PER_USER_PER_MINUTE` applies an additional bucket to preview tools. Rate-limit failures return MCP `RATE_LIMITED` errors with retry metadata from Valkey when available.

MCP audit events are written to `mcp_oauth_audit_log` when `MCP_AUDIT_LOGGING=true`. Each tool/resource event records principal/client/workspace context, scopes, tool/resource name, domain or saved-query id when available, allow/deny decision, denial reason, preview row count, rate-limit buckets, trace id, and a compact request summary. Audit persistence is fail-open with warning logs so a transient audit insert failure does not bypass QueryForge authorization or break governed reads.

### Feedback learning behavior defaults

The feedback-learning work completed so far includes:

- optional `feedback_comment` on `POST /api/v1/prompt-feedback`
- explicit submission status in the response
- negative feedback responses returning `analysis_pending`
- storage of the free-text comment under reserved feedback-learning metadata for later analysis
- typed artifact bundle reconstruction from persisted prompt-feedback, pipeline-trace, and planner-domain conversation sources
- evaluator prompt building plus strict evaluator response validation/retry handling
- synchronous Phase 4 analysis endpoint:
  - `POST /api/v1/feedback-learning/prompt-feedback/<id>/analyze`
  - requires `ai:admin` access in the active workspace
  - idempotently reuses an existing completed analysis row
  - persists normalized semantic/domain candidates and governance decisions
  - does not mutate curated semantic metadata
- Phase 5 manual review and override APIs:
  - `GET /api/v1/feedback-learning/candidates`
  - `GET /api/v1/feedback-learning/candidates/<id>`
  - `POST /api/v1/feedback-learning/candidates/<id>/approve`
  - `POST /api/v1/feedback-learning/candidates/<id>/reject`
  - `POST /api/v1/feedback-learning/candidates/bulk-approve`
  - `POST /api/v1/feedback-learning/candidates/bulk-reject`
  - `GET /api/v1/feedback-learning/semantic-overrides`
  - `GET /api/v1/feedback-learning/domain-overrides`
  - `POST /api/v1/feedback-learning/semantic-overrides/<id>/deactivate`
  - `POST /api/v1/feedback-learning/domain-overrides/<id>/deactivate`
  - `GET /api/v1/feedback-learning/promotion-audits`
- Phase 7 promotion and backfill operators:
  - `app/services/feedback_learning/catalog_promotion_service.py`
  - `app/services/feedback_learning/analysis_backfill_service.py`
  - `scripts/promote_override.py`
  - `scripts/run_feedback_analysis_backfill.py`

Operational notes:

- candidate approval now creates persisted semantic/domain override rows
- approved active overrides now affect live runtime reads behind `FEEDBACK_WORKSPACE_OVERRIDES_ENABLED`
- runtime override resolution is applied in the real planner/semantic seams:
  - `app/services/planner/semantic_catalog_lookup_repository.py`
  - `app/services/semantic/value_alias_resolution_service.py`
  - `app/services/planner/semantic_retrieval_service.py`
  - `app/services/planner_domain/semantic_integration_service.py`
- runtime merges are additive and do not mutate curated base metadata
- workspace overrides override global overrides on direct key conflicts
- supported live runtime behaviors now include:
  - feedback alias and phrase-hint merge for semantic retrieval / grounding
  - concept rank boost and penalty score adjustment during semantic retrieval
  - domain example prompt, lexical hint, and ambiguity note enrichment in semantic candidate payloads
- candidate rejection now stores required reviewer notes and reason codes
- override deactivation and promotion-audit listing are available through admin APIs
- promotion flows are now audited and supported for:
  - semantic alias promotion into `semantic_concept_alias`
  - semantic concept rank boost/penalty promotion into `semantic_concept.display_priority`
  - domain-note/domain-example/domain-lexical promotions into `domain_profile.notes`
- global domain-profile-targeting overrides remain runtime-only and are blocked from promotion
- failed promotions now create or update failed audit rows with retry metadata
- no background analysis jobs are active yet
- auto-apply eligibility is computed and persisted, but Phase 4 does not create overrides
- the feedback-learning env variables now affect both governor decisions and runtime override resolution

Operator examples:

```bash
python3 scripts/promote_override.py --kind semantic --override-id 12 --promoted-by admin
python3 scripts/promote_override.py --kind domain --override-id 21 --promoted-by admin --notes "approved in review"
python3 scripts/run_feedback_analysis_backfill.py --limit 100
python3 scripts/run_feedback_analysis_backfill.py --limit 100 --write --workspace-id ws_123
```

### Feedback learning rollout checklist

Use this order for local, Docker, and production-like rollout:

1. apply:
   - `migrations/20260423_feedback_learning_tables.sql`
   - `migrations/20260423_feedback_learning_review_fields.sql`
2. verify the new tables exist:
   - `prompt_failure_analysis`
   - `semantic_update_candidate`
   - `semantic_override`
   - `domain_override`
   - `catalog_promotion_audit`
3. deploy the backend code that includes:
   - prompt-feedback capture extension
   - feedback-learning analysis/review routes
   - runtime override resolver integration
   - promotion/backfill operator scripts
4. deploy the frontend code that includes `/admin/feedback-learning`
5. verify env values:
   - `FEEDBACK_AUTO_APPLY_ENABLED`
   - `FEEDBACK_CONFIDENCE_THRESHOLD`
   - `FEEDBACK_EVIDENCE_THRESHOLD`
   - `FEEDBACK_EVALUATOR_MAX_RETRIES`
   - `FEEDBACK_WORKSPACE_OVERRIDES_ENABLED`
   - `FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD`
6. run smoke verification:
   - submit negative prompt feedback
   - analyze the feedback row
   - list candidates
   - approve/reject a candidate
   - list/deactivate overrides
   - list promotion audits
7. run promotion/backfill scripts only with an explicit operator identity

### Feedback learning operational cautions

- `FEEDBACK_WORKSPACE_OVERRIDES_ENABLED` controls whether approved overrides affect live planner/semantic runtime behavior.
- Approved overrides are additive runtime merges and do not mutate curated semantic records directly.
- Promotion is still an explicit operator/reviewer action. Runtime approval is not the same as curated metadata promotion.
- Global domain-profile-targeting overrides remain runtime-only and are intentionally blocked from promotion.
- Promotion and backfill operators should be treated as privileged actions and should run with explicit `--promoted-by` or equivalent actor context.

### Feedback learning smoke commands

Example API/operator flow after deployment:

```bash
curl -X POST "http://localhost:5000/api/v1/feedback-learning/prompt-feedback/41/analyze" \
  -H "Authorization: Bearer <token>" \
  -H "X-Workspace-Id: ws_123"

curl "http://localhost:5000/api/v1/feedback-learning/candidates?page=1&page_size=50" \
  -H "Authorization: Bearer <token>" \
  -H "X-Workspace-Id: ws_123"

python3 scripts/promote_override.py --kind semantic --override-id 12 --promoted-by admin@example.com
python3 scripts/run_feedback_analysis_backfill.py --limit 100 --write --workspace-id ws_123
```

## Nginx

Nginx is treated as a first-class runtime layer.

Recommended production host split:

- `api.query-forge.com` → Flask API
- `mcp.query-forge.com` → standalone MCP server
- browser app host → proxied `/api/v1/*` requests to the Flask API

A starter MCP virtual host is provided at:

- `/Users/mmaslak/Local Documents/projects/query_forge/docs/nginx-mcp.query-forge.com.conf.example`

The MCP endpoint should be proxied to:

- `http://127.0.0.1:8001/mcp`

The feedback-learning admin UI does not require a dedicated Nginx location. It uses the same authenticated `/api/v1` browser proxy path as the rest of the admin frontend.

## Tests

### Full backend suite

```bash
./scripts/pytest.sh -q
```

### Focused MCP suite

```bash
./scripts/pytest.sh -q mcp_server/tests
```

### Lint

```bash
./scripts/lint.sh
```

### Single test

```bash
./scripts/pytest.sh tests/path/to/test_file.py::test_name -v
```

## Versioning

- Backend code changes require a patch bump in `version.json`
- `app/api_config.py` route version stays `v1` unless the public API contract changes intentionally

## Related Docs

- MCP implementation spec:
  `/Users/mmaslak/Local Documents/projects/query_forge/docs/plans/queryforge_mcp_codex_implementation_spec.md`
- Docker runtime notes:
  `/Users/mmaslak/Local Documents/projects/query_forge/docs/docker.md`
- MCP package notes:
  `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api/mcp_server/README.md`
