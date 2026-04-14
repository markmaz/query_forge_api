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

### 2026-04-13 - Backend runtime and utility sweep completed

Completed:

- removed the remaining semantic suggestion runtime dependency on `vertical` / `vertical_norm`:
  - generic-only matcher loading and concept resolution
  - generic-only suggestion-run persistence and apply flow
  - dropped `semantic_suggestion_run.vertical` and `vertical_norm` from the ORM and added a follow-on migration
- removed stale compatibility-only `scope_vertical_norm` cleanup from the remaining planner policy service wrappers
- collapsed the planner-domain internal call path off dead `vertical_norm` parameters:
  - domain candidate retrieval
  - domain selection ranking
  - LLM slot/plan generation helpers
  - postprocess retry orchestration
  - pipeline failure trace context
- removed post-migration semantic/runtime queries that still referenced dropped `vertical_norm` columns:
  - planner semantic integration lookups
  - planner LLM cache registry-version lookup
  - planner concept search filter
  - semantic plan concept/value-alias SQL
  - semantic catalog enrichment prompt plumbing
- removed the last runtime-only compatibility payloads in chat/planner helpers and backend utility scripts:
  - education fewshot detection
  - Forge insights auto-plan handoff
  - domain reindex script
  - registry seed builder

Code references:

- [semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_suggestion_service.py)
- [semantic_concept_matcher.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_concept_matcher.py)
- [semantic_suggestion.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/semantic/semantic_suggestion.py)
- [20260413_drop_semantic_suggestion_run_vertical.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260413_drop_semantic_suggestion_run_vertical.sql)
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/service.py)
- [domain_selection_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/domain_selection_service.py)
- [llm_planning_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/llm_planning_service.py)
- [semantic_integration_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/semantic_integration_service.py)
- [cache.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_llm/cache.py)
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_llm/service.py)
- [value_alias_applier.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/value_alias_applier.py)
- [concept_scorer.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/concept_scorer.py)

Verification completed before the final phase gate:

- semantic suggestion + canonical matcher slice: `28 passed`
- semantic route slice: `23 passed`
- planner-domain helper slice: `127 passed`
- semantic/runtime follow-on slice: `122 passed`

Full phase gate:

- backend app/runtime scan: only deliberate removed-field rejection and legacy normalization helpers still mention `vertical_norm`
- backend: `pytest -q`

### 2026-04-13 - Planner and semantic runtime follow-through cleanup complete

Completed:

- removed the remaining live planner runtime calls that still threaded `vertical_norm` into generic-only helpers:
  - semantic grounding alias resolution
  - planner-domain capability loading during selection ranking
  - slot extraction prompt construction
  - next-actions capability loading
- removed stale `PipelineContext` test construction that still passed `vertical_norm` after the shared AI context schema was flattened
- aligned planner-domain and semantic-plan tests with the new generic-only behavior:
  - unified planner helper tests no longer pass `vertical_norm` into `build_plan_and_slots`
  - planner-domain fake capability and alias resolver stubs now match the collapsed helper signatures
  - semantic plan extract coverage now asserts `vertical_norm` is absent from concept retrieval calls
- regenerated planner-domain golden fixtures so the shared pipeline debug snapshot no longer preserves `domain_selection.vertical_norm`
- kept request-model compatibility where public planner and semantic payloads still accept legacy `vertical_norm`, but removed the internal downstream dependency for the cleaned paths above

Code references:

- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/service.py)
- [llm_planning_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/llm_planning_service.py)
- [domain_selection_ranking.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/domain_selection_ranking.py)
- [semantic_grounding_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_grounding_service.py)
- [generate_golden_files.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner_domain/generate_golden_files.py)
- [test_golden_regression.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner_domain/test_golden_regression.py)
- [test_plan_service_semantic_extract.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_plan_service_semantic_extract.py)

Focused verification completed before the final regression gate:

- backend planner helper slice: `8 passed`
- backend planner-domain golden slice: `9 passed`
- backend semantic plan extract slice: `6 passed`

