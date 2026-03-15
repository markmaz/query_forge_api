# LLM_RESOLVER Rollout (Implemented)

## Objective
Route all major backend LLM work through one resolver with this precedence:
1. Explicit `llm_id` override (if provided)
2. Workspace role configuration (`workspace_llm`)
3. Environment fallback defaults

## Runtime Behavior
- `app/config/llm_resolver.py` is the single runtime resolver.
- `build_llm_client_for_role(...)` now returns resolved client + metadata.
- Services using injected `llm_client` (tests/custom wiring) keep using that injected client and skip resolver override.

## Roles in Use
- `planner`
  - `PlannerDomainService`
  - `PlannerLLMService`
  - `PlanService` (`/api/v1/semantic/plan`)
  - compact/unified planner helpers when called without injected client
- `ner`
  - `ForgeInsightsRouterService` route-classification step
- `enrichment`
  - `ForgeMatchLLMRanker`
  - `DomainProfileEmbeddingService`
  - `SemanticLLMLabeler`
  - semantic catalog enrichment (`LLMSemanticEnrichmentClient`)
  - dictionary LLM adapter (when workspace context is supplied)

## API Contract Additions
- Optional `llm_id` override added to:
  - `POST /api/v1/planner/plan_domain`
  - `POST /api/v1/planner/plan_domain/next_actions`
  - `POST /api/v1/planner/plan_llm`
  - `POST /api/v1/semantic/plan`
  - `POST /api/v1/semantic/suggest-columns`
  - `POST /api/v1/forge-match/{session_id}/analyze`
  - `POST /api/v1/forge-match/{session_id}/analyze/start`
  - `POST /api/v1/domain-profiles/{domain_id}/generate`
  - `POST /api/v1/domain-profiles/generate`
  - `POST /api/v1/domain-profiles/generate-all`
  - Admin equivalents under `/api/v1/admin/domain-profiles/*`
  - `POST /api/v1/admin/semantic-catalog/build`
  - `POST /api/v1/semantic-suggestions/runs/{run_id}/execute?llm_id=<id>`

## Discovery Endpoints (for frontend selectors)
- `GET /api/v1/llm-roles`
- `GET /api/v1/llm-providers`
- `GET /api/v1/workspace-llms/workspaces/{workspace_id}/llms`

## Notes
- If no `llm_id` is provided, the resolver uses role mapping + env fallback.
- Resolver metadata is now included in key planner/debug outputs where available (`llm_resolution`).
