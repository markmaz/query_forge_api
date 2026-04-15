# Architecture: Backend Structure

## Purpose

Overview of how the Flask backend is organized, what layers exist, and how requests flow through the system.

## Components

| Layer | Location | Role |
|-------|---------|------|
| WSGI entry | `wsgi.py` | Production entry point, creates the Flask app |
| App factory | `app/factory.py` | Creates and configures the Flask app, registers all namespaces |
| Routes | `app/routes/` | Flask-RESTX namespaces (one per domain) |
| Services | `app/services/` | All business logic |
| Skills | `app/skills/` | Reusable automation skill implementations |
| Tasks | `app/tasks/` | Celery async tasks |
| Adapters | `app/adapters/` | Database executors and token managers |
| Models | `app/models/` | Peewee ORM models (and SQLAlchemy in places) |
| Ports | `app/ports/` | Abstract interfaces (SQL executor, metadata provider) |
| Decorators | `app/decorators/` | `@token_required`, RBAC decorators, `@require_ownership` |
| Config | `app/config/` | Environment-based config, LLM resolver |
| Infra | `app/infra/` | Qdrant client wrapper, embedding model |
| NLP | `app/nlp/` | spaCy Tier2 NER pipeline, gazetteer extraction, entity normalization |
| Constants | `app/constants/` | LLM role and provider constants |
| Exceptions | `app/exceptions/` | `ForgeError` (HTTP-aware exception) |

## Route namespaces (CODE_CONFIRMED from `app/routes/`)

| Namespace | Path prefix | File |
|-----------|-------------|------|
| `admin` | `/admin` | `admin_routes.py` |
| `ai` | `/ai` | `ai.py` |
| `catalog` | (NEEDS_VERIFICATION) | `catalog_routes.py` (referenced in audit, not in directory listing) |
| `chat` | `/chat` | `chat_minimal.py` |
| `data-environment` | `/data-environment` | `data_environment.py` |
| `datasources` | `/datasources` | `datasource_routes.py` |
| `destinations` | `/destinations` | `destination_routes.py` |
| `dictionary` | `/dictionary` | `dictionary_routes.py` |
| `domain-profile-embeddings` | (NEEDS_VERIFICATION) | `domain_profile_embeddings.py` |
| `domains` | `/domains` | `domain_routes.py` |
| `embeddings` | `/embeddings` | `embeddings.py` |
| `executions` | `/executions` | `execution_routes.py` |
| `exports` | `/exports` | `export_routes.py` |
| `forge-insights` | `/forge-insights` | `forge_insights.py` |
| `forge-match` | `/forge-match` | `forge_match_routes.py` |
| `ingestion` | `/ingestion` | `ingestion_routes.py` |
| `nlp` | `/nlp` | `nlp_routes.py` |
| `nlp-review` | `/nlp-review` | `nlp_review.py` |
| `nlp-tier2` | `/nlp-tier2` | `nlp_tier2.py` |
| `prompt-feedback` | `/prompt-feedback` | `prompt_feedback.py` |
| `query_analysis` | `/query_analysis` | `query_analysis_routes.py` |
| `semantic` | `/semantic` | `semantic_routes.py` |
| `semantic-concept-aliases` | (NEEDS_VERIFICATION) | `semantic_concepts.py` |
| `semantic-concept-column-maps` | (NEEDS_VERIFICATION) | `semantic_concepts.py` |
| `semantic-concepts` | (NEEDS_VERIFICATION) | `semantic_concepts.py` |
| `semantic-mappings` | (NEEDS_VERIFICATION) | `semantic_mappings.py` |
| `semantic-registry` | (NEEDS_VERIFICATION) | `semantic_registry.py` |
| `semantic-relationships` | (NEEDS_VERIFICATION) | `semantic_relationships.py` |
| `semantic-suggestions` | (NEEDS_VERIFICATION) | `semantic_suggestions.py` |
| `semantic-value-aliases` | (NEEDS_VERIFICATION) | `semantic_concepts.py` |
| `skills` | `/skills` | `skills_routes.py` |
| `value_overrides` | (NEEDS_VERIFICATION) | `value_override_routes.py` |
| `vector` | `/vector` | `vector_domains.py` |
| `version` | `/version` | `version_routes.py` |

All routes are prefixed with `/api/v1/` (INFERRED_FROM_STRUCTURE from frontend service config).

## Request flow

1. Request arrives at Flask.
2. `@token_required` decorator validates the Bearer token (outermost).
3. RBAC decorator (`@require_access`, `@require_role`, `@require_admin`, `@require_ownership`) checks feature entitlement + user role.
4. Route handler extracts workspace_id from `X-Workspace-Id` header via `request_helpers.extract_workspace_id()`.
5. Route handler calls service layer (thin dispatcher — no logic in routes).
6. Service returns result or raises `ForgeError`.
7. Route handler serializes response.

## Authentication

- JWT Bearer token — validated by `@token_required`
- `X-Workspace-Id` header — workspace scoping, extracted after token validation
- `X-User-Id` header — injected by frontend Axios client

## Async tasks

Celery tasks are defined in `app/tasks/`:
- `email_tasks.py` — email delivery
- `forge_match_tasks.py` — ForgeMatch analysis
- `ingestion_tasks.py` — datasource ingestion
- `skill_runner.py` — skill execution

## NLP pipeline

The NLP tier (spaCy Tier2 + Tier2 review) is served via:
- `POST /api/v1/nlp/extract` — entity extraction
- `POST /api/v1/nlp/extract-and-search` — extraction + vector search
- `POST /api/v1/nlp-tier2/tier2/parse` — Tier2 NER parsing
- NLP review queue for active-learning labeling

Training scripts are in `scripts/` with pipeline definition in `project.yml`.

## Related docs

- [Planner Pipeline](planner-pipeline.md)
- [Shared AI Pipeline](shared-ai-pipeline.md)
- [Admin: Deployment Overview](../admin/deployment-overview.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/` (all namespace declarations)
  - `app/tasks/` (directory listing)
  - `CLAUDE.md`
  - `.claude/audits/backend-audit.md`