Full phase gate:

- backend: `pytest -q` -> `2694 passed, 80 skipped`

### 2026-04-13 - Secondary planner policy vertical scope cleanup complete

Completed:

- removed `scope_vertical_norm` from the secondary planner policy request models, ORM models, and composite scope indexes:
  - semantic join
  - capability packing
  - concept scoring
  - semantic projection
  - semantic time
- collapsed stored `vertical` planner-policy scope rows to `global` in a follow-on migration and dropped the retired vertical scope column/indexes from those tables
- removed `vertical_norm` from the capability packing runtime/service interface and switched secondary planner policy lookups to the shared global/workspace scope predicates and dedupe path
- updated planner-domain callers that still passed removed compatibility arguments into retrieval and domain-selection policy services after the wider planner-policy cleanup
- kept broader semantic/domain compatibility uses of `vertical_norm` outside the planner-policy track unchanged in this slice

Code references:

- [planner_semantic_join_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_semantic_join_policy.py)
- [planner_capability_packing_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_capability_packing_policy.py)
- [planner_concept_scoring_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_concept_scoring_policy.py)
- [planner_semantic_projection_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_semantic_projection_policy.py)
- [planner_semantic_time_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_semantic_time_policy.py)
- [planner_capability_packing_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_capability_packing_policy_service.py)
- [domain_selection_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/domain_selection_service.py)
- [domain_candidate_retriever.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/domain_candidate_retriever.py)
- [capability_compactor.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/capability_compactor.py)
- [20260413_drop_vertical_norm_from_secondary_planner_policies.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260413_drop_vertical_norm_from_secondary_planner_policies.sql)

Focused verification completed before the full phase gate:

- backend secondary planner policy slice: `14 passed`
- backend planner-domain follow-on slice: `101 passed`

Full phase gate:

- backend: `pytest -q` -> `2694 passed, 80 skipped`

### 2026-04-13 - Planner policy compatibility cleanup slice complete

Completed:

- removed the compatibility-only `vertical_norm` parameter and echoed response field from the live planner policy services that had already stopped using it:
  - rerank policy
  - projection policy
  - domain capability
  - prompt intent policy
  - retrieval policy
  - domain selection policy
  - signal extraction
- updated in-repo planner/shared-AI callers and affected tests so they no longer pass the retired compatibility argument to those services
- removed the leftover `vertical_norm` ORM column and composite scope index residue from `planner_rerank_policy_candidate`
- added a follow-on migration to drop `planner_rerank_policy_candidate.vertical_norm` and recreate `idx_prpc_scope` on `workspace_id` only
- removed the remaining raw SQL update that still wrote `vertical_norm = NULL` for rerank policy candidates

Code references:

- [planner_rerank_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_rerank_policy.py)
- [planner_rerank_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_service.py)
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py)
- [planner_domain_capability_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_capability_service.py)
- [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py)
- [planner_retrieval_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_retrieval_policy_service.py)
- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py)
- [planner_signal_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_signal_policy_service.py)
- [planner_rerank_policy_candidate_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_candidate_service.py)
- [20260413_drop_planner_rerank_policy_candidate_vertical.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260413_drop_planner_rerank_policy_candidate_vertical.sql)

Focused verification:

- backend planner compatibility slice: `106 passed`

Follow-on still pending:

- the secondary planner policy families that still model real `scope_vertical_norm` / `vertical` scope behavior:
  - semantic join
  - capability packing
  - concept scoring
  - semantic projection
  - semantic time

### 2026-04-13 - Phase 5 candidate cleanup slice complete

Completed:

- candidate create and suggest request models now reject removed `vertical_norm` inputs instead of silently ignoring them
- candidate insert writes no longer include the retired vertical placeholder, so new planner rerank candidates persist without planner vertical data
- AI candidate suggestion prompt construction no longer includes `vertical_norm` in the LLM context
- candidate approval promotion continues using the existing workspace/domain scope payload without any vertical field
- planner policy seed payloads remain normalized with no `scope_vertical_norm` placeholders in the live planner-policy service defaults

