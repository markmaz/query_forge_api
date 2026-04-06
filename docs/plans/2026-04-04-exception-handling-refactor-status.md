# Exception Handling Refactor Status

Date: 2026-04-04
Scope: `query-forge-api/`

## Snapshot

This note captures the current status of the backend exception-handling refactor as of April 4, 2026.

Current state:

- App-level error handling is now centralized in `app/factory.py`
- Route-layer blanket catches are almost eliminated
- Service-layer cleanup is materially underway, but still incomplete
- Tasks, skills, and some adapter/integration layers still carry the largest concentration of broad `except Exception` fallbacks

Working estimates from the current tree:

- Route/features `except Exception` count: `2`
- Service `except Exception` count: `122`
- Total `app/` `except Exception` count: `202`
- Current diff removes `493` blanket `except Exception` catches and adds `1`

Reference baseline from the 2026-04-03 backend audit:

- Route layer: `209`
- Service layer: `350`

Interpretation:

- The route pass is effectively near completion
- The backend is in the middle of the service/task/skill long-tail cleanup

## Completed So Far

### 1. Centralized app-level handling landed

`app/factory.py` now provides centralized handling for:

- `ForgeError`
- `pydantic.ValidationError`
- uncaught `Exception`

This gives the codebase a consistent response contract for:

- expected domain errors
- payload validation failures
- unexpected 500s

It also now carries correlation and trace context through the shared error path.

### 2. Route boilerplate was heavily reduced

The refactor removed repeated per-route patterns like:

- `except ForgeError: return ...`
- `except Exception: return {"error": ...}, 500`

Much of that work appears to have been absorbed by:

- the app-level handlers in `app/factory.py`
- route decomposition under `app/routes/admin/`
- route decomposition under `app/routes/skills/`

### 3. Fallback handling is starting to be named and scoped

Some services now define explicit fallback groups instead of catching every exception class, for example:

- `TENANCY_ADMIN_FALLBACK_ERRORS` in `app/services/tenancy/tenancy_admin_service.py`
- `CONVERSATION_STORE_FALLBACK_ERRORS` in `app/services/planner_domain/service.py`
- `OPTIONAL_TIME_POLICY_FALLBACK_ERRORS` in `app/services/planner_domain/service.py`

This is the right direction because it preserves defensive behavior without hiding programmer errors.

### 4. Focused regression coverage exists for some of the new paths

Verified on the current tree:

- `tests/services/test_llm_client.py`
- `tests/services/semantic/test_semantic_llm_labeler.py`
- `tests/services/tenancy/test_tenancy_admin_service.py`

Result:

- `42 passed` in `34.60s`

## Still Open

### Remaining route cleanup

Only two broad catches remain in the route/features layer:

- `app/features/auth/auth_api.py:477`
- `app/features/auth/auth_api.py:503`

These should be cleaned up to finish the route pass cleanly.

### Remaining service-layer cleanup

The service layer still has `122` `except Exception` sites. This is the main unfinished part of the refactor.

High-concentration service hotspots from the current tree:

- `app/services/semantic/plan/service.py` — `3`
- `app/services/planner_llm/cache.py` — `3`
- `app/services/planner/unified_llm_planner.py` — `3`
- `app/services/forge_match/session_job_coordinator.py` — `3`
- `app/services/forge_match/pipeline_adapters.py` — `3`
- `app/services/forge_match/llm_ranker.py` — `3`
- `app/services/domain/planner_rerank_policy_service.py` — `3`
- `app/services/domain/planner_domain_capability_service.py` — `3`
- `app/services/analytics/dictionary_enrichment_service.py` — `3`

Secondary service hotspots:

- `app/services/workspace_inventory/workspace_context.py` — `2`
- `app/services/sqljson/validate_derived.py` — `2`
- `app/services/shared_ai/adapters/policies.py` — `2`
- `app/services/semantic/semantic_registry_service.py` — `2`
- `app/services/semantic/semantic_concept_matcher.py` — `2`
- `app/services/semantic/plan/sql_json_builder.py` — `2`
- `app/services/query_tree/query_tree_read_model_service.py` — `2`
- `app/services/query_forge/where_compiler.py` — `2`
- `app/services/query_forge/sql_utils.py` — `2`
- `app/services/query_forge/requirements.py` — `2`
- `app/services/query_forge/projection_compiler.py` — `2`
- `app/services/query_forge/normalizers/query_json.py` — `2`
- `app/services/forge_insights_threads_service.py` — `2`
- `app/services/embedding/embedding_search_service.py` — `2`
- `app/services/embedding/domain_embedding_service.py` — `2`
- `app/services/domain/planner_retrieval_policy_service.py` — `2`

### Remaining non-service hotspots

These are outside the route/service core, but they are now among the largest remaining sources of broad exception swallowing:

- `app/tasks/skill_runner.py` — `7`
- `app/skills/threshold_alert.py` — `6`
- `app/skills/ai_summary_digest.py` — `6`
- `app/skills/delivery/__init__.py` — `5`
- `app/skills/schedule_utils.py` — `4`
- `app/adapters/analytics/snowflake_executor.py` — `4`
- `app/tasks/ingestion_tasks.py` — `3`
- `app/skills/webhook_delivery.py` — `3`
- `app/skills/email_delivery.py` — `3`
- `app/skills/data_freshness_check.py` — `3`

## Recommended Punch List

### Phase 1. Finish the route layer

Goal:

- Reduce route/features `except Exception` from `2` to `0`

Files:

- `app/features/auth/auth_api.py`

Expected outcome:

- Route code relies on app-level handlers instead of local blanket catches
- Token-validation failures stay intentionally mapped to 400/401 responses

### Phase 2. Stabilize shared service boundaries

Goal:

- Tighten broad catches in the highest-leverage shared services first

Files:

- `app/services/planner/unified_llm_planner.py`
- `app/services/planner_llm/cache.py`
- `app/services/semantic/plan/service.py`
- `app/services/shared_ai/adapters/policies.py`
- `app/services/analytics/dictionary_enrichment_service.py`

Why this phase is next:

- These services sit on common execution paths and shape error behavior for multiple callers
- They are likely to influence the most downstream incident noise

### Phase 3. Finish planner-domain and semantic long-tail cleanup

Goal:

- Replace defensive blanket catches with explicit infrastructure/domain fallback sets

Files:

- `app/services/domain/planner_rerank_policy_service.py`
- `app/services/domain/planner_domain_capability_service.py`
- `app/services/domain/planner_retrieval_policy_service.py`
- `app/services/semantic/semantic_registry_service.py`
- `app/services/semantic/semantic_concept_matcher.py`
- `app/services/semantic/plan/sql_json_builder.py`

Expected outcome:

- Known infrastructure failures degrade gracefully
- Unexpected programmer errors propagate instead of being flattened into generic failures

### Phase 4. Clean up QueryForge and ForgeMatch compiler/runtime paths

Goal:

- Remove broad catches from compilation and orchestration paths that should fail loudly on invalid internal state

Files:

- `app/services/query_forge/where_compiler.py`
- `app/services/query_forge/sql_utils.py`
- `app/services/query_forge/requirements.py`
- `app/services/query_forge/projection_compiler.py`
- `app/services/query_forge/normalizers/query_json.py`
- `app/services/forge_match/session_job_coordinator.py`
- `app/services/forge_match/pipeline_adapters.py`
- `app/services/forge_match/llm_ranker.py`

Expected outcome:

- User input errors remain `ForgeError`
- true internal invariants fail fast
- retry/fallback behavior is kept only around real integration boundaries

### Phase 5. Tackle task and skill execution surfaces

Goal:

- Stop background job code from swallowing bugs while preserving operational resilience

Files:

- `app/tasks/skill_runner.py`
- `app/tasks/ingestion_tasks.py`
- `app/skills/threshold_alert.py`
- `app/skills/ai_summary_digest.py`
- `app/skills/delivery/__init__.py`
- `app/skills/email_delivery.py`
- `app/skills/webhook_delivery.py`
- `app/skills/data_freshness_check.py`
- `app/skills/schedule_utils.py`

Why this needs to be separated from service cleanup:

- Background work often does need catch-and-log behavior
- The refactor should preserve worker durability while still surfacing coding defects and trace context

### Phase 6. Tighten adapter boundaries

Goal:

- Keep sanitized external-driver error mapping, but stop catching unrelated internal failures

Files:

- `app/adapters/analytics/snowflake_executor.py`
- other analytics executors/providers still using broad `except Exception`

Expected outcome:

- Driver/network/config errors are translated cleanly
- internal coding errors are not mislabeled as datasource failures

## Suggested Definition Of Done

This refactor should be considered complete when all of the following are true:

- Route/features `except Exception` count is `0`
- Service `except Exception` count is near-zero and any remaining sites are justified integration boundaries
- Task/skill catches are limited to explicit operational boundaries with structured logging
- Adapters catch specific driver/network exceptions rather than blanket `Exception`
- New exception paths are covered with focused tests, especially for:
  - LLM unavailability and timeout handling
  - validation failures
  - background task retry/failure behavior
  - datasource/driver failures
  - auth token validation failures

## Practical Next Step

If work resumes immediately, the cleanest next slice is:

1. `app/features/auth/auth_api.py`
2. `app/services/planner/unified_llm_planner.py`
3. `app/services/planner_llm/cache.py`
4. `app/services/semantic/plan/service.py`
5. `app/tasks/skill_runner.py`

That order closes the route layer first, then removes broad catches from shared planning paths before moving into async job execution.

## Progress Log

### 2026-04-04 1st slice: auth route cleanup

Changes:

- Replaced the final broad invite-token catches in `app/features/auth/auth_api.py` with a narrow invalid-token helper that only absorbs expected token parse failures
- Updated `tests/routes/test_auth_routes.py` to exercise invalid-token behavior through `itsdangerous.BadSignature`
- Bumped backend version to `0.3.139`

Verification:

- `pytest tests/routes/test_auth_routes.py -q`
- Result: `16 passed`

Post-slice state:

- Route/features `except Exception` count is now `0`
- The route-layer portion of the exception-handling refactor is complete

### 2026-04-04 2nd slice: unified planner parse/fallback cleanup

Changes:

- Narrowed parsing fallbacks in `app/services/planner/unified_llm_planner.py` to JSON/serialization failure classes only
- Added a regression test proving unexpected parse failures now propagate instead of being swallowed
- Bumped backend version to `0.3.140`

Verification:

- `pytest tests/services/planner/test_unified_llm_planner.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/planner/unified_llm_planner.py` no longer contains `except Exception`

### 2026-04-04 3rd slice: planner cache boundary cleanup

Changes:

- Narrowed `PlannerLLMCache` read/write fallbacks in `app/services/planner_llm/cache.py` to SQLAlchemy database failures
- Narrowed JSON parse fallback in `_loads_json()`
- Added direct cache tests for:
  - successful read
  - missing table fallback
  - unexpected error propagation
  - successful write fallback behavior
- Bumped backend version to `0.3.141`

Verification:

- `pytest tests/services/planner_llm/test_cache.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/planner_llm/cache.py` no longer contains `except Exception`

### 2026-04-04 4th slice: semantic plan service fallback cleanup

Changes:

- Replaced broad semantic extractor and Tier2 runner catches in `app/services/semantic/plan/service.py` with explicit fallback tuples
- Narrowed model-column coercion to `TypeError` and `ValueError`
- Added degrade-vs-propagate tests for:
  - semantic extractor runtime failures
  - unexpected semantic extractor failures
  - Tier2 runtime failures
  - unexpected Tier2 failures
- Bumped backend version to `0.3.142`

Verification:

- `pytest tests/services/semantic/test_plan_service_semantic_extract.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/semantic/plan/service.py` no longer contains `except Exception`

### 2026-04-04 5th slice: skill runner helper cleanup

Changes:

- Tightened non-boundary catches in `app/tasks/skill_runner.py` for:
  - workspace config loading
  - runtime config JSON parsing
  - schedule datetime parsing
  - cron interval fallback
- Left two explicit top-level task-boundary catches in place:
  - execution status update boundary
  - dispatch loop boundary
- Added task tests proving workspace config runtime failures degrade while unexpected failures propagate
- Bumped backend version to `0.3.143`

Verification:

- `pytest tests/tasks/test_skill_runner.py -q`
- Result: `7 passed`

Post-slice state:

- `app/tasks/skill_runner.py` is down to `2` broad task-boundary catches

### 2026-04-04 checkpoint after five slices

Current counts from the live tree:

- Route/features `except Exception` count: `0`
- Service `except Exception` count: `113`
- Task `except Exception` count: `6`
- Skill `except Exception` count: `32`
- Total `app/` `except Exception` count: `186`

Net effect versus the original status snapshot in this note:

- Services dropped from `122` to `113`
- Total `app/` dropped from `202` to `186`

Next recommended slice from here:

1. `app/services/forge_match/session_job_coordinator.py`
2. `app/services/forge_match/pipeline_adapters.py`
3. `app/services/forge_match/llm_ranker.py`
4. `app/skills/ai_summary_digest.py`
5. `app/skills/threshold_alert.py`

### 2026-04-05 6th slice: ForgeMatch session coordinator cleanup

Changes:

- Replaced broad DB fallbacks in `app/services/forge_match/session_job_coordinator.py` with explicit SQLAlchemy-backed fallback tuples
- Narrowed the analyze-job failure boundary so expected operational failures still mark the session failed, while unexpected programmer bugs now propagate
- Added direct coordinator tests for:
  - cancel-check DB fallback
  - unexpected cancel-check propagation
  - progress-update fallback when extended columns are missing
  - unexpected progress-write propagation
  - expected analyze-job failure handling
  - unexpected analyze-job propagation
