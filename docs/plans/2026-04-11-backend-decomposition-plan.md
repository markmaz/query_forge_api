# Backend Decomposition Plan

Date: 2026-04-11
Scope: `query-forge-api/`
Source plans:
- [2026-04-10-backend-code-review-implementation-plan.md](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/docs/plans/2026-04-10-backend-code-review-implementation-plan.md)
- [2026-04-10-backend-code-review-findings.md](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/docs/plans/2026-04-10-backend-code-review-findings.md)

## Goal

Turn the remaining backend refactor backlog into a safe, test-driven decomposition sequence. This plan is intentionally structural, not behavioral: no feature changes, no new compatibility shims, and no service-contract churn unless a slice explicitly calls for it.

## Priority Order

| Priority | File | Current size | Why first |
| --- | --- | ---: | --- |
| 1 | [semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_suggestion_service.py) | 1254 | Highest behavior density: run lifecycle, batching, LLM orchestration, persistence, and result normalization are all mixed together. |
| 2 | [semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_concept_service.py) | 1145 | Multiple CRUD domains live in one file: concepts, aliases, value aliases, and column maps. |
| 3 | [tenancy_admin_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/tenancy/tenancy_admin_service.py) | 1162 | High operator impact and broad admin surface; changes here need careful slice boundaries. |
| 4 | [minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/minimal_chat_service.py) | 1039 | Already behaviorally improved, but transport, storage, summarization, and orchestration are still tightly coupled. |
| 5 | [semantic_retrieval_helpers.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_retrieval_helpers.py) | 974 | Pure-function heavy and lower-risk to split, but broad planner reach means it should happen after the heavier service decompositions. |
| 6 | [planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_signal_policy_service.py) | 957 | Policy matching, rule parsing, and persistence are mixed, but the blast radius is smaller than the items above. |

Secondary backlog after the six core items:
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_llm/service.py) `915`
- [llm_planning_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/llm_planning_service.py) `861`

## Working Rules

- Keep each slice behavior-preserving.
- Extract by runtime concern, not by arbitrary line count.
- Add direct tests for newly extracted helpers or modules when they become meaningful units.
- Run focused tests after every slice.
- Run full `pytest -q` after each file-level decomposition completes.
- If a slice requires public API changes, stop and make that an explicit contract-change task instead of hiding it inside a refactor.

## Workstream 1: Semantic Suggestion Service

Primary test anchor:
- [test_semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_suggestion_service.py)

Recommended slices:

1. Extract run lifecycle and row serialization helpers
   - Move request normalization, run-row normalization, JSON coercion, and error formatting into a sibling helper module.
   - Keep `SemanticSuggestionService` as the orchestration entry point.
   - Target tests:
     - existing [test_semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_suggestion_service.py)
     - add a focused helper test file if serialization logic becomes non-trivial

2. Extract batch execution pipeline
   - Move card chunking, pre-LLM deterministic matching, unresolved-card preparation, and batch merge logic into a dedicated batch runner/helper module.
   - Keep DB writes in the service for this slice.
   - Target tests:
     - batch-oriented cases in [test_semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_suggestion_service.py)

3. Extract persistence adapter/repository layer
   - Move raw SQL read/write concerns for runs, run items, status updates, and approval actions into a repository-style module.
   - Leave validation and orchestration in the service.
   - Target tests:
     - current service tests
     - add direct repository tests only if query branching becomes hard to cover through the service

Exit criteria:
- `SemanticSuggestionService` becomes an orchestration facade instead of a mixed SQL + batch + serialization module.
- Main service file should drop below roughly `700` lines without adding compatibility wrappers.

## Workstream 2: Semantic Concept Service

Primary test anchor:
- [test_semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_concept_service.py)

Recommended slices:

1. Extract payload normalization and row-shaping helpers
   - Move concept/alias/value-alias/column-map payload normalization into `semantic_concept_payloads.py` or equivalent.
   - Move row normalization into a separate serializer module.
   - Target tests:
     - existing [test_semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_concept_service.py)
     - add direct payload-normalizer tests if needed

2. Split alias and value-alias operations from concept CRUD
   - Keep concept CRUD in the main service or a core service.
   - Move alias CRUD and value-alias CRUD into dedicated services or modules.
   - Preserve one route-level facade if needed, but stop co-locating all write paths in one class.
   - Target tests:
     - [test_semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_concept_service.py)

3. Split concept-column-map management
   - Extract concept-column-map CRUD and validation into its own service.
   - This is the cleanest independent subdomain in the file.
   - Target tests:
     - existing service tests that cover column maps
     - new focused tests only if extraction reveals separate edge cases

Exit criteria:
- Concept CRUD, alias CRUD, value alias CRUD, and column-map CRUD no longer share a single oversized service file.

## Workstream 3: Tenancy Admin Service

Primary test anchor:
- [test_tenancy_admin_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/tenancy/test_tenancy_admin_service.py)

Recommended slices:

1. Extract datasource row normalization and JSON helpers
   - Move datasource row coercion, namespace dedupe, JSON safe conversion, and flag normalization into a tenancy serializer/helper module.
   - This is the lowest-risk slice.
   - Target tests:
     - [test_tenancy_admin_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/tenancy/test_tenancy_admin_service.py)