Code references:

- [planner_rerank_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_rerank_policy.py)
- [planner_rerank_policy_candidate_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_candidate_service.py)
- [planner_rerank_policy_candidate_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_rerank_policy_candidate_suggestion_service.py)
- [test_planner_rerank_policy_candidate_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/test_planner_rerank_policy_candidate_service.py)
- [test_planner_rerank_policy_candidate_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/test_planner_rerank_policy_candidate_suggestion_service.py)
- [test_domain_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/routes/test_domain_routes.py)

Focused verification completed before the full phase gate:

- backend candidate services: `16 passed`
- backend candidate domain routes: `9 skipped` (`TEST_USERNAME` / `TEST_PASSWORD` not set in local env)

### 2026-04-13 - Compact semantic planner runtime collapsed off vertical_norm

Completed:

- removed `vertical_norm` from the compact semantic candidate payload and retry trimming path
- removed `vertical_norm` from compact semantic retrieval, prompt-building, and plan-compilation interfaces
- changed the planner catalog lookup repository to query only the normalized generic semantic partition instead of pretending the compact planner still accepts a vertical axis
- removed the compact planner `vertical_norm` parameter from the planner-domain call path
- removed `vertical_norm` from compact semantic planner prompt payloads and compiled `plan_json_v2`
- kept alias resolution on the deeper semantic service contract for now; this slice is limited to the compact planner runtime path

Code references:

- [semantic_candidate_models.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_candidate_models.py)
- [semantic_retrieval_helpers.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_retrieval_helpers.py)
- [semantic_catalog_lookup_repository.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_catalog_lookup_repository.py)
- [semantic_retrieval_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_retrieval_service.py)
- [planner_prompt_builder.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/planner_prompt_builder.py)
- [semantic_plan_compiler.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_plan_compiler.py)
- [compact_planner.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/compact_planner.py)
- [semantic_grounding_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_grounding_service.py)
- [llm_planning_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/llm_planning_service.py)

Focused verification completed before the full phase gate:

- backend compact semantic planner slice: `24 passed`
- backend planner-domain integration slice: `97 passed`

Full phase gate:

- backend: `pytest -q` -> `2694 passed, 78 skipped`

### 2026-04-13 - Planner-domain semantic assist runtime collapsed off vertical_norm

Completed:

- removed `vertical_norm` from planner-domain semantic alias constraint resolution
- removed `vertical_norm` from planner-domain semester-indicator resolution and semantic value-alias normalization interfaces
- changed planner-domain semantic assist SQL lookups to read only the normalized generic partition instead of preferring a caller-selected vertical
- removed `vertical_norm` from semantic grounding bundle construction in the planner-domain call path
- updated domain candidate retrieval to use semantic alias constraints without threading a vertical argument through semantic integration

Code references:

- [semantic_grounding_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner/semantic_grounding_service.py)
- [semantic_integration_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/semantic_integration_service.py)
- [domain_candidate_retriever.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/domain_candidate_retriever.py)
- [domain_selection_ranking.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/domain_selection_ranking.py)
- [plan_postprocess_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/plan_postprocess_service.py)
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/service.py)

Focused verification completed before the full phase gate:

- backend semantic grounding / semantic integration slice: `86 passed`

Full phase gate:

- backend: `pytest -q` -> `2694 passed, 78 skipped`

### 2026-04-13 - Semantic plan core collapsed off vertical_norm

Completed:

- removed `vertical_norm` from semantic plan concept-scoring runtime interfaces
- changed slot-driven intent normalization, lexical alias lookup, concept detail lookup, and resolved value-constraint lookup to operate on the generic compatibility partition only
- removed `vertical_norm` from the semantic plan value-alias applier interface and changed its SQL/runtime canonicalization path to generic-only
- updated `PlanService` to keep accepting compatibility request payloads while routing the internal semantic-plan core through the generic-only runtime

Code references:

