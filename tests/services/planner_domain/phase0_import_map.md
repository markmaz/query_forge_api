# Phase 0c — Import Map for `service.py`

Generated: 2026-03-27
Purpose: Prevent accidental import breakage during Phase 1–8 extractions.

---

## Modules that import FROM `service.py`

| Importer | What it imports |
|---|---|
| `app/services/planner_domain/__init__.py` | `PlannerDomainService` |
| `app/routes/planner_domain.py` | `PlannerDomainService` (via `__init__`) |
| `app/routes/admin_routes.py` | `PlannerDomainService` (via `__init__`) |
| `app/services/chat/forge_insights_router_service.py` | `PlannerDomainService` (via `__init__`) |
| `tests/services/planner_domain/test_service.py` | `PlannerDomainService`, `LLMPlanResult`, `SlotExtractionResult`, `_serialize_domain_candidates_for_debug`, `_column_heuristic_boost`, `_district_county_retry_hint`, `_normalize_relative_time_in_plan`, `_normalize_top_bottom_ranking_in_plan`, `_normalize_year_keyword_filters_in_plan`, `_prompt_is_followup_edit`, `_required_column_keys` |
| `tests/services/planner_domain/test_conversation_context.py` | `PlannerDomainService` |
| `tests/services/planner_domain/test_semester_normalization.py` | `_normalize_semester_filters_in_plan`, `_semester_bucket_from_text` |
| `tests/services/planner_domain/test_adm_filter_normalization.py` | `_normalize_adm_default_filters_in_plan` |
| `tests/services/planner_domain/test_school_year_normalization.py` | `_normalize_school_year_filters_in_plan` |
| `tests/services/planner_domain/test_country_normalization.py` | `_normalize_country_filters_in_plan` |
| `tests/services/planner_domain/test_staff_role_normalization.py` | `_normalize_staff_role_filters_in_plan` |
| `tests/services/planner_domain/test_school_name_normalization.py` | `_normalize_school_name_filters_in_plan` |
| `tests/services/planner_domain/test_next_actions_normalization.py` | `_normalize_next_actions` |
| `tests/services/planner_domain/test_pipeline_profile_list.py` | `service` module (as `svc_mod`) |
| `tests/services/planner_domain/test_pipeline_profile_lookup.py` | `service` module (as `planner_domain_service_module`), `_read_pipeline_profile_from_log` |
| `tests/services/planner/test_unified_llm_planner.py` | `service` module (as `planner_domain_service_module`), `PlannerDomainService` |

---

## Modules that `service.py` imports FROM

### Standard library
- `json`, `logging`, `os`, `re`, `uuid`, `dataclasses`, `datetime`, `logging.handlers`, `time`, `typing`, `zoneinfo`

### Third-party
- `pydantic` (`BaseModel`, `ConfigDict`, `Field`, `ValidationError`, `field_validator`)
- `qdrant_client.http.models`

