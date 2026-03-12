# QueryForge Frontend Prompt — Phase 8 Workspace-First Compatibility

You are working in the QueryForge frontend (React + Bootstrap).

Goal:
Keep the app workspace-first. The UI must continue using `workspace_id` as the primary routing/scope key. Do not redesign flows around datasource IDs.

## Rules
- Keep `workspace_id` as the main app scope.
- Do not pass `datasource_id` in normal query/planner/chat flows.
- Only use datasource IDs in admin tenancy screens.
- Keep all existing non-admin flows backward compatible.

## Backend Endpoints (already implemented)
Base: `/api/v1/admin` (admin-only)

### Organization
- `GET /organizations?include_inactive=true|false&q=&limit=&offset=`
- `POST /organizations`
- `GET /organizations/{organization_id}`
- `PATCH /organizations/{organization_id}`
- `DELETE /organizations/{organization_id}?hard=true|false`

### Organization Membership
- `GET /organizations/{organization_id}/memberships?include_inactive=&limit=&offset=`
- `POST /organizations/{organization_id}/memberships`
- `PATCH /organizations/{organization_id}/memberships/{membership_id}`
- `DELETE /organizations/{organization_id}/memberships/{membership_id}`

### Datasource
- `GET /organizations/{organization_id}/datasources?include_inactive=&limit=&offset=`
- `POST /organizations/{organization_id}/datasources`
- `GET /datasources/{datasource_id}`
- `PATCH /datasources/{datasource_id}`
- `DELETE /datasources/{datasource_id}?hard=true|false`
- `POST /datasources/{datasource_id}/test`

### Workspace Binding (workspace-first bridge)
- `GET /workspaces?organization_id=&include_inactive=&limit=&offset=`
- `GET /workspaces/{workspace_id}/binding`
- `PATCH /workspaces/{workspace_id}/binding`

### Workspace Membership
- `GET /workspaces/{workspace_id}/memberships?include_inactive=&limit=&offset=`
- `POST /workspaces/{workspace_id}/memberships`
- `PATCH /workspaces/{workspace_id}/memberships/{membership_id}`
- `DELETE /workspaces/{workspace_id}/memberships/{membership_id}`

## Implementation Tasks

1. API client updates
- Add a new `adminTenancyApi` module with typed methods for all endpoints above.
- Reuse existing auth header and error interceptors.
- Use query builders for `include_inactive`, `limit`, `offset`, and `organization_id`.

2. Admin navigation
- Under System Admin, add menu group: `Tenancy`.
- Pages:
  - `Organizations`
  - `Datasources`
  - `Workspace Bindings`
- Guard all routes by admin role (same guard pattern as other admin pages).

3. Organizations page
- Table with search + pagination.
- Create/Edit modal for name/slug/description/is_active.
- Soft delete and hard delete actions.
- Row action: open memberships drawer.

4. Datasources page
- Context is selected organization.
- Table: name, slug, type, active, last test status/time.
- Create/Edit modal fields:
  - name, slug, type, description, is_active, secret_ref, config_json (JSON editor textarea).
- Actions:
  - Save
  - Test connection (`POST /datasources/{id}/test`)
  - Soft/hard delete.

5. Workspace Bindings page (key Phase 8 page)
- Table columns:
  - workspace_id, workspace_name, organization_name, datasource_name, datasource_type, workspace_is_active.
- Filters:
  - organization
  - include inactive
- Row details panel:
  - call `GET /admin/workspaces/{workspace_id}/binding`.
- Edit form (PATCH binding):
  - organization_id
  - datasource_id
  - name
  - description
  - is_active
  - default_catalog
  - default_schema

6. Workspace membership UI
- In workspace row actions, open memberships modal.
- CRUD using `/admin/workspaces/{workspace_id}/memberships*` endpoints.

7. Contract safety
- Do not alter existing planner/chat/query calls that already send `workspace_id`.
- Do not introduce datasource selector in end-user query flow.
- Datasource selection remains admin configuration through workspace binding.

8. UX details
- Use optimistic updates only for simple toggles (`is_active`).
- For test connection, show inline status badge + latency + message.
- Confirm dialogs for hard delete.
- JSON validation before submitting `config_json`.

9. Tests
- Unit tests for API serialization/deserialization.
- Component tests for:
  - org create/update/delete
  - datasource test action
  - workspace binding patch
- Route guard tests ensuring non-admin users cannot access Tenancy screens.

10. Rollout
- Feature flag: `REACT_APP_ADMIN_TENANCY_ENABLED=true`.
- Hide Tenancy nav when flag is off.
- Keep existing admin pages unchanged.

## Acceptance Criteria
- Existing workspace-scoped product flows still work unchanged.
- Admin can fully manage organizations, datasources, and workspace bindings.
- Workspace binding page is the only place where datasource assignment happens.
- No frontend flow requires replacing `workspace_id` with datasource ID.