- [concept_scorer.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/concept_scorer.py)
- [value_alias_applier.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/value_alias_applier.py)
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/plan/service.py)
- [test_plan_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_plan_service.py)
- [test_plan_service_semantic_extract.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_plan_service_semantic_extract.py)
- [test_slot_driven_planner.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_slot_driven_planner.py)

Focused verification completed before the full phase gate:

- backend semantic plan slice: `36 passed`

Full phase gate:

- backend: `pytest -q` -> pending

### 2026-04-13 - Planner-domain runtime and plan payload boundary cleaned up

Completed:

- removed `vertical_norm` from the planner-domain request DTOs used by the live service boundary
- removed planner-domain conversation-state persistence of `vertical_norm`
- removed the planner-domain follow-up fallback that revived legacy `education` or `healthcare` verticals from prior conversation state
- normalized planner-domain runtime execution to the generic compatibility partition at the service boundary
- removed `vertical_norm` from the planner-domain `PlanV2` schema and plan normalization path
- updated the Query Forge frontend `PlanV2` type/parser to stop requiring or preserving `vertical_norm`
- refreshed the planner-domain golden debug fixtures to match the new prompt-normalization step name and the removed vertical field

Code references:

- [types.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/types.py)
- [conversation_context.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/conversation_context.py)
- [conversation_store.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/conversation_store.py)
- [plan_finalization_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/plan_finalization_service.py)
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/service.py)
- [schema_v2.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/schema_v2.py)
- [validate_v2.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/validate_v2.py)
- [llm_planning_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_domain/llm_planning_service.py)
- [types.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/ai/types.ts)

Focused verification completed before the full phase gate:

- backend planner-domain route and service slice: `138 passed`
- backend expanded planner-domain regression slice: `404 passed`
- frontend Query Forge planner slice: `54 passed | 3 todo`

Full phase gate:

- backend: `pytest -q` -> `2694 passed, 78 skipped`
- frontend: `npx vitest run` -> `659 passed | 3 todo`

### 2026-04-13 - Forge Match and semantic catalog public contracts cleaned up

Completed:

- removed `vertical_norm` from the Forge Match analyze request schema, routes, Celery task, mapping/session job orchestration, candidate retrieval path, and row/session pipeline request payloads
- removed the Forge Match vertical input and vertical pipeline badge from the frontend, and dropped the field from the shared Forge Match frontend contracts
- removed `vertical_norm` from the semantic catalog build admin request contract on both backend and frontend
- changed semantic catalog build to reject stale `vertical_norm` input instead of silently accepting it
- stripped `vertical_norm` from the semantic catalog build admin response payload so the admin surface no longer advertises the field

Code references:

- [forge_match_schema.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/schemas/forge_match_schema.py)
- [forge_match_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/forge_match_routes.py)
- [forge_match_tasks.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/tasks/forge_match_tasks.py)
- [mapping_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/forge_match/mapping_service.py)
- [session_job_coordinator.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/forge_match/session_job_coordinator.py)
- [row_pipeline_runner.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/forge_match/row_pipeline_runner.py)
- [pipeline_adapters.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/forge_match/pipeline_adapters.py)
- [candidate_retriever.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/forge_match/candidate_retriever.py)
- [ForgeMatchAnalyzeControls.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/forgeMatch/components/ForgeMatchAnalyzeControls.tsx)
- [ForgeMatchSummary.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/forgeMatch/components/ForgeMatchSummary.tsx)
- [ForgeMatchResultDrawer.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/forgeMatch/components/ForgeMatchResultDrawer.tsx)
- [contracts.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/shared/services/forgeMatch/contracts.ts)
- [semantic_catalog_admin.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/semantic/semantic_catalog_admin.py)
- [models.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/admin/models.py)
- [vector_domain_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/admin/vector_domain_routes.py)
- [semanticCatalog.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/api/semanticCatalog.ts)
- [semanticCatalog.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/types/semanticCatalog.ts)
- [SemanticCatalogBuilderPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/semantic-catalog/SemanticCatalogBuilderPage.tsx)

Focused verification completed before the full phase gate:

