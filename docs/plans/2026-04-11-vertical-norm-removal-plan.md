# Vertical Norm Removal Plan

## Goal

Remove `vertical_norm` from planner policy scoping and move to the four-scope model:

- `global`
- `workspace`
- `global_domain`
- `workspace_domain`

This matches the product decision that a customer belongs to one vertical, so planner behavior should be driven by customer-specific policy data and semantic registry content rather than a separate vertical axis.

## Decision

### Supported planner policy scopes

Keep:

- `global`
- `workspace`
- `global_domain`
- `workspace_domain`

Remove:

- `vertical`
- `vertical_domain`

### Scope semantics

- `global`: shared across all workspaces
- `workspace`: customer-specific, applies across all domains in one workspace
- `global_domain`: shared across all workspaces for one domain profile/template
- `workspace_domain`: customer-specific, applies to one domain in one workspace

## Important boundary

This is two related changes, not one:

1. Planner policy scope cleanup
2. Semantic registry flattening

The planner policy cleanup is straightforward and should happen first.

The semantic registry cleanup is broader because `vertical_norm` is still used in:

- semantic concepts
- aliases
- concept-column maps
- relationships
- value aliases
- semantic catalog build/read paths
- semantic plan services

The correct execution order is:

1. remove `vertical_norm` from planner policy scope
2. stabilize planner behavior
3. then flatten semantic registry usage

## Current state

### Planner policies still use vertical scope

Backend scope constants still allow vertical-based scopes in [policy_scope_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/policy_scope_service.py).

Current definitions:

