# User Management

## Purpose

Guide for system administrators managing users, workspace memberships, and role assignments.

## User lifecycle

### Create / invite users

Users are invited via bulk invite or individual invite:
- `POST /api/v1/users/bulk-invite` (INFERRED_FROM_STRUCTURE from backend-audit)
- `POST /api/v1/users/{user_id}/resend-invite` — resend invitation

### View users

- `GET /api/v1/users` — list all users (system admin)
- `GET /api/v1/users/{user_id}` — get user details
- `GET /api/v1/users/counts` — count statistics

### Update users

`PATCH /api/v1/users/{user_id}` — update user details.

### Workspace membership

- `GET /api/v1/admin/workspaces/{workspace_id}/memberships` — list workspace members
- `POST /api/v1/admin/workspaces/{workspace_id}/memberships` — add a user to workspace
- `DELETE /api/v1/admin/workspaces/{workspace_id}/memberships/{membership_id}` — remove

Alternatively:
- `GET /api/v1/users/{user_id}/workspaces` — list workspaces for a user
- `GET/POST/DELETE /api/v1/user-workspace-map` (INFERRED_FROM_STRUCTURE from backend-audit)

## Role assignment

### Role model

20 roles total (SPEC_CONFIRMED from `specs/queryforge_rbac_spec.md`):

**Global:**
- `super_admin` — bypasses all checks

**Workspace-scoped:**
- `workspace_admin` — implies all feature:user roles in workspace
- `forge_match:admin` / `forge_match:user`
- `query_studio:admin` / `query_studio:user`
- `skills:admin` / `skills:user`
- `planner:admin` / `planner:user`
- `semantic:admin` / `semantic:user`
- `ingestion:admin` / `ingestion:user`
- `vector:admin` / `vector:user`
- `ai:admin` / `ai:user`
- `system:admin` / `system:user`

### Role resolution rules

```
super_admin       → bypasses ALL checks (global)
workspace_admin   → bypasses feature checks, implies all feature:user roles
feature:admin     → implies feature:user for same feature
feature:user      → explicit access only
Roles are additive
```

### Assign roles

Via service: `RBACService.assign_role(user_id, role_name, workspace_id, granted_by)`

Via API:
- `GET /api/v1/users/{user_id}/direct-roles` — view direct role assignments
- `POST /api/v1/users/{user_id}/direct-roles` — assign a role
- `DELETE /api/v1/users/{user_id}/direct-roles/{role_id}` — revoke

### List available roles

`GET /api/v1/roles` — list all defined roles.

### Cache invalidation

Role changes take effect within 60 seconds (Valkey cache TTL). Force immediate invalidation: `RBACService.invalidate_user_roles(user_id, workspace_id)` (no public API endpoint — NEEDS_VERIFICATION).

## Related docs

- [Concepts: Feature Entitlements](../concepts/feature-entitlements.md)
- [Admin: Feature Entitlements](feature-entitlements.md)
- [Spec: RBAC](../../specs/queryforge_rbac_spec.md)

## Source grounding
- STATUS: SPEC_CONFIRMED (role model), CODE_CONFIRMED (route classes from RBAC audit)
- Sources:
  - `specs/queryforge_rbac_spec.md`
  - `.claude/audits/backend-audit.md` (Tasks 5-7)
  - `app/routes/admin_routes.py`