- Bumped backend version to `0.3.144`

Verification:

- `pytest tests/services/forge_match/test_session_job_coordinator.py tests/services/forge_match/test_mapping_service.py -q -k 'analyze_session_persists_mappings_and_summary or start_analyze_session_job_sets_queued_status or get_analysis_status_serializes_progress or cancel_analysis_job_marks_row_canceled or test_is_cancel_requested_returns_false_on_sqlalchemy_error or test_is_cancel_requested_surfaces_unexpected_errors or test_update_session_progress_falls_back_when_extended_columns_missing or test_update_session_progress_surfaces_unexpected_write_errors or test_run_analyze_job_marks_failed_progress_on_expected_runtime_error or test_run_analyze_job_surfaces_unexpected_pipeline_failures'`
- Result: `10 passed`

Post-slice state:

- `app/services/forge_match/session_job_coordinator.py` no longer contains `except Exception`
- Service `except Exception` count is now `110`
- Total `app/` `except Exception` count is now `183`

Next recommended slice from here:

1. `app/services/forge_match/pipeline_adapters.py`
2. `app/services/forge_match/llm_ranker.py`
3. `app/skills/ai_summary_digest.py`
4. `app/skills/threshold_alert.py`
5. `app/skills/delivery/__init__.py`

### 2026-04-05 7th slice: ForgeMatch pipeline adapters cleanup

Changes:

- Replaced broad adapter fallbacks in `app/services/forge_match/pipeline_adapters.py` with explicit fallback tuples for:
  - persistence source-record ID coercion
  - expected row-pipeline operational failures
  - JSON parse fallback in `_parse_json_dict()`
- Kept per-row degradation for expected runtime/domain/infrastructure failures, but now let unexpected programmer bugs propagate
- Added direct adapter tests for:
  - invalid persistence IDs
  - row failure persistence on expected runtime errors
  - propagation of unexpected row-pipeline failures
  - handling of `ForgeError` row failures
  - JSON helper parse behavior
- Bumped backend version to `0.3.145`

Verification:

- `pytest tests/services/forge_match/test_pipeline_adapters.py tests/services/forge_match/test_mapping_service.py -q -k 'test_persistence_adapter_rejects_non_integer_source_record_id or test_session_execution_adapter_persists_failure_for_expected_runtime_errors or test_session_execution_adapter_surfaces_unexpected_row_pipeline_failures or test_session_execution_adapter_handles_domain_errors_as_row_failures or test_parse_json_dict_returns_none_for_invalid_json or test_parse_json_dict_returns_mapping_for_valid_json or analyze_session_persists_mappings_and_summary or analyze_session_workflow_prefers_birth_date_candidate_from_shared_pipeline or analyze_session_workflow_prefers_school_day_flag_candidate_from_shared_pipeline or get_session_surfaces_shared_pipeline_debug_for_mapping_rows'`
- Result: `10 passed`

Post-slice state:

- `app/services/forge_match/pipeline_adapters.py` no longer contains `except Exception`
- Service `except Exception` count is now `107`
- Total `app/` `except Exception` count is now `180`

Next recommended slice from here:

1. `app/services/forge_match/llm_ranker.py`
2. `app/skills/ai_summary_digest.py`
3. `app/skills/threshold_alert.py`
4. `app/skills/delivery/__init__.py`
5. `app/tasks/ingestion_tasks.py`

### 2026-04-05 8th slice: ForgeMatch LLM ranker cleanup

Changes:

- Replaced broad numeric-normalization catches in `app/services/forge_match/llm_ranker.py` with explicit coercion fallbacks for `TypeError` and `ValueError`
- Left invalid numeric payloads degrading to safe defaults, but now let unexpected conversion bugs propagate
- Added a direct ranker regression test proving unexpected selected-ID conversion failures surface instead of being silently normalized away
- Bumped backend version to `0.3.146`

Verification:

- `pytest tests/services/forge_match/test_llm_ranker.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/forge_match/llm_ranker.py` no longer contains `except Exception`
- Service `except Exception` count is now `104`
- Total `app/` `except Exception` count is now `177`

Next recommended slice from here:

1. `app/skills/ai_summary_digest.py`
2. `app/skills/threshold_alert.py`
3. `app/skills/delivery/__init__.py`
4. `app/tasks/ingestion_tasks.py`
5. `app/skills/schedule_utils.py`

### 2026-04-05 9th slice: AI summary digest skill cleanup

Changes:

- Replaced broad digest skill fallbacks in `app/skills/ai_summary_digest.py` with explicit fallback tuples for:
  - execution-time operational failures
  - destination resolution
  - LLM summarization fallback
  - snapshot load/save fallback
- Kept expected delivery/runtime failures degrading into `SkillResult` failures or fallback content, but now let unexpected assertion-like bugs propagate
- Added digest tests for:
  - expected destination-resolution degradation
  - unexpected destination-resolution propagation
  - expected LLM fallback behavior
  - unexpected LLM propagation
  - expected send failure handling
  - unexpected send propagation
  - expected snapshot load degradation
  - unexpected snapshot load propagation
- Bumped backend version to `0.3.147`

Verification:

- `pytest tests/test_skills_v4.py -q -k 'digest'`
- Result: `19 passed`

Post-slice state:

- `app/skills/ai_summary_digest.py` no longer contains `except Exception`
- Skill `except Exception` count is now `26`
- Total `app/` `except Exception` count is now `171`

Next recommended slice from here:

1. `app/skills/threshold_alert.py`
2. `app/skills/delivery/__init__.py`
3. `app/tasks/ingestion_tasks.py`
4. `app/skills/schedule_utils.py`
5. `app/skills/webhook_delivery.py`

### 2026-04-05 10th slice: Threshold alert skill cleanup

Changes:

- Replaced broad skill fallbacks in `app/skills/threshold_alert.py` with explicit fallback tuples for:
  - AI expectation evaluation
  - alert-state persistence and lookup
  - channel delivery degradation
- Kept expected LLM/DB/delivery failures fail-open or degraded where the skill already depended on that behavior, but now let unexpected assertion-like defects propagate
- Added threshold-alert tests for:
  - expected AI expectation fallback
  - unexpected AI expectation propagation
  - expected alert-state load fallback
  - unexpected alert-state propagation
  - expected delivery degradation
  - unexpected delivery propagation
- Bumped backend version to `0.3.148`

Verification:

- `pytest tests/test_threshold_alert.py -q`
- Result: `38 passed`

Post-slice state:

- `app/skills/threshold_alert.py` no longer contains `except Exception`
- Skill `except Exception` count is now `20`
- Total `app/` `except Exception` count is now `165`

Next recommended slice from here:

1. `app/skills/delivery/__init__.py`
2. `app/tasks/ingestion_tasks.py`
3. `app/skills/schedule_utils.py`
4. `app/skills/webhook_delivery.py`
5. `app/skills/email_delivery.py`

### 2026-04-05 11th slice: Delivery channel package cleanup

Changes:

- Replaced broad transport and destination-resolution fallbacks in `app/skills/delivery/__init__.py` with explicit fallback tuples for:
  - email send failures
  - Slack, Teams, and generic webhook transport failures
  - destination resolution errors
- Kept expected network/runtime/input failures returning channel-level error tuples, but now let unexpected assertion-like failures propagate
- Added delivery tests for:
  - expected email transport degradation
  - unexpected email failure propagation
  - expected Teams transport degradation
  - unexpected generic webhook propagation
- Bumped backend version to `0.3.149`

Verification:

- `pytest tests/test_destinations.py -q`
- Result: `29 passed`

Post-slice state:

- `app/skills/delivery/__init__.py` no longer contains `except Exception`
- Skill `except Exception` count is now `15`
- Total `app/` `except Exception` count is now `160`

Next recommended slice from here:

1. `app/tasks/ingestion_tasks.py`
2. `app/skills/schedule_utils.py`
3. `app/skills/webhook_delivery.py`
4. `app/skills/email_delivery.py`
5. `app/skills/data_freshness_check.py`

### 2026-04-05 12th slice: Ingestion task cleanup

Changes:

- Replaced broad task fallbacks in `app/tasks/ingestion_tasks.py` with explicit fallback tuples for:
  - advanced progress-column schema drift during progress writes
  - expected sync-service/runtime/database failures that should still mark the ingestion run failed
- Kept expected schema-drift and operational failures degrading into legacy writes or failed task records, but now let unexpected assertion-like failures propagate
- Added ingestion-task tests for:
  - expected progress-write fallback to legacy columns
  - unexpected progress-write propagation
  - expected final-status fallback to legacy columns
  - unexpected sync-service propagation
- Bumped backend version to `0.3.150`

Verification:

- `pytest tests/analytics/test_ingestion_tasks.py -q`
- Result: `8 passed`

Post-slice state:

- `app/tasks/ingestion_tasks.py` no longer contains `except Exception`
- Task `except Exception` count is now `3`
- Total `app/` `except Exception` count is now `157`

Next recommended slice from here:

1. `app/skills/schedule_utils.py`
2. `app/skills/webhook_delivery.py`
3. `app/skills/email_delivery.py`
4. `app/skills/data_freshness_check.py`
5. `app/services/domain/planner_rerank_policy_service.py`

### 2026-04-05 13th slice: Scheduler utility cleanup

Changes:

- Replaced broad scheduler-helper fallbacks in `app/skills/schedule_utils.py` with explicit fallback tuples for:
  - cron runtime evaluation and next-run preview
  - Valkey-backed scheduler health checks and heartbeat writes
- Kept expected cron/runtime/Valkey failures degrading into validation errors, empty previews, or unhealthy status payloads, but now let unexpected assertion-like failures propagate
- Added schedule utility tests for:
  - expected cron evaluation fallback
  - unexpected cron evaluation propagation
  - expected next-run preview fallback
  - unexpected next-run propagation
  - expected scheduler health degradation
  - unexpected scheduler health propagation
  - expected heartbeat write degradation
  - unexpected heartbeat propagation
- Bumped backend version to `0.3.151`

Verification:

- `pytest tests/test_threshold_alert.py -q -k 'cron or next_n_runs or scheduler_health or heartbeat'`
- Result: `16 passed`

Post-slice state:

- `app/skills/schedule_utils.py` no longer contains `except Exception`
- Skill `except Exception` count is now `11`
- Total `app/` `except Exception` count is now `153`

Next recommended slice from here:

1. `app/skills/webhook_delivery.py`
2. `app/skills/email_delivery.py`
3. `app/skills/data_freshness_check.py`
4. `app/services/domain/planner_rerank_policy_service.py`
5. `app/services/domain/planner_domain_capability_service.py`

### 2026-04-05 14th slice: Webhook delivery skill cleanup

Changes:

- Replaced broad webhook skill fallbacks in `app/skills/webhook_delivery.py` with explicit fallback tuples for:
  - execution-time delivery failures
  - email HTML generation fallback
  - highlight-generation LLM fallback
- Kept expected delivery/runtime/LLM failures degrading into failed `SkillResult`s, empty HTML, or summary fallback, but now let unexpected assertion-like failures propagate
- Added webhook skill tests for:
  - expected execute-time channel failure handling
  - unexpected execute-time propagation
  - expected email HTML fallback
  - unexpected email HTML propagation
  - expected highlight fallback
  - unexpected highlight propagation
- Bumped backend version to `0.3.152`

Verification:

- `pytest tests/test_skills_v4.py -q -k 'webhook'`
- Result: `19 passed`

Post-slice state:

- `app/skills/webhook_delivery.py` no longer contains `except Exception`
- Skill `except Exception` count is now `8`
- Total `app/` `except Exception` count is now `150`

Next recommended slice from here:

1. `app/skills/email_delivery.py`
2. `app/skills/data_freshness_check.py`
3. `app/services/domain/planner_rerank_policy_service.py`
4. `app/services/domain/planner_domain_capability_service.py`
5. `app/services/analytics/dictionary_enrichment_service.py`

### 2026-04-05 15th slice: Email delivery skill cleanup

Changes:

- Replaced broad email skill fallbacks in `app/skills/email_delivery.py` with explicit fallback tuples for:
  - per-recipient send failures
  - destination resolution fallback
  - LLM summary generation fallback
- Kept expected send/destination/LLM failures degrading into partial-send tracking, empty destination overrides, or no summary text, but now let unexpected assertion-like failures propagate
- Added email delivery tests for:
  - expected partial-send degradation
  - unexpected send propagation
  - expected destination-resolution fallback
  - unexpected destination-resolution propagation
  - expected LLM summary fallback
  - unexpected LLM summary propagation
- Bumped backend version to `0.3.153`

Verification:

- `pytest tests/test_email_delivery.py -q`
- Result: `11 passed`

Post-slice state:

- `app/skills/email_delivery.py` no longer contains `except Exception`
- Skill `except Exception` count is now `5`
- Total `app/` `except Exception` count is now `147`

Next recommended slice from here:

1. `app/skills/data_freshness_check.py`
2. `app/services/domain/planner_rerank_policy_service.py`
3. `app/services/domain/planner_domain_capability_service.py`
4. `app/services/analytics/dictionary_enrichment_service.py`
5. `app/services/workspace_inventory/workspace_context.py`

### 2026-04-05 16th slice: Data freshness skill cleanup

Changes:

- Replaced broad freshness-skill fallbacks in `app/skills/data_freshness_check.py` with explicit fallback tuples for:
  - snapshot load/save operations
  - channel delivery degradation