- [policy_scope_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/policy_scope_service.py#L8)
- [policy_scope_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/policy_scope_service.py#L9)
- [policy_scope_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/policy_scope_service.py#L43)
- [policy_scope_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/policy_scope_service.py#L74)

Planner policy routes still take `vertical_norm` query params:

- [planner_policy_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/admin/planner_policy_routes.py#L40)

Domain-scoped planner services still use vertical-based lookup precedence:

- [planner_domain_capability_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_capability_service.py#L36)
- [planner_rerank_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_service.py#L39)
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py)

The frontend Planner Policies page still exposes `verticalNorm` as a page-level state and API filter:

- [usePlannerPoliciesPageState.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/plannerPolicies/usePlannerPoliciesPageState.ts#L100)
- [usePlannerPoliciesPageState.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/plannerPolicies/usePlannerPoliciesPageState.ts#L195)
- [PlannerPoliciesPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/PlannerPoliciesPage.tsx#L158)
- [useDomainPlannerPolicies.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/hooks/useDomainPlannerPolicies.ts)

### Domain vector lookup already stopped using vertical

The domain vector path already ignores `vertical_norm` for effective lookup and keeps it only for compatibility:

- [memory.md](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/memory.md#L160)

### Semantic registry still uses vertical

This is still real behavior, not dead code:

- [semantic_registry_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_registry_service.py#L72)
- [concept_to_column_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/concept_to_column_service.py#L20)
- [semantic/plan/service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/service.py#L150)

## Migration rules

### Scope type mapping

Planner policy rows should be rewritten as follows:

- `vertical` -> `global`
- `vertical_domain` -> `global_domain`
- `workspace` -> `workspace`
- `workspace_domain` -> `workspace_domain`
- `global` -> `global`
- `global_domain` -> `global_domain`

### `scope_vertical_norm`

After migration:

- planner policy rows should no longer rely on `scope_vertical_norm`
- all planner policy writes should persist `NULL` there during the transition
- the column should be dropped after all readers/writers stop referencing it

### Request parameters

Remove `vertical_norm` from planner policy list and write APIs.

### UI state

Remove `verticalNorm` from:

- URL search params
- list queries
- create/update payload construction
- candidate suggestion payloads
- coverage calculations

## Phase 1: Freeze the new scope contract

### Backend

Update scope helpers in [policy_scope_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/policy_scope_service.py):

- replace `GLOBAL_VERTICAL_WORKSPACE_SCOPE_TYPES`
- replace `FULL_POLICY_SCOPE_TYPES`
- remove vertical branches from `scoped_policy_rank()`
- remove vertical branches from `scoped_query_predicate()`

New scope constants should be:

- global/workspace-only families:
  - `{"global", "workspace"}`
- domain-aware families:
  - `{"global", "workspace", "global_domain", "workspace_domain"}`

### Frontend

Update [constants.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/plannerPolicies/constants.ts):

- remove `vertical`
- remove `vertical_domain`
- keep only the four supported options on domain-scoped forms

### Acceptance criteria

- no planner policy form offers vertical-based scope choices
- shared backend scope helpers no longer admit vertical-based scopes

## Phase 2: Backend planner policy service cleanup

### Affected policy families

Domain-scoped:

- planner domain capabilities
- planner rerank policies
- planner projection policies

Cross-domain:

- signal policies
- prompt intent policies
- retrieval policies
- domain selection policies

### Required service changes

For domain-scoped services:

- remove `vertical_norm` from list/read method signatures
- remove `scope_vertical_norm` from lookup SQL
- remove vertical-specific precedence and ranking
- preserve precedence as:
  - `workspace_domain`
  - `workspace`
  - `global_domain`
  - `global`

For cross-domain services:

- keep only `workspace` and `global`
- remove any vertical validators and dedupe conditions using `scope_vertical_norm`

### Affected files

At minimum:

- [planner_domain_capability_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_capability_service.py)
- [planner_rerank_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_service.py)
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py)
- [planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_signal_policy_service.py)
- [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py)
- [planner_retrieval_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_retrieval_policy_service.py)
- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py)

### Acceptance criteria

- planner policy list endpoints do not require or accept `vertical_norm`
- planner policy service ranking uses only the four scopes
- no planner policy service reads `scope_vertical_norm` for effective behavior

## Phase 3: Model and schema cleanup

### Pydantic / ORM models

Remove `scope_vertical_norm` from planner policy request/record models where it is part of the public contract.

At minimum:

- [planner_domain_selection_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_domain_selection_policy.py)
- [planner_prompt_intent_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_prompt_intent_policy.py)
- planner domain capability / rerank / projection models
- any shared planner policy record schemas

### Database migration

For each planner policy table:

1. rewrite `vertical` rows to `global`
2. rewrite `vertical_domain` rows to `global_domain`
3. null out `scope_vertical_norm`
4. rebuild unique constraints and indexes without `scope_vertical_norm`
5. drop `scope_vertical_norm`

### Tables likely affected

- `planner_domain_capability`
- `planner_rerank_policy`
- `planner_projection_policy`
- `planner_signal_policy`
- `planner_prompt_intent_policy`
- `planner_retrieval_policy`
- `planner_domain_selection_policy`

### Migration safeguards

Before dropping columns:

- run an audit query for any rows where `scope_type IN ('vertical', 'vertical_domain')`
- snapshot row counts by table and scope type
- detect duplicate collisions after remapping, especially where multiple former vertical rows collapse into one global key

### Acceptance criteria

- planner policy tables contain no `vertical` or `vertical_domain` rows
- planner policy tables no longer include `scope_vertical_norm`
- ORM and request schemas match the database

## Phase 4: Route and frontend cleanup

### Backend routes

Remove `vertical_norm` from planner policy route parsing:

- [planner_policy_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/admin/planner_policy_routes.py)

### Frontend

Update:

- [usePlannerPoliciesPageState.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/plannerPolicies/usePlannerPoliciesPageState.ts)
- [useDomainPlannerPolicies.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/hooks/useDomainPlannerPolicies.ts)
- [PlannerPoliciesPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/PlannerPoliciesPage.tsx)
- [PlannerPoliciesDrawerForms.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/plannerPolicies/components/PlannerPoliciesDrawerForms.tsx)
- planner policy types/forms/constants

### UI behavior after cleanup

Domain-scoped policies:

- domain picker present
- scope selector offers:
  - `workspace_domain`
  - `workspace`
  - `global_domain`
  - `global`

Cross-domain policies:

- no domain picker
- scope selector offers:
  - `workspace`
  - `global`

No planner-policy page control should mention vertical.

### Acceptance criteria

- Planner Policies page has no vertical input or vertical URL param
- API calls no longer send `vertical_norm`
- policy tables and coverage summaries still render correctly

## Phase 5: Candidate and seed cleanup

### Candidate flow

Remove `vertical_norm` from:

- candidate creation
- candidate suggestion
- candidate approval promotion

Candidate approval should continue promoting to `workspace_domain` unless explicitly changed.

### Seed data

Seeded planner policies currently include `scope_vertical_norm: None` in many service defaults. Normalize those payloads so the field disappears entirely after schema cleanup.

### Acceptance criteria

- candidate APIs no longer persist planner vertical data
- seeded rows use only the four supported scopes

## Phase 6: Semantic registry flattening

This is the larger follow-on. Do not mix it into the initial planner policy scope cleanup unless necessary.

### Current problem

The semantic layer still uses `vertical_norm` as a real partition key:

- registry list/read
- concept retrieval
- concept-to-column mapping
- value alias application
- relationships
- semantic catalog build/read
- semantic suggestion generation
- semantic plan service

### Recommended direction

For customer-specific semantics, use workspace/domain ownership rather than vertical partitioning.

Two viable models:

1. Minimal compatibility model
   - keep semantic tables as-is
   - normalize all customer data to `generic`
   - remove vertical from UI and request surfaces
   - treat the column as internal compatibility residue until a later migration

2. Full flattening model
   - introduce explicit workspace/global ownership for semantic artifacts
   - migrate data off `vertical_norm`
   - remove the column from semantic tables and services

### Recommendation

Do model 1 first unless there is a strong need for immediate schema simplification. It gives the product behavior you want without forcing a large semantic-data migration into the planner policy cleanup.

## Execution order

1. Phase 1: scope constant cleanup
2. Phase 2: planner policy service cleanup
3. Phase 3: planner policy schema migration
4. Phase 4: planner policy UI and route cleanup
5. Phase 5: candidate and seed cleanup
6. Full backend and frontend regression run
7. Phase 6 later: semantic registry flattening

## Verification plan

### Targeted backend tests

- planner policy service tests
- admin planner policy route tests
- candidate approval/suggestion tests

### Targeted frontend tests

- [PlannerPoliciesPage.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/PlannerPoliciesPage.test.tsx)
- [PlannerPoliciesRoute.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/PlannerPoliciesRoute.test.tsx)

### Phase gate

At the end of the planner-policy cleanup:

- backend: `pytest -q`
- frontend: `npx vitest run`

## Recommended first implementation slice

Start with Phase 1 plus the domain-scoped planner policy families only:

- capabilities
- rerank policies
- projection policies

That is the smallest slice that proves the four-scope model end to end without immediately touching the cross-domain families or semantic registry.

## Progress

### 2026-04-11 - Phase 1 complete

Completed:

- planner policy scope helpers now admit only:
  - `global`
  - `workspace`
  - `global_domain`
  - `workspace_domain`
- vertical-based scope options were removed from the frontend planner policy forms
- planner prompt-intent and domain-selection contract validators now reject vertical scope types
- planner projection upsert validation now rejects vertical and vertical-domain scopes
- the TypeScript planner-policy scope union now matches the four-scope contract

Code references:

- [policy_scope_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/policy_scope_service.py)
- [planner_rerank_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_rerank_policy.py)
- [planner_projection_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_projection_policy.py)
- [planner_domain_selection_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_domain_selection_policy.py)
- [planner_prompt_intent_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_prompt_intent_policy.py)
- [constants.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/plannerPolicies/constants.ts)
- [domainPlannerPolicy.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/types/domainPlannerPolicy.ts)

Focused verification completed before the full phase gate:

- backend planner-policy slice: `71 passed`
- frontend planner-policy slice: `34 passed`

Full phase gate:

- backend: `pytest -q` -> `2658 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `655 passed | 3 todo`

### 2026-04-11 - Phase 2 complete

Completed:

- removed vertical-based runtime lookup from domain-scoped planner policy services
- removed vertical-based runtime lookup from cross-domain planner policy services
- updated service precedence to:
  - `workspace_domain`
  - `workspace`
  - `global_domain`
  - `global`
- forced planner policy service writes to persist `scope_vertical_norm = NULL` during the compatibility period
- kept route/request compatibility for `vertical_norm` inputs, but services now ignore that input for effective policy resolution

Code references:

- [planner_rerank_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_service.py)
- [planner_domain_capability_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_capability_service.py)
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py)
- [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py)
- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py)
- [planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_signal_policy_service.py)
- [planner_retrieval_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_retrieval_policy_service.py)

Focused verification completed before the full phase gate:

- planner policy service slice: `71 passed`
- planner admin route slice: `15 passed`

Full phase gate:

- backend: `pytest -q` -> `2658 passed, 78 skipped`

Notes:

- the first full backend run exposed a stale internal call path in
  [planner_domain_capability_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_capability_service.py)
  plus one leftover planner-domain test that still asserted retired `vertical` scope behavior
- both were corrected before the final full-suite gate passed

### 2026-04-11 - Phase 3 complete

Completed:

- removed `scope_vertical_norm` from the live planner policy upsert/approval request models
- removed `scope_vertical_norm` from the ORM definitions and scope indexes for:
  - planner domain capabilities
  - planner rerank policies
  - planner projection policies
  - planner signal policies
  - planner prompt intent policies
  - planner retrieval policies
  - planner domain selection policies
- removed raw SQL reads and writes of `scope_vertical_norm` from the live planner policy services
- updated the admin request models so the field no longer appears in the documented write contract
- added the database migration to rewrite retired scope rows, rebuild indexes, and drop the column from the live planner policy tables
- tightened the write models to reject removed fields rather than silently tolerating them

Code references:

- [planner_rerank_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_rerank_policy.py)
- [planner_projection_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_projection_policy.py)
- [planner_signal_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_signal_policy.py)
- [planner_prompt_intent_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_prompt_intent_policy.py)
- [planner_retrieval_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_retrieval_policy.py)
- [planner_domain_selection_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_domain_selection_policy.py)
- [planner_rerank_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_service.py)
- [planner_domain_capability_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_capability_service.py)
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py)
- [planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_signal_policy_service.py)
- [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py)
- [planner_retrieval_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_retrieval_policy_service.py)
- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py)
- [models.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/admin/models.py)
- [20260411_drop_vertical_norm_from_planner_policies.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260411_drop_vertical_norm_from_planner_policies.sql)

Focused verification completed before the full phase gate:

- planner policy and admin route slice: `94 passed`

Full phase gate:

- backend: `pytest -q` -> `2658 passed, 78 skipped`

### 2026-04-12 - Phase 4 complete

Completed:

- removed planner-policy route parsing for `vertical_norm` from the live backend domain and admin surfaces
- removed `verticalNorm` from the Planner Policies page URL state, query flow, and mutation payload construction
- removed the Planner Policies page vertical input and updated the domain/cross-domain copy so the page only describes the four-scope model
- removed planner-policy API request params for `vertical_norm` on:
  - domain capabilities
  - rerank policy list
  - projection policy list
  - candidate list
- removed stale `scope_vertical_norm` and vertical request fields from the frontend planner-policy types and approval/suggestion flows
- updated the planner-policy route tests and frontend planner-policy regression tests to match the four-scope public contract

Code references:

- [planner_policy_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/admin/planner_policy_routes.py)
- [domain_planner_api.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/features/domains/domain_planner_api.py)
- [test_domain_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/routes/test_domain_routes.py)
- [usePlannerPoliciesPageState.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/plannerPolicies/usePlannerPoliciesPageState.ts)
- [useDomainPlannerPolicies.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/hooks/useDomainPlannerPolicies.ts)
- [domainPlannerPolicies.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/api/domainPlannerPolicies.ts)
- [domainPlannerPolicy.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/types/domainPlannerPolicy.ts)
- [PlannerPoliciesPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/PlannerPoliciesPage.tsx)
- [PlannerPoliciesDrawerForms.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/plannerPolicies/components/PlannerPoliciesDrawerForms.tsx)
- [PlannerPoliciesPage.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/PlannerPoliciesPage.test.tsx)
- [domainPlannerPolicies.test.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/api/domainPlannerPolicies.test.ts)

Focused verification completed before the full phase gate:

- backend planner-route slice: `15 passed, 14 skipped`
- frontend planner-policy slice: `34 passed`

Full phase gate:

- backend: `pytest -q` -> `2658 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `655 passed | 3 todo`

### 2026-04-12 - Phase 5 complete

Completed:

- removed `vertical_norm` from the live planner rerank candidate create and suggest request models
- removed candidate list filtering and public response fields for planner vertical data
- changed candidate create/update persistence to write `vertical_norm = NULL`
- added a data migration to null existing planner rerank candidate vertical values
- removed stale `scope_vertical_norm: None` keys from the seeded planner policy defaults that still exposed them in the public planner-policy services

Code references:

- [planner_rerank_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_rerank_policy.py)
- [planner_rerank_policy_candidate_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_candidate_service.py)
- [planner_rerank_policy_candidate_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_candidate_suggestion_service.py)
- [planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_signal_policy_service.py)
- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py)
- [planner_retrieval_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_retrieval_policy_service.py)
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py)
- [20260412_clear_vertical_norm_from_planner_rerank_policy_candidate.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260412_clear_vertical_norm_from_planner_rerank_policy_candidate.sql)
- [domainPlannerPolicy.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/types/domainPlannerPolicy.ts)
- [domainPlannerPolicies.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/api/domainPlannerPolicies.ts)

Focused verification completed before the full phase gate:

- backend candidate slice: `16 passed, 7 skipped`
- frontend planner-policy slice: `34 passed`

Full phase gate:

- backend: `pytest -q` -> `2659 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `655 passed | 3 todo`

### 2026-04-13 - Semantic public-contract cleanup slice complete

Completed:

- removed `vertical_norm` from the public semantic planner request model on `/semantic/plan`
- removed `vertical` from the public planner-LLM request model on `/planner/plan_llm`
- removed the semantic planner UI/client `vertical` request field so planner requests now rely on the generic semantic partition implicitly
- removed `vertical` from the public semantic suggestion run contract and stopped persisting caller-supplied run verticals on create
- stripped `vertical` and `vertical_norm` from semantic CRUD, registry, relationship, and suggestion-run route responses so the semantic-admin API no longer exposes those compatibility fields
- stripped stray runtime `vertical` query params from the concept-column-map client helper so the frontend semantic client layer matches the backend contract

Code references:

- [semantic_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_routes.py)
- [planner_llm_api.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/features/planner/planner_llm_api.py)
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_llm/service.py)
- [semantic_suggestions.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_suggestions.py)
- [semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_suggestion_service.py)
- [semantic_concepts.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_concepts.py)
- [semantic_relationships.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_relationships.py)
- [semantic_registry.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_registry.py)
- [planner.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/planner.ts)
- [PlannerPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/PlannerPage.tsx)
- [conceptColumnMaps.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/conceptColumnMaps.ts)

Focused verification completed before the full phase gate:

- backend semantic public-contract slice: `25 passed`
- frontend semantic public-contract slice: `35 passed`

Full phase gate:

- backend: `pytest -q` -> `2688 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-13 - Semantic CRUD and registry contract cleanup slice complete

Completed:

- removed the remaining semantic `vertical` and `vertical_norm` request/response contract from the direct semantic CRUD routes:
  - semantic concepts
  - concept aliases
  - value aliases
  - concept-column maps
  - semantic relationships
  - semantic registry
- removed the compatibility route shims that were still passing synthetic `generic` vertical values into the direct semantic services
- removed the last direct semantic service method parameters that only existed to accept ignored vertical values:
  - concept list/key/alias/value-alias/concept-column-map reads
  - primary-key backfill
  - seed
  - semantic relationship list and lookup
  - semantic registry list
- removed semantic vertical from the shared frontend CRUD clients for relationships and locked those clients to the real supported query params only
- updated the semantic admin UI regression coverage so create/edit/rebuild flows now assert the actual no-vertical payloads instead of the old compatibility fields

Code references:

- [semantic_concepts.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_concepts.py)
- [semantic_relationships.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_relationships.py)
- [semantic_registry.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_registry.py)
- [semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_concept_service.py)
- [semantic_relationship_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_relationship_service.py)
- [semantic_registry_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_registry_service.py)
- [relationships.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/relationships.ts)
- [semanticServices.test.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/__tests__/semanticServices.test.ts)
- [AliasesPage.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/__tests__/AliasesPage.test.tsx)
- [ConceptsPage.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/__tests__/ConceptsPage.test.tsx)
- [ValueAliasesPage.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/__tests__/ValueAliasesPage.test.tsx)
- [ConceptColumnMapsPage.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/__tests__/ConceptColumnMapsPage.test.tsx)

Focused verification completed before the full phase gate:

- backend semantic CRUD/route slice: `60 passed`
- frontend semantic CRUD/admin slice: `53 passed`

Open follow-on after this slice:

- semantic planner and suggestion contracts still carry vertical input deeper in the semantic core and planner-LLM surfaces; those should be flattened in a separate follow-on if the goal is total semantic vertical removal beyond CRUD/registry behavior

### 2026-04-12 - Semantic catalog normalization slice complete

Completed:

- normalized semantic catalog repository reads to route legacy and omitted vertical inputs through the shared generic compatibility rule
- normalized semantic catalog builder vertical handling so catalog-build flows use the same semantic vertical helper as the rest of the stack
- normalized semantic-registry backfill mapping from semantic concept ids so catalog-generated registry rows collapse legacy verticals onto `generic`
- added focused regression coverage for concept reads, alias reads, and catalog-builder normalization behavior

Code references:

- [semantic_catalog_repository.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/catalog/semantic_catalog_repository.py)
- [semantic_catalog_builder.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/catalog/semantic_catalog_builder.py)
- [test_semantic_catalog_repository.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_catalog_repository.py)
- [test_semantic_catalog_builder_pipeline.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_catalog_builder_pipeline.py)

Focused verification completed before the full phase gate:

- backend semantic catalog repository slice: `4 passed`
- backend semantic catalog builder slice: `8 passed`

Full phase gate:

- backend: `pytest -q` -> `2680 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-13 - Semantic catalog contract normalization slice complete

Completed:

- normalized semantic catalog build request parsing through the shared semantic vertical helper instead of a local lowercase-only rule
- changed semantic catalog upsert/result Pydantic models so `vertical_norm` defaults to `generic` and normalizes legacy compatibility values on model construction
- added regression coverage proving the catalog payload models no longer require explicit `vertical_norm` to land in the generic compatibility set
- added an end-to-end admin route regression proving a legacy `education` semantic-catalog build request is normalized to `generic` before the builder sees it

Code references:

- [semantic_catalog_admin.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/semantic/semantic_catalog_admin.py)
- [catalog_models.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/catalog/catalog_models.py)
- [test_semantic_catalog_builder_pipeline.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_catalog_builder_pipeline.py)
- [test_admin_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/routes/test_admin_routes.py)

Focused verification completed before the full phase gate:

- backend semantic catalog model slice: `9 passed`
- backend semantic catalog route slice: `4 passed`

Full phase gate:

- backend: `pytest -q` -> `2682 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-13 - Direct semantic storage normalization slice complete

Completed:

- added a dedicated semantic storage normalization service for the direct semantic tables so legacy compatibility rows can be audited and collapsed into `generic` without touching the semantic registry graph yet
- added a matching production migration that de-duplicates legacy direct-table rows, drops rows that would collide with an existing generic row, and then updates the survivors into the generic compatibility set
- kept this slice intentionally scoped to:
  - `semantic_concept`
  - `semantic_concept_alias`
  - `workspace_column_semantic_concept_map`
  - `semantic_value_alias`
- left `semantic_registry`, `semantic_column_map`, and `semantic_relationship` for the next phase because they require ID-preserving remap logic across graph edges and column-map foreign keys

Code references:

- [semantic_storage_normalization_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_storage_normalization_service.py)
- [20260413_normalize_direct_semantic_verticals.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260413_normalize_direct_semantic_verticals.sql)
- [test_semantic_storage_normalization_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_storage_normalization_service.py)
- [test_semantic_catalog_builder_pipeline.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_catalog_builder_pipeline.py)
- [test_semantic_catalog_repository.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_catalog_repository.py)

Focused verification completed before the full phase gate:

- backend semantic storage normalization service slice: `3 passed`
- backend adjacent semantic catalog slice: `13 passed`

Full phase gate:

- backend: `pytest -q` -> `2685 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-13 - Semantic registry graph normalization slice complete

Completed:

- added a dedicated semantic registry graph normalization service that audits and collapses legacy registry rows into the generic compatibility set while preserving dependent graph integrity
- added the matching production migration that:
  - builds an old-id to new-id remap table
  - promotes surviving keeper rows to `vertical = 'generic'`
  - de-duplicates conflicting `semantic_column_map` rows before remapping foreign keys
  - drops collapsing/self-referential `semantic_relationship` rows, de-duplicates remapped edges, and then updates parent/child foreign keys
  - deletes superseded legacy `semantic_registry` rows after dependent references have been moved
- kept this slice intentionally bounded to:
  - `semantic_registry`
  - `semantic_column_map`
  - `semantic_relationship`
- left follow-on cleanup such as physical schema simplification or route/admin execution surfaces for a later phase

Code references:

- [semantic_registry_graph_normalization_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_registry_graph_normalization_service.py)
- [20260413_normalize_semantic_registry_graph_verticals.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260413_normalize_semantic_registry_graph_verticals.sql)
- [test_semantic_registry_graph_normalization_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_registry_graph_normalization_service.py)
- [test_semantic_registry_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_registry_service.py)
- [test_semantic_relationship_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_relationship_service.py)

Focused verification completed before the full phase gate:

- backend semantic registry graph normalization service slice: `3 passed`
- backend adjacent registry/relationship slice: `24 passed`

Full phase gate:

- backend: `pytest -q` -> `2688 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-12 - Semantic matcher and seed flattening slice complete

Completed:

- collapsed semantic concept seed normalization so omitted, `global`, and legacy `education` vertical input all resolve to `generic`
- merged the old education compatibility seed set into the generic compatibility set so the semantic core keeps the prior school and student language without a separate vertical axis
- changed semantic concept matcher vertical normalization so legacy `education` lookups resolve to `generic`
- removed the matcher's runtime dependency on `vertical == "education"` for school, student, course, and geography heuristic matches
- updated the age-extreme planner golden to the new generic semantic behavior under the test suite's `PLANNER_UNIFIED_LLM=False` regression mode
- fixed auth route test isolation exposed by the full backend gate by stubbing login rate limiting in the remaining unisolated `/login` and `/auth` route tests

Code references:

- [concept_seed.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/concept_seed.py)
- [semantic_concept_matcher.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_concept_matcher.py)
- [test_semantic_canonical_mapping.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/semantic/test_semantic_canonical_mapping.py)
- [test_semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_concept_service.py)
- [age_extreme.json](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner_domain/golden/age_extreme.json)
- [test_auth_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/routes/test_auth_routes.py)

Focused verification completed before the full phase gate:

- backend matcher/seed slice: `15 passed`
- backend semantic concept service slice: `16 passed`
- backend age-extreme golden slice: `1 passed, 8 deselected`
- backend auth route slice: `16 passed`

Full phase gate:

- backend: `pytest -q` -> `2675 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-12 - Planner-facing semantic path cleanup slice complete

Completed:

- added a shared semantic vertical normalizer so planner-facing services collapse legacy `education`, `global`, `__global__`, and missing values into the generic compatibility partition
- normalized planner semantic catalog lookup reads so concept, alias, relationship, concept-column-map, and value-alias lookup all execute against `generic` for legacy planner inputs
- normalized semantic retrieval, semantic grounding, semantic plan request parsing, semantic plan compilation metadata, planner prompt payload building, concept vector lookup, and value-alias application to the same generic compatibility rule
- added regression coverage proving that planner retrieval, grounding, concept vector search, plan execution, and value-alias application all receive `generic` when callers still send `education`

Code references:

- [vertical_norm.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/vertical_norm.py)
- [semantic_catalog_lookup_repository.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_catalog_lookup_repository.py)
- [semantic_retrieval_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_retrieval_service.py)
- [semantic_grounding_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_grounding_service.py)
- [concept_retrieval_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/concept_retrieval_service.py)
- [models.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/models.py)
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/service.py)
- [value_alias_applier.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/value_alias_applier.py)
- [semantic_plan_compiler.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_plan_compiler.py)
- [planner_prompt_builder.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/planner_prompt_builder.py)

Focused verification completed before the full phase gate:

- backend planner semantic retrieval slice: `13 passed`
- backend planner grounding slice: `3 passed`
- backend semantic plan/concept retrieval slice: `33 passed`

Full phase gate:

- backend: `pytest -q` -> `2677 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-12 - Semantic storage service normalization slice complete

Completed:

- collapsed semantic registry vertical normalization onto the shared generic compatibility rule so create/list flows now treat legacy `education`, `global`, and missing values as `generic`
- collapsed semantic concept CRUD, alias CRUD, value-alias CRUD, concept-column-map CRUD, and backfill vertical parsing onto the same shared normalizer
- normalized concept-to-column mapping and semantic value-alias resolution so planner-adjacent storage lookups no longer preserve a separate legacy `education` branch
- kept stored historical rows readable, but changed live request/write normalization so the service contract now converges on `generic` instead of continuing to emit legacy planner-specific verticals

Code references:

- [semantic_registry_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_registry_service.py)
- [semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_concept_service.py)
- [concept_to_column_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/concept_to_column_service.py)
- [value_alias_resolution_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/value_alias_resolution_service.py)
- [vertical_norm.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/vertical_norm.py)

Focused verification completed before the full phase gate:

- backend semantic registry slice: `11 passed`
- backend semantic concept slice: `16 passed`
- backend semantic relationship/concept-to-column/value-alias slice: `19 passed`

Full phase gate:

- backend: `pytest -q` -> `2677 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-12 - Semantic service defaulting slice complete

Completed:

- moved the `generic` defaulting rule for semantic reads down into the semantic concept and semantic relationship services instead of relying only on route wrappers
- changed concept, concept-key, alias, value-alias, and concept-column-map service reads to treat missing vertical input as `generic`
- changed semantic relationship list and semantic relationship concept-lookup service reads to treat missing vertical input as `generic`
- made the shared frontend concept-alias mutation schema default `vertical_norm` to `generic` when callers omit it
- simplified the shared frontend concept-alias list params so the live UI contract no longer advertises a vertical filter for aliases

Code references:

- [semantic_concept_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_concept_service.py)
- [semantic_relationship_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_relationship_service.py)
- [schemas.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/schemas.ts)
- [conceptAliases.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/conceptAliases.ts)

Focused verification completed before the full phase gate:

- backend semantic service slice: `27 passed`
- frontend shared semantic slice: `39 passed`

Full phase gate:

- backend: `pytest -q` -> `2663 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-12 - Registry and core lookup defaulting slice complete

Completed:

- changed semantic registry reads to default missing vertical input to `generic` instead of leaving the registry unfiltered
- changed semantic registry create normalization so new entries default to `generic` when callers omit vertical
- changed concept-to-column mapping to accept omitted `vertical_norm` and normalize it to `generic` internally
- updated the semantic registry route model description so the public contract reflects the compatibility-default behavior instead of implying null/global as the normal path

Code references:

- [semantic_registry_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_registry_service.py)
- [concept_to_column_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/concept_to_column_service.py)
- [semantic_registry.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_registry.py)

Focused verification completed before the full phase gate:

- backend registry/core lookup slice: `16 passed`

Full phase gate:

- backend: `pytest -q` -> `2666 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-12 - Semantic suggestion run normalization slice complete

Completed:

- normalized semantic suggestion run creation so omitted or explicit `global` vertical input now persists as `generic`
- changed semantic suggestion execution to resolve matcher lookups against `generic` when a run has missing/global vertical input
- changed semantic suggestion concept-id lookup to normalize global/missing vertical input to `generic`
- changed semantic registry upsert from approved suggestion items to persist `generic` instead of treating global as a null/special partition
- changed semantic column-semantic assignment writes from approved suggestion items to persist `generic` for the mapping vertical when the run omits vertical
- added regression coverage for run creation normalization, matcher normalization during execute, concept-id lookup normalization, and registry/assignment normalization during apply

Code references:

- [semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_suggestion_service.py)
- [test_semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_suggestion_service.py)

Focused verification completed before the full phase gate:

- backend semantic suggestion slice: `31 passed`

Full phase gate:

- backend: `pytest -q` -> `2670 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `656 passed | 3 todo`

### 2026-04-12 - Semantic registry follow-on slice complete

Completed:

- removed the last visible vertical controls from the semantic aliases page and semantic planner debug page
- changed the semantic aliases page to create new aliases in the generic compatibility set by default
- changed the semantic planner UI and shared planner client default from `education` to `generic`
- changed semantic concept, alias, value-alias, concept-column-map, semantic-registry, and semantic-relationship read routes to default to `generic` when no vertical is supplied
- kept the hidden vertical query/input path available only as a compatibility override for older edit/data paths
- updated the semantic help copy so the setup guidance no longer tells admins to manage a vertical field in the UI

Code references:

- [semantic_concepts.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_concepts.py)
- [semantic_registry.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_registry.py)
- [semantic_relationships.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_relationships.py)
- [AliasesPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/AliasesPage.tsx)
- [PlannerPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/PlannerPage.tsx)
- [planner.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/planner.ts)
- [SemanticHelpPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/SemanticHelpPage.tsx)

Focused verification completed before the full phase gate:

- backend semantic route slice: `20 passed`
- frontend semantic admin slice: `12 passed`

Full phase gate:

- backend: `pytest -q` -> `2659 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `655 passed | 3 todo`

### 2026-04-12 - Phase 6 complete

Completed:

- removed vertical inputs from the user-facing semantic admin pages:
  - concepts
  - concept-column maps
  - value aliases
  - relationships
  - semantic catalog builder
- removed vertical from semantic admin URL/query state where it was only a UI-controlled filter
- defaulted new semantic concept, concept-column map, and value-alias create flows to the generic compatibility set instead of prompting for vertical
- normalized semantic catalog build requests to always use `generic` without exposing a vertical field in the UI contract
- updated semantic concept seed to default to `generic` when no vertical is supplied
- relaxed the public semantic route models so `vertical_norm` is no longer required on the semantic CRUD create surfaces
- kept the underlying semantic tables and services intact as the compatibility layer for now

Code references:

- [semantic_concepts.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_concepts.py)
- [ConceptsPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/ConceptsPage.tsx)
- [ConceptColumnMapsPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/ConceptColumnMapsPage.tsx)
- [ValueAliasesPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/ValueAliasesPage.tsx)
- [RelationshipsPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/RelationshipsPage.tsx)
- [SemanticCatalogBuilderPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/semantic-catalog/SemanticCatalogBuilderPage.tsx)
- [semanticCatalog.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/api/semanticCatalog.ts)
- [admin.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/admin.ts)
- [concepts.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/concepts.ts)

Focused verification completed before the full phase gate:

- backend semantic route/catalog slice: `23 passed`
- frontend semantic admin/catalog slice: `28 passed`

Full phase gate:

- backend: `pytest -q` -> `2659 passed, 78 skipped`
- frontend: `npx vitest run` -> `143 passed`, `655 passed | 3 todo`
