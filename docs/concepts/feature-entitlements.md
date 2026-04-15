# Feature Entitlements

## What it is

Feature entitlements are workspace-level flags that control which product features are available in a given workspace. A workspace either has a feature key or it does not — there is no "enabled/disabled" flag column. A missing row means the feature is disabled.

## Why it matters

Different customers may license different feature sets. Feature entitlements let system administrators enable or disable features per workspace without deploying different code. They also provide the first layer of access control: even an `admin`-role user cannot access a feature that is not entitled to their workspace.

## Who uses it

- **System administrators** — grant or revoke features for workspaces via `RBACService.set_workspace_feature()`.
- **The RBAC system** — checks entitlement on every `@require_access` decorated route.

## Key concepts

### Feature Keys (CODE_CONFIRMED from RBAC spec and route audit)

| Feature Key | Description |
|-------------|-------------|
| `forge_match` | ForgeMatch assisted field mapping |
| `query_studio` | Query Studio (query builder and runner) |
| `semantic` | Semantic registry management |
| `skills` | Skills automation |
| `ingestion` | Metadata ingestion management |
| `planner` | AI planner (plan-domain endpoint) |
| `ai` | AI endpoints (suggest, NLP) |
| `vector` | Vector search and embedding |
| `catalog` | Catalog / domain management |
| `exports` | Query result exports |
| `forge_insights` | ForgeInsights chat (projects + threads) |
| `workspaces` | Workspace read access |

NEEDS_VERIFICATION: complete canonical list of feature keys. The above is inferred from `@require_access(...)` decorator arguments in route files.

### Storage
Feature entitlements are stored in the `workspace_features` table:
```sql
workspace_features:
  id           INT PK
  workspace_id INT FK
  feature_key  VARCHAR(64)
  granted_at   DATETIME
  granted_by   INT NULL
  UNIQUE(workspace_id, feature_key)
```

### Cache
Feature entitlements are cached in Valkey at key `qf:rbac:workspace_features:{workspace_id}` with a 120-second TTL. Cache failures fall back to the database silently.

### Enforcement
The `@require_access("feature_key")` decorator checks both:
1. Workspace has the feature entitlement (`workspace_features` row exists)
2. User has at least `feature_key:user` role in the workspace (or `workspace_admin` / `super_admin`)

`@require_access("feature_key", role="admin")` additionally requires the `feature_key:admin` role.

## Related features

- [Workspaces and Organizations](workspaces-and-organizations.md)
- [Admin: Feature Entitlements](../admin/feature-entitlements.md)
- [Reference: Entitlements Model](../reference/entitlements-model.md)

## Source grounding
- STATUS: SPEC_CONFIRMED (design), CODE_CONFIRMED (decorator usage)
- Sources:
  - `specs/queryforge_rbac_spec.md`
  - `.claude/audits/backend-audit.md` (Tasks 5-7: decorator audit)
