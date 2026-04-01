# Workspaces and Organizations

## What it is

Organizations and workspaces are the two-level tenancy hierarchy in QueryForge. An organization groups multiple workspaces and datasources. A workspace is the operational unit where users, domains, queries, skills, and semantic content live.

## Why it matters

QueryForge is a multi-tenant platform. Workspaces provide isolation between tenants or teams — all data, roles, and features are scoped to a workspace. Organizations allow grouping workspaces under a single administrative entity with shared datasource management.

## Who uses it

- **System administrators** — create organizations, workspaces, and datasources via the admin panel.
- **Workspace administrators** — manage workspace memberships, feature entitlements, and LLM configurations.

## Key concepts

### Organization
Top-level grouping entity.
- `GET/POST /api/v1/admin/organizations` — list/create
- `GET/PATCH/DELETE /api/v1/admin/organizations/{organization_id}` — manage
- `GET/POST /api/v1/admin/organizations/{organization_id}/memberships` — membership
- `GET/POST /api/v1/admin/organizations/{organization_id}/datasources` — datasource binding

### Datasource
A connection to an analytics database. Stored under an organization.
- `GET/PATCH/DELETE /api/v1/admin/datasources/{datasource_id}`
- `POST /api/v1/admin/datasources/{datasource_id}/test` — test connection
- `GET /api/v1/admin/datasources/{datasource_id}/namespaces` — list available namespaces

Supported datasource types (CODE_CONFIRMED from adapter implementations): Databricks SQL, MySQL, Snowflake.

### Workspace
The operational unit. Each workspace is bound to a datasource.
- `GET/POST /api/v1/admin/workspaces` — list/create workspace bindings
- `GET/PATCH /api/v1/admin/workspaces/{workspace_id}/binding` — manage binding
- `GET/PATCH/DELETE /api/v1/admin/workspaces/{workspace_id}` — manage workspace
- `GET/POST /api/v1/admin/workspaces/{workspace_id}/memberships` — manage users
- `GET /api/v1/workspaces` — list workspaces available to the current user

### Workspace Table Catalog
Physical tables discovered from the datasource during ingestion. Browseable at `GET /api/v1/workspace-tables/columns` (INFERRED_FROM_STRUCTURE from `workspace_table_routes.py`).

### Feature Entitlements
Workspace-level feature flags stored in `workspace_features` table. A missing row disables the feature. Managed via RBAC service: `set_workspace_feature(workspace_id, feature_key, enabled, granted_by)`. Feature keys correspond to route access requirements (e.g., `forge_match`, `query_studio`, `semantic`, `skills`, `ingestion`, `planner`, `ai`, `vector`, `catalog`, `exports`).

### Workspace LLM Configuration
Per-workspace LLM assignments by role (`planner`, `ner`, `summarizer`, `query_generator`, `enrichment`). API keys are Fernet-encrypted at rest. Managed at:
- `GET /api/v1/llm-roles` — list roles
- `GET /api/v1/llm-providers` — list providers
- `GET/POST /api/v1/workspaces/{workspace_id}/llms` — list/create
- `GET/PUT/DELETE /api/v1/workspaces/{workspace_id}/llms/{llm_id}` — manage
- `POST /api/v1/workspaces/{workspace_id}/llms/{llm_id}/test` — test connection

Providers: `openai`, `anthropic`, `azure_openai`, `ollama`, `generic`.
Roles: `planner`, `ner`, `summarizer`, `query_generator`, `enrichment`.

### Tenancy Bootstrap
`POST /api/v1/admin/tenancy/bootstrap` — initializes a new tenant (organization + workspace + initial user). Part of the customer onboarding flow.

### External Links
Workspaces can have external links defined for dynamic sidebar menu items (from phase 8 implementation). `GET /api/v1/workspaces/{workspace_id}/external-links` (INFERRED_FROM_STRUCTURE from `workspace_routes.py`).

## Related features

- [Feature Entitlements](feature-entitlements.md)
- [Admin: Workspace Setup](../admin/workspace-setup.md)
- [Admin: User Management](../admin/user-management.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/admin_routes.py`
  - `app/routes/workspace_routes.py` (referenced in RBAC audit)
  - `.claude/audits/implementation-notes.md` (workspace LLM)
  - `docs/plans/2026-03-11-workspace-llm-configuration.md`
  - `docs/plans/tenancy_bootstrap_runbook.md` (existence confirmed)
