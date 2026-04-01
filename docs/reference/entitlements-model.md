# Reference: Entitlements Model

## Purpose

Database schema and service API for workspace feature entitlements and user roles.

## Database tables (SPEC_CONFIRMED from `specs/queryforge_rbac_spec.md`)

### roles
```sql
id          INT PK
name        VARCHAR(64) UNIQUE NOT NULL
description VARCHAR(500)
created_at  DATETIME
```

### user_roles
```sql
id           INT PK
user_id      INT FK → users.id CASCADE
role_id      INT FK → roles.id CASCADE
workspace_id INT NULL FK → workspaces.id CASCADE
             -- NULL for global roles (super_admin only)
             -- workspace-scoped for all other roles
granted_by   INT NULL
granted_at   DATETIME
UNIQUE KEY uq_user_role (user_id, role_id, COALESCE(workspace_id, 0))
```

Note: MySQL `NULL != NULL` — the COALESCE handles the NULL-safe unique constraint for the `super_admin` global role. Uniqueness is also enforced at the service layer.

### workspace_features
```sql
id           INT PK
workspace_id INT FK → workspaces.id CASCADE
feature_key  VARCHAR(64) NOT NULL
granted_at   DATETIME
granted_by   INT NULL
UNIQUE(workspace_id, feature_key)
```

**Missing row = feature disabled.** No is_enabled flag. Delete row to disable.

## Role names (SPEC_CONFIRMED)

```
super_admin
workspace_admin
forge_match:admin  /  forge_match:user
query_studio:admin /  query_studio:user
skills:admin       /  skills:user
planner:admin      /  planner:user
semantic:admin     /  semantic:user
ingestion:admin    /  ingestion:user
vector:admin       /  vector:user
ai:admin           /  ai:user
system:admin       /  system:user
```

## Implication rules (SPEC_CONFIRMED)

```
super_admin         → bypasses ALL checks (global)
workspace_admin     → bypasses feature checks; implies all feature:user roles
feature:admin       → implies feature:user (same feature)
feature:user        → explicit access only
```

All implication logic lives in `RBACService` only. Decorators call the service.

## Valkey cache keys

```
qf:rbac:user_roles:{user_id}:{workspace_id}    TTL: 60s
qf:rbac:workspace_features:{workspace_id}      TTL: 120s
```

Cache failures are non-blocking — fall back to DB.

## Service API (SPEC_CONFIRMED)

```python
# app/services/rbac_service.py
get_effective_roles(user_id, workspace_id) -> set[str]
user_has_role(user_id, role, workspace_id) -> bool
workspace_has_feature(workspace_id, feature_key) -> bool
assign_role(user_id, role_name, workspace_id, granted_by) -> dict
revoke_role(user_id, role_name, workspace_id) -> bool
set_workspace_feature(workspace_id, feature_key, enabled, granted_by) -> dict
invalidate_user_roles(user_id, workspace_id) -> None
invalidate_workspace_features(workspace_id) -> None
```

## Decorator API (SPEC_CONFIRMED)

```python
@require_role("forge_match:user")            # single role required
@require_access("forge_match")               # feature + :user role
@require_access("forge_match", role="admin") # feature + :admin role
@require_admin()                             # workspace_admin or super_admin
@public                                      # no auth required
@require_ownership(model, id_param, admin_role, check_read=True)  # resource ownership
```

HTTP error codes:
- 401 → not authenticated
- 403 → lacks permission or feature disabled
- 503 → `g.workspace_id` missing (misconfiguration)

## Source grounding
- STATUS: SPEC_CONFIRMED
- Sources:
  - `specs/queryforge_rbac_spec.md`
  - `.claude/audits/backend-audit.md` (Tasks 5-7)