- Kept expected DB/runtime/delivery failures degrading into missing snapshots or failed delivery results, but now let unexpected assertion-like failures propagate
- Added freshness-skill tests for:
  - expected snapshot load fallback
  - unexpected snapshot load propagation
  - expected delivery degradation
  - unexpected delivery propagation
- Bumped backend version to `0.3.154`

Verification:

- `pytest tests/test_data_freshness_check.py -q`
- Result: `38 passed`

Post-slice state:

- `app/skills/data_freshness_check.py` no longer contains `except Exception`
- Skill `except Exception` count is now `2`
- Total `app/` `except Exception` count is now `144`

Next recommended slice from here:

1. `app/services/domain/planner_rerank_policy_service.py`
2. `app/services/domain/planner_domain_capability_service.py`
3. `app/services/analytics/dictionary_enrichment_service.py`
4. `app/services/workspace_inventory/workspace_context.py`
5. `app/services/sqljson/validate_derived.py`

### 2026-04-05 17th slice: Planner rerank policy service cleanup

Changes:

- Replaced broad rerank-policy fallbacks in `app/services/domain/planner_rerank_policy_service.py` with explicit fallback tuples for:
  - expected runtime/database lookup failures in `get_applicable_policies()`
  - JSON parse failures in `_parse_policy_rule()`
  - policy rule validation failures in `_parse_policy_rule()`
- Kept expected lookup failures degrading to an empty policy list and expected policy JSON problems mapping to `ForgeError`, but now let unexpected assertion-like failures propagate
- Added rerank-policy tests for:
  - expected lookup fallback
  - unexpected lookup propagation
  - expected JSON parse wrapping
  - unexpected JSON parse propagation
  - expected validation wrapping
  - unexpected validation propagation
- Bumped backend version to `0.3.155`

Verification:

- `pytest tests/services/test_planner_rerank_policy_service.py -q`
- Result: `12 passed`

Post-slice state:

- `app/services/domain/planner_rerank_policy_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `101`
- Total `app/` `except Exception` count is now `141`

Next recommended slice from here:

1. `app/services/domain/planner_domain_capability_service.py`
2. `app/services/analytics/dictionary_enrichment_service.py`
3. `app/services/workspace_inventory/workspace_context.py`
4. `app/services/sqljson/validate_derived.py`
5. `app/services/shared_ai/adapters/policies.py`

### 2026-04-05 18th slice: Planner domain capability service cleanup

Changes:

- Replaced broad capability-service fallbacks in `app/services/domain/planner_domain_capability_service.py` with explicit fallback tuples for:
  - expected runtime/database lookup failures in `_load_effective_capability_rows()`
  - per-record capability validation failures in `list_capabilities()` and `_load_effective_capability_rows()`
- Kept expected lookup failures degrading to an empty capability list and expected invalid persisted rows being skipped, but now let unexpected assertion-like failures propagate
- Added capability-service tests for:
  - expected list-time record validation fallback
  - unexpected list-time validation propagation
  - expected lookup fallback
  - unexpected lookup propagation
  - expected effective-row validation fallback
  - unexpected effective-row validation propagation
- Bumped backend version to `0.3.156`

Verification:

- `pytest tests/services/test_planner_domain_capability_service.py -q`
- Result: `11 passed`

Post-slice state:

- `app/services/domain/planner_domain_capability_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `98`
- Total `app/` `except Exception` count is now `138`

Next recommended slice from here:

1. `app/services/analytics/dictionary_enrichment_service.py`
2. `app/services/workspace_inventory/workspace_context.py`
3. `app/services/sqljson/validate_derived.py`
4. `app/services/shared_ai/adapters/policies.py`
5. `app/services/semantic/semantic_registry_service.py`

### 2026-04-05 19th slice: Dictionary enrichment service cleanup

Changes:

- Replaced broad enrichment-service fallbacks in `app/services/analytics/dictionary_enrichment_service.py` with explicit fallback tuples for:
  - expected table-enrichment runtime/database failures
  - expected column-enrichment runtime/database failures
  - confidence coercion parse failures
- Kept expected enrichment failures degrading into logged error counts, but now let unexpected assertion-like failures propagate
- Added enrichment tests for:
  - expected table-enrichment fallback
  - unexpected table-enrichment propagation
  - unexpected column-enrichment propagation
  - invalid confidence coercion behavior
- Bumped backend version to `0.3.157`

Verification:

- `pytest tests/analytics/test_dictionary_enrichment_service.py -q`
- Result: `9 passed`

Post-slice state:

- `app/services/analytics/dictionary_enrichment_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `95`
- Total `app/` `except Exception` count is now `135`

Next recommended slice from here:

1. `app/services/workspace_inventory/workspace_context.py`
2. `app/services/sqljson/validate_derived.py`
3. `app/services/shared_ai/adapters/policies.py`
4. `app/services/semantic/semantic_registry_service.py`
5. `app/services/semantic/semantic_concept_matcher.py`

### 2026-04-05 20th slice: Derived SQL validation cleanup

Changes:

- Replaced broad integer-coercion fallbacks in `app/services/sqljson/validate_derived.py` with explicit `TypeError`/`ValueError` parse handling
- Preserved current behavior for invalid `workspaceTableId` and `modelColumnId`, but stopped masking unexpected assertion-like failures
- Added derived-validation tests for:
  - invalid object-style `workspaceTableId`
  - invalid object-style `modelColumnId` being ignored
- Bumped backend version to `0.3.158`

Verification:

- `pytest tests/services/sqljson/test_validate_derived.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/sqljson/validate_derived.py` no longer contains `except Exception`
- Service `except Exception` count is now `93`
- Total `app/` `except Exception` count is now `133`

### 2026-04-05 21st slice: Shared-AI policy adapter cleanup

Changes:

- Replaced broad numeric parse fallbacks in `app/services/shared_ai/adapters/policies.py` with explicit `TypeError`/`ValueError` handling for:
  - candidate base-score selection
  - preferred-domain request parsing
- Kept expected numeric parse failures degrading to fallback values, but now let unexpected assertion-like conversion bugs propagate
- Added rerank-adapter helper tests for:
  - expected base-score parse fallback
  - unexpected base-score propagation
  - expected preferred-domain parse fallback
  - unexpected preferred-domain propagation
- Bumped backend version to `0.3.159`

Verification:

- `pytest tests/services/shared_ai/test_apply_policy_rerank_node.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/shared_ai/adapters/policies.py` no longer contains `except Exception`
- Service `except Exception` count is now `91`
- Total `app/` `except Exception` count is now `131`

### 2026-04-05 22nd slice: Workspace context builder cleanup

Changes:

- Replaced broad datasource-resolution fallbacks in `app/services/workspace_inventory/workspace_context.py` with explicit fallback tuples for:
  - expected datasource-resolution/runtime/database failures that should fall back to legacy workspace context
  - expected datasource-resolution failures that should be wrapped as `ForgeError`
- Kept legacy fallback compatibility for expected resolver failures, but now let unexpected assertion-like bugs propagate instead of silently switching to the legacy path
- Added workspace-context tests for:
  - expected fallback to legacy context
  - unexpected datasource-resolution propagation
- Bumped backend version to `0.3.160`

Verification:

- `pytest tests/services/test_workspace_context.py -q`
- Result: `12 passed`

Post-slice state:

- `app/services/workspace_inventory/workspace_context.py` no longer contains `except Exception`
- Service `except Exception` count is now `89`
- Total `app/` `except Exception` count is now `129`

Next recommended slice from here:

1. `app/services/semantic/semantic_registry_service.py`
2. `app/services/semantic/semantic_concept_matcher.py`
3. `app/services/query_forge/where_compiler.py`
4. `app/services/query_forge/sql_utils.py`
5. `app/services/query_forge/requirements.py`

### 2026-04-05 23rd slice: Semantic registry service cleanup

Changes:

- Replaced broad semantic-registry write fallbacks in `app/services/semantic/semantic_registry_service.py` with an explicit write fallback tuple for expected runtime/database failures
- Kept duplicate/write error mapping for expected DB-style failures, but now let unexpected assertion-like write bugs propagate
- Added registry tests for:
  - expected write failure mapping to `ForgeError`
  - unexpected create-time write propagation
  - unexpected update-time write propagation
- Bumped backend version to `0.3.161`

Verification:

- `pytest tests/services/semantic/test_semantic_registry_service.py -q`
- Result: `9 passed`

Post-slice state:

- `app/services/semantic/semantic_registry_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `87`
- Total `app/` `except Exception` count is now `127`

### 2026-04-05 24th slice: Semantic concept matcher cleanup

Changes:

- Replaced broad numeric parse fallbacks in `app/services/semantic/semantic_concept_matcher.py` with explicit `TypeError`/`ValueError` handling for:
  - alias-rule weight coercion
  - canonical confidence clamping
- Kept expected numeric parse failures degrading to safe defaults, but now let unexpected assertion-like conversion bugs propagate
- Added matcher tests for:
  - expected alias weight parse fallback
  - unexpected alias weight propagation
  - expected clamp fallback
  - unexpected clamp propagation
- Bumped backend version to `0.3.162`

Verification:

- `pytest tests/semantic/test_semantic_canonical_mapping.py -q`
- Result: `12 passed`

Post-slice state:

- `app/services/semantic/semantic_concept_matcher.py` no longer contains `except Exception`
- Service `except Exception` count is now `85`
- Total `app/` `except Exception` count is now `125`

### 2026-04-05 25th slice: WHERE compiler cleanup

Changes:

- Replaced broad list-parse fallbacks in `app/services/query_forge/where_compiler.py` with explicit parse tuples for:
  - JSON bracket-list parsing
  - `ast.literal_eval` fallback parsing
- Kept expected invalid bracket-list inputs degrading to the existing fallback path, but now let unexpected assertion-like parser failures propagate
- Added WHERE compiler tests for:
  - bracket-string fallback through `ast.literal_eval`
  - unexpected JSON parse propagation
- Bumped backend version to `0.3.163`

Verification:

- `pytest tests/services/query_forge/test_where_compiler.py -q`
- Result: `21 passed`

Post-slice state:

- `app/services/query_forge/where_compiler.py` no longer contains `except Exception`
- Service `except Exception` count is now `83`
- Total `app/` `except Exception` count is now `123`

Next recommended slice from here:

1. `app/services/query_forge/sql_utils.py`
2. `app/services/query_forge/requirements.py`
3. `app/services/query_forge/projection_compiler.py`
4. `app/services/query_forge/normalizers/query_json.py`
5. `app/services/query_tree/query_tree_read_model_service.py`

### 2026-04-05 26th slice: QueryForge SQL utilities cleanup

Changes:

- Replaced broad workspace-table ID coercion fallbacks in `app/services/query_forge/sql_utils.py` with explicit `TypeError`/`ValueError` handling
- Preserved current behavior for bad numeric IDs in rewrite and alias lookup paths, but now let unexpected assertion-like conversion bugs propagate
- Added SQL utility tests for:
  - invalid `workspaceTableId` mapping to `ForgeError`
  - expected rewrite-path parse fallback
  - unexpected rewrite-path propagation
- Bumped backend version to `0.3.164`

Verification:

- `pytest tests/services/query_forge/test_sql_utils.py -q`
- Result: `25 passed`

Post-slice state:

- `app/services/query_forge/sql_utils.py` no longer contains `except Exception`
- Service `except Exception` count is now `81`
- Total `app/` `except Exception` count is now `121`

### 2026-04-05 27th slice: QueryForge requirement analyzer cleanup

Changes:

- Replaced broad integer coercion fallbacks in `app/services/query_forge/requirements.py` with explicit `TypeError`/`ValueError` handling
- Kept expected bad table-ID inputs being ignored in requirement collection, but now let unexpected assertion-like conversion bugs propagate
- Added dedicated requirement-analyzer tests for:
  - expected `required_table_ids_from_query()` parse fallback
  - unexpected `required_table_ids_from_query()` propagation
  - expected `collect_required_column_keys()` parse fallback
  - unexpected `collect_required_column_keys()` propagation
- Bumped backend version to `0.3.165`

Verification:

- `pytest tests/services/query_forge/test_requirements.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/query_forge/requirements.py` no longer contains `except Exception`
- Service `except Exception` count is now `79`
- Total `app/` `except Exception` count is now `119`

### 2026-04-05 28th slice: QueryForge projection compiler cleanup

Changes:

- Replaced broad alias-hint coercion fallbacks in `app/services/query_forge/projection_compiler.py` with explicit `TypeError`/`ValueError` handling
- Kept expected bad `workspaceTableId` inputs degrading to no alias hint, but now let unexpected assertion-like conversion bugs propagate
- Added dedicated projection-compiler tests for:
  - expected aggregated alias-hint fallback
  - unexpected aggregated alias-hint propagation
  - expected non-aggregated alias-hint fallback
- Bumped backend version to `0.3.166`

Verification:

- `pytest tests/services/query_forge/test_projection_compiler.py -q`
- Result: `3 passed`

Post-slice state:

- `app/services/query_forge/projection_compiler.py` no longer contains `except Exception`
- Service `except Exception` count is now `77`
- Total `app/` `except Exception` count is now `117`

Next recommended slice from here:

1. `app/services/query_forge/normalizers/query_json.py`
2. `app/services/query_tree/query_tree_read_model_service.py`
3. `app/services/embedding/embedding_search_service.py`
4. `app/services/embedding/domain_embedding_service.py`
5. `app/services/semantic/plan/sql_json_builder.py`

### 2026-04-05 29th slice: QueryForge query JSON normalizer cleanup

Changes:

