# QueryForge API

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

### QueryForge MCP server

- module: `mcp_server`
- entrypoint: `python -m mcp_server`
- default local/container port: `8001`
- streamable HTTP path: `/mcp`
- auth model: bearer token only
- execution model: preview-only governed query execution, no raw SQL input from clients

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
- `mcp`

The runtime command determines which process starts.

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
- `MCP_INCLUDE_RAW_SQL`
- `MCP_ENABLE_RESOURCES`
- `MCP_ENABLE_SAVED_QUERIES`
- `MCP_PREVIEW_DEFAULT_LIMIT`
- `MCP_PREVIEW_HARD_LIMIT`
- `MCP_PREVIEW_TIMEOUT_SECONDS`
- `MCP_AUDIT_LOGGING`
- `MCP_DEBUG`

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
