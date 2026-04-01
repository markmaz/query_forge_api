# QueryForge Documentation Inventory

Generated: 2026-03-31

## Feature Inventory

| Feature | Audience | Key Routes | Key Services | Frontend Entry | Docs Category | Status |
|---------|----------|-----------|--------------|----------------|---------------|--------|
| Query Studio | Analysts | `POST /query-forge/plan`, `POST /executions/start`, `GET /executions/{id}/status`, `GET /executions/{id}/results` | `QueryForgeService`, `PlannerDomainService` | `src/features/query-forge/ui/QueryForgePage.tsx` | user-guides, concepts | CODE_CONFIRMED |
| Domains | Domain admins | `GET/POST /domains/`, `GET/POST /domains/{id}/tables`, `GET/POST /domains/{id}/joins` | `DomainCapabilitiesService`, `DomainTimePolicyService` | `src/features/domain-studio/ui/` | user-guides, concepts, task-playbooks | CODE_CONFIRMED |
| Semantic Registry | Semantic admins | `GET/POST /semantic-concepts`, `/semantic-concept-aliases`, `/semantic-value-aliases`, `/semantic-concept-column-maps`, `/semantic-relationships`, `/semantic-suggestions` | `SemanticRegistryService` | `src/features/semantic-admin/ui/` | concepts, architecture | CODE_CONFIRMED |
| ForgeMatch | Data analysts | `POST /forge-match/upload`, `POST /forge-match/{id}/analyze/start`, `GET /forge-match/status/{job_id}`, `PATCH /forge-match/{id}/mappings` | `ForgeMatchMappingService` | `src/features/forgeMatch/` | user-guides, concepts, task-playbooks | CODE_CONFIRMED |
| Skills | Automation users | `GET/POST /skills`, `POST /skills/{id}/execute`, `POST /skills/{id}/schedules` | `SkillRegistry`, `SkillRunner` (tasks) | `src/features/skills/` | concepts, user-guides | CODE_CONFIRMED |
| ForgeInsights | Chat users | `POST /chat/forge-insights`, `GET/POST /forge-insights/projects`, `GET/POST /forge-insights/threads` | `ForgeInsightsThreadsService` | `src/features/insights/ui/` | user-guides | CODE_CONFIRMED |
| Ingestion | System admins | `POST /ingestion/sync`, `GET /ingestion/status/{job_id}` | `IngestionTasks` (tasks) | `src/features/ingestion/` (NEEDS_VERIFICATION) | admin | CODE_CONFIRMED |
| RBAC | System admins | Role assignment via service API + user_routes | `RBACService` | `src/features/access-admin/`, `src/features/tenant-admin/` | admin, reference | SPEC_CONFIRMED |
| Workspace LLM | System admins | `GET/POST /workspaces/{id}/llms`, `POST /workspaces/{id}/llms/{id}/test` | `WorkspaceLLMService` | (NEEDS_VERIFICATION) | admin | CODE_CONFIRMED |
| Agents | Power users | NEEDS_VERIFICATION (no routes found) | NEEDS_VERIFICATION | NEEDS_VERIFICATION | concepts, user-guides | SPEC_CONFIRMED (design only) |
| AI Suggest | Platform | `POST /ai/suggest`, `POST /ai/suggest-semantic-adapter` | `AISuggestService` | (internal) | architecture | CODE_CONFIRMED |
| NLP / Tier2 | Platform | `POST /nlp/extract`, `POST /nlp-tier2/tier2/parse` | spaCy NER pipeline | (internal) | architecture | CODE_CONFIRMED |
| Exports | Analysts | `POST /exports/excel`, `GET /exports/excel/{token}` | ExportService | (inline in Query Studio UI) | reference | CODE_CONFIRMED |
| Dictionary | Admins | `GET /dictionary/tables`, `PATCH /dictionary/columns/{id}`, `POST /dictionary/columns/import` | `DictionaryService` | `src/features/catalog-admin/` (NEEDS_VERIFICATION) | reference | CODE_CONFIRMED |
| Value Overrides | Admins | `GET/POST /value_overrides/...` | ValueOverrideService | (NEEDS_VERIFICATION) | reference | INFERRED_FROM_STRUCTURE |
| Organizations | System admins | `GET/POST /admin/organizations`, memberships, datasources | AdminService | `src/features/tenant-admin/` | admin | CODE_CONFIRMED |

## Concept Inventory

| Concept | Description | Status |
|---------|-------------|--------|
| Workspace | Primary organizational unit; all features scoped to workspace | CODE_CONFIRMED |
| Organization | Top-level entity grouping workspaces | CODE_CONFIRMED |
| Domain | Curated multi-table view used by planner | CODE_CONFIRMED |
| Semantic concept | Canonical business term in registry | CODE_CONFIRMED |
| Concept alias | Alternate name for a semantic concept | CODE_CONFIRMED |
| Value alias | Normalized filter value mapping | CODE_CONFIRMED |
| Concept column map | Maps concept to physical column in domain | CODE_CONFIRMED |
| Saved query | Persisted query plan in query tree | INFERRED_FROM_STRUCTURE |
| Skill | Automation block (5 types confirmed) | CODE_CONFIRMED |
| Agent | Goal-driven skill orchestration with state | SPEC_CONFIRMED (design), NEEDS_VERIFICATION (impl) |
| ForgeMatch session | Upload+analysis cycle for field mapping | CODE_CONFIRMED |
| ForgeInsights project/thread | Structured chat project and conversation | CODE_CONFIRMED |
| Feature entitlement | Workspace-level feature flag | SPEC_CONFIRMED |
| RBAC role | User+workspace role for access control | SPEC_CONFIRMED |
| SQL-JSON | Intermediate query representation | CODE_CONFIRMED |
| Shared AI pipeline | Reusable AI pipeline node framework | SPEC_CONFIRMED + CODE_CONFIRMED |
| Pipeline trace | Step-by-step planner execution record | CODE_CONFIRMED |
| Workspace LLM | Per-workspace LLM assignment by role | CODE_CONFIRMED |
| Domain profile embedding | Vector embedding of domain for planner selection | CODE_CONFIRMED |

## Gap Summary

Items marked NEEDS_VERIFICATION: **14 distinct items**

Key gaps requiring human review:
1. Agent Layer implementation status (spec exists, no routes found)
2. Query tree routes file location (`query_tree_routes.py` referenced in audit but not in route directory listing)
3. Exact plan response shape (fields returned by planner endpoint)
4. Distinction between `semantic-registry` and `semantic-concepts` namespaces
5. Distinction between `semantic-mappings` and `semantic-concept-column-maps`
6. Workspace LLM frontend surfaces (CustomerInitializationPage Step 4, WorkspaceLLMPage)
7. All URL prefixes for namespaces (only some confirmed)
8. Exact sidebar navigation structure and labels
9. Complete list of feature keys
10. ForgeInsights chat LLM role requirement
11. Whether `/api/v1/` prefix is consistent across all namespaces
12. `catalog_routes.py` referenced in RBAC audit but not in directory listing — may have been added after the audit
13. `workspace_table_routes.py`, `workspace_inventory_routes.py`, `product_routes.py`, `product_groups_routes.py`, `auth_routes.py`, `user_routes.py`, `role_routes.py`, `otp_routes.py`, `public_sales_inquiry.py`, `workspace_llm_routes.py`, `planner_domain.py`, `planner_llm.py`, `planner_extract.py`, `query_forge_routes.py`, `query_studio_routes.py` — referenced in RBAC audit but not found in current directory listing
14. Value override routes behavior
