# Core Concepts

## What it is

A reference glossary of the most important terms and objects in QueryForge, with enough context to understand how they relate to each other.

## Why it matters

QueryForge uses several layers of abstraction. Understanding how they stack — from physical tables up to natural-language queries — prevents confusion when configuring, debugging, or extending the system.

## Who uses it

All users and administrators. This page is the starting point before diving into any feature-specific guide.

## Key concepts

### Organization
The top-level entity. An organization can contain multiple workspaces and datasources. Managed under `GET/POST /api/v1/admin/organizations`.

### Workspace
The primary operational unit. Every user interaction (queries, domains, skills, semantic concepts) is scoped to a workspace. Workspaces are bound to datasources and have their own feature entitlements and LLM configurations.

### Datasource
A connection to an analytics database (Databricks SQL, MySQL, Snowflake — inferred from adapter implementations). Datasources are registered under an organization and bound to workspaces.

### Domain
A curated, multi-table view built on top of workspace tables. Domains define:
- Which tables participate (primary + secondary)
- Join conditions between tables
- Time policy (which column to use for date filtering)
- Capabilities (which analytical operations are available)
- Rerank policies (how the planner prioritizes candidates)

### Workspace Table / Catalog
Physical tables discovered from the datasource via ingestion. The workspace table catalog (`workspace_inventory`) is the raw material that domains and the dictionary layer are built on.

### Semantic Concept
A canonical business term (e.g., "enrollment", "attendance rate") stored in the semantic registry. Each concept can have:
- Aliases (alternate names for the concept)
- Value aliases (normalized values for filter terms)
- Column maps (which physical columns this concept maps to in each domain)
- Relationships (how concepts relate to one another)

### Semantic Registry
The registry of canonical semantic concepts. Concepts are stored in MySQL and also indexed in Qdrant (`semantic_concepts_v1` collection) for vector search.

### Planner
The AI pipeline that converts a natural-language prompt into a structured SQL-JSON plan. The planner selects a domain, resolves concepts, applies semantic enrichment, calls an LLM for structured output, then normalizes and validates the result before returning a compiled SQL query.

### SQL-JSON (sqljson)
The intermediate structured representation of a query plan — a JSON object that encodes selected columns, filters, groupings, sorts, and derived conditions. The `QueryForgeService` compiles this into executable SQL.

### Saved Query / Query Tree
Users can save query plans in a folder hierarchy. The query tree is the folder+saved-query structure. Folders can be renamed, moved, trashed, and restored. Saved queries can be shared with other users.

### Skill
A reusable automation block attached to a saved query. Built-in skill types (CODE_CONFIRMED from `app/skills/`):
- `threshold_alert` — fires when query results cross a numeric threshold
- `ai_summary_digest` — uses an LLM to generate a narrative summary of query results
- `data_freshness_check` — verifies that data was updated within a configured window
- `email_delivery` — sends results or digests via email
- `webhook_delivery` — POSTs results to a webhook URL

Skills run on a cron schedule (managed via Celery) or can be triggered on demand via `POST /api/v1/skills/{skill_id}/execute`.

### ForgeMatch
An assisted source-to-domain field mapping tool. Upload a CSV or Excel file, run AI-assisted analysis to find the best matching workspace columns for each source field, then review, accept, reject, or manually remap suggestions. Export results or draft a domain/view from accepted mappings.

### ForgeInsights
A structured conversational AI feature. Users create Projects (topic groups) and Threads (conversations) within them. The underlying chat endpoint is `POST /api/v1/chat/forge-insights`. Conversation state is persisted server-side.

### RBAC — Roles and Feature Entitlements
Access is controlled by two orthogonal systems:
1. **Feature entitlements** — a workspace either has a feature key or it does not (stored in `workspace_features` table). Missing row = disabled.
2. **User roles** — workspace-scoped roles (e.g., `forge_match:user`, `query_studio:admin`). Role resolution is handled by `RBACService` with a Valkey cache (60s TTL for roles, 120s for features).

## Related features

- [Domains](../concepts/domains.md)
- [Semantic Registry](../concepts/semantic-registry.md)
- [Planner](../concepts/planner.md)
- [Skills](../concepts/skills.md)
- [ForgeMatch](../concepts/forgematch.md)
- [Feature Entitlements](../concepts/feature-entitlements.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `specs/queryforge_rbac_spec.md`
  - `app/skills/registry.py`, `app/skills/base.py`
  - `app/routes/` (namespace names and route paths)
  - `app/services/forge_insights_threads_service.py`
  - `app/services/query_forge_service.py`
  - `.claude/audits/backend-audit.md`
  - `.claude/audits/implementation-notes.md`