- Replaced broad workspace-table ID coercion fallbacks in `app/services/query_forge/normalizers/query_json.py` with explicit `TypeError`/`ValueError` handling
- Kept expected bad `workspaceTableId` inputs being ignored in filter and sorting table-ID collection, but now let unexpected assertion-like conversion bugs propagate
- Extended QueryForge coverage tests for:
  - expected filter/sorting table-ID parse fallback
  - unexpected filter/sorting table-ID propagation
- Bumped backend version to `0.3.167`

Verification:

- `pytest tests/services/test_query_forge_service_coverage.py -q -k 'filter_and_sorting_table_ids'`
- Result: `2 passed`

Post-slice state:

- `app/services/query_forge/normalizers/query_json.py` no longer contains `except Exception`
- Service `except Exception` count is now `75`
- Total `app/` `except Exception` count is now `115`

Next recommended slice from here:

1. `app/services/query_tree/query_tree_read_model_service.py`
2. `app/services/embedding/embedding_search_service.py`
3. `app/services/embedding/domain_embedding_service.py`
4. `app/services/semantic/plan/sql_json_builder.py`

### 2026-04-05 30th slice: Query tree read-model cleanup

Changes:

- Replaced broad SQL JSON decode fallback in `app/services/query_tree/query_tree_read_model_service.py` with explicit `json.JSONDecodeError` handling
- Replaced broad recent-query limit coercion fallback with explicit `TypeError`/`ValueError` handling
- Added query-tree coverage for:
  - invalid SQL JSON strings returning no detected tool
  - unexpected JSON loader failures propagating
  - expected recent-query limit parse fallback
  - unexpected recent-query limit conversion propagation
- Bumped backend version to `0.3.168`

Verification:

- `pytest tests/services/query_tree/test_saved_query_tree_service.py tests/services/query_tree/test_saved_query_read_service.py -q`
- Result: `14 passed`

Post-slice state:

- `app/services/query_tree/query_tree_read_model_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `73`
- Total `app/` `except Exception` count is now `113`

Next recommended slice from here:

1. `app/services/embedding/embedding_search_service.py`
2. `app/services/embedding/domain_embedding_service.py`
3. `app/services/semantic/plan/sql_json_builder.py`

### 2026-04-05 31st slice: Embedding search scope boost cleanup

Changes:

- Replaced broad domain and workspace-table ID coercion fallbacks in `app/services/embedding/embedding_search_service.py` with explicit `TypeError`/`ValueError` handling
- Kept expected bad scope IDs degrading to no domain boost, but now let unexpected assertion-like conversion bugs propagate
- Extended embedding semantic-scoring tests for:
  - expected domain ID parse fallback
  - unexpected domain ID propagation
  - expected workspace-table ID parse fallback
  - unexpected workspace-table ID propagation
- Bumped backend version to `0.3.169`

Verification:

- `pytest tests/services/embedding/test_embedding_search_service_semantic.py -q`
- Result: `11 passed`

Post-slice state:

- `app/services/embedding/embedding_search_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `71`
- Total `app/` `except Exception` count is now `111`

Next recommended slice from here:

1. `app/services/embedding/domain_embedding_service.py`
2. `app/services/semantic/plan/sql_json_builder.py`

### 2026-04-05 32nd slice: Domain embedding cleanup

Changes:

- Replaced broad payload-build fallback in `app/services/embedding/domain_embedding_service.py` with explicit `TypeError`/`ValueError` handling
- Replaced broad JSON parse fallback in domain payload parsing with explicit `json.JSONDecodeError` handling
- Added domain-embedding coverage for:
  - invalid JSON list payload fallback
  - unexpected JSON loader propagation
  - expected payload-build error recording during upsert
  - unexpected payload-build bug propagation during upsert
- Bumped backend version to `0.3.170`

Verification:

- `pytest tests/test_domain_embedding.py -q`
- Result: `6 passed`

Post-slice state:

- `app/services/embedding/domain_embedding_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `69`
- Total `app/` `except Exception` count is now `109`

Next recommended slice from here:

1. `app/services/semantic/plan/sql_json_builder.py`

### 2026-04-05 33rd slice: Semantic SQL JSON builder cleanup

Changes:

- Replaced broad edit-construction fallbacks in `app/services/semantic/plan/sql_json_builder.py` with explicit `TypeError`/`ValueError` handling
- Kept expected invalid planner edits being dropped during grounding, but now let unexpected edit-construction bugs propagate
- Added semantic planner coverage for:
  - expected invalid `SetDomainEdit` drop behavior
  - unexpected `SetDomainEdit` propagation
  - expected invalid `AddSelectEdit` drop behavior
  - unexpected `AddSelectEdit` propagation
- Bumped backend version to `0.3.171`

Verification:

- `pytest tests/services/semantic/test_plan_service.py -q -k 'build_grounded_sql_json'`
- Result: `4 passed`

Post-slice state:

- `app/services/semantic/plan/sql_json_builder.py` no longer contains `except Exception`
- Service `except Exception` count is now `67`
- Total `app/` `except Exception` count is now `107`

Next recommended slice from here:

1. `app/services/ai_suggest/vllm_client.py`
2. `app/services/domain/planner_retrieval_policy_service.py`
3. `app/services/domain/planner_rerank_policy_candidate_suggestion_service.py`
4. `app/services/domain/planner_rerank_policy_candidate_service.py`
5. `app/services/domain/planner_domain_selection_policy_service.py`
6. `app/services/analytics/metadata_sync_service.py`

### 2026-04-05 34th slice: AI suggest vLLM transport cleanup

Changes:

- Replaced broad request wrappers in `app/services/ai_suggest/vllm_client.py` with explicit `requests.RequestException` handling
- Kept expected network-layer failures logged and re-raised, but now let unexpected non-request bugs propagate without being swallowed by the transport wrapper
- Added direct transport coverage for:
  - expected request exception propagation in `call()`
  - unexpected `post()` failure propagation
  - unexpected `get()` failure propagation
- Bumped backend version to `0.3.172`

Verification:

- `pytest tests/test_ai_suggest.py -q -k 'test_vllm_client_call_preserves_expected_request_errors or test_vllm_client_call_surfaces_unexpected_post_errors or test_vllm_client_health_surfaces_unexpected_get_errors'`
- Result: `3 passed`

Post-slice state:

- `app/services/ai_suggest/vllm_client.py` no longer contains `except Exception`
- Service `except Exception` count is now `65`
- Total `app/` `except Exception` count is now `105`

Next recommended slice from here:

1. `app/services/domain/planner_retrieval_policy_service.py`
2. `app/services/domain/planner_rerank_policy_candidate_suggestion_service.py`
3. `app/services/domain/planner_rerank_policy_candidate_service.py`
4. `app/services/domain/planner_domain_selection_policy_service.py`
5. `app/services/analytics/metadata_sync_service.py`
6. `app/services/forge_insights_threads_service.py`

### 2026-04-05 35th slice: Retrieval and domain-selection policy cleanup

Changes:

- Replaced broad DB lookup fallbacks in `app/services/domain/planner_retrieval_policy_service.py` and `app/services/domain/planner_domain_selection_policy_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Replaced broad policy-rule validation fallbacks in both services with explicit `ValidationError`/`TypeError`/`ValueError` handling
- Kept expected lookup and malformed-policy rows degrading to seeded-policy behavior, but now let unexpected parser bugs propagate
- Added policy service coverage for:
  - expected DB lookup fallback in retrieval policy selection
  - unexpected retrieval policy parse propagation
  - expected DB lookup fallback in domain-selection scoring
  - unexpected domain-selection policy parse propagation
- Bumped backend version to `0.3.173`

Verification:

- `pytest tests/services/test_planner_retrieval_policy_service.py tests/services/test_planner_domain_selection_policy_service.py -q`
- Result: `17 passed`

Post-slice state:

- `app/services/domain/planner_retrieval_policy_service.py` no longer contains `except Exception`
- `app/services/domain/planner_domain_selection_policy_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `61`
- Total `app/` `except Exception` count is now `101`

Next recommended slice from here:

1. `app/services/domain/planner_rerank_policy_candidate_suggestion_service.py`
2. `app/services/domain/planner_rerank_policy_candidate_service.py`
3. `app/services/analytics/metadata_sync_service.py`
4. `app/services/forge_insights_threads_service.py`

### 2026-04-05 36th slice: Rerank candidate service cleanup

Changes:

- Replaced broad LLM fallback handling in `app/services/domain/planner_rerank_policy_candidate_suggestion_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Replaced broad LLM payload validation fallback in the same service with explicit `ValidationError`/`TypeError`/`ValueError` handling
- Replaced broad candidate JSON parse and validation fallbacks in `app/services/domain/planner_rerank_policy_candidate_service.py` with explicit `json.JSONDecodeError` and `ValidationError`/`TypeError`/`ValueError` handling
- Kept expected invalid or unavailable AI/candidate JSON on the fallback or wrapped-error path, but now let unexpected parser and validator bugs propagate
- Added rerank candidate coverage for:
  - expected runtime LLM fallback
  - unexpected LLM bug propagation
  - unexpected LLM payload validation propagation
  - expected invalid candidate JSON wrapping
  - unexpected JSON loader propagation
  - unexpected candidate validator propagation
- Bumped backend version to `0.3.174`

Verification:

- `pytest tests/services/test_planner_rerank_policy_candidate_suggestion_service.py tests/services/test_planner_rerank_policy_candidate_service.py -q`
- Result: `15 passed`

Post-slice state:

- `app/services/domain/planner_rerank_policy_candidate_suggestion_service.py` no longer contains `except Exception`
- `app/services/domain/planner_rerank_policy_candidate_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `57`
- Total `app/` `except Exception` count is now `97`

Next recommended slice from here:

1. `app/services/analytics/metadata_sync_service.py`
2. `app/services/forge_insights_threads_service.py`

### 2026-04-05 37th slice: Metadata sync optional-stage cleanup

Changes:

- Replaced broad optional profiling and enrichment fallbacks in `app/services/analytics/metadata_sync_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected optional-stage runtime failures on the log-and-continue path, but now let unexpected assertion-like bugs propagate
- Added metadata sync coverage for:
  - expected profiling fallback
  - unexpected profiling bug propagation
  - expected enrichment fallback
  - unexpected enrichment bug propagation
- Bumped backend version to `0.3.175`

Verification:

- `pytest tests/analytics/test_metadata_sync_service.py -q`
- Result: `12 passed`

Post-slice state:

- `app/services/analytics/metadata_sync_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `55`
- Total `app/` `except Exception` count is now `95`

Next recommended slice from here:

1. `app/services/forge_insights_threads_service.py`

### 2026-04-05 38th slice: Forge insights thread fallback cleanup

Changes:

- Replaced broad legacy-thread query fallback in `app/services/forge_insights_threads_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Replaced broad stale-thread cache filter fallback in the same service with explicit `ImportError`/`OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected legacy schema and cache outage behavior on the fallback path, but now let unexpected listing and cache-filter bugs propagate
- Added forge-insights coverage for:
  - expected legacy query fallback
  - unexpected legacy query propagation
  - expected cache-filter fallback
  - unexpected cache-filter bug propagation
- Bumped backend version to `0.3.176`

Verification:

- `pytest tests/services/test_forge_insights_threads_service.py -q`
- Result: `9 passed`

Post-slice state:

- `app/services/forge_insights_threads_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `53`
- Total `app/` `except Exception` count is now `93`

Next recommended slice from here:

1. `app/services/semantic/plan/value_alias_applier.py`
2. `app/services/semantic/semantic_suggestion_service.py`
3. `app/services/semantic/semantic_validation.py`
4. `app/services/shared/jsonify.py`
5. `app/services/shared_ai/executor.py`

### 2026-04-05 39th slice: Value alias applier cleanup

Changes:

- Replaced broad SQL JSON round-trip fallback in `app/services/semantic/plan/value_alias_applier.py` with explicit `TypeError`/`ValueError` handling
- Kept expected non-serializable SQL JSON on the shallow-copy fallback path, but now let unexpected serializer bugs propagate
- Added semantic planner coverage for unexpected JSON round-trip bug propagation during alias application
- Bumped backend version to `0.3.177`

Verification:

- `pytest tests/services/semantic/test_plan_service.py -q -k 'apply_value_aliases_to_llm_plan'`
- Result: `3 passed`

Post-slice state:

- `app/services/semantic/plan/value_alias_applier.py` no longer contains `except Exception`
- Service `except Exception` count is now `52`
- Total `app/` `except Exception` count is now `92`

Next recommended slice from here:

1. `app/services/semantic/semantic_suggestion_service.py`
2. `app/services/semantic/semantic_validation.py`
3. `app/services/shared/jsonify.py`
4. `app/services/shared_ai/executor.py`
5. `app/services/shared_ai/adapters/candidates.py`

### 2026-04-05 40th slice: Semantic validation cleanup

Changes:

- Replaced broad confidence parsing fallback in `app/services/semantic/semantic_validation.py` with explicit `TypeError`/`ValueError` handling
- Kept expected invalid confidence values on the existing validation-error path, but now let unexpected float-conversion bugs propagate
- Added semantic validation coverage for unexpected confidence parse propagation
- Bumped backend version to `0.3.178`

Verification:

- `pytest tests/services/semantic/test_semantic_validation.py -q`
- Result: `6 passed`

Post-slice state:

- `app/services/semantic/semantic_validation.py` no longer contains `except Exception`
- Service `except Exception` count is now `51`
- Total `app/` `except Exception` count is now `91`

### 2026-04-05 41st slice: Shared jsonify cleanup

Changes:

