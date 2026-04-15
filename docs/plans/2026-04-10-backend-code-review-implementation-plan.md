# Backend Review Implementation Plan

Date: 2026-04-10
Scope: `query-forge-api/`
Source review: [2026-04-10-backend-code-review-findings.md](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/docs/plans/2026-04-10-backend-code-review-findings.md)

## Goal

Convert the backend review findings into a staged cleanup plan that reduces operational risk first, then removes misleading contracts and stale compatibility surfaces, and finally pays down structural debt that is slowing future work.

## Progress

- 2026-04-10: Phase 1 implemented
  - recursive request-body audit scrubbing added
  - `SMTP_PORT` env handling fixed
  - broker health now reports `degraded` when the broker is reachable but workers are absent
  - regression tests added for all three slices
  - full backend gate after Phase 1: `pytest -q` -> `2639 passed, 78 skipped`
- 2026-04-10: Phase 2 implemented
  - workspace inventory freshness now honors `min_fresh_age_minutes` instead of always syncing
  - non-Databricks analytics executor adapter now rejects unsupported per-call warehouse/catalog/schema overrides
  - metadata-mode compatibility shims now validate supported modes and expose configured vs effective behavior explicitly
  - regression tests added for freshness, unsupported execution context, and metadata mode validation
  - full backend gate after Phase 2: `pytest -q` -> `2646 passed, 78 skipped`
- 2026-04-10: Phase 3 implemented
  - planner projection policies now support the full scope model consistently across validation, lookup, list, and upsert paths
  - planner domain-selection and prompt-intent policies now support vertical scope instead of silently discarding `vertical_norm`
  - admin planner policy routes now pass vertical scope context where applicable
  - fake `actor_user_id` plumbing was removed from projection, prompt-intent, and domain-selection policy families where no audit trail exists
  - regression tests added for scope precedence, scoped upserts, vertical-scope validation, and updated admin route contracts
  - full backend gate after Phase 3: `pytest -q` -> `2655 passed, 78 skipped`
- 2026-04-10: Phase 4 implemented
  - minimal chat in-memory fallback now stores expiry metadata, evicts expired entries on access, and trims itself to a bounded key count
  - the primary minimal-chat / ForgeInsights conversation-store interface no longer carries a dead per-save TTL parameter
  - ForgeInsights MySQL conversation storage now reflects non-expiring persistence without pretending to honor TTL
  - execution status timestamps now use timezone-aware UTC instead of `datetime.utcnow()`
  - regression tests added for expired-memory eviction, bounded fallback trimming, updated conversation-store signatures, and UTC timestamp formatting
  - full backend gate after Phase 4: `pytest -q` -> `2658 passed, 78 skipped`
- 2026-04-10: Phase 5 implemented
  - completed the unused-argument and dead-contract sweep across domain feature wrappers, execution routes, metadata sync, chat persistence, QueryForge helpers, and route/framework placeholder signatures
  - removed misleading wrapper keywords and stale service parameters where the live behavior no longer used them
  - converted required placeholder parameters into explicit no-op interface markers instead of accidental unused-argument debt
  - `ruff check app --select ARG001,ARG002,F841` is now `0` findings, down from `36`
  - adjacent stale imports surfaced by the sweep were also removed so focused Ruff checks stay clean
  - full backend gate after Phase 5: `pytest -q` -> `2658 passed, 78 skipped`

## Plan Summary

1. Fix production-facing correctness and security issues first.
2. Remove or implement misleading service contracts and ignored parameters.
3. Make planner-policy scoping and write-audit behavior internally consistent.
4. Tighten degraded-mode behavior and runtime hygiene.
5. Finish with broader dead-code and large-file decomposition once behavior is correct.

## Phase 1: Security And Operational Correctness

Priority: `P1`
Target outcome: close the bugs that can leak secrets, misconfigure email, or misreport platform health.

### Slice 1.1: Harden request-body audit scrubbing

Files:
- [factory.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/factory.py)

Tasks:
- Replace the current shallow masking helper with a recursive scrubber.
- Cover dicts, lists, nested objects, and case-insensitive secret-like keys.
- Decide whether some endpoints should log no body at all.

Acceptance criteria:
- Top-level and nested secrets are redacted before `g.audit_data` is written.
- Destination, auth, and tenancy credential payloads are covered by tests.
- Audit log output remains structurally useful for debugging.

