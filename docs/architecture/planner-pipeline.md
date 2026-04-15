# Architecture: Planner Pipeline

## Purpose

The planner pipeline translates a natural-language prompt and an optional domain hint into a compiled SQL query via a structured intermediate representation (SQL-JSON v2). It is the core AI-driven capability of QueryForge.

## Components

| Component | Description |
|-----------|-------------|
| `PlannerDomainService` | Main orchestrator (`app/services/planner_domain/service.py`) |
| `DomainSelectionService` | Selects the best-matching domain using vector search + reranking |
| `PromptSignalService` | Extracts typed signals (entities, intents, constraints) from the normalized prompt |
| `NormalizationPipeline` | Runs entity, metric, and time normalizers before LLM call |
| `LLMPlanningService` | Calls the workspace LLM with domain schema + prompt; receives schema v2 JSON |
| `SemanticIntegrationService` | Resolves semantic concepts; applies value aliases and concept-column maps |
| `PlanPostprocessService` | Applies post-LLM normalization and validation |
| `PlanEnrichmentService` | Enriches the plan with additional domain metadata |
| `PlanFinalizationService` | Final validation pass |
| `ExplanationService` | Builds human-readable explanation of the plan |
| `NextActionsService` | Generates suggested follow-up queries |
| `PlannerResponseBuilderService` | Assembles the API response object |
| `PlannerDomainRerankPolicyEngine` | Applies workspace-level rerank policies to domain/column scoring |
| `Rerank Policy Engine` (shared_ai) | Shared reranking node used by both planner and ForgeMatch |
| `PipelineTraceService` | Records step-by-step timing and intermediate data when tracing is enabled |
| `ConversationStore` | Persists multi-turn conversation state with TTL |
| `QueryForgeService` | Compiles the SQL-JSON plan into executable SQL |

## Flow

1. **Request received** — `POST /api/v1/query-forge/plan` (NEEDS_VERIFICATION: route path). Input: prompt, optional domain_id, optional conversation_id.

2. **Conversation context** — if conversation_id provided, load prior state from `ConversationStore`. Bootstrap conversation from seed if new.

3. **Prompt normalization** — `normalize_plan_prompt` cleans the prompt. `NormalizationPipeline` runs entity, metric, and time normalizers.

4. **Signal extraction** — `PromptSignalService` extracts typed signals (via shared_ai pipeline executor).

5. **Domain selection** — `DomainSelectionService` queries Qdrant (`table_catalog` collection) for candidate domains. `PlannerDomainRerankPolicyEngine` reranks candidates using workspace policies. Best domain selected.

6. **Capability resolution** — `DomainCapabilitiesService` loads domain capabilities. Capability packing policy applied.

7. **LLM planning** — `LLMPlanningService` constructs the prompt (domain schema, capabilities, normalized prompt, conversation context) and calls the workspace LLM. Output: schema v2 JSON.

8. **Semantic integration** — `SemanticIntegrationService` resolves concept keys from the LLM output against the semantic registry. Value aliases normalized.

9. **Postprocessing** — `PlanPostprocessService` validates and normalizes the raw LLM output (handles malformed output, missing fields, type coercions).

10. **Enrichment** — `PlanEnrichmentService` adds derived fields and domain-specific metadata.

11. **Finalization** — `PlanFinalizationService` final validation.

12. **Map to SQL-JSON** — `map_plan_v2_to_sqljson` converts the v2 plan to `sqljson` format.

13. **Compile SQL** — `QueryForgeService.compile()` compiles the sqljson into parameterized SQL.

14. **Explanation** — `ExplanationService.build_explanation()` generates a narrative (LLM call optional, controlled by `QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED`).

15. **Next actions** — `NextActionsService.maybe_generate()` generates follow-up suggestions (async-capable, controlled by `QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT`).

16. **Response** — `PlannerResponseBuilderService` assembles the final response including SQL, explanation, debug trace, and next actions.

17. **Conversation state saved** — conversation state updated in `ConversationStore`.

## Inputs / Outputs

**Inputs:**
- `prompt` (string) — user's natural language question
- `workspace_id` (string) — determines which domains and semantic content to search
- `domain_id` (int, optional) — pin to a specific domain
- `conversation_id` (string, optional) — resume a prior conversation
- `fast_mode` (bool, optional) — skip expensive operations (default from `QF_PLAN_DOMAIN_FAST_MODE_DEFAULT`)

**Outputs:**
- `sql` — compiled SQL query
- `plan` — structured SQL-JSON plan
- `explanation` — human-readable narrative
- `next_actions` — suggested follow-up queries
- `conversation_id` — for conversation continuity
- `debug` — pipeline trace reference (if tracing enabled)

## Important decisions

- **LLM is not the orchestrator** — the pipeline is deterministic code. The LLM only generates the structured plan schema v2 JSON; it does not make routing or normalization decisions.
- **Shared AI pipeline** — signal extraction and reranking run through `app/services/shared_ai/` executor (phases 1-8 complete as of 2026-03-28).
- **Conversation state is Redis-backed** — `HybridPlannerDomainConversationStore` with configurable TTL.
- **Explanation and next actions are optional** — controlled by env vars, can be disabled for performance.
- **Next actions can run async** — `QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT` controls default.

## Related systems

- [Semantic Layer](semantic-layer.md)
- [Shared AI Pipeline](shared-ai-pipeline.md)
- [Concepts: Planner](../concepts/planner.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/services/planner_domain/service.py`
  - `app/services/planner_domain/` (directory listing)
  - `.claude/audits/backend-audit.md` (Phase 7)
  - `specs/queryforge_shared_ai_pipeline_architecture_spec.md`
