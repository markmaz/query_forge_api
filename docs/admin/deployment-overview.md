# Deployment Overview

## Purpose

Overview of QueryForge backend infrastructure dependencies and deployment configuration for system administrators.

## Infrastructure dependencies

| Component | Role |
|-----------|------|
| MySQL | Primary metadata store (workspaces, domains, semantic concepts, skills, users, etc.) |
| Redis / Valkey | Celery broker + task result backend; RBAC cache |
| Qdrant | Vector database (collections: `table_catalog`, `semantic_concepts_v1`) |
| Celery worker | Async task execution (ingestion, ForgeMatch analysis, skill execution) |
| Celery beat | Scheduler for skill cron execution |
| Analytics datasource | Databricks SQL, MySQL, or Snowflake (per workspace) |

## Application entry points

| Command | Purpose |
|---------|---------|
| `python app/main.py` | Development Flask server (port 5000) |
| `wsgi.py` | WSGI entry for production (Gunicorn, uWSGI, etc.) |
| `celery -A app.celery_app worker --loglevel=INFO` | Celery worker |

## Key environment variables

| Variable | Purpose | Fallback role |
|----------|---------|--------------|
| `QF_LLM_ENCRYPTION_KEY` | Fernet key for workspace LLM API key encryption | Required if workspace LLMs configured |
| `VLLM_BASE_URL` | Default LLM base URL | `planner`, `query_generator`, `enrichment` roles |
| `SEMANTIC_PLAN_LLM_MODEL` | Default planner model name | `planner` role |
| `SEMANTIC_LLM_ENDPOINT` | Default NER/summarizer endpoint | `ner`, `summarizer` roles |
| `SEMANTIC_LLM_MODEL` | Default NER/summarizer model | `ner`, `summarizer` roles |
| `LOG_FILE` | Path to log file for debug output | — |

Workspace-level LLM overrides take precedence over env vars. If neither is configured for a role, `WorkspaceLLMService.get_llm_for_role()` returns `None` and features requiring that role return 503.

## Qdrant collections

| Collection | Contents | Used by |
|-----------|----------|---------|
| `table_catalog` | Domain/table embeddings for planner domain selection | PlannerDomainService |
| `semantic_concepts_v1` | Semantic concept embeddings | Planner semantic grounding, ForgeMatch |

Rebuild commands:
- `POST /api/v1/admin/vector/semantic-concepts/rebuild`
- `POST /api/v1/admin/vector/domains/reindex`
- `POST /api/v1/admin/vector/embeddings/rebuild`
- `POST /api/v1/admin/vector/rebuild-all`

## Health checks

- `GET /api/v1/admin/healthz` — basic liveness (public)
- `GET /api/v1/admin/health/detailed` — detailed health check (admin only)
- `GET /api/v1/admin/health/broker` — Celery broker diagnostics (admin only)

## Systemd / process management

The `docs/systemd/` directory (existence confirmed) likely contains systemd unit files for the API server and Celery worker. NEEDS_VERIFICATION: exact file contents.

## LLM data environment

For workspaces using a locally hosted LLM:
- `POST /api/v1/data-environment/llm/start` — start LLM process (system:admin)
- `POST /api/v1/data-environment/llm/stop` — stop LLM process
- `GET /api/v1/data-environment/llm/status` — check status

## Related docs

- [Admin: Workspace Setup](workspace-setup.md)
- [Architecture: Backend Structure](../architecture/backend-structure.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/admin_routes.py`
  - `app/routes/data_environment.py`
  - `.claude/audits/implementation-notes.md`
  - `CLAUDE.md` (infrastructure dependencies)