Suggested tests:
- new unit tests around the scrubber helper
- route-level assertions for auth and destination payload logging

### Slice 1.2: Fix SMTP port config typo

Files:
- [__init__.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/config/__init__.py)
- config tests to add under [tests](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests)

Tasks:
- Change `SMPT_PORT` to `SMTP_PORT`.
- Add a config regression test.
- Decide whether to preserve temporary backward compatibility with the typo for one release.

Acceptance criteria:
- `SMTP_PORT` is honored in app init.
- Misconfigured env handling is covered by tests.

### Slice 1.3: Correct broker health semantics

Files:
- [health_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/admin/health_service.py)
- related tests under [tests/services](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services)

Tasks:
- Decide the desired truth table for:
  - Valkey up / broker up / workers up
  - Valkey up / broker up / workers down
  - Valkey down / broker up / workers up
- Encode that as `ok`, `degraded`, or `error`.
- Keep worker state visible in the response regardless.

Acceptance criteria:
- Health response cannot return fully green while workers are unreachable unless that is an explicit documented mode.
- Tests cover broker-up/worker-down behavior.

## Phase 2: Contract Honesty And Ignored-Parameter Cleanup

Priority: `P2`
Target outcome: stop accepting parameters that the backend silently ignores.

### Slice 2.1: Workspace inventory freshness contract

Files:
- [domain_table_read_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/domain_table_read_service.py)
- sync helpers under [app/services/domain/table_read](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/table_read)

Tasks:
- Either implement `min_fresh_age_minutes` or remove it from the public method contract.
- If implemented, define freshness off `last_seen_at` and/or a dedicated sync timestamp.
- Keep sync fallback behavior explicit.

Acceptance criteria:
- Fresh inventory reads skip sync when within threshold.
- Stale inventory reads trigger sync.
- Tests cover both branches.

### Slice 2.2: Analytics executor adapter context handling

Files:
- [executor_adapter.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/analytics/executor_adapter.py)
- any callers that expect per-call warehouse/catalog/schema override

Tasks:
- Audit all callers of `submit_statement()` and `submit_statement_async()`.
- For non-Databricks adapters, either:
  - support context application where meaningful, or
  - reject unsupported context arguments with a clear error.
- Remove “pretend async” behavior where it creates false confidence.

Acceptance criteria:
- Per-call execution context is either honored or explicitly rejected.
- Contract tests make silent dropping impossible to reintroduce.

### Slice 2.3: Remove stale compatibility knobs

Files:
- [gateway.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/metadata/gateway.py)
- [domain_table_read_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/domain_table_read_service.py)
- any callers passing `metadata_mode`, `mode`, `legacy_repo`, or discarded TTLs

Tasks:
- Remove dead parameters if they are no longer used anywhere meaningful.
- Where temporary compatibility is needed, emit explicit warnings or validation errors instead of `del ...`.
- Update tests to assert current supported behavior only.

Acceptance criteria:
- Public service signatures match live behavior.
- Dead migration shims are deleted or explicitly deprecated.

## Phase 3: Planner Policy Consistency

Priority: `P2`
Target outcome: policy reads, writes, and scope metadata all agree with one another.

### Slice 3.1: Decide supported policy scope model

Files:
- planner policy services under [app/services/domain](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain)
- planner policy models under [app/models/domain](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain)

Tasks:
- Decide which scopes are actually supported now:
  - global
  - workspace
  - vertical
  - base-domain
- Document unsupported scope combinations and remove them from request models if necessary.

Acceptance criteria:
- Request schemas, persistence logic, and lookup filters all support the same scope model.

### Slice 3.2: Implement or remove vertical/base-domain scoping

Initial target files:
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py)
- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py)
- [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py)

Tasks:
- Wire `scope_vertical_norm` through upsert, lookup, and duplicate detection.
- For projection policy, also decide whether `scope_base_domain_id` is real or should be removed.
- Add round-trip tests proving policy persistence and lookup by scope.

Acceptance criteria:
- Persisted scoped policies can be read back and affect only the intended scope.
- The response payload no longer claims unsupported scope filtering.

### Slice 3.3: Add actor attribution or remove fake audit parameters

Files:
- planner policy write/delete services
- any admin policy routes or audit sinks

Tasks:
- Decide whether policy changes require actor attribution.
- If yes, persist actor information in an audit/event table or structured log.
- If not, remove `actor_user_id` from the service interface.

