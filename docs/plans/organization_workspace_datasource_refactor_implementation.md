# QueryForge Tenancy + Datasource Refactor (Implementation Note)

Date: 2026-03-10

## Scope
This change implements an additive tenancy model while keeping `workspace_id` as the primary UI/backend routing key:

`user -> organization -> membership -> workspace -> datasource`

## Phase 1 Audit Findings (Current-State)
- `workspace_id` is deeply embedded as the request scope across routes/services.
- Query execution already funnels through a workspace context builder, making it the right insertion point for datasource indirection.
- Access checks were legacy (`user_workspace_map`) and needed organization/workspace membership support.
- Analytics datasource registration previously depended on static config loading; DB-backed datasource definitions were not first-class.
- Existing user PK is `users.user_id` (`varchar`), not `user.id` (`bigint`), so FK design needed to match actual schema.

## What Changed

### 1) Migration-safe DDL
Added migration:
- `/Users/mmaslak/Local Documents/projects/query-forge-api/migrations/20260310_add_organization_datasource_workspace.sql`

Creates:
- `organization`
- `organization_membership`
- `datasource`
- `workspace_membership` (optional)

Adds to `workspace` (additive):
- `organization_id`
- `datasource_id`
- `name`
- `description`
- `is_active`
- `default_catalog`
- `default_schema`
- `updated_at`

Safety:
- Uses `information_schema` checks + helper procedures for idempotent column/index/FK/check-constraint adds.

### 2) Tenancy/Datasource Models
Added:
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/organization.py`
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/organization_membership.py`
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/datasource.py`
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/workspace_membership.py`

### 3) Datasource Resolution Services
Added:
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/tenancy/datasource_resolver_service.py`
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/tenancy/datasource_catalog_service.py`
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/tenancy/secret_resolver.py`

Core lookup is now:
- `workspace_id -> workspace row -> datasource row`

Validation enforced:
- workspace existence
- active workspace/datasource checks
- workspace org == datasource org consistency

### 4) Runtime Executor Resolution
Updated workspace context resolution:
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/workspace_inventory/workspace_context.py`

Behavior:
- Tries DB tenancy resolution first.
- For Databricks datasource rows, builds `DatabricksForgeQueryPort` from datasource `config_json` + `secret_ref`.
- For non-Databricks (`snowflake`, `mysql`), builds executor from `ExecutorFactory` and adapts it to `ForgeQueryPort`.
- Keeps legacy fallback path for environments not fully migrated yet.

Adapter added:
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/analytics/executor_adapter.py`

### 5) Authorization Boundary Update
Updated workspace access checks:
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/workspace_access_service.py`

Now grants access through any of:
- `user_workspace_map` (legacy)
- `workspace_membership`
- `organization_membership` joined via workspace’s `organization_id`

### 6) Datasource Catalog Exposure
Updated datasource listing route:
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/datasource_routes.py`

Now returns DB-backed datasource definitions (and merges registry entries if present).

### 7) Analytics Registry Bootstrap
Updated:
- `/Users/mmaslak/Local Documents/projects/query-forge-api/app/factory.py`

Now loads datasource configs from DB and overlays/merges with static config sources. Secret refs are resolved at startup for supported ref types.

## Secret Handling
- `datasource.config_json` stores non-secret config only.
- `datasource.secret_ref` stores secret locator (`env:VAR`, future `vault:`/`kms:`).
- Runtime secret resolution is handled server-side by `SecretResolver`.
- Unsupported secret providers are logged and safely ignored (no raw secret persistence added).

## Routing Contract
- Frontend contract remains workspace-first.
- UI continues to pass only `workspace_id`.
- Backend resolves datasource internally from workspace.

## Migration Risks / Assumptions
- Assumes existing user table is `users` with PK `user_id` (varchar).
- `workspace` table must exist before applying this migration.
- Backward compatibility is preserved: legacy access and legacy workspace-context fallback remain active.
- If datasource rows are missing for a workspace, legacy behavior can still be used where fallback paths exist.

## Test Coverage Added/Updated
- `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/tenancy/test_secret_resolver.py`
- `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/tenancy/test_datasource_resolver_service.py`
- `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/test_workspace_context.py`
- `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/test_workspace_access_service.py`
- plus impacted route/service suites

Validated locally:
- 129 modified-suite tests passing.

## Follow-up (Recommended)
1. Add full CRUD admin endpoints for `organization`, `organization_membership`, `datasource`, and `workspace_membership`.
2. Implement vault/kms secret providers in `SecretResolver`.
3. Add explicit health-test endpoint per datasource updating `last_test_*` fields.
4. After rollout stabilization, retire legacy-only fallback branches.