### Internal — `app/`
| Module | What is imported |
|---|---|
| `app/adapters/mysql_sql_executor.py` | `ForgeMetaSQL` |
| `app/config/llm_resolver.py` | `build_llm_client_for_role` |
| `app/config/__init__.py` | 28 config constants (`EMBEDDING_MODEL_NAME`, `PLANNER_UNIFIED_LLM`, `QDRANT_COLUMN_COLLECTION_V2`, `QF_PLAN_DOMAIN_*`, `QF_SCHOOL_YEAR_*`, `QF_SEMESTER_*`, `SEMANTIC_PLAN_LLM_*`, `VLLM_BASE_URL`) |
| `app/constants/llm_roles.py` | `LLMRole` |
| `app/exceptions/forge_error.py` | `ForgeError` |
| `app/infra/embedding_model.py` | `EmbeddingModel` |
| `app/infra/qdrant_client.py` | `QdrantClientWrapper` |
| `app/services/domains/capabilities_service.py` | `DomainCapabilitiesService` |
| `app/services/domain/domain_time_policy_service.py` | `DomainTimePolicyService` |
| `app/services/domain/planner_domain_capability_service.py` | `PlannerDomainCapabilityService` |
| `app/services/domain/planner_rerank_policy_service.py` | `PlannerRerankPolicyService` |
| `app/services/llm/llm_client.py` | `LLMClient` |
| `app/services/llm/prompts_plan_v2.py` | `NEXT_ACTIONS_JSON_SCHEMA`, `SLOT_JSON_SCHEMA`, `build_developer_prompt`, `build_json_repair_prompt`, `build_next_actions_developer_prompt`, `build_next_actions_user_prompt`, `build_slot_developer_prompt`, `build_slot_user_prompt`, `build_system_prompt`, `build_user_prompt` |
| `app/services/planner/unified_llm_planner.py` | `build_plan_and_slots` |
| `app/services/planner/compact_planner.py` | `build_compact_plan_and_project` |
| `app/services/planner/semantic_grounding_service.py` | `SemanticGroundingService` |
| `app/services/planner/value_normalizers/country.py` | `is_country_iso2_column`, `normalize_country_values` |
| `app/services/planner/value_normalizers/school_year.py` | `current_school_year`, `is_school_year_column`, `normalize_school_year_values` |
| `app/services/planner/value_normalizers/semester.py` | `is_semester_column`, `normalize_semester_values` |
| `app/services/planner_domain/conversation_store.py` | `HybridPlannerDomainConversationStore`, `PlannerDomainConversationStore`, `build_conversation_state`, `default_conversation_ttl_seconds`, `new_conversation_id` |
| `app/services/planner_domain/map_to_sqljson.py` | `map_plan_v2_to_sqljson` |
| `app/services/planner_domain/prompt_signal_service.py` | `PromptSignalService` |
| `app/services/planner_domain/rerank_policy_engine.py` | `PlannerDomainRerankPolicyEngine` |
| `app/services/planner_domain/schema_v2.py` | `plan_v2_json_schema` |
| `app/services/planner_domain/validate_v2.py` | `validate_and_repair_plan_v2` |
| `app/services/semantic/value_alias_resolution_service.py` | `ValueAliasResolutionService` |
| `app/services/vector/__init__.py` | `DomainVectorIndexService` |

---

## Symbols exported from `service.py` that tests import directly

These are private functions that tests import by name. When these are moved to new modules during Phase 1–6, the tests must be updated to import from the new module location.

| Symbol | Target module (per spec) | Tests that import it |
|---|---|---|
| `PlannerDomainService` | `service.py` (stays) | all test files |
| `LLMPlanResult` | `types.py` (Phase 1) | `test_service.py` |
| `SlotExtractionResult` | `types.py` (Phase 1) | `test_service.py` |
| `_serialize_domain_candidates_for_debug` | `domain_selection_service.py` (Phase 3) | `test_service.py` |
| `_column_heuristic_boost` | `column_scoring.py` (Phase 2) | `test_service.py` |
| `_district_county_retry_hint` | `service.py` or inline | `test_service.py` |
| `_normalize_relative_time_in_plan` | `normalizers/time.py` (Phase 6) | `test_service.py` |
| `_normalize_top_bottom_ranking_in_plan` | `normalizers/metric.py` (Phase 6) | `test_service.py` |
| `_normalize_year_keyword_filters_in_plan` | `normalizers/time.py` (Phase 6) | `test_service.py` |
| `_prompt_is_followup_edit` | `conversation_context.py` (Phase 1) | `test_service.py` |
| `_required_column_keys` | `column_scoring.py` (Phase 2) | `test_service.py` |
| `_normalize_semester_filters_in_plan` | `normalizers/time.py` (Phase 6) | `test_semester_normalization.py` |
| `_semester_bucket_from_text` | `normalizers/time.py` (Phase 6) | `test_semester_normalization.py` |
| `_normalize_adm_default_filters_in_plan` | `normalizers/metric.py` (Phase 6) | `test_adm_filter_normalization.py` |
| `_normalize_school_year_filters_in_plan` | `normalizers/time.py` (Phase 6) | `test_school_year_normalization.py` |
| `_normalize_country_filters_in_plan` | `normalizers/entity.py` (Phase 6) | `test_country_normalization.py` |
| `_normalize_staff_role_filters_in_plan` | `normalizers/entity.py` (Phase 6) | `test_staff_role_normalization.py` |
| `_normalize_school_name_filters_in_plan` | `normalizers/entity.py` (Phase 6) | `test_school_name_normalization.py` |
| `_normalize_next_actions` | `next_actions_service.py` (Phase 7) | `test_next_actions_normalization.py` |
| `_read_pipeline_profile_from_log` | `pipeline_trace.py` (Phase 8) | `test_pipeline_profile_lookup.py` |
| Module-level constants (`PLANNER_UNIFIED_LLM`, `QF_PLAN_DOMAIN_*`, `_PROFILE_LOGGER_NAME`, etc.) | `service.py` (stay as module re-exports) | `test_service.py`, `test_pipeline_profile_*.py` |