Acceptance criteria:
- The API no longer implies audit coverage it does not provide.

## Phase 4: Degraded-Mode And Runtime Hygiene

Priority: `P2-P3`
Target outcome: fallback modes behave predictably and runtime warnings stop accumulating.

### Slice 4.1: Bound minimal-chat in-memory fallback

Files:
- [minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/minimal_chat_service.py)

Tasks:
- Store expiry metadata alongside in-memory values.
- Evict expired entries on read/list.
- Consider maximum key count and basic LRU-style trimming.
- Document the difference between Valkey-backed and in-memory behavior.

Acceptance criteria:
- TTL is honored in fallback mode.
- In-memory growth is bounded and test-covered.

### Slice 4.2: Normalize TTL semantics across conversation stores

Files:
- [minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/minimal_chat_service.py)
- [forge_insights_conversation_store.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/forge_insights_conversation_store.py)

Tasks:
- Decide whether `qf_ttl_seconds` is meaningful for MySQL-backed stores.
- If not, remove it from the interface and callers.
- If yes, implement retention semantics consistently.

Acceptance criteria:
- Conversation-store interfaces do not carry dead TTL parameters.

### Slice 4.3: Remove current runtime deprecation warnings

Files:
- [execution_status_helpers.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/execution/execution_status_helpers.py)

Tasks:
- Replace `datetime.utcnow()` with timezone-aware UTC handling.
- Sweep for other currently emitted warnings if they are local and actionable.

Acceptance criteria:
- Existing backend deprecation warning from this helper is gone.

## Phase 5: Broad Dead-Code And Structural Cleanup

Priority: `P3`
Target outcome: reduce future maintenance drag once behavior is correct.

Implementation note:
- The review-response work completed Slice 5.1 in full and removed the concrete dead-contract surfaces identified during review.
- Slice 5.2 remains a follow-on refactor backlog item rather than a blocker for closing the review findings.
- The concrete ranked backlog for Slice 5.2 now lives in [2026-04-11-backend-decomposition-plan.md](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/docs/plans/2026-04-11-backend-decomposition-plan.md).

### Slice 5.1: Unused-argument cleanup sweep

Evidence:
- `ruff check query-forge-api/app --select ARG001,ARG002,F841` currently reports 41 findings.

Tasks:
- Triage all unused-argument findings into:
  - real dead contracts to remove
  - interface requirements to document
  - deliberate placeholder hooks
- Prefer deleting misleading parameters over keeping them with `del ...`.

Acceptance criteria:
- Unused-argument count is materially reduced.
- Remaining ignored parameters are deliberate and documented.

### Slice 5.2: Large-file decomposition follow-up

Initial candidates:
- [semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_suggestion_service.py)
- [tenancy_admin_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/tenancy/tenancy_admin_service.py)
- [semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_concept_service.py)
- [semantic_retrieval_helpers.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_retrieval_helpers.py)
- [planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_signal_policy_service.py)

Tasks:
- Split multi-responsibility files by runtime concern, not by arbitrary size.
- Preserve behavior with focused test coverage before and after extraction.

Acceptance criteria:
- High-risk services become easier to reason about and test.
- No new compatibility shims are introduced just to move code around.

## Suggested Execution Order

1. Phase 1.1 secret scrubbing
2. Phase 1.2 SMTP env fix
3. Phase 1.3 broker health semantics
4. Phase 2.1 workspace inventory freshness
5. Phase 2.2 analytics executor adapter contract cleanup
6. Phase 3.1 scope-model decision
7. Phase 3.2 scoped policy implementation/removal
8. Phase 3.3 actor attribution decision
9. Phase 4.1 minimal-chat fallback TTL
10. Phase 4.2 conversation-store TTL normalization
11. Phase 4.3 runtime deprecation cleanup
12. Phase 5.1 unused-argument sweep
13. Phase 5.2 large-file decomposition

## Recommended Working Style

- Treat each slice as a small branch-sized change even if it stays uncommitted locally.
- Run targeted unit tests after every slice.
- After each phase, run `pytest -q` to catch contract drift across services.
- Update the review findings note when a finding is resolved so the plan stays live.

## Deliverables

- Code fixes for each slice
- Targeted regression tests
- Updated docs where public contracts change
- A final resolved-findings checklist added back to the source review note