- backend Forge Match slice: `44 passed`
- backend semantic catalog admin slice: `4 passed`
- frontend Forge Match slice: `14 passed`
- frontend semantic catalog slice: `8 passed`

Full phase gate:

- backend: `pytest -q` -> `2692 passed, 78 skipped`
- frontend: `npx vitest run` -> `659 passed | 3 todo`

### 2026-04-13 - Query Forge AI and planner-domain request contracts cleaned up

Completed:

- removed `vertical_norm`/`verticalNorm` from the deprecated `/api/v1/ai/suggest` and `/api/v1/ai/suggest-semantic-adapter` request surface
- stopped the AI bridge from stripping and honoring legacy vertical overrides; stale request fields now fail under the existing strict request validator
- removed `vertical_norm` from the public `/api/v1/planner/plan_domain` and `/api/v1/planner/plan_domain/next_actions` request models
- added explicit route-level rejection for stale planner request payloads that still send `vertical_norm` or `verticalNorm`
- removed the Query Forge frontend planner request field from the shared AI types and stopped sending `vertical_norm` in planner requests

Code references:

- [ai.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/ai.py)
- [planner_domain_api.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/features/planner/planner_domain_api.py)
- [test_ai_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/routes/test_ai_routes.py)
- [test_planner_domain_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/routes/test_planner_domain_routes.py)
- [types.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/ai/types.ts)
- [aiCopilotApi.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/ai/aiCopilotApi.ts)
- [aiCopilotApi.test.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/ai/__tests__/aiCopilotApi.test.ts)
- [usePlannerConversation.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/ai/__tests__/usePlannerConversation.test.tsx)
- [QueryForgePage.test.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/__tests__/QueryForgePage.test.tsx)

Focused verification completed before the full phase gate:

- backend AI/planner route slice: `16 passed`
- frontend Query Forge AI slice: `35 passed | 3 todo`

Full phase gate:

- backend: `pytest -q` -> `2694 passed, 78 skipped`
- frontend: `npx vitest run` -> `659 passed | 3 todo`

### 2026-04-13 - Domain embedding state schema cleanup slice complete

Completed:

- removed `vertical_norm` from the `domain_embedding_state` write path in the domain vector index service
- removed `vertical_norm` and its old index from the demo DDL for `domain_embedding_state`
- added a dedicated migration to drop the compatibility column from `domain_embedding_state`
- added a regression that proves the incremental index state write no longer references the removed column

Code references:

- [domain_index_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/vector/domain_index_service.py)
- [20260413_drop_domain_embedding_state_vertical.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260413_drop_domain_embedding_state_vertical.sql)
- [query_forge_demo_ddl.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/query_forge_demo_ddl.sql)
- [test_domain_vector_search.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/test_domain_vector_search.py)

Focused verification completed before the full phase gate:

- backend domain embedding state slice: `15 passed`

Full phase gate:

- backend: `pytest -q` -> `2691 passed, 78 skipped`

### 2026-04-13 - Planner LLM vertical cleanup slice complete

Completed:

- removed the internal `vertical` argument from the planner LLM cache key, registry-version lookup, and cache write path
- collapsed planner LLM semantic concept retrieval to the generic-only semantic partition instead of a dynamic vertical filter
- removed the `vertical` column from the planner cache demo DDL and added a migration to drop it from the live schema
- removed planner LLM logging and fake-test contracts that still modeled a planner vertical axis even though runtime had already hardcoded `generic`

Code references:

- [cache.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_llm/cache.py)
- [service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/planner_llm/service.py)
- [20260413_drop_planner_cache_vertical.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/migrations/20260413_drop_planner_cache_vertical.sql)
- [query_forge_demo_ddl.sql](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/query_forge_demo_ddl.sql)
- [test_cache.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner_llm/test_cache.py)
- [test_golden_ratio.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner_llm/test_golden_ratio.py)

Focused verification completed before the full phase gate:

- backend planner LLM slice: `9 passed`

Full phase gate:

- backend: `pytest -q` -> `2692 passed, 78 skipped`

