# Feature Entitlements (Admin)

## Purpose

Instructions for system administrators to enable and disable features for workspaces.

## How entitlements work

A workspace either has a feature row in `workspace_features` or it does not. There is no "enabled" flag column — presence of the row means enabled, absence means disabled.

## Enable a feature for a workspace

Via service:
```python
RBACService.set_workspace_feature(
    workspace_id="ws_abc",
    feature_key="forge_match",
    enabled=True,
    granted_by=admin_user_id
)
```

This inserts a row into `workspace_features`. (NEEDS_VERIFICATION: whether there is a direct admin API endpoint for this, or if it is service-layer only.)

## Disable a feature for a workspace

Set `enabled=False` in the same call — this deletes the row.

## Cache behavior

Feature entitlements are cached in Valkey at:
```
qf:rbac:workspace_features:{workspace_id}
```
Cache TTL: 120 seconds. After disabling a feature, it takes up to 120 seconds to take effect for active users. Force invalidation: `RBACService.invalidate_workspace_features(workspace_id)`.

## Feature key reference

| Feature Key | Product Area | Required By |
|-------------|--------------|-------------|
| `forge_match` | ForgeMatch | All ForgeMatch routes |
| `query_studio` | Query Studio | Query builder, saved queries, analysis |
| `semantic` | Semantic Registry | Concept/alias/mapping management |
| `skills` | Skills and destinations | Skill CRUD, schedules, destinations |
| `ingestion` | Ingestion | Sync, status, history |
| `planner` | AI Planner | planner-domain plan endpoint |
| `ai` | AI features | AI suggest, NLP routes |
| `vector` | Vector search | Domain vector search, embeddings |
| `catalog` | Catalog/Domains | Domain CRUD, workspace inventory |
| `exports` | Exports | Excel export |
| `forge_insights` | ForgeInsights | Chat, projects, threads |
| `workspaces` | Workspace read | Workspace list and detail |

## Related docs

- [Concepts: Feature Entitlements](../concepts/feature-entitlements.md)
- [Admin: User Management](user-management.md)
- [Reference: Entitlements Model](../reference/entitlements-model.md)

## Source grounding
- STATUS: SPEC_CONFIRMED (schema), CODE_CONFIRMED (feature keys from decorator audit)
- Sources:
  - `specs/queryforge_rbac_spec.md`
  - `.claude/audits/backend-audit.md` (Tasks 5-7)