- Replaced broad byte decode fallback in `app/services/shared/jsonify.py` with explicit `UnicodeDecodeError` handling
- Kept expected invalid UTF-8 bytes on the string-fallback path, but now let unexpected decoder bugs propagate
- Added jsonify coverage for invalid UTF-8 fallback and unexpected decode propagation
- Bumped backend version to `0.3.179`

Verification:

- `pytest tests/services/test_jsonify.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/shared/jsonify.py` no longer contains `except Exception`
- Service `except Exception` count is now `50`
- Total `app/` `except Exception` count is now `90`

### 2026-04-05 42nd slice: Shared AI candidate adapter cleanup

Changes:

- Replaced broad score parsing fallback in `app/services/shared_ai/adapters/candidates.py` with explicit `TypeError`/`ValueError` handling
- Kept expected invalid score fields ignored during candidate construction, but now let unexpected float-conversion bugs propagate
- Added candidate adapter coverage for expected parse fallback and unexpected score parse propagation
- Bumped backend version to `0.3.180`

Verification:

- `pytest query-forge-api/tests/services/shared_ai/test_resolve_capabilities_node.py query-forge-api/tests/services/shared_ai/test_executor.py -q`
- Result: `8 passed`

Post-slice state:

- `app/services/shared_ai/adapters/candidates.py` no longer contains `except Exception`
- Service `except Exception` count is now `49`
- Total `app/` `except Exception` count is now `89`

### 2026-04-05 43rd slice: Shared AI executor cleanup

Changes:

- Replaced broad node execution wrapper in `app/services/shared_ai/executor.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected operational node failures wrapped in `PipelineNodeExecutionError`, but now let unexpected assertion-like node bugs propagate
- Added executor coverage for unexpected node error propagation
- Bumped backend version to `0.3.181`

Verification:

- `pytest query-forge-api/tests/services/shared_ai/test_resolve_capabilities_node.py query-forge-api/tests/services/shared_ai/test_executor.py -q`
- Result: `8 passed`

Post-slice state:

- `app/services/shared_ai/executor.py` no longer contains `except Exception`
- Service `except Exception` count is now `48`
- Total `app/` `except Exception` count is now `88`

### 2026-04-05 44th slice: Semantic suggestion run cleanup

Changes:

- Replaced broad run execution wrapper in `app/services/semantic/semantic_suggestion_service.py` with explicit `ForgeError`/`SQLAlchemyError`/`OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected runtime and wiring failures on the existing failed-run path, but now let unexpected assertion-like matcher bugs propagate without forcing a failed status update
- Added semantic suggestion coverage for unexpected assertion propagation during `execute_run()`
- Bumped backend version to `0.3.182`

Verification:

- `pytest tests/services/semantic/test_semantic_suggestion_service.py -q -k 'execute_run_surfaces_unexpected_matcher_errors or execute_run_surfaces_unexpected_assertion_errors'`
- Result: `2 passed`

Post-slice state:

- `app/services/semantic/semantic_suggestion_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `47`
- Total `app/` `except Exception` count is now `87`

Next recommended slice from here:

1. `app/services/workspace_service.py`
2. `app/services/workspace_inventory/column_sample_write_service.py`
3. `app/services/value_overrides/value_override_meta_writer.py`
4. `app/services/user/workspace_user_query.py`
5. `app/services/tenancy/workspace_llm_service.py`

### 2026-04-05 45th slice: Workspace service cleanup

Changes:

- Replaced broad legacy workspace query fallback in `app/services/workspace_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Kept expected schema-compatibility fallback behavior for legacy workspace rows, but now let unexpected lookup bugs propagate
- Added workspace service coverage for unexpected lookup propagation
- Bumped backend version to `0.3.183`

Verification:

- `pytest tests/services/test_workspace_service.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/workspace_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `46`
- Total `app/` `except Exception` count is now `86`

### 2026-04-05 46th slice: Workspace user query cleanup

Changes:

- Replaced broad limit/offset coercion fallback in `app/services/user/workspace_user_query.py` with explicit `TypeError`/`ValueError` handling
- Kept expected invalid integer inputs on the existing `ForgeError` path, but now let unexpected conversion bugs propagate
- Added workspace-user query coverage for unexpected integer parse propagation
- Bumped backend version to `0.3.184`

Verification:

- `pytest tests/services/user/test_workspace_user_query.py -q`
- Result: `3 passed`

Post-slice state:

- `app/services/user/workspace_user_query.py` no longer contains `except Exception`
- Service `except Exception` count is now `45`
- Total `app/` `except Exception` count is now `85`

### 2026-04-05 47th slice: Value override meta writer cleanup

Changes:

- Replaced broad table-existence fallback in `app/services/value_overrides/value_override_meta_writer.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected migration-missing behavior on the wrapped `ForgeError` path, but now let unexpected table-check bugs propagate
- Added value-override writer coverage for unexpected table-check propagation
- Bumped backend version to `0.3.185`

Verification:

- `pytest tests/services/value_overrides/test_value_override_meta_writer.py -q`
- Result: `6 passed`

Post-slice state:

- `app/services/value_overrides/value_override_meta_writer.py` no longer contains `except Exception`
- Service `except Exception` count is now `44`
- Total `app/` `except Exception` count is now `84`

### 2026-04-05 48th slice: Column sample writer cleanup

Changes:

- Replaced broad per-column sampling fallback in `app/services/workspace_inventory/column_sample_write_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected sampling and metadata-sync runtime failures on the recorded column-error path, but now let unexpected assertion-like sampling bugs propagate
- Added column sample writer coverage for unexpected sampling bug propagation
- Bumped backend version to `0.3.186`

Verification:

- `pytest tests/services/workspace_inventory/test_column_sample_write_service.py -q`
- Result: `6 passed`

Post-slice state:

- `app/services/workspace_inventory/column_sample_write_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `43`
- Total `app/` `except Exception` count is now `83`

### 2026-04-05 49th slice: Workspace LLM connection cleanup

Changes:

- Replaced broad test-connection wrapper in `app/services/tenancy/workspace_llm_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected runtime connectivity failures on the unsuccessful-result path, but now let unexpected assertion-like connection bugs propagate
- Added workspace LLM coverage for expected runtime failure wrapping and unexpected connection bug propagation
- Bumped backend version to `0.3.187`

Verification:

- `pytest tests/services/tenancy/test_workspace_llm_service.py -q`
- Result: `17 passed`

Post-slice state:

- `app/services/tenancy/workspace_llm_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `42`
- Total `app/` `except Exception` count is now `82`

Next recommended slice from here:

1. `app/services/tenancy/workspace_external_link_service.py`
2. `app/services/semantic/constrained_column_vector_service.py`
3. `app/services/semantic/catalog/semantic_enrichment_service.py`
4. `app/services/semantic/catalog/semantic_catalog_repository.py`
5. `app/services/sales_inquiry_service.py`

### 2026-04-05 50th slice: Workspace external link cleanup

Changes:

- Replaced the broad datasource-resolution wrapper in `app/services/tenancy/workspace_external_link_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected datasource-resolution failures on the wrapped `ForgeError` path, but now let unexpected resolver bugs propagate
- Added workspace external-link coverage for unexpected resolver bug propagation
- Bumped backend version to `0.3.188`

Verification:

- `pytest tests/services/tenancy/test_workspace_external_link_service.py -q`
- Result: `7 passed`

Post-slice state:

- `app/services/tenancy/workspace_external_link_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `41`
- Total `app/` `except Exception` count is now `81`

### 2026-04-05 51st slice: Constrained column vector cleanup

Changes:

- Replaced the broad candidate `model_column_id` parse fallback in `app/services/semantic/constrained_column_vector_service.py` with explicit `TypeError`/`ValueError` handling
- Kept expected invalid candidate rows on the existing skip path, but now let unexpected integer-conversion bugs propagate
- Added constrained-column vector coverage for unexpected `__int__` failures during candidate normalization
- Bumped backend version to `0.3.189`

Verification:

- `pytest tests/services/semantic/test_constrained_column_vector_service.py -q`
- Result: `3 passed`

Post-slice state:

- `app/services/semantic/constrained_column_vector_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `40`
- Total `app/` `except Exception` count is now `80`

### 2026-04-05 52nd slice: Semantic enrichment fallback cleanup

Changes:

- Replaced the broad batch-level LLM enrichment fallback in `app/services/semantic/catalog/semantic_enrichment_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected LLM and schema/runtime failures on the heuristic fallback path, but now let unexpected assertion-like enrichment bugs propagate
- Added semantic enrichment coverage for unexpected LLM adapter failures
- Bumped backend version to `0.3.190`

Verification:

- `pytest tests/services/semantic/test_semantic_catalog_builder_pipeline.py -q -k 'semantic_enrichment_service'`
- Result: `2 passed, 5 deselected`

Post-slice state:

- `app/services/semantic/catalog/semantic_enrichment_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `39`
- Total `app/` `except Exception` count is now `79`

### 2026-04-05 53rd slice: Semantic catalog repository cleanup

Changes:

- Replaced the broad relationship-FK target fallback in `app/services/semantic/catalog/semantic_catalog_repository.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Kept expected information-schema lookup failures on the legacy `semantic_concept` fallback path, but now let unexpected repository bugs propagate
- Added direct repository coverage for expected FK-target fallback and unexpected lookup propagation
- Bumped backend version to `0.3.191`

Verification:

- `pytest tests/services/semantic/test_semantic_catalog_repository.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/semantic/catalog/semantic_catalog_repository.py` no longer contains `except Exception`
- Service `except Exception` count is now `38`
- Total `app/` `except Exception` count is now `78`

### 2026-04-05 54th slice: Sales inquiry notification cleanup

Changes:

- Replaced the broad notification-email wrapper in `app/services/sales_inquiry_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected mail-delivery failures on the logged-and-continue path after the inquiry write succeeds, but now let unexpected notification bugs propagate
- Added direct sales-inquiry service coverage for expected notification failure swallowing and unexpected mail bug propagation
- Bumped backend version to `0.3.192`

Verification:

- `pytest tests/services/test_sales_inquiry_service.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/sales_inquiry_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `37`
- Total `app/` `except Exception` count is now `77`

Next recommended slice from here:

1. `app/services/domain/planner_capability_packing_policy_service.py`
2. `app/services/domain/planner_concept_scoring_policy_service.py`
3. `app/services/domain/planner_semantic_join_policy_service.py`
4. `app/services/domain/planner_semantic_projection_policy_service.py`
5. `app/services/domain/planner_semantic_time_policy_service.py`

### 2026-04-06 55th slice: Planner capability packing policy cleanup

Changes:

- Replaced the broad optional DB policy-lookup fallback in `app/services/domain/planner_capability_packing_policy_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Kept expected policy-lookup failures on the seeded-policy fallback path, but now let unexpected parse and programming bugs propagate
- Added planner capability-packing coverage for expected DB fallback and unexpected policy-parse propagation
- Bumped backend version to `0.3.193`

Verification:

- `pytest tests/services/test_planner_capability_packing_policy_service.py -q`
- Result: `6 passed`

Post-slice state:

- `app/services/domain/planner_capability_packing_policy_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `36`
- Total `app/` `except Exception` count is now `76`

### 2026-04-06 56th slice: Planner concept scoring policy cleanup

Changes:

- Replaced the broad optional DB policy-lookup fallback in `app/services/domain/planner_concept_scoring_policy_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Kept expected policy-lookup failures on the seeded-policy fallback path, but now let unexpected policy-parse bugs propagate
- Added planner concept-scoring coverage for expected DB fallback and unexpected parse propagation
- Bumped backend version to `0.3.194`

Verification:

- `pytest tests/services/test_planner_concept_scoring_policy_service.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/domain/planner_concept_scoring_policy_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `35`
- Total `app/` `except Exception` count is now `75`

### 2026-04-06 57th slice: Planner semantic join policy cleanup

Changes:

- Replaced the broad optional DB policy-lookup fallback in `app/services/domain/planner_semantic_join_policy_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Kept expected policy-lookup failures on the seeded-policy fallback path, but now let unexpected join-policy parse bugs propagate
- Added planner semantic-join coverage for expected DB fallback and unexpected parse propagation
- Bumped backend version to `0.3.195`

Verification:

- `pytest tests/services/test_planner_semantic_join_policy_service.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/domain/planner_semantic_join_policy_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `34`
- Total `app/` `except Exception` count is now `74`

### 2026-04-06 58th slice: Planner semantic projection policy cleanup

Changes:

- Replaced the broad optional DB policy-lookup fallback in `app/services/domain/planner_semantic_projection_policy_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Kept expected policy-lookup failures on the seeded-policy fallback path, but now let unexpected projection-policy parse bugs propagate
- Added planner semantic-projection coverage for expected DB fallback and unexpected parse propagation
- Bumped backend version to `0.3.196`

Verification:

- `pytest tests/services/test_planner_semantic_projection_policy_service.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/domain/planner_semantic_projection_policy_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `33`
- Total `app/` `except Exception` count is now `73`

### 2026-04-06 59th slice: Planner semantic time policy cleanup

Changes:

- Replaced the broad optional DB policy-lookup fallback in `app/services/domain/planner_semantic_time_policy_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Kept expected policy-lookup failures on the seeded-policy fallback path, but now let unexpected time-policy parse bugs propagate
- Added planner semantic-time coverage for expected DB fallback and unexpected parse propagation
- Bumped backend version to `0.3.197`

Verification:

- `pytest tests/services/test_planner_semantic_time_policy_service.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/domain/planner_semantic_time_policy_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `32`
- Total `app/` `except Exception` count is now `72`

Next recommended slice from here:

