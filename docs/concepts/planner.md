# Planner

## What it is

The planner is the AI pipeline that translates a natural language prompt into an executable SQL query via a structured intermediate representation (SQL-JSON). It lives in `app/services/planner_domain/` and is composed of multiple focused sub-services.

## Why it matters

The planner is the core intelligence layer of QueryForge. It abstracts the complexity of domain selection, semantic concept resolution, LLM-based intent parsing, and query normalization into a single API call. Without it, users would need to hand-craft SQL or SQL-JSON directly.

## Who uses it

- **Query Studio** — calls the planner endpoint when a user submits a prompt.
- **Skills** — the skill runner re-executes saved queries via the planner pipeline.
- **Inline analysis** — `POST /api/v1/query_analysis/{query_id}/analyze` re-runs a saved query for AI analysis.

## Key concepts

### PlannerDomainService
The main orchestration class (`app/services/planner_domain/service.py`). Coordinates all sub-services.

### Domain Selection
Selects the most relevant domain for the prompt using vector search (Qdrant `table_catalog` collection) and policy-based reranking. Extracted into `DomainSelectionService` (`app/services/planner_domain/domain_selection_service.py`).

### Prompt Signal Extraction
`PromptSignalService` extracts typed signals (entities, intents, constraints) from the normalized prompt. Used by both the planner and ForgeMatch via the shared_ai pipeline.

### Normalization Pipeline
`NormalizationPipeline` runs entity normalizers (entity, metric, time) against the prompt before passing to the LLM. Normalizers are in `app/services/planner_domain/normalizers/`.

### LLM Planning
`LLMPlanningService` calls the configured LLM (resolved via `WorkspaceLLMService.get_llm_for_role("planner")` with env-var fallback) with the domain schema and normalized prompt to produce a structured plan (schema v2 format).

### Semantic Integration
`SemanticIntegrationService` resolves semantic concepts against the plan output, applies value alias normalization, and enriches filters with canonical concept keys.

### Plan Postprocessing / Enrichment / Finalization
`PlanPostprocessService`, `PlanEnrichmentService`, `PlanFinalizationService` apply validation, enrichment, and finalization steps.

### Response Builder
`PlannerResponseBuilderService` constructs the API response object including the compiled SQL, explanation, debug trace, and next actions.

### Explanation Service
`ExplanationService` generates a human-readable explanation of the plan (which domain was selected, which concepts were matched, which filters were applied). Configurable via `QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED` env var.

### Next Actions Service
`NextActionsService` generates suggested follow-up queries. Configurable via `QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED` env var. Can run asynchronously (controlled by `QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT`).

### Rerank Policy Engine
`PlannerDomainRerankPolicyEngine` (`app/services/planner_domain/rerank_policy_engine.py`) applies workspace-level rerank policies to domain/column candidate scoring. Policies are defined via admin routes.

### Conversation Context
The planner supports multi-turn planning (conversation). `PlannerDomainConversationStore` persists conversation state with a configurable TTL. The `HybridPlannerDomainConversationStore` is an alternative implementation.

### Pipeline Trace
When `QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED` is set, the planner records step-by-step trace data (timing, intermediate artifacts) retrievable via `GET /api/v1/admin/pipeline-profiles/{trace_id}`.

### Shared AI Pipeline
The planner's signal extraction, capability resolution, and reranking stages now run through the shared `app/services/shared_ai/` executor framework (all 8 phases complete as of 2026-03-28). See [Architecture: Shared AI Pipeline](../architecture/shared-ai-pipeline.md).

### LLM Configuration
LLM is resolved per workspace per role via `WorkspaceLLMService`. The `planner` role maps to `VLLM_BASE_URL` + `SEMANTIC_PLAN_LLM_MODEL` as fallback env vars. API keys are Fernet-encrypted at rest.

## Related features

- [Domains](domains.md)
- [Semantic Registry](semantic-registry.md)
- [Shared AI Pipelines](shared-ai-pipelines.md)
- [Architecture: Planner Pipeline](../architecture/planner-pipeline.md)
- [Troubleshoot Planner Output](../task-playbooks/troubleshoot-planner-output.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/services/planner_domain/service.py`
  - `app/services/planner_domain/` (directory listing)
  - `.claude/audits/backend-audit.md` (Phase 7)
  - `specs/queryforge_shared_ai_pipeline_architecture_spec.md`
  - `.claude/audits/implementation-notes.md` (LLM config)