2. Split workspace administration from datasource administration
   - Create one service for workspace CRUD/binding flows and one for datasource CRUD/binding flows.
   - Keep route-facing coordination thin.
   - Target tests:
     - existing tenancy admin tests
     - add focused datasource-only tests if extraction changes mocking complexity

3. Extract workspace-user/workspace-binding workflows
   - Move workspace binding resolution and assignment logic out of the main admin service.
   - This slice should happen only after workspace and datasource concerns are separated.
   - Target tests:
     - [test_tenancy_admin_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/tenancy/test_tenancy_admin_service.py)

Exit criteria:
- Tenancy admin orchestration stops acting as the repository, serializer, and workflow engine for every tenancy object.

## Workstream 4: Minimal Chat Service

Primary test anchor:
- [test_minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/chat/test_minimal_chat_service.py)

Recommended slices:

1. Extract provider request/response formatting helpers
   - Move provider payload construction, assistant-content extraction, finish-reason parsing, usage normalization, and preview formatting into a provider utility module.
   - Target tests:
     - [test_minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/chat/test_minimal_chat_service.py)

2. Extract conversation compaction/summarization helpers
   - Move message trimming, summary merge, title derivation, and context-budget logic into a separate conversation-shaping module.
   - Target tests:
     - existing minimal-chat tests
     - add focused helper tests if summary and compaction cases become clearer outside the service

3. Split storage concerns from request orchestration
   - Move conversation-store reads/writes, store fallback handling, and store listing/deletion logic into a storage adapter module.
   - Keep `MinimalChatService` focused on request validation and end-to-end orchestration.
   - Target tests:
     - [test_minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/chat/test_minimal_chat_service.py)

Exit criteria:
- `MinimalChatService` reads as API orchestration, not as one file that owns transport, storage, summarization, validation, and fallback internals.

## Workstream 5: Semantic Retrieval Helpers

Primary test anchor:
- [test_semantic_retrieval_helpers.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner/test_semantic_retrieval_helpers.py)

Recommended slices:

1. Split indexing/build phases from scoring phases
   - Move `CapabilityIndex`, `build_capability_index`, and domain-candidate construction into an index-builder module.
   - Move scoring/ranking functions into a scorer module.
   - Target tests:
     - [test_semantic_retrieval_helpers.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner/test_semantic_retrieval_helpers.py)

2. Split lexical alias and entity-matching helpers
   - Extract n-gram, lexical hint, alias override, regex, and entity-term helpers into a lexical matching module.
   - Target tests:
     - existing semantic retrieval helper tests
     - expand direct lexical tests if current coverage is too planner-path specific

3. Split candidate post-processing and preference rules
   - Extract dedupe, dimension/filter/metric preference, and “looks like” heuristics into a postprocess module.
   - Target tests:
     - [test_semantic_retrieval_helpers.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner/test_semantic_retrieval_helpers.py)

Exit criteria:
- The retrieval helper layer becomes discoverable by concern instead of one long utility file.

## Workstream 6: Planner Signal Policy Service

Primary test anchor:
- [test_planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/test_planner_signal_policy_service.py)

Recommended slices:

1. Extract rule parsing and rule matching
   - Move `_parse_policy_rule`, `_rule_matches`, and school-literal helpers into a rule module.
   - Keep service methods calling into those helpers.
   - Target tests:
     - [test_planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/test_planner_signal_policy_service.py)

2. Extract persistence/serialization helpers
   - Move row-to-payload coercion and JSON-safe conversion out of the main service file.
   - Target tests:
     - existing planner signal policy tests

3. Separate list/evaluation paths from admin write paths
   - If the service still mixes read/evaluation and admin CRUD heavily after the first two slices, split those concerns into distinct service modules.
   - Target tests:
     - [test_planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/test_planner_signal_policy_service.py)

Exit criteria:
- Policy evaluation logic is no longer buried inside the same file as admin persistence behavior.

## Secondary Backlog

These are worth doing after the six primary workstreams, not before:

1. [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_llm/service.py)
   - likely split into request building, cache/use-policy handling, and transport/result parsing
   - likely tests: planner LLM and golden-ratio suites

2. [llm_planning_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/llm_planning_service.py)
   - likely split prompt construction, slot-hint handling, retry planning, and response parsing
   - likely tests: planner-domain service and prompt-planning suites

## Suggested Execution Order

1. `semantic_suggestion_service`
2. `semantic_concept_service`
3. `tenancy_admin_service`
4. `minimal_chat_service`
5. `semantic_retrieval_helpers`
6. `planner_signal_policy_service`
7. secondary planner LLM files

Rationale:
- The top three are the highest maintenance drag and the most likely to produce merge friction if left untouched.
- `minimal_chat_service` is large, but its recent cleanup means it is safer to tackle after the more mixed admin/semantic services.
- The pure-function heavy retrieval helper and signal-policy files are good later cleanups once the heavier orchestration services are decomposed.

## Execution Template Per File

For each file-level workstream:

1. Identify 2-3 runtime concerns to separate.
2. Extract the lowest-risk helper/serializer slice first.
3. Run the file’s focused tests.
4. Extract the workflow or repository slice next.
5. Run the focused tests again.
6. Finish with `pytest -q` before declaring that file complete.

## Done Definition

A decomposition workstream is complete when:
- the original file is materially smaller,
- the extracted modules have clear concern boundaries,
- no compatibility-only wrappers were introduced,
- focused tests for the touched area are green,
- and the full backend suite is green.