1. `app/services/domain/admin/domain_table_command_service.py`
2. `app/services/domain/domain_recommendation_service.py`
3. `app/services/domain/domain_table_read_service.py`
4. `app/services/domain/join/domain_join_command_service.py`
5. `app/services/domain_resolution/plan_builder.py`

### 2026-04-06 60th slice: Domain table command cleanup

Changes:

- Replaced the broad ID normalization fallback in `app/services/domain/admin/domain_table_command_service.py` with explicit `TypeError`/`ValueError` handling
- Kept expected integer-validation failures on the existing `ForgeError` path, but now let unexpected `__int__` bugs propagate
- Added domain-table command coverage for expected integer validation wrapping and unexpected ID parse propagation
- Bumped backend version to `0.3.198`

Verification:

- `pytest tests/services/domain/admin/test_domain_table_command_service.py -q`
- Result: `3 passed`

Post-slice state:

- `app/services/domain/admin/domain_table_command_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `31`
- Total `app/` `except Exception` count is now `71`

### 2026-04-06 61st slice: Domain recommendation cleanup

Changes:

- Replaced the broad limit normalization fallback in `app/services/domain/domain_recommendation_service.py` with explicit `TypeError`/`ValueError` handling
- Kept expected integer-validation failures on the existing `ForgeError` path, but now let unexpected limit-conversion bugs propagate
- Added domain-recommendation coverage for expected integer validation wrapping and unexpected limit parse propagation
- Bumped backend version to `0.3.199`

Verification:

- `pytest tests/services/test_domain_recommendation_service.py -q`
- Result: `7 passed`

Post-slice state:

- `app/services/domain/domain_recommendation_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `30`
- Total `app/` `except Exception` count is now `70`

### 2026-04-06 62nd slice: Domain table read cleanup

Changes:

- Replaced the broad inventory-sync fallback in `app/services/domain/domain_table_read_service.py` with explicit `ForgeError`/`OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected snapshot-sync failures on the logged-and-continue path, but now let unexpected inventory-sync bugs propagate
- Added domain-table read coverage for unexpected inventory-sync propagation alongside the existing expected runtime fallback case
- Bumped backend version to `0.3.200`

Verification:

- `pytest tests/services/test_domain_table_read_service.py -q`
- Result: `8 passed`

Post-slice state:

- `app/services/domain/domain_table_read_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `29`
- Total `app/` `except Exception` count is now `69`

### 2026-04-06 63rd slice: Domain join command cleanup

Changes:

- Replaced the broad insert-result fallback in `app/services/domain/join/domain_join_command_service.py` with explicit `AttributeError` handling
- Kept expected missing-`lastrowid` results on the `id=None` path, but now let unexpected insert-result bugs propagate
- Added domain-join command coverage for missing `lastrowid` fallback and unexpected insert-result propagation
- Bumped backend version to `0.3.201`

Verification:

- `pytest tests/services/domain/join/test_domain_join_command_service.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/domain/join/domain_join_command_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `28`
- Total `app/` `except Exception` count is now `68`

### 2026-04-06 64th slice: Domain resolution plan builder cleanup

Changes:

- Replaced the broad join-spec JSON parse fallback in `app/services/domain_resolution/plan_builder.py` with explicit `json.JSONDecodeError` handling
- Kept expected invalid join JSON on the existing `ForgeError` path, but now let unexpected parser bugs propagate
- Added plan-builder coverage for unexpected JSON parser propagation
- Bumped backend version to `0.3.202`

Verification:

- `pytest tests/services/test_domain_resolution_plan_builder.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/domain_resolution/plan_builder.py` no longer contains `except Exception`
- Service `except Exception` count is now `27`
- Total `app/` `except Exception` count is now `67`

Next recommended slice from here:

1. `app/services/analytics/executor_adapter.py`
2. `app/services/analytics/profiling_service.py`
3. `app/services/analytics/runtime_registry.py`
4. `app/services/auth/credential_auth_service.py`
5. `app/services/auth/rate_limit_service.py`

### 2026-04-06 65th slice: Analytics executor adapter cleanup

Changes:

- Replaced the broad async statement fallback in `app/services/analytics/executor_adapter.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected executor runtime failures on the failed-statement record path, but now let unexpected executor bugs propagate
- Added direct analytics executor-adapter coverage for expected runtime failure recording and unexpected executor propagation
- Bumped backend version to `0.3.203`

Verification:

- `pytest tests/analytics/test_executor_adapter.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/analytics/executor_adapter.py` no longer contains `except Exception`
- Service `except Exception` count is now `26`
- Total `app/` `except Exception` count is now `66`

### 2026-04-06 66th slice: Analytics profiling cleanup

Changes:

- Replaced the broad per-table profiling fallback in `app/services/analytics/profiling_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected provider and persistence runtime failures on the logged table-failure path, but now let unexpected profiling bugs propagate
- Added profiling coverage for unexpected assertion-like provider failures alongside the existing expected runtime fallback case
- Bumped backend version to `0.3.204`

Verification:

- `pytest tests/analytics/test_profiling_service.py -q`
- Result: `5 passed`

Post-slice state:

- `app/services/analytics/profiling_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `25`
- Total `app/` `except Exception` count is now `65`

### 2026-04-06 67th slice: Analytics runtime registry cleanup

Changes:

- Replaced the broad datasource-build fallback in `app/services/analytics/runtime_registry.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`KeyError` handling
- Kept expected config and executor-construction failures on the skip-datasource path, but now let unexpected factory bugs propagate
- Added direct runtime-registry coverage for expected runtime skip behavior and unexpected factory propagation
- Bumped backend version to `0.3.205`

Verification:

- `pytest tests/analytics/test_runtime_registry.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/analytics/runtime_registry.py` no longer contains `except Exception`
- Service `except Exception` count is now `24`
- Total `app/` `except Exception` count is now `64`

### 2026-04-06 68th slice: Credential auth claims cleanup

Changes:

- Replaced the broad RBAC role-load fallback in `app/services/auth/credential_auth_service.py` with explicit `OperationalError`/`SQLAlchemyError`/`OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected role-load failures on the warning-and-empty-roles path, but now let unexpected role-lookup bugs propagate
- Added direct credential-auth coverage for expected role-load fallback and unexpected role-lookup propagation
- Bumped backend version to `0.3.206`

Verification:

- `pytest tests/services/auth/test_credential_auth_service.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/auth/credential_auth_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `23`
- Total `app/` `except Exception` count is now `63`

### 2026-04-06 69th slice: Rate limit fail-open cleanup

Changes:

- Replaced the broad Valkey fail-open wrapper in `app/services/auth/rate_limit_service.py` with explicit `redis.RedisError`/`OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected Valkey unavailability on the warning-and-return path, but now let unexpected rate-limit bugs propagate
- Added rate-limit coverage for unexpected increment failures alongside the existing fail-open and `429` behavior
- Bumped backend version to `0.3.207`

Verification:

- `pytest tests/services/auth/test_mfa_services.py -q -k 'rate_limit'`
- Result: `2 passed, 3 deselected`

Post-slice state:

- `app/services/auth/rate_limit_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `22`
- Total `app/` `except Exception` count is now `62`

Next recommended slice from here:

1. `app/services/auth/totp_service.py`
2. `app/services/ai_suggest/domain_seeder.py`
3. `app/services/chat/education_fewshot_service.py`
4. `app/services/dictionary/dictionary_service.py`
5. `app/services/domain/column_sample/domain_column_sample_presenter.py`

### 2026-04-06 70th slice: TOTP QR import cleanup

Changes:

- Replaced the broad QR-code import wrapper in `app/services/auth/totp_service.py` with explicit `ImportError` handling
- Kept expected missing-QR dependency failures on the existing `ForgeError` path, but now let unexpected QR import bugs propagate
- Added TOTP coverage for expected QR import wrapping and unexpected import propagation
- Bumped backend version to `0.3.208`

Verification:

- `pytest tests/services/auth/test_mfa_services.py -q -k 'totp'`
- Result: `4 passed, 3 deselected`

Post-slice state:

- `app/services/auth/totp_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `21`
- Total `app/` `except Exception` count is now `61`

### 2026-04-06 71st slice: AI suggest domain seeder cleanup

Changes:

- Replaced the broad deterministic domain-inference wrapper in `app/services/ai_suggest/domain_seeder.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`AttributeError` handling
- Kept expected inference/runtime failures on the warning-and-`None` path, but now let unexpected domain-inference bugs propagate
- Added AI-suggest coverage for expected inference fallback and unexpected propagation
- Bumped backend version to `0.3.209`

Verification:

- `pytest tests/test_ai_suggest.py -q -k 'infer_domain'`
- Result: `4 passed, 66 deselected`

Post-slice state:

- `app/services/ai_suggest/domain_seeder.py` no longer contains `except Exception`
- Service `except Exception` count is now `20`
- Total `app/` `except Exception` count is now `60`

### 2026-04-06 72nd slice: Education fewshot lookup cleanup

Changes:

- Replaced the broad prompt-feedback lookup fallback in `app/services/chat/education_fewshot_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected fewshot lookup failures on the empty-result fallback path, but now let unexpected fewshot bugs propagate
- Added education-fewshot coverage for expected runtime fallback and unexpected propagation
- Bumped backend version to `0.3.210`

Verification:

- `pytest tests/services/chat/test_education_fewshot_service.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/chat/education_fewshot_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `19`
- Total `app/` `except Exception` count is now `59`

### 2026-04-06 73rd slice: Dictionary JSON parsing cleanup

Changes:

- Replaced the broad JSON-field parse fallback in `app/services/dictionary/dictionary_service.py` with explicit `TypeError`/`ValueError`/`json.JSONDecodeError` handling
- Kept expected malformed JSON values on the `None` fallback path, but now let unexpected parser bugs propagate
- Added dictionary-service coverage for unexpected parser propagation
- Bumped backend version to `0.3.211`

Verification:

- `pytest tests/services/test_dictionary_service.py -q`
- Result: `19 passed`

Post-slice state:

- `app/services/dictionary/dictionary_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `18`
- Total `app/` `except Exception` count is now `58`

### 2026-04-06 74th slice: Domain column sample presenter cleanup

Changes:

- Replaced the broad JSON parse fallback in `app/services/domain/column_sample/domain_column_sample_presenter.py` with explicit `TypeError`/`ValueError`/`json.JSONDecodeError` handling
- Kept expected malformed sample JSON on the `None` fallback path, but now let unexpected parser bugs propagate
- Added presenter coverage for unexpected parser propagation
- Bumped backend version to `0.3.212`

Verification:

- `pytest tests/services/domain/test_domain_column_sample_presenter.py -q`
- Result: `3 passed`

Post-slice state:

- `app/services/domain/column_sample/domain_column_sample_presenter.py` no longer contains `except Exception`
- Service `except Exception` count is now `17`
- Total `app/` `except Exception` count is now `57`

Next recommended slice from here:

1. `app/services/forge_match/artifact_service.py`
2. `app/services/forge_match/candidate_retriever.py`
3. `app/services/forge_match/mapping_store.py`
4. `app/services/forge_match/session_reader.py`
5. `app/services/domain_resolver.py`

### 2026-04-06 75th slice: ForgeMatch artifact execution cleanup

Changes:

- Replaced the broad draft SQL execution wrapper in `app/services/forge_match/artifact_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`KeyError` handling
- Kept expected draft execution/runtime failures on the wrapped `ForgeError` path, but now let unexpected execution bugs propagate
- Added direct artifact-service coverage for expected draft execution wrapping and unexpected propagation
- Bumped backend version to `0.3.213`

Verification:

- `pytest tests/services/forge_match/test_artifact_service.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/forge_match/artifact_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `16`
- Total `app/` `except Exception` count is now `56`

### 2026-04-06 76th slice: ForgeMatch candidate retriever cleanup

Changes:

