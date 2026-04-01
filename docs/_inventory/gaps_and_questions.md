# Documentation Gaps and Questions

Generated: 2026-03-31

---

## Uncertain Flows

### 1. Query Tree Routes File Location
- **Issue**: `query_tree_routes.py` is referenced in `.claude/audits/backend-audit.md` (Task 6) as having `@require_access("query_studio")` applied to 23 methods (QueryTree, Folders, SavedQueryCreate, etc.), but this file was NOT found in `app/routes/` during the inventory.
- **Impact**: Saved query CRUD routes (create, move, trash, restore, purge), folder routes, and share routes are documented as INFERRED_FROM_STRUCTURE only.
- **Question**: Is `query_tree_routes.py` registered under a different path? Was it renamed? Check `app/factory.py` for the actual namespace registration.

### 2. Multiple Route Files Referenced But Not Found in Listing
The RBAC audit (Task 5) references the following files that were NOT in the `app/routes/` directory listing:
- `auth_routes.py`
- `user_routes.py`
- `user_workspace_routes.py`
- `role_routes.py`
- `workspace_routes.py`
- `workspace_table_routes.py`
- `workspace_llm_routes.py`
- `otp_routes.py`
- `public_sales_inquiry.py`
- `catalog_routes.py`
- `product_routes.py`
- `product_groups_routes.py`
- `planner_domain.py`
- `planner_llm.py`
- `planner_extract.py`
- `query_forge_routes.py`
- `query_studio_routes.py`
- **Question**: Are these files in a subdirectory of `app/routes/`? Or were they added after the inventory was taken?

### 3. Exact Plan Response Shape
- **Issue**: The planner's API response shape was not confirmed by reading the route handler or response builder.
- **Impact**: `docs/reference/planner-response-objects.md` has NEEDS_VERIFICATION for the plan response section.
- **Question**: What are the exact top-level fields returned by `POST /api/v1/query-forge/plan` (or the actual planner route)?

### 4. Agent Layer Implementation Status
- **Issue**: `specs/queryforge_agent_layer_codex_spec.md` defines a comprehensive V1 agent layer, but no agent-specific routes, services, or models were found during inventory.
- **Question**: Has agent layer implementation started? Are there agent routes under a different name (e.g., under `skills_routes.py` or a new routes file)?

### 5. Workspace LLM Frontend
- **Issue**: The implementation notes mention two frontend surfaces for workspace LLM: CustomerInitializationPage (Step 4) and WorkspaceLLMPage (`/admin/tenancy/workspace-llms`). Neither was confirmed in the frontend feature directory listing.
- **Question**: Are these pages present in the frontend codebase?

---

## Missing Screenshots

All user guides note NEEDS_VERIFICATION for UI flow details. Screenshots are needed for:
1. Query Studio workflow (domain selection → prompt → plan → results)
2. ForgeMatch workflow stages
3. Skills builder drawer
4. Domain Studio configuration flow
5. Semantic Admin concept/alias management

---

## Unclear Terminology

### 1. `semantic-registry` vs `semantic-concepts`
Two separate namespaces exist: `GET/POST /api/v1/semantic-registry` and `GET/POST /api/v1/semantic-concepts`. Their exact relationship is unclear.
- **Question**: Is `semantic-registry` a higher-level object that references concepts? Or a different model entirely? What are the fields on a `SemanticRegistryEntry` vs a `SemanticConcept`?

### 2. `semantic-mappings` vs `semantic-concept-column-maps`
Both involve mapping concepts to columns. The distinction is not clear from route names alone.
- **Question**: What is the difference between a `SemanticMapping` and a `SemanticConceptColumnMap`?

### 3. `value_overrides` namespace
`value_override_routes.py` defines a `value_overrides` namespace. The purpose (beyond the route name) is not documented.
- **Question**: What are value overrides? Are they user-facing lists (regions, NPI categories, service lines as suggested by `query_forge_service.py` constants)?

### 4. `forge_insights` vs `chat` namespace
The chat endpoint for ForgeInsights is `POST /chat/forge-insights` but there is also a `GET/POST /forge-insights/projects` namespace. The relationship between the two is inferred.
- **Question**: Confirm: ForgeInsights uses `/chat/forge-insights` for LLM messages and `/forge-insights/` for project/thread CRUD?

---

## Spec vs Implementation Conflicts

### 1. MySQL `information_schema.schemata`
Per the project memory: `information_schema.schemata` is inaccessible on the production Databricks configuration. The Databricks metadata provider was updated to use `SELECT DISTINCT table_schema FROM information_schema.tables` instead. MySQL provider uses `information_schema.schemata` (which is valid for MySQL). **No conflict** — implementations are database-specific. Documented in memory.

### 2. `_norm_key` variant
Backend audit notes: `_norm_key` in `explanation_service.py` and `next_actions_service.py` uses `str(value or "").strip().lower()` NOT the `.replace(" ", "_")` variant mentioned in the spec. Implementation wins over spec here.

---

## Docs Needing Human Review

| Doc | Issue |
|-----|-------|
| `getting-started/first-query.md` | Exact sidebar navigation label unknown |
| `user-guides/saved-queries-overview.md` | Route file location unconfirmed |
| `concepts/agents.md` | Implementation existence unconfirmed |
| `reference/planner-response-objects.md` | Plan response field names unconfirmed |
| `reference/saved-query-model.md` | Database schema unconfirmed |
| `reference/agent-definition-model.md` | Full spec, no confirmed implementation |
| `architecture/agent-layer.md` | Full spec, no confirmed implementation |
| All architecture docs | URL prefixes for many namespaces not confirmed (assumed `/api/v1/` + namespace name) |

---

## Additional Investigation Recommended

1. Read `app/factory.py` fully to confirm all namespace registrations and URL prefix patterns.
2. Read `app/routes/planner_domain.py` (if it exists) for exact planner endpoint paths and request/response shapes.
3. Read `app/services/planner_domain/schema_v2.py` and `validate_v2.py` for the SQL-JSON plan schema.
4. Read `app/models/` subdirectories for confirmed database schemas (saved queries, skills, etc.).
5. Read `app/services/query_forge/` (if it exists post-refactor) for updated query service structure.
6. Check `src/features/` for agent, workspace-llm, and other unconfirmed frontend surfaces.
