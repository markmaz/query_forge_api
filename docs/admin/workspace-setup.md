# Workspace Setup

## Purpose

Guide for system administrators setting up a new workspace: creating the organization, datasource, workspace, binding them together, bootstrapping initial users, and enabling features.

## Steps

### 1. Create an organization

`POST /api/v1/admin/organizations` — provide an organization name and optional metadata.

### 2. Register a datasource

`POST /api/v1/admin/organizations/{organization_id}/datasources` — register a datasource with connection details. Supported types (CODE_CONFIRMED): Databricks SQL, MySQL, Snowflake.

Test the connection: `POST /api/v1/admin/datasources/{datasource_id}/test`.

View available namespaces: `GET /api/v1/admin/datasources/{datasource_id}/namespaces`.

### 3. Create a workspace

`POST /api/v1/admin/workspaces` — create a workspace binding. Provide:
- Workspace ID (string, not auto-generated — chosen by admin)
- Organization ID
- Datasource binding

### 4. Bootstrap the tenant

`POST /api/v1/admin/tenancy/bootstrap` — initializes a new tenant with default configuration. Refer to `docs/plans/tenancy_bootstrap_runbook.md` for step-by-step details.

### 5. Add users to the organization and workspace

`POST /api/v1/admin/organizations/{organization_id}/memberships` — add users to the organization.

`POST /api/v1/admin/workspaces/{workspace_id}/memberships` — add users to the workspace.

### 6. Assign roles

Assign workspace-scoped roles to users via `RBACService.assign_role()` or through the user management UI. See [User Management](user-management.md) and [Feature Entitlements](feature-entitlements.md).

### 7. Enable feature entitlements

Enable features for the workspace via `RBACService.set_workspace_feature(workspace_id, feature_key, enabled=True, granted_by=admin_user_id)`. Feature keys: `forge_match`, `query_studio`, `semantic`, `skills`, `ingestion`, `planner`, `ai`, `vector`, `catalog`, `exports`, `forge_insights`, `workspaces`.

### 8. Configure LLMs

Assign LLMs per role via the Workspace LLM API:
`POST /api/v1/workspaces/{workspace_id}/llms` — create LLM assignment.

Required roles at minimum: `planner` (for Query Studio), `summarizer` (for AI summaries and ForgeInsights).

See [Implementation Notes: Workspace LLM](.././.claude/audits/implementation-notes.md) for env-var fallback details.

### 9. Run ingestion

`POST /api/v1/ingestion/sync` — ingest workspace tables from the datasource. Monitor status at `GET /api/v1/ingestion/status/{job_id}`.

### 10. Create domains

See [Task Playbook: Create a Domain](../task-playbooks/create-a-domain.md).

## Related docs

- [Concepts: Workspaces and Organizations](../concepts/workspaces-and-organizations.md)
- [Admin: User Management](user-management.md)
- [Admin: Feature Entitlements](feature-entitlements.md)
- [Admin: Deployment Overview](deployment-overview.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/admin_routes.py`
  - `docs/plans/tenancy_bootstrap_runbook.md` (existence confirmed)
  - `.claude/audits/implementation-notes.md`