### 2026-04-13 - Domain vector contract cleanup slice complete

Completed:

- removed `vertical_norm` from the domain vector admin rebuild contract:
  - `/admin/vector/domains/reindex`
  - `/admin/vector/rebuild-all`
- removed `vertical_norm` from the public domain vector search contract:
  - `/vector/domains/search`
- removed the dead `vertical_norm` parameter from the domain vector service entry points and the internal `DomainEmbeddingState` runtime object
- updated the Forge Insights domain-vector caller to use the generic-only domain vector search contract
- removed the vertical input from the frontend rebuild-all dialog and domain vector rebuild requests
- updated the domain profile UI follow-up rebuild flow to call domain vector reindex without a vertical payload

Code references:

- [domain_index_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/vector/domain_index_service.py)
- [vector_domain_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/admin/vector_domain_routes.py)
- [vector_domains.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/vector_domains.py)
- [forge_insights_router_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/forge_insights_router_service.py)
- [vectorIndex.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/types/vectorIndex.ts)
- [VectorIndexPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/vectors/VectorIndexPage.tsx)
- [RebuildAllDialog.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/vectors/RebuildAllDialog.tsx)
- [DomainProfileList.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileList.tsx)

Focused verification completed before the full phase gate:

- backend domain vector slice: `80 passed`
- frontend vector admin/domain profile slice: `11 passed`

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

### 2026-04-13 - Final backend zero-reference cleanup complete

Completed:

- removed the last explicit backend app/runtime references to `vertical_norm` and `scope_vertical_norm`
- replaced the planner-domain and semantic-suggestion request-boundary special cases with generic unsupported-field validation so stale payloads still fail without hardcoding retired field names
- deleted the now-unreferenced semantic normalization helper services that only existed to rewrite legacy `vertical_norm` storage rows
- regenerated the planner-domain golden fixtures and closed the remaining full-suite fallout from the runtime cleanup

Code references:

- [planner_domain_api.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/features/planner/planner_domain_api.py)
- [semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/semantic/semantic_suggestion_service.py)
- [test_planner_domain_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/routes/test_planner_domain_routes.py)
- [test_semantic_suggestion_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/semantic/test_semantic_suggestion_service.py)
- [generate_golden_files.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/planner_domain/generate_golden_files.py)

Focused verification completed before the final gate:

- targeted regression rerun: `13 passed`
- backend app/runtime scan: `rg -n "vertical_norm|scope_vertical_norm" app/features app/services app/models app/routes app/nlp app/scripts` -> no matches

Full phase gate:

- backend: `pytest -q` -> `2688 passed, 80 skipped`
- frontend: not rerun in this slice because the changes were backend-only

### 2026-04-13 - Semantic concept vector rebuild cleanup slice complete

Completed:

- removed the semantic concept embedding service rebuild entrypoint's `vertical_norm` parameter and made semantic concept vector rebuild implicitly generic-only
- changed the semantic concept embedding service generic load queries to read only normalized generic concept and alias rows during full rebuild
- removed `vertical_norm` from the semantic concept rebuild admin route contract and response
- removed the semantic concept rebuild `vertical_norm` payload from the frontend vector admin types and client call path
- kept `vertical_norm` in the broader vector admin flow only where domain-vector rebuild still actually depends on it

Code references:

- [semantic_concept_embedding_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/embedding/semantic_concept_embedding_service.py)
- [vector_domain_routes.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/admin/vector_domain_routes.py)
- [semantic_concepts.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/routes/semantic_concepts.py)
- [test_semantic_concept_embedding_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/tests/services/embedding/test_semantic_concept_embedding_service.py)
- [vectorIndex.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/types/vectorIndex.ts)
- [VectorIndexPage.tsx](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/vectors/VectorIndexPage.tsx)
- [vectorIndexes.test.ts](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-ui/src/features/system-admin/api/vectorIndexes.test.ts)

Focused verification completed before the full phase gate:

- backend semantic vector slice: `78 passed`
- frontend vector admin api slice: `1 passed`

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