- Replaced the broad vector-search fallback in `app/services/forge_match/candidate_retriever.py` with explicit `ForgeError`/`OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected vector retrieval failures on the warning-and-empty-scores path, but now let unexpected vector bugs propagate
- Added candidate-retriever coverage for expected vector fallback and unexpected propagation
- Bumped backend version to `0.3.214`

Verification:

- `pytest tests/services/forge_match/test_candidate_retriever.py -q`
- Result: `7 passed`

Post-slice state:

- `app/services/forge_match/candidate_retriever.py` no longer contains `except Exception`
- Service `except Exception` count is now `15`
- Total `app/` `except Exception` count is now `55`

### 2026-04-06 77th slice: ForgeMatch mapping store cleanup

Changes:

- Replaced the broad manual-column ID parse fallback in `app/services/forge_match/mapping_store.py` with explicit `TypeError`/`ValueError` handling
- Kept expected manual-column validation failures on the existing `ForgeError` path, but now let unexpected integer-conversion bugs propagate
- Added direct mapping-store coverage for expected integer validation wrapping and unexpected manual-column parse propagation
- Bumped backend version to `0.3.215`

Verification:

- `pytest tests/services/forge_match/test_mapping_store.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/forge_match/mapping_store.py` no longer contains `except Exception`
- Service `except Exception` count is now `14`
- Total `app/` `except Exception` count is now `54`

### 2026-04-06 78th slice: ForgeMatch session reader cleanup

Changes:

- Replaced the broad JSON-dict parse fallback in `app/services/forge_match/session_reader.py` with explicit `TypeError`/`ValueError`/`json.JSONDecodeError` handling
- Kept expected malformed JSON payloads on the `None` fallback path, but now let unexpected parser bugs propagate
- Added direct session-reader coverage for unexpected parser propagation and shaped session-row responses
- Bumped backend version to `0.3.216`

Verification:

- `pytest tests/services/forge_match/test_session_reader.py -q`
- Result: `3 passed`

Post-slice state:

- `app/services/forge_match/session_reader.py` no longer contains `except Exception`
- Service `except Exception` count is now `13`
- Total `app/` `except Exception` count is now `53`

### 2026-04-06 79th slice: Legacy domain resolver cleanup

Changes:

- Replaced the broad domain-id coercion fallback in `app/services/domain_resolver.py` with explicit `TypeError`/`ValueError` handling
- Kept expected invalid domain-id values on the existing `ForgeError` path, but now let unexpected integer-conversion bugs propagate
- Added domain-resolver coverage for unexpected domain-id coercion propagation
- Bumped backend version to `0.3.217`

Verification:

- `pytest tests/services/test_domain_resolver.py -q`
- Result: `9 passed`

Post-slice state:

- `app/services/domain_resolver.py` no longer contains `except Exception`
- Service `except Exception` count is now `12`
- Total `app/` `except Exception` count is now `52`

Next recommended slice from here:

1. `app/services/domains/domain_resolver_service.py`
2. `app/services/execution/execution_result_formatter.py`
3. `app/services/execution_service.py`
4. `app/services/llm/io_logging.py`
5. `app/services/query_tree/query_tree_folder_command_service.py`

### 2026-04-06 80th slice: Domain resolver service hit normalization cleanup

Changes:

- Replaced the broad table-hit ID coercion fallback in `app/services/domains/domain_resolver_service.py` with explicit `TypeError`/`ValueError` handling
- Kept expected malformed hit IDs on the existing skip-invalid-hit path, but now let unexpected integer-coercion bugs propagate
- Added direct domain-resolver-service coverage for unexpected table-hit coercion propagation
- Bumped backend version to `0.3.218`

Verification:

- `pytest tests/test_domain_resolver_service.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/domains/domain_resolver_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `11`
- Total `app/` `except Exception` count is now `51`

### 2026-04-06 81st slice: Execution result formatter cleanup

Changes:

- Replaced the broad total-count coercion fallback in `app/services/execution/execution_result_formatter.py` with explicit `TypeError`/`ValueError` handling
- Kept expected malformed total values on the existing `None` summary path, but now let unexpected integer-coercion bugs propagate
- Added direct formatter coverage for invalid totals and unexpected total coercion propagation
- Bumped backend version to `0.3.219`

Verification:

- `pytest tests/services/execution/test_execution_result_formatter.py -q`
- Result: `6 passed`

Post-slice state:

- `app/services/execution/execution_result_formatter.py` no longer contains `except Exception`
- Service `except Exception` count is now `10`
- Total `app/` `except Exception` count is now `50`

### 2026-04-06 82nd slice: Execution service inline snapshot cleanup

Changes:

- Replaced the broad inline-row snapshot fallback in `app/services/execution_service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError` handling
- Kept expected sync-adapter inline snapshot failures on the existing `inline_rows=None` fallback path, but now let unexpected fetch bugs propagate
- Added direct execution-service coverage for expected inline snapshot fallback and unexpected inline fetch propagation
- Bumped backend version to `0.3.220`

Verification:

- `pytest tests/services/test_execution_service.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/execution_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `9`
- Total `app/` `except Exception` count is now `49`

### 2026-04-06 83rd slice: LLM IO logging cleanup

Changes:

- Replaced the broad log-text JSON serialization fallback in `app/services/llm/io_logging.py` with explicit `TypeError`/`ValueError` handling
- Kept expected JSON serialization failures on the existing `str(value)` fallback path, but now let unexpected stringification bugs propagate
- Added direct IO logging coverage for expected JSON serialization fallback and unexpected string conversion propagation
- Bumped backend version to `0.3.221`

Verification:

- `pytest tests/services/llm/test_io_logging.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/llm/io_logging.py` no longer contains `except Exception`
- Service `except Exception` count is now `8`
- Total `app/` `except Exception` count is now `48`

### 2026-04-06 84th slice: Query tree folder command cleanup

Changes:

- Replaced the broad duplicate-folder create wrapper in `app/services/query_tree/query_tree_folder_command_service.py` with explicit `IntegrityError` handling
- Kept expected duplicate-folder writes on the existing `ForgeError("Folder already exists")` path, but now let unexpected insert failures propagate
- Extended saved-query folder write coverage for duplicate-folder creation and unexpected insert propagation
- Bumped backend version to `0.3.222`

Verification:

- `pytest tests/services/query_tree/test_saved_query_folder_write_service.py -q`
- Result: `19 passed`

Post-slice state:

- `app/services/query_tree/query_tree_folder_command_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `7`
- Total `app/` `except Exception` count is now `47`

Next recommended slice from here:

1. `app/services/prompt_feedback_service.py`
2. `app/services/query_forge/data_prep_compiler.py`
3. `app/services/planner/value_normalizers/country.py`
4. `app/services/planner/compact_planner.py`
5. `app/services/planner_llm/service.py`
6. `app/services/nlp/nlp_to_vector.py`
7. `app/services/planner/semantic_retrieval_helpers.py`

### 2026-04-06 85th slice: Prompt feedback delete validation cleanup

Changes:

- Replaced the broad feedback-id coercion wrapper in `app/services/prompt_feedback_service.py` with explicit `TypeError`/`ValueError` handling
- Kept expected invalid feedback IDs on the existing `ForgeError("feedback_id must be an integer")` path, but now let unexpected integer-conversion bugs propagate
- Added prompt-feedback coverage for invalid feedback IDs and unexpected feedback-id coercion propagation
- Bumped backend version to `0.3.223`

Verification:

- `pytest tests/services/test_prompt_feedback_service.py -q`
- Result: `10 passed`

Post-slice state:

- `app/services/prompt_feedback_service.py` no longer contains `except Exception`
- Service `except Exception` count is now `6`
- Total `app/` `except Exception` count is now `46`

### 2026-04-06 86th slice: Data prep compiler base-select cleanup

Changes:

- Replaced the broad workspace-table ID skip path in `app/services/query_forge/data_prep_compiler.py` with explicit `TypeError`/`ValueError` handling
- Kept expected malformed non-primary workspace-table IDs on the existing skip-invalid-required-column path, but now let unexpected integer-conversion bugs propagate
- Added direct data-prep compiler coverage for invalid required-column table IDs and unexpected workspace-table coercion propagation
- Bumped backend version to `0.3.224`

Verification:

- `pytest tests/services/query_forge/test_data_prep_compiler.py -q`
- Result: `11 passed`

Post-slice state:

- `app/services/query_forge/data_prep_compiler.py` no longer contains `except Exception`
- Service `except Exception` count is now `5`
- Total `app/` `except Exception` count is now `45`

### 2026-04-06 87th slice: Country normalizer DB fallback cleanup

Changes:

- Replaced the broad optional DB fallback wrapper in `app/services/planner/value_normalizers/country.py` with explicit `SQLAlchemyError` handling
- Kept expected missing/unavailable country reference tables on the existing `None` fallback path, but now let unexpected query bugs propagate
- Added country normalizer coverage for reference-table fallback and unexpected DB lookup propagation
- Bumped backend version to `0.3.225`

Verification:

- `pytest tests/services/planner/test_country_normalizer.py -q`
- Result: `8 passed`

Post-slice state:

- `app/services/planner/value_normalizers/country.py` no longer contains `except Exception`
- Service `except Exception` count is now `4`
- Total `app/` `except Exception` count is now `44`

### 2026-04-06 88th slice: Compact planner provider-metadata cleanup

Changes:

- Replaced the broad provider-response parse fallback in `app/services/planner/compact_planner.py` with explicit `json.JSONDecodeError` handling
- Kept expected malformed provider metadata on the existing fallback-model path, but now let unexpected JSON parser bugs propagate
- Added compact-planner coverage for malformed provider metadata and unexpected parser propagation
- Bumped backend version to `0.3.226`

Verification:

- `pytest tests/services/planner/test_compact_planner.py -q`
- Result: `8 passed`

Post-slice state:

- `app/services/planner/compact_planner.py` no longer contains `except Exception`
- Service `except Exception` count is now `3`
- Total `app/` `except Exception` count is now `43`

### 2026-04-06 89th slice: Planner LLM cache-write cleanup

Changes:

- Replaced the broad planner-cache write wrapper in `app/services/planner_llm/service.py` with explicit `OSError`/`RuntimeError`/`TypeError`/`ValueError`/`SQLAlchemyError` handling
- Kept expected cache-write infrastructure failures on the existing non-fatal logging path, but now let unexpected programming bugs propagate
- Added planner-LLM coverage for expected cache-write fallback and unexpected cache-write propagation
- Bumped backend version to `0.3.227`

Verification:

- `pytest tests/services/planner_llm/test_golden_ratio.py -q`
- Result: `3 passed`

Post-slice state:

- `app/services/planner_llm/service.py` no longer contains `except Exception`
- Service `except Exception` count is now `2`
- Total `app/` `except Exception` count is now `42`

Next recommended slice from here:

1. `app/services/nlp/nlp_to_vector.py`
2. `app/services/planner/semantic_retrieval_helpers.py`

### 2026-04-06 90th slice: NLP vector domain-hint cleanup

Changes:

- Replaced the broad domain-hint ID coercion skip path in `app/services/nlp/nlp_to_vector.py` with explicit `TypeError`/`ValueError` handling
- Kept expected malformed domain-hint IDs on the existing skip-invalid-hint path, but now let unexpected integer-conversion bugs propagate
- Added NLP vector request coverage for invalid domain hints and unexpected domain-hint coercion propagation
- Bumped backend version to `0.3.228`

Verification:

- `pytest tests/test_nlp_to_vector.py -q`
- Result: `4 passed`

Post-slice state:

- `app/services/nlp/nlp_to_vector.py` no longer contains `except Exception`
- Service `except Exception` count is now `1`
- Total `app/` `except Exception` count is now `41`

### 2026-04-06 91st slice: Semantic retrieval helper integer cleanup

Changes:

- Replaced the broad integer-coercion fallback in `app/services/planner/semantic_retrieval_helpers.py` with explicit `TypeError`/`ValueError` handling
- Kept expected invalid integer-like values on the existing `None` fallback path, but now let unexpected integer-conversion bugs propagate
- Added direct semantic retrieval helper coverage for invalid integer values and unexpected coercion propagation
- Bumped backend version to `0.3.229`

Verification:

- `pytest tests/services/planner/test_semantic_retrieval_helpers.py -q`
- Result: `2 passed`

Post-slice state:

- `app/services/planner/semantic_retrieval_helpers.py` no longer contains `except Exception`
- Service `except Exception` count is now `0`
- Total `app/` `except Exception` count is now `40`

Next recommended slice from here:

1. `app/tasks/skill_runner.py`
2. `app/tasks/forge_match_tasks.py`
3. `app/adapters/analytics/databricks_executor.py`
4. `app/adapters/analytics/snowflake_executor.py`
5. `app/adapters/analytics/mysql_executor.py`
6. `app/adapters/analytics/databricks_metadata_provider.py`
7. `app/adapters/analytics/mysql_metadata_provider.py`

### 2026-04-06 92nd slice: Skill runner task cleanup

Changes:

- Replaced the broad execution and dispatch wrappers in `app/tasks/skill_runner.py` with explicit operational failure tuples
- Kept expected skill runtime/dispatch failures on the existing mark-failed or log-and-continue paths, but now let unexpected assertion-style bugs propagate
- Extended task-runner coverage for expected execution failure recording, expected dispatch fallback, and unexpected bug propagation
- Bumped backend version to `0.3.230`

Verification:

- `pytest tests/tasks/test_skill_runner.py -q`
- Result: `11 passed`

Post-slice state:

- `app/tasks/skill_runner.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `38`

### 2026-04-06 93rd slice: ForgeMatch analyze task cleanup

Changes:

- Replaced the broad task-level failure wrapper in `app/tasks/forge_match_tasks.py` with an explicit operational failure tuple
- Kept expected analyze-job failures on the existing log-and-reraise path, but now let unexpected assertion-style bugs propagate without task-level swallowing
- Added direct ForgeMatch task coverage for expected task logging and unexpected bug propagation
- Bumped backend version to `0.3.231`

Verification:

- `pytest tests/tasks/test_forge_match_tasks.py -q`
- Result: `2 passed`

Post-slice state:

- `app/tasks/forge_match_tasks.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `37`

### 2026-04-06 94th slice: Databricks analytics executor cleanup

Changes:

- Replaced the broad execution and connection-test wrappers in `app/adapters/analytics/databricks_executor.py` with explicit runtime failure handling
- Kept expected delegate/runtime failures on the existing sanitized `RuntimeError` path, but now let unexpected assertion-style bugs propagate
- Extended Databricks analytics executor coverage for sanitized execution/test failures and unexpected delegate propagation
- Bumped backend version to `0.3.232`

Verification:

- `pytest tests/analytics/test_databricks_executor.py -q`
- Result: `15 passed`

Post-slice state:

- `app/adapters/analytics/databricks_executor.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `35`

### 2026-04-06 95th slice: MySQL analytics executor cleanup

Changes:

- Replaced the broad execution and connection-test wrappers in `app/adapters/analytics/mysql_executor.py` with explicit SQLAlchemy/runtime failure handling
- Kept expected SQLAlchemy and connection failures on the existing sanitized `RuntimeError` path, but now let unexpected assertion-style bugs propagate
- Added direct MySQL analytics executor coverage for sanitized execution/test failures and unexpected propagation
- Bumped backend version to `0.3.233`

Verification:

- `pytest tests/analytics/test_mysql_executor.py -q`
- Result: `4 passed`

Post-slice state:

- `app/adapters/analytics/mysql_executor.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `33`

### 2026-04-06 96th slice: Snowflake analytics executor cleanup

Changes:

- Replaced the broad execution, cleanup, and connection-test wrappers in `app/adapters/analytics/snowflake_executor.py` with explicit driver/runtime failure handling
- Kept expected Snowflake driver failures on the existing sanitized `RuntimeError` path and expected cleanup failures on the ignore-cleanup path, but now let unexpected assertion-style bugs propagate
- Tightened the Snowflake driver import fallback to `ImportError` so the slice does not reintroduce a blanket catch at module import time
- Extended Snowflake analytics executor coverage for sanitized driver failures, cleanup fallback, and unexpected cleanup propagation
- Bumped backend version to `0.3.235`

Verification:

- `pytest tests/analytics/test_snowflake_executor.py -q`
- Result: `22 passed`

Post-slice state:

- `app/adapters/analytics/snowflake_executor.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `29`

Next recommended slice from here:

1. `app/adapters/analytics/databricks_metadata_provider.py`
2. `app/adapters/analytics/mysql_metadata_provider.py`
3. `app/adapters/analytics/snowflake_metadata_provider.py`
4. `app/adapters/databricks_sql_executor.py`
5. `app/adapters/base_token_manager.py`
6. `app/infra/qdrant_client.py`
7. `app/decorators/security.py`

### 2026-04-06 97th slice: Databricks metadata provider cleanup

Changes:

- Replaced the broad schema/profile sampling fallbacks in `app/adapters/analytics/databricks_metadata_provider.py` with explicit runtime failure handling
- Kept expected executor/runtime failures on the existing schema fallback and per-column sample-error paths, but now let unexpected assertion-style bugs propagate
- Extended Databricks metadata provider coverage for unexpected schema lookup and top-value sampling propagation
- Bumped backend version to `0.3.236`

Verification:

- `pytest tests/analytics/test_metadata_provider_databricks.py -q`
- Result: `17 passed`

Post-slice state:

- `app/adapters/analytics/databricks_metadata_provider.py` no longer contains `except Exception`

### 2026-04-06 98th slice: MySQL metadata provider cleanup

Changes:

- Replaced the broad profile sampling wrappers in `app/adapters/analytics/mysql_metadata_provider.py` with explicit runtime failure handling
- Kept expected executor/runtime failures on the existing sample-error paths, but now let unexpected assertion-style bugs propagate
- Added MySQL metadata provider coverage for unexpected top-value sampling propagation
- Bumped backend version to `0.3.237`

Verification:

- `pytest tests/analytics/test_metadata_provider_mysql.py -q`
- Result: `10 passed`

Post-slice state:

- `app/adapters/analytics/mysql_metadata_provider.py` no longer contains `except Exception`

### 2026-04-06 99th slice: Snowflake metadata provider cleanup

Changes:

- Replaced the broad profile sampling wrappers in `app/adapters/analytics/snowflake_metadata_provider.py` with explicit runtime failure handling
- Kept expected executor/runtime failures on the existing sample-error paths, but now let unexpected assertion-style bugs propagate
- Added Snowflake metadata provider coverage for unexpected top-value sampling propagation
- Bumped backend version to `0.3.238`

Verification:

- `pytest tests/analytics/test_metadata_provider_snowflake.py -q`
- Result: `14 passed`

Post-slice state:

- `app/adapters/analytics/snowflake_metadata_provider.py` no longer contains `except Exception`

### 2026-04-06 100th slice: Databricks SQL port JSON parse cleanup

Changes:

- Replaced the broad JSON parse wrapper in `app/adapters/databricks_sql_executor.py` with explicit `ValueError` handling
- Kept expected non-JSON Databricks responses on the existing sanitized `RuntimeError` path, but now let unexpected assertion-style parser bugs propagate
- Added Databricks SQL port coverage for non-JSON responses and unexpected parser propagation
- Bumped backend version to `0.3.239`

Verification:

- `pytest tests/adapters/test_databricks_sql_executor.py -q`
- Result: `18 passed`

Post-slice state:

- `app/adapters/databricks_sql_executor.py` no longer contains `except Exception`

### 2026-04-06 101st slice: Base token manager refresh cleanup

Changes:

- Replaced the broad token refresh wrapper in `app/adapters/base_token_manager.py` with explicit request/JSON failure handling
- Kept expected token refresh network/JSON failures on the existing log-only path, but now let unexpected assertion-style bugs propagate
- Added direct base token manager coverage for expected request fallback, success-path token population, and unexpected propagation
- Bumped backend version to `0.3.240`

Verification:

- `pytest tests/adapters/test_base_token_manager.py -q`
- Result: `3 passed`

Post-slice state:

- `app/adapters/base_token_manager.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `20`

### 2026-04-06 102nd slice: Qdrant payload index cleanup

Changes:

- Replaced the broad payload-index wrapper in `app/infra/qdrant_client.py` with explicit Qdrant/runtime failure handling
- Kept expected Qdrant/runtime index failures on the existing log-and-reraise path, but now let unexpected assertion-style bugs propagate
- Added direct Qdrant wrapper coverage for expected payload-index reraising and unexpected propagation
- Bumped backend version to `0.3.241`

Verification:

- `pytest tests/test_qdrant_client.py tests/test_qdrant_filters.py -q`
- Result: `3 passed`

Post-slice state:

- `app/infra/qdrant_client.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `19`

### 2026-04-06 103rd slice: Security RBAC fallback cleanup

Changes:

- Replaced the broad RBAC preload and effective-role fallback wrappers in `app/decorators/security.py` with explicit import/runtime failure handling
- Kept expected RBAC availability failures on the existing graceful fallback path, but now let unexpected assertion-style bugs propagate during both preload and effective-role resolution
- Added direct security decorator coverage for expected RBAC fallback plus unexpected preload and second-load propagation
- Bumped backend version to `0.3.242`

Verification:

- `pytest tests/decorators/test_security.py -q`
- Result: `3 passed`

Post-slice state:

- `app/decorators/security.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `17`

### 2026-04-06 104th slice: Workspace LLM resolver cleanup

Changes:

- Replaced the broad workspace LLM resolver fallback in `app/config/llm_resolver.py` with explicit runtime/config failure handling
- Tightened `_to_int_or_none` to catch only `TypeError`/`ValueError`, preserving the existing `None` fallback for invalid identifiers while letting unexpected assertion-style conversion bugs propagate
- Added resolver coverage for unexpected service propagation and unexpected integer conversion propagation
- Bumped backend version to `0.3.243`

Verification:

- `pytest tests/config/test_llm_resolver.py -q`
- Result: `10 passed`

Post-slice state:

- `app/config/llm_resolver.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `15`

### 2026-04-06 105th slice: Config env helper cleanup

Changes:

- Replaced the broad environment parsing fallbacks in `app/config/__init__.py` with explicit `TypeError`/`ValueError` handling
- Kept invalid environment values on the existing default-value path, but now let unexpected `os.getenv` assertion-style bugs propagate
- Added direct config helper coverage for invalid-value fallback and unexpected getenv propagation
- Bumped backend version to `0.3.244`

Verification:

- `pytest tests/config/test_config_helpers.py -q`
- Result: `2 passed`

Post-slice state:

- `app/config/__init__.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `13`

### 2026-04-06 106th slice: spaCy model loader cleanup

Changes:

- Replaced the broad spaCy model-load wrapper in `app/nlp/spacy_pipeline.py` with explicit import/model-path failure handling
- Kept expected spaCy availability and bad-model-path failures on the existing `None` fallback path, but now let unexpected loader assertion-style bugs propagate
- Added direct spaCy pipeline coverage for expected model-load fallback and unexpected propagation
- Bumped backend version to `0.3.245`

Verification:

- `pytest tests/services/nlp/test_spacy_pipeline.py -q`
- Result: `2 passed`

Post-slice state:

- `app/nlp/spacy_pipeline.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `12`

### 2026-04-06 107th slice: Gazetteer overwrite compatibility cleanup

Changes:

- Replaced the broad `overwrite_ents` compatibility wrapper in `app/nlp/gazetteer.py` with explicit attribute/value compatibility handling
- Kept expected spaCy compatibility setter failures on the existing ignore-and-continue path, but now let unexpected assertion-style setter bugs propagate
- Extended gazetteer coverage for expected compatibility fallback and unexpected propagation
- Bumped backend version to `0.3.246`

Verification:

- `pytest tests/services/nlp/test_normalization_and_gazetteer.py -q`
- Result: `4 passed`

Post-slice state:

- `app/nlp/gazetteer.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `11`

### 2026-04-06 108th slice: Entity ruler loader compatibility cleanup

Changes:

- Replaced the broad `overwrite_ents` compatibility wrapper in `app/nlp/gazetteers/load_entity_ruler.py` with explicit attribute/value compatibility handling
- Kept expected spaCy compatibility setter failures on the existing ignore-and-continue path, but now let unexpected assertion-style setter bugs propagate
- Added direct entity-ruler loader coverage for expected compatibility fallback and unexpected propagation
- Bumped backend version to `0.3.247`

Verification:

- `pytest tests/services/nlp/test_load_entity_ruler.py -q`
- Result: `2 passed`

Post-slice state:

- `app/nlp/gazetteers/load_entity_ruler.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `10`

### 2026-04-06 109th slice: Tier2 pipeline fallback cleanup

Changes:

- Replaced the broad Tier2 inference and model-load wrappers in `app/nlp/tier2_spacy/pipeline.py` with explicit runtime/model availability handling
- Kept expected Tier2 inference and model-load failures on the existing degraded-mode warning paths, but now let unexpected assertion-style bugs propagate
- Extended Tier2 pipeline coverage for expected inference fallback, expected model-load fallback, and unexpected propagation in both paths
- Bumped backend version to `0.3.248`

Verification:

- `pytest tests/services/nlp/test_tier2_pipeline.py -q`
- Result: `6 passed`

Post-slice state:

- `app/nlp/tier2_spacy/pipeline.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `8`

### 2026-04-06 110th slice: Tier2 dataset helper cleanup

Changes:

- Replaced the broad JSONL parsing wrapper and spaCy import wrapper in `app/nlp/tier2_spacy/training/dataset.py` with explicit malformed-input and dependency-import handling
- Kept expected malformed dataset rows and missing spaCy dependency failures on the existing user-facing error paths, but now let unexpected assertion-style parser/import bugs propagate
- Added direct Tier2 dataset coverage for expected parse wrapping, expected missing-spaCy wrapping, and unexpected propagation in both paths
- Bumped backend version to `0.3.249`

Verification:

- `pytest tests/services/nlp/test_tier2_dataset.py -q`
- Result: `4 passed`

Post-slice state:

- `app/nlp/tier2_spacy/training/dataset.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `6`

### 2026-04-06 111th slice: Destination model fallback cleanup

Changes:

- Replaced the broad config-access and usage-summary fallbacks in `app/models/domain/destinations.py` with explicit config/decryption and database/runtime failure handling
- Kept expected decryption/config and usage-query failures on the existing empty-config / zero-or-unknown usage fallback paths, but now let unexpected assertion-style bugs propagate
- Extended destination coverage for expected fallback and unexpected propagation in `get_masked_config`, `get_usage_summary`, and `_count_skills_using_destination`
- Bumped backend version to `0.3.250`

Verification:

- `pytest tests/test_destinations.py -q`
- Result: `35 passed`

Post-slice state:

- `app/models/domain/destinations.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `3`

### 2026-04-06 112th slice: Datasource secret command JSON cleanup

Changes:

- Replaced the broad JSON parse wrapper in `app/commands/encrypt_datasource_secrets.py` with explicit JSON decode handling
- Kept invalid datasource config JSON on the existing empty-dict fallback path, but now let unexpected assertion-style parser bugs propagate
- Added direct datasource secret command coverage for invalid JSON fallback and unexpected parser propagation
- Bumped backend version to `0.3.251`

Verification:

- `pytest tests/commands/test_encrypt_datasource_secrets.py -q`
- Result: `2 passed`

Post-slice state:

- `app/commands/encrypt_datasource_secrets.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `2`

### 2026-04-06 113th slice: Destination usage tracking cleanup

Changes:

- Replaced the broad destination usage-recording wrapper in `app/skills/destination_resolver.py` with explicit database/runtime failure handling
- Kept expected usage-recording failures on the existing warn-and-continue path, but now let unexpected assertion-style bugs propagate
- Extended destination resolver coverage for expected usage fallback and unexpected propagation during `resolve_channel_config`
- Bumped backend version to `0.3.252`

Verification:

- `pytest tests/test_destinations.py -q -k 'resolve_channel_config or validate_ref'`
- Result: `7 passed, 30 deselected`

Post-slice state:

- `app/skills/destination_resolver.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `1`

### 2026-04-06 114th slice: Skill autodiscovery import cleanup

Changes:

- Replaced the broad skill autodiscovery submodule import wrapper in `app/skills/registry.py` with explicit `ImportError` handling
- Kept expected missing optional-skill import failures on the existing log-and-continue path, but now let unexpected assertion-style module import bugs propagate
- Added direct skill registry coverage for expected optional dependency import fallback and unexpected propagation
- Bumped backend version to `0.3.253`

Verification:

- `pytest tests/test_skill_registry.py -q`
- Result: `2 passed`

Post-slice state:

- `app/skills/registry.py` no longer contains `except Exception`
- Total `app/` `except Exception` count is now `0`

Next recommended slice from here:

- Broad `except Exception` cleanup across `query-forge-api/app` is complete
