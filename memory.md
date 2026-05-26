# Working Memory

Last updated: 2026-05-05

## Current FlowForge Runtime Note

- Canonical cross-repo memory is now `/Users/mmaslak/Local Documents/projects/query_forge/memory.md`.
- FlowForge Phase 11 backend foundation is implemented: Celery run dispatch, runtime dispatcher, webhook-created run enqueue, idempotent dispatch/node events, and basic node support for `intake`, `decision`, `notification`, `wait`, and `end`.
- FlowForge Phase 12 backend foundation is implemented: runtime `matching` node resolves published policy versions, loads active resource snapshots, persists matching evaluations/candidate rows, and branches on `matched` or `no_match`.
- FlowForge Phase 13 backend foundation is implemented: pending FlowForge notification rows can be sent by `qf.flowforge.dispatch_notifications` with minimal summary-level email content, sent/failed status updates, and timeline events.
- FlowForge Phase 14 backend foundation has been deepened and hardened: runtime matching creates offer tasks/tokens/notifications/resource active-offer state and candidate queue context; accept mutates assignment/active-offer state and creates durable assignment rows; decline/timeout mutates decline/active-offer state, offers the next queued candidate, or advances to no-match when exhausted.
- Added deterministic offer-task idempotency keys, `flowforge_assignments`, configurable offer template keys/timeouts from matching node config, and explicit runtime support for `assignment`, `iterator`, and `event_capture` nodes.
- Applied the Phase 14 hardening migration to local `query_forge_rbac`: `flowforge_human_tasks.idempotency_key`, `uidx_ff_human_task_idempotency`, and `flowforge_assignments` are present.
- FlowForge Phase 15 has begun with the operator monitoring UI: `/automation/flowforge/runs`, `/automation/flowforge/runs/:runId`, and `/automation/flowforge/needs-attention` now target the persisted runtime endpoints for run status, timeline events, human tasks, notifications, matching explanation, and operator notes.
- FlowForge Phase 16 has begun with workspace settings GET/PUT plus admin UI pages for integrations, resource sets/manual snapshots, matching policy simulation/save, and FlowForge workspace defaults.
- FlowForge Phase 17 has begun with persisted workflow draft creation, JSON node config editing, draft-version saving, version history, and publish action support.
- FlowForge Phase 18 has begun with governed reporting read-model metadata, production-default dashboard metrics, sensitive-field exclusions, read-model views, and a FlowForge Reports UI linked to Query Studio prompts.
- Backend app version is `0.3.375`; frontend app version is `0.4.29`.
- Remaining runtime hardening: assignment lifecycle beyond initial assigned rows and retry-safe recovery if a worker crashes mid-offer side-effect sequence.

## Repos in play

- API repo: `/Users/mmaslak/Local Documents/projects/query-forge-api`
- UI repo: `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui`

## Current context

- User wants long-running context persisted to a `memory.md` file so compressed context can be recovered later.
- This file is the canonical working memory for the current thread unless the user asks for a different location.
- Branch/PR hygiene rule: before starting a feature, bugfix, or refactor larger than a small single-file change, create or confirm a branch named for that workstream.
- Do not mix unrelated product surfaces on one branch when avoidable. MCP OAuth, FlowForge, tenancy cleanup, planner policy work, and feedback-learning work should each have their own branch/PR boundary.
- Commit after each coherent milestone, such as backend foundation, frontend UI, migrations, docs/config, test fixes, or a bugfix slice. PRs should represent one reviewable behavior unit.
- If urgent work lands on the wrong branch, stop before adding more changes and either move it with selective staging/stash/patch flow or explicitly record that the branch is temporarily mixed.

## Recent API work

- Updated the semantic catalog build admin route so it uses workspace-admin access instead of the old system-admin gate.
- File changed: `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/admin_routes.py`
- Regression test added for workspace admin access:
  `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/routes/test_admin_routes.py`
- Updated `/admin/vector/semantic-concepts/rebuild` to allow `workspace_admin` via `@require_admin()`.
- Added regression coverage for workspace-admin access to the semantic concept vector rebuild endpoint in:
  `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/routes/test_admin_routes.py`
- Updated `/admin/vector/embeddings/rebuild` to allow `workspace_admin` via `@require_admin()`.
- Updated `/admin/vector/domains/reindex` to allow `workspace_admin` via `@require_admin()`.
- Added regression coverage for workspace-admin access to both endpoints in:
  `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/routes/test_admin_routes.py`

## Recent UI work

- Added a static Semantic Help page for the Semantic Registry area.
- Main page file:
  `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/SemanticHelpPage.tsx`
- Route added:
  `/semantic/help`
- Semantic Help access was changed so `semantic:user` is sufficient.
- Sidebar behavior:
  - Admin users see `Help` as the last item under the existing `Semantic Registry` submenu.
  - Non-admin users with `semantic:user` see a standalone `Semantic Registry` section with `Help`.

## UI files touched for Semantic Help

- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/navigation/routes.ts`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/navigation/AppRoutes.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/chrome/sidebar/widgets/menuList/useNewMenuList.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/components/SemanticAdminShell.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/styles/semanticAdmin.css`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/SemanticHelpPage.tsx`

## Latest UI navigation work

- Reorganized the `Query Forge` sidebar section into grouped rollups:
  - `Build`
  - `Shape`
  - `AI`
  - `Automation`
- Current child structure:
  - `Build` -> `Query Studio`, `Analysis Studio`
  - `Shape` -> `Domain Studio`, `Data Dictionary`, `Data Mappings`
  - `AI` -> `Forge Insights`, `Forge Match`
  - `Automation` -> `Skills`
- Renamed visible labels/page headers:
  - `Query Studio V3` -> `Analysis Studio`
  - `Forge Management` -> `Domain Studio`
  - `Crosswalk Management` -> `Data Mappings`
- Sidebar implementation file:
  `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/chrome/sidebar/widgets/menuList/useNewMenuList.tsx`
- Updated page headers:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/domain-studio/ui/NoCodeManagementPage.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/v3/QueryStudioV3Page.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/list-ops/ui/ListManagementPage.tsx`

## Latest admin help-page work

- Added `Data Foundation Help` and `Tenancy Help` pages in the UI repo.
- New help page files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/help/DataFoundationHelpPage.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/help/TenancyHelpPage.tsx`
- New routes:
  - `/admin/data-foundation/help`
  - `/admin/tenancy/help`
- Sidebar behavior:
  - `Help` is now the last item under `Data Foundation`
  - `Help` is now the last item under `Tenancy`
- Route/menu wiring files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/navigation/routes.ts`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/navigation/AppRoutes.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/chrome/sidebar/widgets/menuList/useNewMenuList.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/systemAdmin.css`

## UI tests added

- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/__tests__/SemanticHelpPage.test.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/__tests__/SemanticHelpRoute.test.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/chrome/sidebar/widgets/menuList/useNewMenuList.semanticHelp.test.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/chrome/sidebar/widgets/menuList/useNewMenuList.queryForgeStructure.test.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/chrome/sidebar/widgets/menuList/useNewMenuList.adminHelpLinks.test.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/help/DataFoundationHelpRoute.test.tsx`
- `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/help/TenancyHelpRoute.test.tsx`

## Verification status

- API verification completed:
  - `pytest tests/routes/test_admin_routes.py -q`
  - Result: passed
- UI verification completed:
  - `npm test -- --run src/features/semantic-admin/ui/__tests__/SemanticHelpPage.test.tsx src/features/semantic-admin/ui/__tests__/SemanticHelpRoute.test.tsx src/app/chrome/sidebar/widgets/menuList/useNewMenuList.semanticHelp.test.tsx`
  - Result: passed
- Existing warning observed in test output: `Missing VITE_API_URL. Add it to your .env file.`

## Latest UI bug fix

- Fixed the vector index result card renderer so nested response objects and arrays display as readable metrics instead of `[object Object]` or blank values.
- This was prompted by the Domain Vectors response shape containing nested `timings_ms` and `collection` objects.
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/vectors/IndexCard.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/types/vectorIndex.ts`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/vectors/IndexCard.test.tsx`
- Verification completed:
  - `npm test -- --run src/features/system-admin/ui/vectors/IndexCard.test.tsx`
  - Result: passed
- Additional UI verification completed for Query Forge navigation:
  - `npm test -- --run src/app/chrome/sidebar/widgets/menuList/useNewMenuList.queryForgeStructure.test.tsx src/app/chrome/sidebar/widgets/menuList/useNewMenuList.semanticHelp.test.tsx src/features/semantic-admin/ui/__tests__/SemanticHelpPage.test.tsx src/features/semantic-admin/ui/__tests__/SemanticHelpRoute.test.tsx`
  - Result: passed
  - Existing warning observed in test output: `Missing VITE_API_URL. Add it to your .env file.`
- Additional UI verification completed for admin help pages:
  - `npm test -- --run src/app/chrome/sidebar/widgets/menuList/useNewMenuList.adminHelpLinks.test.tsx src/features/system-admin/ui/help/DataFoundationHelpRoute.test.tsx src/features/system-admin/ui/help/TenancyHelpRoute.test.tsx`
  - Result: passed
  - Existing warning observed in test output: `Missing VITE_API_URL. Add it to your .env file.`

## User preferences captured

- Persist long-running working context to `memory.md`.
- When context is compressed, summarize current state into `memory.md` so the thread does not lose continuity.

## Open notes

- The UI repo already had many unrelated local modifications before this Semantic Help work.
- If future work continues mainly in the UI repo, this memory file should still be updated unless the user asks for a separate UI-local memory file.
- Planner `/api/v1/planner/plan_domain` diagnosis on 2026-03-19 for trace `9a7f5af4-1e85-43ac-9039-e00a49f19e8c`:
  - Request workspace: `ws_3de8526699214b2d87830352`
  - Prompt: `Show me all the schools in clarksville, tn`
  - The planner failed in `PlannerDomainService._get_domain_candidates()` with `No candidate domain found for prompt`.
  - Confirmed runtime state:
    - SQL domain load returns 20 active domains for that workspace.
    - Qdrant collection `domain_catalog_v1` has 13 points total, but none for workspace `ws_3de8526699214b2d87830352`.
    - Domain vector search returns 0 results for `generic`, `education`, and `healthcare`.
    - `domain_embedding_state` also has 0 rows for that workspace, so a normal domain reindex should repopulate vectors rather than skipping them.
  - Most likely remediation: run `/api/v1/admin/vector/domains/reindex` for that workspace, then retry `/api/v1/planner/plan_domain`.
  - Additional code-path note:
    - The admin reindex route does pass `X-Workspace-Id` through `extract_workspace_id()` into `DomainVectorIndexService.reindex_domains()`.
    - A `{"total": 0}` reindex response can still happen even when the workspace id is correct, because `_load_domains()` catches SQL exceptions and returns an empty list instead of surfacing the query failure.
    - Relevant likely log line if this happens in runtime: `domain profile query failed; attempting fallback`.
  - Vertical inference note:
    - For workspace `ws_3de8526699214b2d87830352`, the 20 loaded domain rows all infer to `education`.
    - Therefore:
      - `/admin/vector/domains/reindex` with `{"vertical_norm":"generic"}` will return `total: 0`.
      - `/planner/plan_domain` with no `vertical_norm` still normalizes to `generic`, so it will not match those `education` vectors even after a successful reindex.
    - Likely correct request value for both indexing/search in this workspace is `vertical_norm: "education"` unless a base domain is provided.
  - Implemented fix on 2026-03-19:
    - Removed vertical-based filtering and inferred classification from the domain vector path.
    - `DomainVectorIndexService.reindex_domains()` no longer filters rows by `vertical_norm`.
    - `DomainVectorIndexService.upsert_domains()` no longer infers `education`/`healthcare` from domain text and no longer writes inferred `vertical_norm` into Qdrant payloads.
    - `DomainVectorIndexService.search_domains()` now scopes by `workspace_id` and `is_active` only; `vertical_norm` is ignored for compatibility.
    - `PlannerDomainService._get_domain_candidates()` no longer passes `vertical_norm` into domain vector search.
    - Updated regression tests confirm:
      - workspace scoping still works
      - vertical is ignored during domain search
      - reindex does not drop rows when called with `vertical_norm="generic"`
  - Follow-up root cause:
    - After removing vertical-driven lookup, domain reindex still failed in runtime because `domain_embedding_state.vertical_norm` is `NOT NULL`.
    - The write path was attempting to persist `NULL` there, causing `IntegrityError: Column 'vertical_norm' cannot be null`.
    - Fixed by keeping vertical lookup semantics disabled while persisting `"generic"` into `domain_embedding_state.vertical_norm` only as a schema-compatibility placeholder.
    - Verified runtime locally:
      - `reindex_domains(workspace_id='ws_3de8526699214b2d87830352', vertical_norm='generic', force=True)` => `total: 20, upserted: 20`
      - Qdrant now contains points for that workspace
      - `search_domains(...)` for `Show me all the schools in clarksville, tn` returns candidates instead of an empty result
  - Remaining planner quality issue after reindex fix:
    - `plan_domain` now returns a plan but selected domain 23 (`Programs, Cohorts And Student Services`) instead of intended domain 19 (`Organization, Tenancy And Education Agency Structure`) for school-directory style prompt `Show me all the schools in clarksville, tn`.
    - Vector/domain ranking still dominates candidate selection; shortlist logic has school-aware boosts, but they apply after the wrong domain is already chosen.
    - `build_domain_embedding_text()` in `app/services/vector/domain_index_service.py` embeds these domain-profile fields directly when `embedding_text` is absent:
      - `name`
      - `summary` / `description`
      - `entities`
      - `metrics`
      - `dimensions` / `attributes`
      - `keywords`
      - `questions` / `questions_this_domain_answers` / `example_questions`
    - Domain 19 profile observations:
      - Summary/attributes/entities already contain strong school and district structure signals.
      - Keywords already include `school`, `district`, `LEA`, `education agency`, codes, and org structure terms.
      - Best profile-level improvements are likely:
        - make the summary explicitly say domain 19 is the authoritative school/district directory and lookup domain
        - add exact query-shaped keywords like `schools`, `list schools`, `school directory`, `find schools`, `schools by city`, `schools by district`
        - add example questions such as `Show me all the schools in Clarksville, TN`
    - Longer-term code fix still likely needed:
      - bias school-listing prompts toward domains exposing `school_name`/location fields
      - reject text filters placed on identifier columns like `ed_org_id`
  - Domain profile editor issue identified and fixed on 2026-03-19 in the UI repo:
    - The hidden `embedding_text` field in the Domain Profile form was pre-populated and always submitted on save, even when the user only changed summary/keywords/notes.
    - Because backend update logic preserves explicitly submitted `embedding_text`, stale custom embedding text could mask later domain-profile edits and keep vector indexing anchored to old wording.
    - Fixed in `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.tsx`:
      - `embedding_text` is now sent only if the user actually edited that field (`dirtyFields.embedding_text`)
      - otherwise the backend can rebuild embedding text from the updated profile fields
    - Added regression tests in `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx` proving:
      - unchanged hidden embedding text is omitted on save
      - explicitly edited embedding text is still submitted
    - Verified with:
      - `npm test -- --run src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx src/features/system-admin/ui/domains/DomainProfileForm.timePolicy.test.tsx`
      - Result: 11 passed

## Latest product cleanup

- User requested removal of dead product/product-group/product-role/user-product code from API and UI because RBAC now uses workspace features instead.
- API cleanup completed:
  - Removed product models:
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/tenancy/product.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/tenancy/product_group.py`
    - product enums from `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/tenancy/status_enum.py`
  - Removed product routes/services:
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/product_routes.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/product_groups_routes.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/product_service.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/product_groups_service.py`
  - Updated `/Users/mmaslak/Local Documents/projects/query-forge-api/app/features/catalog/__init__.py` and `/Users/mmaslak/Local Documents/projects/query-forge-api/app/features/catalog/routes.py` to stop registering those namespaces.
  - Simplified `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/user_service.py` so users no longer load, sync, or delete `user_product_map` rows and bulk invite no longer accepts product payloads.
  - Updated `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/user_routes.py` bulk invite route to accept only `emails` and `workspaces`.
  - Removed backend product-specific tests:
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/test_product_service.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/test_product_group_service.py`
  - Updated user/auth-guard tests to remove product assumptions.
- UI cleanup completed:
  - Removed product domain models and clients:
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/domain-model/Products.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/domain-model/ProductRole.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/domain-model/ProductGroup.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/products.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/productGroup.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/clients/productClient.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/clients/productGroupClient.ts`
  - Removed dead catalog-admin product UI components and wrapper page under:
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/catalog-admin/ui/`
  - Updated user payload types/services so `UserProfile` / `UserProfileUpdate` no longer include `products`.
  - Simplified bulk import wizard to upload emails plus assign workspaces only:
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/access-admin/ui/ImportUserModal/index.tsx`
  - Removed product-based state fallback:
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/access-admin/model/userSlice.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/runtime/useCan.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/preferences/ui/AccountSettingsPanel.tsx`
  - Renamed the admin route key/path from legacy product naming to workspace features:
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/app/navigation/routes.ts`
    - new path: `/workspace-features`
- Verification completed:
  - API:
    - `python3 -m pytest tests/services/test_user_service.py tests/routes/test_mutating_auth_guards.py -q`
    - Result: 36 passed
  - UI:
    - `npm test -- --run src/shared/services/__tests__/users.security.test.ts src/shared/services/__tests__/userRolesApi.test.ts src/features/preferences/ui/__tests__/AccountSettingsPanel.test.tsx src/features/access-admin/model/userSlice.test.ts src/app/chrome/sidebar/widgets/menuList/useNewMenuList.adminHelpLinks.test.tsx src/app/chrome/sidebar/widgets/menuList/useNewMenuList.semanticHelp.test.tsx src/app/chrome/sidebar/widgets/menuList/useNewMenuList.queryForgeStructure.test.tsx src/app/chrome/sidebar/widgets/menuList/useNewMenuList.externalLinks.test.tsx src/features/forgeMatch/__tests__/ForgeMatchRoute.test.tsx src/features/forgeMatch/__tests__/ForgeMatchPage.test.tsx`
    - Result: 37 passed
    - Existing warning observed in UI test output: `Missing VITE_API_URL. Add it to your .env file.`

## Latest UI fix

- Fixed a focus-loss bug in the Domain Profile metric configuration grid in the Edit Domain Profile drawer.
- Root cause:
  - metric rows were rendered with a React key derived from `metric_key`
  - while typing in the `metric_key` input, each keystroke changed the row key and caused the row to remount
  - remounting made the input lose focus, so users could only enter one character at a time
- Updated file:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.tsx`
- Fix approach:
  - added a stable local `ui_key` per metric row for rendering
  - kept API payload shape unchanged by stripping that local key before save
- Added regression coverage:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx`
  - new test verifies continuous typing in a new metric key row retains focus and the full value
- Verification completed:
  - `npm test -- --run src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx`
  - Result: 7 passed

## Latest drawer tweak

- Widened the Domain Profile drawer slightly without affecting other system-admin drawers.
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/systemAdmin.css`
- Change details:
  - added a scoped `sa-domain-profile-drawer` class to the drawer container
  - set that drawer width to `min(860px, 100vw)` instead of the shared default `min(640px, 100vw)`
- Verification completed:
  - `npm test -- --run src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx`
  - Result: 7 passed

## Latest metric config UX improvement

- Replaced the freeform `column_key` input in the Domain Profile drawer's metric configuration grid with a domain-aware dropdown.
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/api/domainProfiles.ts`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/types/domainProfile.ts`
- Behavior change:
  - the drawer now fetches all columns for the active domain from `/domains/columns`
  - the dropdown shows `table_name.column_name`
  - the saved metric payload still includes the canonical `column_key` (`wt<table_id>.<column_name>`)
  - the saved metric payload now also includes a generated `sql_metric.field` with resolved ids/column metadata from the selected option
- Regression coverage updated:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.timePolicy.test.tsx`
- Verification completed:
  - `npm test -- --run src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx src/features/system-admin/ui/domains/DomainProfileForm.timePolicy.test.tsx`
  - Result: 12 passed

## Latest metric persistence bug fix

- Found and fixed a bug where the main `Save Changes` action in the Domain Profile drawer could overwrite structured metric configuration in `domain_profile.metrics`.
- Root cause:
  - the drawer has two metric editing paths:
    - the top-level `Metrics` tag input on the main profile form
    - the structured `Profile Metric Configuration` grid
  - on existing profiles, the main save path was sending `metrics` from the tag input
  - that flattened structured metric objects back into plain strings and removed fields like `agg`, `column_key`, and `sql_metric`
  - planner capabilities then saw only the flattened metric list, which caused prompts to miss intended metrics like `student_count`
- Updated file:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.tsx`
- Fix approach:
  - for existing profiles, `Save Changes` now omits `metrics` entirely
  - structured metric configuration remains owned by the Profile Metric Configuration grid and its dedicated save action
- Regression coverage updated:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx`
  - assertion now verifies the main save payload does not include `metrics`
- Verification completed:
  - `npm test -- --run src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx src/features/system-admin/ui/domains/DomainProfileForm.timePolicy.test.tsx`
  - Result: 12 passed

## Latest admin RBAC adjustment

- Updated the pipeline profiles admin endpoint so `workspace_admin` can access it.
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/admin_routes.py`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/routes/test_admin_routes.py`
- Change details:
  - `/api/v1/admin/pipeline-profiles` now uses `@require_admin()` instead of `@require_role("system:admin")`
  - removed the legacy `_require_admin()` runtime check from that route
  - added a regression proving `workspace_admin` can call `/api/v1/admin/pipeline-profiles?limit=50`
- Verification completed:
  - `python3 -m pytest tests/routes/test_admin_routes.py -q`
  - Result: 41 passed

## Latest SQL compiler join-order fix

- Diagnosed the `Join order invalid: from table not yet joined` failure for domain 21 as a compiler sensitivity to out-of-order domain join metadata.
- Runtime diagnosis for workspace `ws_3de8526699214b2d87830352`, domain `21`:
  - primary table is `556` (`edfi_wh.dim_student`)
  - required path for school enrollment queries uses:
    - `556 -> 593`
    - `593 -> 552`
  - but the stored join sort order had `593 -> 552` before `556 -> 593`
  - the compiler previously iterated joins in metadata order and failed before it had joined table `593`
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/query_forge_service.py`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/test_query_forge_service_compile_extra.py`
- Fix approach:
  - `_from_clause_from_plan()` now schedules only the needed joins in dependency order
  - it no longer assumes `plan.joins` is already topologically sorted
  - it still raises the same error if no join progress is possible
- Regression coverage updated:
  - existing compile test now proves the compiler can recover when required joins are out of order
- Verification completed:
  - `python3 -m pytest tests/services/test_query_forge_service_compile_extra.py -q`
  - Result: 57 passed

## Latest semantic aliases UI search fix

- Diagnosed the Semantic Aliases screen search issue as UI behavior that depended on backend refetch/filtering even though the alias list endpoint effectively returns the loaded row set for the page to render directly.
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/AliasesPage.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/__tests__/AliasesPage.test.tsx`
- Fix approach:
  - changed the aliases query to refetch only by `vertical`
  - added local filtering for `conceptKey` and `q`
  - added normalization so user search terms like `school year` match `SCHOOL_YEAR` and alias text with spaces/hyphens/underscores
  - added local paging over the filtered result set so the table rows and total stay in sync
- Regression coverage added:
  - new test proves typing into `Concept key` narrows to `SCHOOL_YEAR`
  - new test proves typing into `Search aliases` narrows to matching alias text
- Verification completed:
  - `npm test -- --run src/features/semantic-admin/ui/__tests__/AliasesPage.test.tsx`
  - Result: 4 passed

## Latest domain time policy column-picker update

- Updated the Edit Domain Profile drawer Time Policy field so it no longer presents `default_time_concept_key` as a free-text concept key.
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.timePolicy.test.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx`
- Change details:
  - renamed the visible label from `Default Time Concept Key` to `Default Time Column`
  - replaced the text input with a dropdown backed by the same domain-column list used in Profile Metric Configuration
  - dropdown shows `table.column` display labels but saves the canonical `wt###.column_name` key into `default_time_concept_key`
  - added helper text clarifying that the saved value is the planner’s default time field
  - added a fallback option when an existing stored column key is no longer available in the domain
- Verification completed:
  - `npm test -- --run src/features/system-admin/ui/domains/DomainProfileForm.timePolicy.test.tsx src/features/system-admin/ui/domains/DomainProfileForm.metrics.test.tsx`
  - Result: 12 passed

## Latest school-year filter synthesis fix

- Diagnosed why planner output still omitted `this school year` for prompts like `Which students have more than 10 absences this school year?`
- Root cause:
  - `_normalize_school_year_filters_in_plan()` only synthesized a school-year filter from the `time` block when `plan.filters` was empty
  - when the plan already had a non-time filter such as `days_absent > 10`, the normalizer skipped adding `school_year = 2026`
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/planner_domain/service.py`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/planner_domain/test_school_year_normalization.py`
- Fix approach:
  - detect whether an existing school-year filter is already present
  - if not, synthesize a school-year filter from `time.time_column_key` and the prompt, even when other filters already exist
  - preserve existing filters and append the synthesized school-year filter
- Regression coverage added:
  - new test proves `school_year` is synthesized when another non-time filter is already present
- Verification completed:
  - `python3 -m pytest tests/services/planner_domain/test_school_year_normalization.py -q`
  - Result: 4 passed

## Latest reverse-join path fix for domain compiler

- Diagnosed the `Join path not found for table in domain` failure for domain 9 after planner started producing the correct `days_absent` and `school_year` filters.
- Runtime diagnosis for workspace `ws_3de8526699214b2d87830352`, domain `9`:
  - primary table is `593` (`fct_student_school_association`)
  - stored joins included:
    - `556 -> 593`
    - `556 -> 603`
  - from the primary table’s perspective, `556` and `603` were unreachable because the resolver only traversed joins in the stored forward direction
- Updated files:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/domain_resolver.py`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/query_forge_service.py`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/test_domain_resolver.py`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/test_query_forge_service_compile_extra.py`
- Fix approach:
  - `DomainResolver.get_join_path()` now traverses the domain join graph bidirectionally
  - reverse traversal synthesizes a reversed join edge with swapped join predicates
  - compiler `_from_clause_from_plan()` now consumes the actual path edges returned by the resolver instead of filtering back down to only stored `plan.joins`
- Verified runtime path:
  - domain 9 now resolves:
    - `593 -> 556`
    - `593 -> 556 -> 603`
- Verification completed:
  - `python3 -m pytest tests/services/test_domain_resolver.py tests/services/test_query_forge_service_compile_extra.py -q`
  - Result: 66 passed

## Latest skills pipeline audit

- Audited the QueryForge Skills feature end to end across:
  - frontend skills UI in `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills`
  - backend routes/models/tasks in `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/skills_routes.py`, `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/destination_routes.py`, `/Users/mmaslak/Local Documents/projects/query-forge-api/app/tasks/skill_runner.py`, `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/query/skills.py`, `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/domain/destinations.py`
- Confirmed implemented pieces:
  - skills CRUD is wired UI -> `/api/v1/skills` -> `query_skills`
  - schedule preview/validation is wired UI -> `/api/v1/skills/schedule/validate`
  - saving a schedule through the skill trigger persists `skill_schedules`
  - manual test execution queues Celery work via `/api/v1/skills/<id>/execute`
  - destinations CRUD/test endpoints are implemented at `/api/v1/workspaces/<workspace_id>/destinations`
  - Celery beat is configured to run `qf.skills.dispatch_due` every 60s in `/Users/mmaslak/Local Documents/projects/query-forge-api/app/celery_app.py`
- Confirmed gaps / defects:
  - recurring schedules are not truly recurring right now:
    - dispatcher in `/Users/mmaslak/Local Documents/projects/query-forge-api/app/tasks/skill_runner.py` sets `next_run_at = NULL` after dispatch and never advances to the next cron occurrence
  - destinations are not integrated into the Skill Builder UI:
    - builder still collects raw recipients / webhook URLs in `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/SkillBlockConfigPanel.tsx`
    - `DestinationPicker` exists in `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/DestinationForm.jsx` but is not used anywhere
  - destination usage counting / delete guarding is buggy:
    - `_count_skills_using_destination()` queries `JSON_SEARCH(config, ...)` instead of `config_json` in `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/domain/destinations.py`
  - generic webhook support is misleading/incomplete:
    - UI exposes generic webhook destination/action concepts
    - backend `webhook_delivery` skill only supports `slack` or `teams`
  - scheduler health endpoint is admin-only, but the builder requests it for all skills users, so non-admin users see a degraded/false warning state
  - run/event timeline support is still partial; frontend README still describes runs/events as scaffolding and placeholder behavior
- Verification completed:
  - backend: `python3 -m pytest tests/routes/test_skills_routes.py tests/tasks/test_skill_runner.py tests/test_destinations.py tests/test_skills_v4.py -q`
    - Result: 50 passed
  - frontend: `npm test -- --run src/features/skills/__tests__/skillsApi.test.ts src/features/skills/__tests__/SkillBuilderDrawer.test.tsx`
    - Result: 11 passed

## Latest skills pipeline implementation

- Implemented the 4 requested skills fixes across API and UI.
- Recurring schedules now advance `next_run_at` instead of being nulled after the first dispatch.
  - Updated `/Users/mmaslak/Local Documents/projects/query-forge-api/app/tasks/skill_runner.py`
  - Added regression in `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/tasks/test_skill_runner.py`
- Skill Builder now wires saved destinations into action editors and persists `destination_id`.
  - Updated UI:
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/SkillBlockConfigPanel.tsx`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/DestinationForm.jsx`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/SkillBuilderDrawer.tsx`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/pages/SkillsPage.tsx`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/constants.ts`
  - Updated API/runtime translation:
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/skills_routes.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/skills/email_delivery.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/skills/ai_summary_digest.py`
  - Added route regression in `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/routes/test_skills_routes.py`
- Fixed destination usage counting/delete protection to inspect `config_json`.
  - Updated `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/domain/destinations.py`
  - Added regression in `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/test_destinations.py`
- Completed the generic webhook path instead of removing it.
  - Updated:
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/skills/webhook_delivery.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/skills/delivery/__init__.py`
    - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/skills_routes.py`
  - Added webhook regressions in `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/test_skills_v4.py`
- Also opened scheduler health to general `skills` access so non-admin skills users can see the real scheduler state in the builder.

- Verification completed:
  - backend: `python3 -m pytest tests/routes/test_skills_routes.py tests/tasks/test_skill_runner.py tests/test_destinations.py tests/test_skills_v4.py -q`
    - Result: 56 passed
  - frontend: `npm test -- --run src/features/skills/__tests__/skillsApi.test.ts src/features/skills/__tests__/SkillBuilderDrawer.test.tsx`
    - Result: 11 passed
    - Existing warning remains: `Missing VITE_API_URL`

## Latest query library admin work

- Implemented library-management permissions in Saved Queries for a new global `library_admin` role plus existing workspace admins.
- Permission split implemented:
  - `workspace_admin`, `library_admin`, `super_admin`: can publish a saved query into Library via a new `Save to Library` action
  - `workspace_admin`, `library_admin`, `super_admin`: can create, move, rename, and delete library folders and library queries
- Backend:
  - added `library_admin` as a global RBAC role in `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/rbac.py`
  - updated `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/rbac_service.py` so `library_admin` is treated as global and implies `query_studio:user`
  - added `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/query_tree/saved_query_library_service.py` for library-scope query/folder writes
  - wired `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/query_tree_routes.py` so:
    - `POST /api/v1/saved-queries/<id>/save-to-library` publishes into Library
    - library query/folder create/move/rename/delete all use library service for `library_admin`
    - library query/folder routes no longer fall through to personal-query services
- Frontend:
  - updated `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/components/saved-queries/SavedQueriesTreeSection.tsx`
    - adds `Save to Library` for eligible my/shared/recent queries
    - enables library query context menus with role-aware options
    - enables library root/folder menus for library admins and workspace admins
  - updated `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/QueryForgePage.tsx`
    - derives `library_admin` / `workspace_admin` / `super_admin` from token roles
    - wires save-to-library action
    - routes library moves through a generic move dialog
  - updated `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/components/MoveModalDialog.tsx`
    - generalized from “My” only to either My tree or Library tree
  - updated query-tree API client wrappers:
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/clients/queryTreeClient.ts`
    - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/queryTreeApi.ts`
  - updated client role normalization in `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/access-admin/model/userSlice.ts`
- Verification completed:
  - backend: `python3 -m pytest tests/routes/test_query_tree_routes.py -q`
    - Result: 5 passed, 2 skipped
  - frontend:
    - `npm test -- --run src/shared/components/saved-queries/SavedQueriesTreeSection.test.tsx`
      - Result: 2 passed
    - `npm test -- --run src/shared/components/saved-queries/SavedQueriesTreeSection.test.tsx src/features/query-forge/ui/__tests__/QueryForgePage.test.tsx -t "renders smoke UI with primary builder controls"`
      - Result: 1 passed, 24 skipped
    - Existing warning remains: `Missing VITE_API_URL`
  - Note:
    - the broader existing `QueryForgePage.test.tsx` suite still has unrelated MSW failures around unhandled `POST /api/v1/planner/plan_domain` requests in AI copilot tests; those were not introduced by this library-admin change

- Follow-up fix:
  - workspace admins were not seeing the Library `New folder…` menu because `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/QueryForgePage.tsx` was deriving library-admin gating from JWT roles only
  - updated it to combine token roles with profile/effective roles loaded into app state, so workspace admins and library admins now see the Library folder-management menu even when the JWT does not carry the canonical role name

## Latest workspace-features and user-management fixes

- Investigated why `workspace-features` looked dead for `workspace_admin` and found 3 separate issues:
  - workspace feature enable/disable endpoints were still `super_admin` only
  - the Organization / Workspace selectors on the access-control pages were backed by `/api/v1/admin/organizations` and `/api/v1/admin/workspaces`, which were `system:admin` only
  - user management list and counts were still global, not workspace-scoped, and the user search only matched `username` prefix instead of email/name fields

- Backend fixes implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/workspace_feature_routes.py`
    - changed feature `POST` and `DELETE` to `@require_admin()` so `workspace_admin` can enable/disable workspace features
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/admin_routes.py`
    - changed `GET /api/v1/admin/organizations` and `GET /api/v1/admin/workspaces` to `@require_admin()`
    - for non-`super_admin` admins, those list endpoints now scope to the current `X-Workspace-Id` instead of exposing global tenancy data
    - added helpers to derive the current workspace binding and return paged scoped results
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/user_service.py`
    - `get_users(...)` now scopes to the current workspace when `workspace_id` is provided
    - user search now matches `username`, `email`, `first_name`, `last_name`, and full name using contains matching
    - `get_counts(...)` now scopes to the current workspace when `workspace_id` is provided
    - `get_user(...)` now enforces workspace visibility when a workspace scope is provided
    - `get_user_workspaces(...)` can now scope workspace rows to the current workspace
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/user_routes.py`
    - passes `X-Workspace-Id` into user list and user counts

- Expected UI impact without additional frontend edits:
  - `workspace-features` Organization / Workspace dropdowns should populate for `workspace_admin`
  - workspace feature toggles should no longer be disabled by RBAC once a workspace is selected
  - Invite/Edit user workspace selectors and role-assignment workspace selectors should stop failing due to empty tenancy lists
  - user list/counts/search should now behave like workspace-scoped admin tooling rather than a global user directory

- Verification completed:
  - `python3 -m pytest tests/routes/test_workspace_feature_routes.py tests/routes/test_admin_routes.py tests/routes/test_user_routes.py tests/services/test_user_service.py -q`
    - Result: `92 passed, 3 skipped`

## Latest Skills destination admin visibility fix

- Investigated why a `workspace_admin` could not see `+ Add destination` on the Skills -> Destinations tab even though the backend destination routes already allowed workspace admins.
- Root cause:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/pages/SkillsPage.tsx` was deriving destination admin visibility from local role parsing instead of the app's canonical capability state
  - this made the UI gate less reliable than the rest of the app for workspace-scoped admin sessions
- Frontend fix implemented:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/pages/SkillsPage.tsx`
    - now uses `useCan()` and the canonical `skills:admin` capability / `skills` admin role to decide whether destination create/edit controls are visible
    - removed the ad hoc token/profile admin derivation from the page
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/__tests__/SkillsPage.test.tsx`
    - added a regression proving a `workspace_admin` session with `skills:admin` capability sees the destination creation controls
- Verification completed:
  - `npm test -- --run src/features/skills/__tests__/SkillsPage.test.tsx src/features/skills/__tests__/SkillBuilderDrawer.test.tsx`
    - Result: `4 passed`
    - Existing warning remains: `Missing VITE_API_URL`

## Latest destination encryption fix

- Investigated destination create failure on:
  - `POST /api/v1/workspaces/<workspace_id>/destinations/`
- Root cause had two parts:
  - the runtime environment did not have `DESTINATION_ENCRYPTION_KEY` set
  - the app was not wiring `DESTINATION_ENCRYPTION_KEY` from env into `app.config`, so destination encryption could not work even if the env var existed
- Backend fixes implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/config/__init__.py`
    - added `DESTINATION_ENCRYPTION_KEY = os.getenv("DESTINATION_ENCRYPTION_KEY", "").strip() or None`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/factory.py`
    - now sets `app.config["DESTINATION_ENCRYPTION_KEY"] = DESTINATION_ENCRYPTION_KEY`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/destination_routes.py`
    - destination create/update now catch missing-encryption-key `RuntimeError` and return a clean JSON error with HTTP 503 instead of an unhandled traceback
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/.env.example`
    - added `DESTINATION_ENCRYPTION_KEY=`
- Tests added/updated:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/test_destinations.py`
    - added route coverage proving destination create returns a clear error when the key is missing
- Verification completed:
  - `python3 -m pytest tests/test_destinations.py -q`
    - Result: `24 passed`

## Latest workspace_destinations schema fix

- Investigated destination create failure after encryption was fixed and found a database schema mismatch:
  - `workspace_destinations.created_by` and `updated_by` were defined as `INT`
  - the application writes actor ids as strings / UUIDs (for example `16167dac-606c-4843-b780-d95cd530b967`)
  - MySQL was failing on insert with `Data truncated for column 'created_by'`
- Fixes implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/models/domain/destinations.py`
    - changed `created_by` and `updated_by` from `Integer` to `String(255)`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/migrations/20260316_add_workspace_destinations.sql`
    - corrected the original table definition to use `VARCHAR(255)` for both columns
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/migrations/20260321_fix_workspace_destinations_actor_columns.sql`
    - added forward migration for existing databases:
      - `ALTER TABLE workspace_destinations MODIFY COLUMN created_by VARCHAR(255) NULL, MODIFY COLUMN updated_by VARCHAR(255) NULL`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/query_forge_demo_ddl.sql`
    - updated demo DDL accordingly
- Verification completed:
  - `python3 -m pytest tests/test_destinations.py -q`
    - Result: `24 passed`

## Latest webhook SSL fix

- Investigated destination test failures returning:
  - `Slack webhook error: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1000)>`
- Root cause:
  - webhook delivery used Python `urllib` with the local interpreter's default trust store
  - on this machine, `curl` trusted the Slack certificate chain via the system store, but Python did not
- Backend fix implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/skills/delivery/__init__.py`
    - webhook-based delivery channels now use an explicit SSL context built from `certifi.where()`
    - applied to:
      - `SlackDeliveryChannel`
      - `TeamsDeliveryChannel`
      - `GenericWebhookDeliveryChannel`
    - added `_ssl_context()` helper
- Tests updated:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/test_destinations.py`
    - added coverage proving Slack delivery calls `urlopen(..., context=_ssl_context())`
- Verification completed:
  - `python3 -m pytest tests/test_destinations.py -q`
    - Result: `25 passed`

## Latest Skills destinations table refresh

- Follow-up UI issues on the Skills -> Destinations tab:
  - after a successful destination test, the row badge could still show `Failed` because the table status was driven by stale list data
  - the table did not match the rest of the app's table patterns
  - admins wanted row click to open edit, with compact icon actions for test/delete
- Frontend changes implemented:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/DestinationsTab.jsx`
    - successful and failed test actions now patch the tested row in local state immediately:
      - `last_test_status`
      - `last_test_message`
      - `last_tested_at`
    - admin row click now opens the edit drawer
    - action strip now uses icon buttons:
      - test: flask icon / spinner while running
      - deactivate: ban icon
      - delete: trash icon for inactive rows
    - switched the table to a more standard card + responsive table layout
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/styles/skills.css`
    - added shared styling for destinations table rows, badges, icon actions, feedback strip, and drawer
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/__tests__/DestinationsTab.test.tsx`
    - added regression tests proving:
      - a successful test immediately updates the row from `Failed` to `Healthy`
      - clicking a destination row opens the edit drawer
- Verification completed:
  - `npm test -- --run src/features/skills/__tests__/DestinationsTab.test.tsx src/features/skills/__tests__/SkillsPage.test.tsx src/features/skills/__tests__/SkillBuilderDrawer.test.tsx`
    - Result: `6 passed`
    - Existing warning remains: `Missing VITE_API_URL`

## Latest saved_query title fix for skills/query analysis

- Investigated skill execution failure:
  - `(pymysql.err.OperationalError) (1054, "Unknown column 'name' in 'field list'")`
  - failing SQL:
    - `SELECT sql_json, name FROM saved_query ...`
- Root cause:
  - the current `saved_query` table uses `title`, not `name`
  - two stale code paths were still selecting `saved_query.name`
- Backend fixes implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/tasks/skill_runner.py`
    - changed saved query lookup to `SELECT sql_json, title AS name FROM saved_query ...`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/query_analysis_routes.py`
    - changed query analysis lookup to `SELECT sql_json, title AS name FROM saved_query ...`
- Tests updated:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/tasks/test_skill_runner.py`
    - added coverage proving the aliased saved query title flows through as the query name
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/test_query_analysis.py`
    - added coverage proving `_run_query()` uses the saved query title alias
- Verification completed:
  - `python3 -m pytest tests/tasks/test_skill_runner.py tests/test_query_analysis.py -q`
    - Result: `18 passed, 6 skipped`

## Latest skills run normalization and Slack skip investigation

- Investigated why a skills run appeared to "work" but did not post to Slack.
- Live execution state confirmed:
  - latest run for skill `d7503926-b3c2-443d-8ce4-9b5c3aef7b15` was not a delivery success
  - `skill_executions.result_json` recorded:
    - `success: true`
    - `message: "No rows returned — webhook skipped (send_if_empty=False)."`
    - `data.skipped: true`
    - `data.row_count: 0`
  - the saved skill config also had no Slack target bound:
    - `destination_id: null`
    - `webhook_url: ""`
  - a workspace destination does exist and has a successful test:
    - `workspace_destinations.id = 1`
    - `name = "QueryForge All Channel"`
    - `last_test_status = "success"`
- Backend fix implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/skills_routes.py`
    - `_normalize_skill_run_row()` now:
      - parses `result_json`
      - remaps `status` from `success` to `skipped` when `result_json.data.skipped = true`
      - surfaces the actual skill message from `result_json.message`
- Tests updated:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/routes/test_skills_routes.py`
    - added regression proving successful skip executions are returned as:
      - `status = "skipped"`
      - `message = "No rows returned — webhook skipped (send_if_empty=False)."`
- Verification completed:
  - `python3 -m pytest tests/routes/test_skills_routes.py -q`
    - Result: `8 passed`

## Latest skills builder usability and timeline refresh

- User reported the Skills builder drawer was too busy, unclear about destination attachment, and had bunched footer actions.
- UI improvements implemented in:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/SkillBuilderDrawer.tsx`
    - removed the cramped meta strip and reorganized the builder into:
      - an onboarding-style step summary (`Set Up`, `Add Logic`, `Attach Delivery`)
      - a top overview card with linked query, status, description, templates, and delivery readiness
      - an always-visible delivery summary list that lets users click directly into each action to configure destinations
    - footer actions now use a clear left/right layout instead of bunching in the lower-left corner
    - draft saves remain permissive, while final saves still respect full validation
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/SkillBlockCard.tsx`
    - action previews now show meaningful delivery state like:
      - `Saved destination attached`
      - `Direct webhook configured`
      - `Needs a destination or webhook`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/SkillBlockConfigPanel.tsx`
    - generic `Block Configuration` header replaced with contextual headings and helper copy
    - action config now explicitly explains that destinations are attached there
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/styles/skills.css`
    - added layout and presentation styles for the new overview, stepper, delivery summary, sticky config panel, and responsive footer
- Validation improvement implemented:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/hooks/useSkillBuilder.ts`
    - final save now blocks delivery actions that have neither a saved destination nor a direct target
    - examples:
      - email actions need destination or recipients
      - Slack/webhook actions need destination or webhook URL
- Timeline improvements implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/skills_routes.py`
    - run normalization now synthesizes basic timeline events:
      - queued
      - started
      - finished/skipped/failed
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/SkillRunsPanel.tsx`
    - if a run still has no explicit events, the UI falls back to a summary timeline event from the run message
- Verification completed:
  - API: `python3 -m pytest tests/routes/test_skills_routes.py -q`
    - Result: `8 passed`
  - UI: `npm test -- --run src/features/skills/__tests__/SkillBuilderDrawer.test.tsx src/features/skills/__tests__/SkillsPage.test.tsx`
    - Result: `4 passed`
    - Existing warning remains: `Missing VITE_API_URL`

## Latest skills run detail inspector

- User asked for a way to inspect run details beyond the current summary/timeline.
- Frontend/API client updates implemented:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/types.ts`
    - expanded `SkillRun` with:
      - `createdAt`
      - `errorMessage`
      - `result`
      - `triggeredBy`
      - `jobId`
      - `scheduleId`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/api.ts`
    - `listSkillRuns()` normalization now preserves detailed run fields from the backend payload, including `result_json`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/components/SkillRunsPanel.tsx`
    - right-hand pane now shows:
      - outcome/status
      - queued/started/finished timestamps
      - duration
      - triggered-by user
      - job id
      - error block when present
      - timeline
      - pretty-printed result payload JSON
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/styles/skills.css`
    - added styling for run detail summary, metadata grid, error panel, and result JSON viewer
- Tests added/updated:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/__tests__/skillsApi.test.ts`
    - verifies detailed run normalization
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/skills/__tests__/SkillRunsPanel.test.tsx`
    - verifies the detail pane renders metadata and result payload
- Verification completed:
  - `npm test -- --run src/features/skills/__tests__/skillsApi.test.ts src/features/skills/__tests__/SkillRunsPanel.test.tsx src/features/skills/__tests__/SkillBuilderDrawer.test.tsx src/features/skills/__tests__/SkillsPage.test.tsx`
    - Result: `14 passed`
    - Existing warning remains: `Missing VITE_API_URL`

## Latest skills saved-query lookup fix for library/global queries

- User asked whether there was a way to see the query a skill ran because a skill reported `No rows returned` even though the query works interactively.
- Runtime investigation of the exact skill/query showed:
  - skill `d7503926-b3c2-443d-8ce4-9b5c3aef7b15` points at saved query `c3c153c8-94aa-4f4f-9103-be1bcc185ef5`
  - that `saved_query` row exists with:
    - `title = "Born in Mexico"`
    - `workspace_id = NULL`
    - `is_deleted = 0`
  - `app/tasks/skill_runner.py::_execute_skill_query()` was still looking up:
    - `WHERE id = :id AND workspace_id = :ws`
  - so the skill runner treated the query as missing, logged a warning, and returned the empty fallback bundle, which then led to:
    - `No rows returned — webhook skipped (send_if_empty=False).`
- Backend fixes implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/tasks/skill_runner.py`
    - saved query lookup now allows library/global rows:
      - `WHERE id = :id AND (workspace_id = :ws OR workspace_id IS NULL) AND is_deleted = 0`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/query_analysis_routes.py`
    - applied the same fix to inline query analysis re-execution
- Tests updated:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/tasks/test_skill_runner.py`
    - added coverage proving global/library saved queries are accepted
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/test_query_analysis.py`
    - added coverage proving `_run_query()` accepts global/library saved queries
- Verification completed:
  - `python3 -m pytest tests/tasks/test_skill_runner.py tests/test_query_analysis.py -q`
    - Result: `20 passed, 6 skipped`

## Latest frontend workspace-table contract cleanup

- Resumed the frontend cleanup for legacy `model_table` / `model_column` usage after backend compatibility work had already landed.
- Updated UI service/contracts in the UI repo so workspace-first table naming is normalized instead of relying on legacy table-name fields:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/queryStudioAdminApi.ts`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/schemas.ts`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/semantic/conceptColumnMaps.ts`
- UI behavior updates:
  - Concept Column Maps now reads/displays `workspace_table_name` and labels that column as `Workspace Table`.
  - Domain Studio surfaces now refer to `Primary table` / `table` instead of `Model` in the affected domain-management screens.
  - Query Forge domain selection fallback now prefers `primary_table_name` when present.
- Updated UI files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/ConceptColumnMapsPage.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/domain-studio/ui/components/DomainDrawer.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/domain-studio/ui/components/DomainsTab.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/domain-studio/ui/components/DomainDrawerTablesTab.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/domain-studio/ui/components/DomainTableModal.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/components/DomainSection.tsx`
- Tests updated:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/__tests__/semanticServices.test.ts`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/__tests__/queryStudioRouteContracts.test.ts`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/semantic-admin/ui/__tests__/ConceptColumnMapsPage.test.tsx`
- Verification completed:
  - `npm test -- --run src/shared/services/__tests__/semanticServices.test.ts src/shared/services/__tests__/queryStudioRouteContracts.test.ts src/features/semantic-admin/ui/__tests__/ConceptColumnMapsPage.test.tsx`
  - Result: `47 passed`
  - Existing warning remains: `Missing VITE_API_URL. Add it to your .env file.`
- Additional verification attempted:
  - `npx tsc --noEmit`
  - Result: fails due to many unrelated pre-existing TypeScript errors in untouched areas (`domain-graph`, `identity`, `skills`, `forgeMatch`, `semantic-catalog`, etc.); no reported errors were in the files touched for this cleanup.

## Latest frontend TypeScript cleanup pass

- Continued the UI repo cleanup to eliminate the previously noted pre-existing `npx tsc --noEmit` failures.
- Non-ForgeMatch cleanup completed in the affected files:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/ai/__tests__/AiCopilotDrawer.test.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/domains/DomainProfileList.test.tsx`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/system-admin/ui/tenancy/TenancyOrganizationsPage.tsx`
- ForgeMatch cleanup completed by separating local workbook-analysis types from the API response contracts instead of forcing both flows through one incompatible shape:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/forgeMatch/contracts.ts`
    - added explicit local pipeline types such as `ForgeMatchCandidate`, `ForgeMatchConfidenceBreakdown`, `ForgeMatchSession`, `ForgeMatchPipelineSourceRecord`, `ForgeMatchPipelineMapping`, `ForgeMatchPipelineSummary`, and `ForgeMatchPipelineAnalyzeResponse`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/forgeMatch/pipeline.ts`
    - switched workbook parsing / local analysis helpers to the new pipeline-specific types
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/forgeMatch/persistence.ts`
    - updated local storage session persistence to use the pipeline-specific types
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/forgeMatch/__tests__/pipeline.test.ts`
    - pipeline tests now compile cleanly against the restored local types
- Also updated a stale AI copilot test expectation to match current behavior:
  - deferred `planDomainNextActions()` requests currently include `workspace_id`, `prompt`, `plan_json_v2`, `base_domain_id`, `conversation_id`, and `trace_id`, but not a top-level `vertical_norm`
- Verification completed:
  - `npx tsc --noEmit`
    - Result: passes with no TypeScript errors
  - `npm test -- --run src/shared/services/forgeMatch/__tests__/contracts.test.ts src/shared/services/forgeMatch/__tests__/pipeline.test.ts src/features/query-forge/ui/ai/__tests__/AiCopilotDrawer.test.tsx src/features/system-admin/ui/domains/DomainProfileList.test.tsx`
    - Result: `33 passed`
    - Existing warning remains: `Missing VITE_API_URL. Add it to your .env file.`

## Latest frontend removal of dead news/cohort surfaces

- User asked to remove the frontend references to `news` and cohort visibility because those routes should not exist on the frontend at all.
- Removed the dead news API/UI surface in the UI repo:
  - deleted `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/news.ts`
  - deleted `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/landing/ui/NewsArticles.tsx`
- Removed the dead cohort visibility API wrapper and mock fixture:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/shared/services/queryStudioAdminApi.ts`
    - removed `CohortVisibilityRow`
    - removed `CohortVisibilityResponse`
    - removed `getVisibleCohorts()`
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/qa/msw/handlers.ts`
    - removed the `/saved-queries/cohorts/visible` handler
  - deleted `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/qa/fixtures/queryForge/cohortVisibility.json`
- Removed the dormant cohort join UI path from Query Forge domain selection while preserving the ability to clear any legacy `cohortAttachment` state already present in `sqlJson`:
  - `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui/src/features/query-forge/ui/components/DomainSection.tsx`
    - removed the cohort visibility import/types
    - removed the cohort join modal and cohort join section
    - updated copy from `cohorts/value overrides` to `value overrides`
    - kept the existing `cohortAttachment` summary/clear path so legacy state is still visible/removable
- Verification completed:
  - `npx tsc --noEmit`
    - Result: passes
  - `npm test -- --run src/shared/services/__tests__/queryStudioRouteContracts.test.ts`
    - Result: `12 passed`

## Latest semantic registry datetime serialization fix

- A live backend request to `GET /api/v1/semantic/registry?limit=1` failed with:
  - `TypeError: Object of type datetime is not JSON serializable`
- Root cause:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/semantic/semantic_registry_service.py`
  - `SemanticRegistryService._normalize_row()` coerced bool/int fields but left `created_at` and `updated_at` as raw `datetime` objects when returned from MySQL.
- Fix implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/semantic/semantic_registry_service.py`
    - added `_json_ready_datetime()`
    - now converts `datetime` / `date` values in `created_at` and `updated_at` to ISO 8601 strings during row normalization
- Regression coverage added:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/semantic/test_semantic_registry_service.py`
    - added service-level test proving datetime fields are normalized to strings
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/routes/test_semantic_routes.py`
    - added route-level test exercising `/api/v1/semantic/registry` through the real service over a fake SQL port and asserting JSON-safe timestamps
- Verification completed:
  - `python3 -m pytest tests/services/semantic/test_semantic_registry_service.py tests/routes/test_semantic_routes.py -q`
    - Result: `12 passed`

## Latest datasource RBAC cleanup

- Smoke testing exposed that `GET /api/v1/datasources/` still required `system:admin`, which blocked the normal smoke user even though datasources are intended to be a workspace-admin surface.
- Fix implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/routes/datasource_routes.py`
    - replaced `@require_role("system:admin")` with `@require_admin()`
    - datasources now follow the same workspace-admin access model as the broader ingestion area
- Regression coverage tightened:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/analytics/test_datasource_routes.py`
    - expanded auth mocking to control effective roles explicitly
    - added a route test proving `workspace_admin` can list datasources without the legacy `is_admin` flag
    - added a route test proving a non-admin feature role still gets `403`
- Verification completed:
  - `pytest tests/analytics/test_datasource_routes.py -q`
    - Result: `9 passed`
  - `pytest tests/test_smoke_test.py -q`
    - Result: `35 passed`

## Latest users legacy-query regression check

- A live `GET /api/v1/users/<id>` failure log referenced the removed `product_roles` / `products` join path in `app.services.user_service`.
- Current source on disk no longer contains any of those legacy joins; both `get_user()` and `find_user_by_username()` read directly from `users` and attach workspaces/RBAC separately.
- Added regressions to pin that behavior:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/test_user_service.py`
    - added a `get_user()` test asserting the primary query uses `FROM users` and never references `product_roles`, `products`, or `user_product_map`
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/routes/test_user_routes.py`
    - added a `/api/v1/users/<id>` route test proving the detail endpoint redacts `password` and `otp_secret` and forwards `X-Workspace-Id`
- Verification completed:
  - `pytest tests/services/test_user_service.py tests/routes/test_user_routes.py -q`
    - Result: `43 passed, 4 skipped`
  - `pytest tests/routes/test_auth_routes.py -q`
    - Result: `16 passed`
- Operational note:
  - If that exact `product_roles` SQL still appears at runtime, the app server is running stale code and needs to be restarted/reloaded.

## Latest planner relative-time SQL mapping fix

- A live planner result for the prompt "Which schools have the highest number of absences this month?" showed correct normalized `plan_json_v2.time` output (`2026-03-01` through current date), but the compiled `sql_json` still contained the original placeholder filters:
  - `calendar_date >= "this month"`
  - `calendar_date <= "this month"`
  - plus the normalized `between ["2026-03-01", "2026-03-23"]`
- Root cause:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/planner_domain/map_to_sqljson.py`
  - the mapper copied plan filters first, then always appended the normalized custom time `between` filter without stripping same-column relative placeholders.
- Fix implemented:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/app/services/planner_domain/map_to_sqljson.py`
    - when `time.time_range == "custom"` and `time.time_column_key` is present, the mapper now drops same-column relative-time placeholder filters before adding the executable `between` filter
    - covers canonical relative tokens such as `this month`, `last month`, `this quarter`, `last quarter`, `this year`, and `last year`
- Regression coverage added:
  - `/Users/mmaslak/Local Documents/projects/query-forge-api/tests/services/planner_domain/test_map_to_sqljson.py`
    - added a mapper test proving relative placeholder filters are removed and only the normalized `between` predicate remains
- Verification completed:
  - `pytest tests/services/planner_domain/test_map_to_sqljson.py -q`
    - Result: `12 passed`
  - `pytest tests/services/planner_domain/test_service.py -q`
    - Result: `47 passed`
- Behavior note:
  - planner `"this month"` currently means month-to-date for the current month, anchored by the domain time policy timezone when configured.

## Query Studio AI Summary feature (2026-03-22)

Both repos bumped to version 0.3.0.

### What was built

A stateless `POST /api/v1/query-studio/summarize` endpoint that accepts a result-set payload from the client, caps it to a configurable row limit, passes it through the shared `analysis_utils` LLM pipeline, and returns a natural-language summary of the data.

### Backend files

- `app/routes/query_studio_summary_routes.py` — Flask-RestX namespace, single POST resource, registered under the `query_studio` feature
- `app/services/query_studio_summary_service.py` — service layer; enforces `QUERY_STUDIO_SUMMARY_MAX_ROWS` (default 100) row cap before calling the LLM pipeline; uses the shared `analysis_utils` helpers
- `app/exceptions/llm_unavailable_error.py` — `LLMUnavailableError` exception class

### Error handling

- `LLMUnavailableError` raised by the service maps to HTTP 503
- Any other unhandled exception maps to HTTP 500
- Both return the standard JSON envelope `{ "status", "message", "data" }`

### Configuration

- `QUERY_STUDIO_SUMMARY_MAX_ROWS` env/config key (default `100`) — rows beyond this limit are silently truncated before the LLM call

### Frontend files (query-forge-ui)

- `src/features/query-forge/ui/hooks/useResultSummary.ts` — React Query mutation hook; posts rows to `/api/v1/query-studio/summarize`, manages loading/error state
- `src/features/query-forge/ui/components/ResultSummary.tsx` — UI component rendering the AI summary panel (trigger button, loading skeleton, summary text, error message)
- `src/features/query-forge/ui/components/PreviewSection.tsx` — wired in `ResultSummary` below the query result grid; passes current result rows into the hook

### Version bumps

- `query-forge-api`: `pyproject.toml` / `app/__init__.py` → `0.3.0`
- `query-forge-ui`: `package.json` → `0.3.0`

## Tenancy membership display cleanup

- Organization and workspace membership API rows now include joined user profile fields: `username`, `email`, `first_name`, `last_name`, and `display_name`.
- The organization admin UI now shows member names/email instead of raw `user_id` as the primary membership label.
- Organization membership roles in the add/edit flows are dropdowns with `member` and `org_admin` options.
- Verification completed:
  - API: `./scripts/pytest.sh tests/services/tenancy/test_tenancy_admin_service.py -q`
  - UI: `npm test -- --run src/features/system-admin/ui/tenancy/TenancyOrganizationsPage.test.tsx`
  - UI build: `npm run build`

## Tenancy workspace-binding admin access fix

- Fixed `GET/PATCH /api/v1/admin/workspaces/<workspace_id>/binding` so `workspace_admin` can view and update the current workspace binding instead of being blocked by `system:admin`.
- Scoped workspace-admin updates must stay in the current workspace organization, and datasource changes are validated against the current organization.
- Workspace create/delete remain `system:admin` only.
- Backend version bumped to `0.3.335`.
- Verification completed:
  - `./scripts/pytest.sh tests/routes/test_admin_routes.py -q -k "workspace_binding"`
  - `.venv/bin/ruff check app/routes/admin/tenancy_routes.py tests/routes/test_admin_routes.py`

## MCP workspace feature toggle

- Added `queryforge_mcp` to the workspace-feature management catalog without adding it to RBAC `FEATURE_KEYS`, preserving the no workspace-admin/super-admin MCP role implication decision.
- The Workspace Features UI now renders an `MCP Server` card and toggles it through the same workspace feature API as other features.
- Backend toggle writes both the generic `workspace_features` row and `workspace_mcp_settings.enabled`; MCP settings are written first to avoid partial enablement.
- Effective access summaries do not grant MCP access from `workspace_admin` alone; users still need MCP-specific roles/grants.
- Version bumps:
  - API: `0.3.336`
  - UI: `0.4.22`
- Verification completed:
  - `./scripts/pytest.sh tests/routes/test_workspace_feature_routes.py tests/test_rbac.py -q -k "workspace_feature or mcp_roles"`
  - `.venv/bin/ruff check app/models/rbac.py app/features/workspaces/workspace_feature_api.py app/repositories/mcp_oauth/mcp_access_repository.py tests/routes/test_workspace_feature_routes.py tests/test_rbac.py`
  - `npm test -- --run src/features/access-control/__tests__/WorkspaceFeatureManagementPage.test.tsx src/features/access-control/__tests__/accessControlApi.test.ts`
  - `npm run build`

## MCP OAuth local loopback redirects

- Added `OAUTH_ALLOW_LOOPBACK_REDIRECTS` for local OAuth clients such as Codex.
- Default remains `false`; production registrations are still restricted to HTTPS redirect URIs under `OAUTH_ALLOWED_REDIRECT_HOSTS`.
- When enabled, dynamic client registration accepts loopback redirect URIs on `localhost`, `127.0.0.1`, and `::1` over `http` or `https`.
- Authorization requests now default a missing OAuth `resource` parameter to `MCP_RESOURCE_URL`, matching Codex local MCP login behavior while still rejecting explicit mismatched resources.
- Dynamic client registration now defaults omitted client scopes to all supported MCP OAuth scopes (`qf:mcp:read`, `qf:mcp:plan`, `qf:mcp:preview`) so local Codex can request preview during authorization; preview execution remains protected by QueryForge RBAC and Query Studio access checks.
- OAuth authorize GET now returns a real `text/html` Flask response instead of a JSON-encoded template string, so browser-based consent renders normally.
- OAuth authorize GET now renders a polished split-card QueryForge consent page with clearer resource, scope, credential, and safety messaging.
- The global security-header middleware now preserves route-specific CSP values, and the OAuth consent page uses a narrow CSP that allows only inline styles for the server-rendered form while keeping scripts blocked.
- OAuth authorize page colors now use the QueryForge palette: teal primary `#2b5f60`, copper secondary `#c06240`, orange accent `#ff4d1f`, dark chrome, and light canvas surfaces.
- OAuth authorize page now uses the cropped QueryForge logo mark from `/static/images/qf_logo_mark.png` in the brand block; the page-specific CSP allows same-origin images while keeping scripts blocked.
- OAuth authorize page CSP now includes the registered redirect origin in `form-action`, allowing browser form POST redirects to local Codex callback ports while preserving the tight page-specific CSP.
- Backend version bumped to `0.3.345`.
- Verification completed:
  - `./scripts/pytest.sh tests/config/test_mcp_oauth_config.py tests/services/mcp_oauth/test_dynamic_client_registration_service.py tests/services/mcp_oauth/test_authorization_code_service.py tests/services/mcp_oauth/test_token_service.py -q`
  - `.venv/bin/ruff check app/config/mcp_oauth_config.py app/services/mcp_oauth/dynamic_client_registration_service.py tests/config/test_mcp_oauth_config.py tests/services/mcp_oauth/test_dynamic_client_registration_service.py tests/services/mcp_oauth/test_authorization_code_service.py tests/services/mcp_oauth/test_token_service.py`
  - `./scripts/pytest.sh tests/services/mcp_oauth/test_authorization_code_service.py tests/services/mcp_oauth/test_token_service.py tests/routes/test_mcp_oauth_metadata_routes.py -q`
  - `.venv/bin/ruff check app/services/mcp_oauth/authorization_code_service.py tests/services/mcp_oauth/test_authorization_code_service.py`
  - `./scripts/pytest.sh tests/services/mcp_oauth/test_dynamic_client_registration_service.py tests/services/mcp_oauth/test_authorization_code_service.py tests/routes/test_mcp_oauth_metadata_routes.py -q`
  - `.venv/bin/ruff check app/services/mcp_oauth/dynamic_client_registration_service.py tests/services/mcp_oauth/test_dynamic_client_registration_service.py`
  - `./scripts/pytest.sh tests/routes/test_mcp_oauth_metadata_routes.py -q`
  - `.venv/bin/ruff check app/features/mcp_oauth/routes.py tests/routes/test_mcp_oauth_metadata_routes.py`

## MCP app-principal admin UI

- Added workspace-scoped admin APIs at `/api/v1/workspaces/<workspace_id>/mcp/app-principals` for listing and creating non-human MCP app principals, plus `DELETE /api/v1/workspaces/<workspace_id>/mcp/app-principals/<client_id>` for revocation.
- App-principal creation writes both `mcp_app_clients` and `mcp_principal_grants`; the plaintext client secret is returned only once and only the SHA-256 hash is persisted.
- App grants support tool allow-lists, domain-key allow-lists, preview permission, preview row limits, and optional expiration. Empty tool/domain lists mean all currently supported tools/domains for the grant.
- Added the frontend admin screen at `/admin/mcp/app-principals` and sidebar item under Admin. Workspace admins can select an organization/workspace, create credentials, copy the one-time secret, inspect grant status, and revoke principals.
- Version bumps:
  - API: `0.3.348`
  - UI: `0.4.23`
- Verification completed:
  - API: `./scripts/pytest.sh tests/services/mcp_oauth/test_app_principal_service.py tests/routes/test_mcp_app_principal_routes.py tests/repositories/test_mcp_oauth_access_repositories.py -q`
  - API lint: `.venv/bin/ruff check app/features/mcp_oauth/app_principal_api.py app/features/mcp_oauth/routes.py app/repositories/mcp_oauth/mcp_access_repository.py app/services/mcp_oauth/app_principal_service.py app/services/mcp_oauth/__init__.py tests/services/mcp_oauth/test_app_principal_service.py tests/routes/test_mcp_app_principal_routes.py tests/repositories/test_mcp_oauth_access_repositories.py`
  - UI: `npm test -- --run src/features/access-control/__tests__/MCPAppPrincipalsPage.test.tsx src/features/access-control/__tests__/WorkspaceFeatureManagementPage.test.tsx`
  - UI: `npm test -- --run src/app/chrome/sidebar/widgets/menuList/useNewMenuList.adminAccess.test.tsx src/features/access-control/__tests__/accessControlApi.test.ts`
  - UI build: `npm run build`

## FlowForge QueryForge module

- FlowForge is now being integrated as a QueryForge module rather than a separate app/repo.
- Added backend feature package `app/features/flowforge` with read-only seeded workflow definitions, graph validation, and a run-inspector placeholder.
- Added initial API surface:
  - `GET /api/v1/flowforge/workflows`
  - `GET /api/v1/flowforge/workflows/<workflow_id>`
  - `POST /api/v1/flowforge/workflows/validate`
  - `GET /api/v1/flowforge/workflows/<workflow_id>/run-inspector`
  - `POST /api/v1/flowforge/webhooks/jotform/<webhook_public_id>`
- Jotform webhook intake now uses persisted integration configs only. The endpoint verifies the per-integration `webhook_secret` via `X-FlowForge-Webhook-Token`, `X-Jotform-Webhook-Token`, or `token` query parameter and stores an idempotent intake event.
- The Jotform receiver normalizes JSON/form payloads and `rawRequest`, persists the intake event, and returns `202 Accepted`; asynchronous workflow execution remains future runtime work.
- Added `flowforge` to normal RBAC feature keys so workspace feature gating and `flowforge:user` / `flowforge:admin` roles follow the existing QueryForge feature pattern.
- Added frontend feature package `src/features/flowforge` with a React Flow canvas, seeded Therapist Intake Routing workflow, node inspector, validation panel, and event-first run inspector placeholder.
- Added sidebar navigation under `Automation -> FlowForge` and route `/automation/flowforge`.
- Important modeling note: the therapist routing graph contains a decline/timeout loop. Validation treats loops as warnings, not errors, because future execution should use state-machine/event semantics rather than strict DAG-only semantics.
- Added FlowForge schema/repository foundation migrations for workspace settings, workflow definitions/versions, integrations/intake events, resource sets/snapshots, matching policies/versions/simulations/evaluations, and runtime run/event tables.
- Added Resource Sets API foundation for listing/creating resource sets, listing compiled resource records, listing snapshot batches, and creating manual snapshot batches.
- Added deterministic matching policy validation/simulation with the first operator set: `equals`, `not_equals`, `in`, `not_in`, `contains`, `not_contains`, `exists`, `not_exists`, `gt`, `gte`, `lt`, `lte`, `between`, `overlaps`, `matches_context`, and `contains_context`.
- Added persisted matching policy foundation: list/get/create policy headers, list versions, and create validated draft versions. Reads require `flowforge:user`; writes currently require `flowforge:admin`; publish/runtime activation remains deferred.
- Added LLM-assisted matching-rule draft foundation: deterministic local draft generator, optional injected LLM generation path, persisted LLM draft audit records, validation metadata, and admin acceptance into a normal draft policy version.
- FlowForge LLM-assisted rule drafting now uses only the workspace LLM role `flowforge_rule_drafting`; direct default/env-based `LLMClient()` construction was removed from FlowForge.
- Added Jotform integration admin setup foundation: list integration configs and create Jotform integrations with generated public webhook id/path, one-time webhook secret, stored SHA-256 secret hash, test/production mode, field mapping, and safe response serialization.
- Added persisted Jotform public webhook intake: `ffj_...` webhook ids now resolve integration configs, verify the supplied token against the stored secret hash, normalize payloads, persist idempotent intake events, and return existing intake event ids for duplicate deliveries.
- Removed the unused scaffold Jotform workspace/workflow webhook route and global token service path; all Jotform intake now goes through persisted integration public ids.
- Added persisted integration trigger configuration: `GET /api/v1/flowforge/integrations/<integration_config_id>/triggers` and `POST /api/v1/flowforge/integrations/<integration_config_id>/triggers`.
- Integration triggers connect a persisted integration to workflow definitions/versions and store trigger mode, trigger policy, version strategy, priority, conditions, field mapping, and no-match configuration. Runtime trigger evaluation and workflow run creation remain deferred.
- Added webhook-time trigger evaluation for persisted Jotform intake. New intake events now load enabled triggers, evaluate `always` and simple `conditional` rules against normalized payload paths, store `trigger_evaluation_json`, and return selected trigger details in the webhook response.
- Duplicate Jotform deliveries now return the previously stored trigger evaluation from the idempotent intake event.
- Added initial durable runtime creation from selected pinned triggers. Webhook intake now creates idempotent `flowforge_runs` using `intake:<intake_event_id>:trigger:<trigger_id>`, stores the intake/trigger context in `run_context_json`, and appends an initial `workflow.run.created` event.
- Trigger evaluation is updated after run creation with `workflow_run_creation`, `created_run_count`, and workflow run summaries.
- Selected `latest_published` triggers without a resolved workflow version are skipped with `workflow_version_unresolved`; published-version resolution is still future work.
- Added persisted runtime visibility endpoints: `GET /api/v1/flowforge/runs`, `GET /api/v1/flowforge/runs/<run_id>`, and `GET /api/v1/flowforge/runs/<run_id>/events`.
- Runtime read endpoints are workspace-scoped, require `flowforge:user`, support basic run filtering/paging, and expose redacted run context/event payloads only.
- Added operator timeline note support through `POST /api/v1/flowforge/runs/<run_id>/notes`; notes are stored as `workflow.operator.note` run events.
- Added Phase 7A human-task foundation with run-scoped task persistence helpers and `GET /api/v1/flowforge/runs/<run_id>/human-tasks`.
- Full node execution, matching execution, notification dispatch, retries, and assignment automation remain deferred to later runtime phases.
- Completed behavior-preserving FlowForge package cleanup after file-size thresholds were exceeded:
  - split `routes.py` into `routes/` endpoint-family modules
  - split `service.py` into `service/` mixins behind the public `FlowForgeService` facade
  - split `schemas.py` into `schemas/` payload-family modules behind `register_models(namespace)`
  - split `repositories/foundation.py` into concern-specific repository modules while keeping `foundation.py` as a compatibility re-export
  - preserved public imports for `FlowForgeService`, `flowforge_ns`, `register_models`, and repository classes
- Completed Phase 6B persisted runtime read API:
  - added runtime repository methods for listing workflow runs, reading a workspace-scoped run, and listing run events
  - added service serialization for run lists, run details, and event timelines with limit/offset caps
  - added `GET /api/v1/flowforge/runs`, `GET /api/v1/flowforge/runs/<run_id>`, and `GET /api/v1/flowforge/runs/<run_id>/events`
  - run/event reads require `flowforge:user` and intentionally omit sensitive event payload JSON
- Completed Phase 6C operator timeline note API:
  - added service validation for appending notes only to workspace-scoped existing runs
  - added `POST /api/v1/flowforge/runs/<run_id>/notes`
  - notes are append-only run events with `event_type=workflow.operator.note`
  - note creation currently requires `flowforge:admin` because QueryForge RBAC only has feature `user/admin` roles today; the planned `flowforge:operator` role remains future RBAC work
- Completed Phase 7A human-task read foundation:
  - added runtime repository support for creating human tasks and listing run-scoped human tasks
  - added service serialization for human tasks with capped limits and workspace-scoped run existence checks
  - added `GET /api/v1/flowforge/runs/<run_id>/human-tasks`
  - this is the backend foundation for offer history, signed-response tasks, and needs-attention views
- Completed Phase 7B signed public action foundation:
  - added one-time signed action token persistence for human tasks; plaintext tokens are returned once and only SHA-256 hashes are stored
  - added public token inspection and accept/decline routes under `/api/v1/flowforge/public/actions/<token>`
  - accept/decline updates the human task response and appends redacted timeline events
- Completed Phase 7C notification/no-match foundations:
  - added notification audit persistence and `GET /api/v1/flowforge/runs/<run_id>/notifications`
  - added `POST /api/v1/flowforge/runs/<run_id>/no-match-escalations` to mark a run `needs_attention`, append a redacted timeline event, and queue pending email notification rows
  - notification dispatch remains a later worker phase
- Completed Phase 8 reporting foundation:
  - added `GET /api/v1/flowforge/reports/domains`
  - added `GET /api/v1/flowforge/reports/summary` for concise run-count metrics by optional mode
  - this is the first curated reporting layer while QueryForge-native semantic reporting domains remain future work
- Completed Phase 9 workflow version hardening:
  - added workflow version listing and publish repository/service support
  - added `GET /api/v1/flowforge/workflows/<workflow_definition_id>/versions`
  - added `POST /api/v1/flowforge/workflows/<workflow_definition_id>/versions/<version_id>/publish`
  - publishing requires `flowforge:admin` by default
- Completed Phase 10 initial MCP FlowForge tools:
  - added `flowforge_list_runs`, `flowforge_get_run`, `flowforge_get_run_timeline`, `flowforge_list_human_tasks`, `flowforge_get_needs_attention`, `flowforge_get_resource_profile`, `flowforge_get_matching_summary`, `flowforge_get_report_summary`, and `flowforge_add_operator_note`
  - tools call `FlowForgeService` instead of raw tables and run through the existing MCP OAuth, workspace enablement, app-principal grant, audit, and rate-limit boundary
  - human read tools require `flowforge:user` or `flowforge:admin`; human operator-note mutation requires `flowforge:admin`
  - `flowforge_set_resource_hold` was intentionally not exposed because the override table exists but the runtime/matching read path does not yet consume holds
- Completed follow-up size-threshold cleanup:
  - split runtime persistence into `runtime_runs.py`, `runtime_events.py`, `runtime_human_tasks.py`, `runtime_signed_actions.py`, and `runtime_notifications.py` behind the stable `FlowForgeRuntimeRepository`
  - split signed-action and notification orchestration into dedicated service mixins behind `FlowForgeService`
- FlowForge productionization assessment persisted:
  - root plan: `/Users/mmaslak/Local Documents/projects/query_forge/docs/plans/2026-05-05-flowforge-productionization-plan.md`
  - conclusion: FlowForge is a strong backend/module foundation but not production-ready until Celery runtime execution, runtime matching, notification dispatch, human response loops, operator/admin UI, QueryForge-native reporting, RBAC/security hardening, and production runbooks are complete
  - next implementation target should be Phase 11: Celery Runtime Dispatch Foundation
  - priority guidance: implement asynchronous runtime execution before frontend polish
- Version bumps:
  - API: `0.3.368`
  - UI: `0.4.24`
- Verification completed:
  - API: `./scripts/pytest.sh tests/features/flowforge -q`
  - MCP: `./scripts/pytest.sh mcp_server/tests -q`
  - API full suite: `./scripts/pytest.sh -q` (`3060 passed, 81 skipped`)
  - API: `./scripts/pytest.sh tests/features/flowforge/test_service.py tests/features/flowforge/test_routes.py -q`
  - API lint: `.venv/bin/ruff check app/features/flowforge tests/features/flowforge`
  - API/MCP lint: `.venv/bin/ruff check app/features/flowforge mcp_server tests/features/flowforge mcp_server/tests/test_flowforge_adapter.py mcp_server/tests/test_server_and_resources.py`
  - API diff hygiene: `git diff --check`
  - UI: `npm test -- --run src/features/flowforge/__tests__/FlowForgeStudioPage.test.tsx src/features/access-control/__tests__/accessControlApi.test.ts src/app/chrome/sidebar/widgets/menuList/useNewMenuList.adminAccess.test.tsx`
  - UI build: `npm run build`
  - `./scripts/pytest.sh tests/routes/test_mcp_oauth_metadata_routes.py -q`
  - `.venv/bin/ruff check app/features/mcp_oauth/routes.py tests/routes/test_mcp_oauth_metadata_routes.py`

## FlowForge Phase 17 authoring/versioning

- Phase 17 started and delivered the first real workflow authoring/versioning slice.
- Backend changes:
  - Added persisted workflow definition listing/get lookup in the FlowForge workflow repository.
  - Added workflow definition creation that validates the submitted graph and creates the first immutable draft version.
  - Added draft workflow version creation for existing persisted workflow definitions.
  - Updated workflow list/get service behavior so persisted definitions are returned while the seeded Therapist Intake Routing workflow remains as a fallback/reference.
  - Added `POST /api/v1/flowforge/workflows`.
  - Added `POST /api/v1/flowforge/workflows/<workflow_definition_id>/versions`.
  - Backend version bumped to `0.3.374`.
- Frontend companion changes:
  - FlowForge Studio can create a persisted draft from the active graph, edit selected node configuration through JSON, save new draft versions, view version history, and publish valid saved versions.
  - Added FlowForge workflow authoring API client calls for create draft, list versions, create version, and publish version.
  - Frontend version bumped to `0.4.28`.
- Current limitations:
  - Node editing is JSON-based for Phase 17; richer node-specific config forms remain future work.
  - The “Draft with AI” button remains disabled until workflow-drafting LLM support is implemented.
  - Visual graph topology editing remains future work.
- Verification completed:
  - API: `./scripts/pytest.sh tests/features/flowforge/test_repository_foundation.py tests/features/flowforge/test_service.py tests/features/flowforge/test_routes.py -q` (`124 passed`)
  - API lint: `.venv/bin/ruff check app/features/flowforge tests/features/flowforge/test_repository_foundation.py tests/features/flowforge/test_service.py tests/features/flowforge/test_routes.py`
  - UI: `npm test -- --run src/features/flowforge/__tests__/FlowForgeStudioPage.test.tsx src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx src/features/flowforge/__tests__/FlowForgeRuntimePages.test.tsx src/app/chrome/sidebar/widgets/menuList/useNewMenuList.queryForgeStructure.test.tsx` (`13 passed`)
  - UI build: `npm run build` passed with existing legacy Vite asset/chunk warnings.
  - Diff hygiene: `git diff --check` passed in both API and UI repos.

## FlowForge Phase 18 QueryForge-native reporting

- Backend changes:
  - Added governed FlowForge reporting domain metadata for workflow runs, intake events, matching evaluations, resource snapshots, offers/responses, assignments, and notifications.
  - Each domain now advertises a redacted read model, production-default filters, semantic registration status, sensitive excluded fields, metrics, dimensions, and starter Query Studio prompts.
  - Added `GET /api/v1/flowforge/reports/dashboard` for production-default operational metrics across the same read-model layer.
  - `GET /api/v1/flowforge/reports/summary` now defaults to `mode=production`, so test-mode records are excluded unless explicitly requested.
  - Added SQL read-model views in `migrations/20260505_flowforge_reporting_read_models.sql`; views intentionally omit raw intake payloads, normalized intake payloads, sensitive profiles, notification recipients, payload summaries, and signed-token data.
  - Backend version bumped to `0.3.375`.
- Frontend companion changes:
  - Added `/automation/flowforge/reports`.
  - Added a Reports tab to the FlowForge runtime nav.
  - Added `FlowForgeReportsPage` with production/test mode selector, dashboard metrics, governed domain cards, sensitive exclusion display, and Query Studio prompt links.
  - Frontend version bumped to `0.4.29`.
- Verification completed:
  - API: `./scripts/pytest.sh tests/features/flowforge/test_repository_foundation.py tests/features/flowforge/test_reporting_read_model_migration.py tests/features/flowforge/test_service.py tests/features/flowforge/test_routes.py -q` (`127 passed`)
  - API lint: `.venv/bin/ruff check app/features/flowforge tests/features/flowforge/test_repository_foundation.py tests/features/flowforge/test_reporting_read_model_migration.py tests/features/flowforge/test_service.py tests/features/flowforge/test_routes.py`
  - UI: `npm test -- --run src/features/flowforge/__tests__/FlowForgeRuntimePages.test.tsx src/features/flowforge/__tests__/FlowForgeStudioPage.test.tsx src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx src/app/chrome/sidebar/widgets/menuList/useNewMenuList.queryForgeStructure.test.tsx` (`14 passed`)
  - UI build: `npm run build` passed with existing legacy Vite asset/chunk warnings.

## FlowForge Phase 19 Access Control And Sensitive Data Hardening

- Backend changes:
  - Added FlowForge least-privilege role model: `flowforge:viewer`, `flowforge:operator`, `flowforge:designer`, and `flowforge:admin`, while keeping `flowforge:user` as a legacy read-only alias that maps to viewer.
  - Added role implication logic so `flowforge:admin` implies designer/operator/viewer/user, designer and operator each imply viewer/user, and designer/operator do not imply each other.
  - Remapped FlowForge endpoints by responsibility: viewer for run/report/read APIs, operator for run notes, signed action creation, and no-match escalation, designer for workflow/resource/integration/matching authoring, and admin for settings and publish.
  - Added `migrations/20260505_flowforge_rbac_roles.sql` for production role seeding.
  - Added public signed-action rate limiting using the existing auth `RateLimitService`, keyed by source IP plus a SHA-256 token fingerprint instead of the raw token.
  - Added raw webhook payload purge support via `FlowForgeIntegrationRepository.purge_expired_raw_payloads()` and Celery task `qf.flowforge.purge_expired_raw_payloads`.
  - Added `block_sensitive_reporting_mcp` workspace setting, stored in FlowForge settings JSON, for future sensitive-domain blocking in MCP/reporting read paths.
  - Backend version bumped to `0.3.376`.
- Frontend companion changes:
  - Updated feature role implication in `useCan` for viewer/operator/designer/admin without letting designer and operator satisfy each other.
  - Updated FlowForge route/sidebar guards: runs/reports read as viewer, needs-attention and notes as operator, designer/admin setup as designer, settings as admin.
  - Updated access-control role copy for the new FlowForge roles.
  - Frontend version bumped to `0.4.30`.
- Verification completed:
  - API focused: `./scripts/pytest.sh tests/test_rbac.py tests/features/flowforge/test_repository_foundation.py tests/features/flowforge/test_service.py tests/features/flowforge/test_routes.py -q` (`161 passed`)
  - API full lint/test gate: `./scripts/lint.sh` (`3111 passed, 81 skipped`; existing warnings only)
  - UI focused: `npm test -- --run src/shared/runtime/useCan.test.ts src/features/flowforge/__tests__/FlowForgeRuntimePages.test.tsx src/app/chrome/sidebar/widgets/menuList/useNewMenuList.queryForgeStructure.test.tsx` (`9 passed`)
  - UI build: `npm run build` passed with existing legacy Vite asset/chunk warnings.

## FlowForge Phase 20 Production Operations And Runbooks

- Backend/ops changes:
  - Added FlowForge worker heartbeat support in `app/features/flowforge/runtime/health.py`.
  - FlowForge Celery tasks now record heartbeat under Valkey key `flowforge:worker:last_dispatch`.
  - Celery Beat now schedules FlowForge timeout dispatch every 60 seconds, notification dispatch every 60 seconds, and expired raw-payload purge every 60 minutes.
  - Admin detailed health now includes `flowforge` with worker heartbeat, pending notification backlog, failed notification side effects, stuck run count, and failed run count.
  - Root Docker Compose now includes a `celerybeat` service in the `worker` profile, alongside the API, worker, UI/nginx, MCP, Qdrant, and Valkey services.
  - Added Docker smoke script: `/Users/mmaslak/Local Documents/projects/query_forge/scripts/smoke_flowforge_docker.sh`.
  - Added production runbook: `/Users/mmaslak/Local Documents/projects/query_forge/docs/flowforge-production-runbook.md`.
  - Updated Docker docs and API README with Celery Beat, FlowForge health, runtime maintenance, systemd unit examples, migration order, rollback notes, and incident runbooks.
  - Backend version bumped to `0.3.377`.
- Frontend companion changes:
  - Added System Health `FlowForge Runtime` card showing heartbeat state, last task, pending/failed notifications, stuck runs, failed runs, and issues.
  - Health status types now support `degraded` in addition to `ok` and `error`.
  - Frontend version bumped to `0.4.31`.
- Verification completed:
  - API focused: `./scripts/pytest.sh tests/services/admin/test_health_service.py tests/features/flowforge/test_repository_foundation.py tests/features/flowforge/test_service.py tests/features/flowforge/test_routes.py -q` (`142 passed`)
  - API lint: `.venv/bin/ruff check app/celery_app.py app/features/flowforge/runtime/health.py app/tasks/flowforge_tasks.py app/services/admin/health_service.py tests/services/admin/test_health_service.py`
  - UI focused: `npm test -- --run src/features/system-admin/ui/health/HealthDashboard.test.tsx` (`2 passed`)
  - UI build: `npm run build` passed with existing legacy Vite asset/chunk warnings.
  - Smoke script syntax: `bash -n scripts/smoke_flowforge_docker.sh`
  - Docker Compose rendering: `docker compose config`

## FlowForge UI Navigation And Page Style Polish

- FlowForge sidebar navigation was consolidated under `Automation -> FlowForge`, with runtime pages and admin pages nested below that parent.
- FlowForge pages now use a shared `FlowForgePageHeader` component backed by the existing QueryForge `qf-hero` header style.
- Removed the custom gradient/page background treatment from FlowForge page shells so the pages align with the rest of QueryForge.
- Frontend version bumped to `0.4.32`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`14 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Next Batch Requirements

- The next FlowForge batch is centered on the Designer UI.
- Requirements captured:
  - Add a left-hand palette of workflow elements, modeled after the Domain Model Builder style, with drag/drop onto the React Flow canvas.
  - Add a right-side AI chat/drawer like Query Studio so users can describe workflows in natural language and have the graph built/modified.
  - Hide raw JSON inspector editing behind an Advanced tab; default node inspectors should become user-friendly forms.
  - Add a Query Studio/ForgeMatch-style toolbar for opening/selecting workflows, saving, publishing where allowed, and common editing actions.
- Implementation should wait for the rest of the batch requirements unless the user explicitly asks to begin.

## FlowForge Designer First UI Slice

- Started the FlowForge Designer batch with frontend-only designer improvements.
- Added a left-hand workflow element palette with drag/drop and Add-button insertion onto the React Flow canvas.
- Added a QueryForge-style designer toolbar with workflow selector, AI toggle, create persisted draft, and save draft version actions.
- Added a right-side AI assistant panel shell for natural-language workflow drafting; current behavior locally infers and adds one draft step until full workspace-LLM graph generation is wired.
- Updated the node inspector so friendly Details editing is the default and raw JSON is available only under Advanced.
- Frontend version bumped to `0.4.33`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`19 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Drag Fix

- Fixed FlowForge Designer canvas node dragging.
- Root cause: React Flow node position changes were not being persisted back into the controlled `draftGraph` state.
- `WorkflowCanvas` now handles `onNodesChange` position updates and `FlowForgeStudioPage` writes those positions back into the draft graph.
- Dragged positions are included in saved draft workflow versions.
- Frontend version bumped to `0.4.34`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`20 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Palette Compact Icons

- Compact palette pass completed.
- Added per-element icons to FlowForge workflow element definitions.
- Palette elements are now compact icon-plus-label buttons with detailed native/accessibility tooltips instead of large cards with visible explanatory copy.
- Palette width and item spacing were reduced to limit scrolling.
- Add behavior remains single-click, double-click, and drag/drop.
- Frontend version bumped to `0.4.35`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`20 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Canvas Icons

- Added the same workflow element icons used in the compact palette to React Flow canvas nodes.
- Canvas nodes now render a compact icon block plus node label/type text, using shared metadata from the FlowForge element registry.
- Added shared element lookup helpers so palette and canvas icon selection stay aligned.
- Frontend version bumped to `0.4.36`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`20 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## Sidebar Hover Polish

- Removed hover-only highlight/glow from non-active QueryForge sidebar menu and nested submenu items.
- Added the final override in `queryforge-bootstrap.css` because it loads after the compiled template SCSS; the earlier `qf-internal-theme.css` override could be superseded by later template rules.
- Disabled the template's submenu icon hover glow that added circular SVG backgrounds and box-shadow on sibling hover.
- Active/current route styling remains intact.
- Frontend version bumped to `0.4.38`.
- Verification completed:
  - Sidebar menu focused UI tests passed (`7 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Page Navigation Cleanup

- Removed redundant FlowForge in-page runtime/admin navigation link strips from Designer, Runs, Needs Attention, Reports, Integrations, Resources, Matching Policies, Settings, and Run Detail pages.
- Deleted the now-unused `FlowForgeRuntimeNav` and `FlowForgeAdminNav` components and removed their dead CSS selectors.
- Sidebar menu navigation remains the only primary cross-page navigation surface for FlowForge.
- Frontend version bumped to `0.4.39`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`20 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Report Badge Shape

- Changed FlowForge status badges from pill-shaped ovals to rounded rectangles so the Reports page `registered` chip reads less like a large oval.
- Frontend version bumped to `0.4.40`.
- Verification completed:
  - FlowForge runtime/report focused UI tests passed (`4 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Vertical Rail

- Moved FlowForge Designer persistence/workflow actions out of the hero header and into a left-side vertical tool rail matching the ForgeMatch/QueryStudio rail placement.
- Added rail actions for save draft version, open workflows, create persisted draft, and AI toggle.
- Added a workflow side panel that opens next to the rail for selecting/opening workflows, matching the ForgeMatch sessions-panel pattern.
- Kept publish controls in the version history panel.
- Frontend version bumped to `0.4.41`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`21 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Workflow Rail Cards

- Shifted the FlowForge Designer left rail/workflow panel cluster about 100px left so it aligns closer to the QueryStudio/ForgeMatch tool rail position.
- Replaced the workflow selector in the rail panel with QueryStudio-style workflow cards.
- Workflow cards now show the workflow name and source metadata, with an ellipsis action menu on the right.
- Wired workflow card actions:
  - `Open` switches the active workflow.
  - `Copy` creates a persisted draft copy using the current workflow graph.
  - `Publish` and `Delete` are visible but disabled until direct workflow-level publish/delete backend support exists.
- Frontend version bumped to `0.4.42`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`21 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Rail Visibility Fix

- Replaced the fixed `translateX(-100px)` designer rail shift with a clamped viewport-gutter-based offset.
- The rail can still move left toward the QueryStudio/ForgeMatch position when there is available page gutter, but it no longer moves the 56px rail completely offscreen when the workflow panel is closed.
- Frontend version bumped to `0.4.43`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`21 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Rail Transform Removal

- Removed the designer rail left-shift transform entirely after the rail still rendered offscreen after refresh.
- Visibility now takes priority over horizontal offset tuning; future left-position adjustments should use stable layout spacing/margins instead of transforms that can move the 56px rail outside its visible grid slot.
- Frontend version bumped to `0.4.44`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`21 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Designer Rail 23px Offset

- Shifted the FlowForge Designer left rail cluster `23px` left using `margin-left: -23px` instead of transform-based positioning.
- The mobile/narrow layout resets this margin to `0` so the rail stays visible on constrained screens.
- Frontend version bumped to `0.4.45`.
- Verification completed:
  - FlowForge/sidebar focused UI tests passed (`21 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - UI `git diff --check` passed.

## FlowForge Workflow Create/Delete/Publish Patch

- Added backend soft-delete/archive support for persisted FlowForge workflow definitions:
  - `DELETE /api/v1/flowforge/workflows/<workflow_id>` requires `flowforge:admin`.
  - Seed workflows cannot be deleted because only persisted numeric workflow ids are accepted.
  - Repository archives definitions by setting `archived_at`, `archived_by`, and `updated_at`; list/get queries already filter archived definitions.
- Added FlowForge Designer UI support:
  - Rail now includes `New blank workflow`, which creates a persisted workflow with a single `Start` intake node.
  - Workflow card ellipsis menu can publish the active workflow's latest valid unpublished version.
  - Workflow card ellipsis menu can delete/archive persisted workflows with confirmation.
  - Seed workflow delete remains disabled.
- Version bumps:
  - Backend version bumped to `0.3.378`.
  - Frontend version bumped to `0.4.46`.
- Verification completed:
  - Backend FlowForge tests passed (`165 passed`).
  - FlowForge/sidebar focused UI tests passed (`24 passed`).
  - UI production build passed with existing legacy Vite asset/chunk warnings.
  - Backend and frontend `git diff --check` passed.

## FlowForge Data Movement Automation Direction

- FlowForge should include governed data import/export automation as a first-class future capability, not as a separate ETL product.
- Scheduler support should be modeled as a trigger primitive (`schedule_trigger`), alongside webhook/file-watch triggers; mid-flow waits should remain `wait` or future `wait_until`.
- Data movement workflow nodes should include `query_extract`, `export`, `import`, `map_transform`, and `approval`.
- `query_extract` must use governed QueryForge saved queries, semantic plans, or query-builder artifacts. FlowForge should not become an arbitrary raw-SQL execution surface.
- Export destinations and import sources should be workspace-configured, allowlisted, health-tested, and fully audited.
- Import workflows should stage and validate data before activating resource snapshots or future domain refresh paths.
- High-risk MCP import/export tools should be deferred until UI, RBAC, audit, and destination/source allowlist controls are proven.
- Updated:
  - `/Users/mmaslak/Local Documents/projects/query_forge/docs/plans/2026-05-04-flowforge-design-and-implementation-plan.md`
  - `/Users/mmaslak/Local Documents/projects/query_forge/docs/plans/2026-05-05-flowforge-productionization-plan.md`
- No version bump was required because this was documentation/memory only.

## FlowForge Settings Toggle Polish

- Updated the FlowForge admin settings page so `Enable FlowForge Runtime` and `Allow Designer Publish` render as inline accessible switch controls instead of stacked checkbox rows.
- Added switch styling in `flowforgeAdmin.css` using QueryForge teal for the enabled state and compact rounded switch controls.
- Added a focused UI regression assertion that the settings booleans render with `role="switch"` and the expected loaded states.
- Frontend version bumped to `0.4.47`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`4 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI changes; FlowForge UI files are still untracked in the current worktree from the broader feature branch state.

## FlowForge Settings Form Layout Polish

- Tightened the FlowForge admin settings page so the settings form no longer spans the full content width.
- Added a settings-specific panel width cap and grouped settings into compact cards:
  - Runtime Controls
  - Timing Defaults
  - Notification Defaults
- Numeric timing fields now sit in a two-column compact grid on desktop and collapse on narrow screens.
- Notification textareas were shortened to reduce unnecessary vertical bulk.
- Save/error controls now live in a compact action footer.
- Frontend version bumped to `0.4.48`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`4 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI changes.

## FlowForge Resource Sets Page Polish

- Reworked the FlowForge Resource Sets page to make the user path explicit:
  - `1. Choose or create a pool`
  - `2. Load resource records`
  - `3. Review what matching sees`
- Updated the page description and panel copy so resource sets are explained as the people/assets a workflow can route to.
- Resource set cards now show selected state, source type, active snapshot id, and a clearer `Select Resource Set` action.
- Split snapshot loading and record review into separate panels so JSON entry is not the first thing the user has to interpret.
- Added empty-state guidance for no resource sets and no active records.
- Frontend version bumped to `0.4.49`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`4 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI changes.

## FlowForge Resource Upload UI

- Added a front-end resource upload path to the FlowForge Resource Sets page.
- Users can now upload CSV or JSON while loading resource records for the selected resource set.
- CSV uploads support a header row, basic quoted-field parsing, boolean/number coercion, and automatic `source_record_key` fallback values when omitted.
- JSON uploads support either an array of records or an object with a `records` array.
- Uploaded records are loaded into the existing snapshot review textarea, then persisted through the existing `Create Snapshot` action and backend endpoint.
- Added FileReader fallback for environments where `File.text()` is unavailable.
- Frontend version bumped to `0.4.50`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`4 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI changes.

## FlowForge Matching Policies Page Polish

- Reworked the FlowForge Matching Policies page to make the policy workflow explicit:
  - `1. Choose the resource pool`
  - `2. Define matching rules`
  - `3. Simulate before saving`
- Updated the hero/page copy so matching policies are explained as eligibility, ranking, and selection rules.
- Existing policy cards now show selected state, resource set id, and clearer `Select Policy` behavior.
- Saved versions now include resource set context and empty-state guidance.
- The builder panel now explains the current sample rule in plain language before exposing advanced JSON.
- Simulation now displays a human-readable summary for status, selected candidate, eligible count, and excluded count, with raw simulation JSON tucked under expandable details.
- Frontend version bumped to `0.4.51`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`4 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI changes.

## FlowForge Matching Policy Builder Direction

- The current matching policy UX should pivot away from raw JSON editing.
- Target UX:
  - list existing policies in a Saved Queries/Workflow-style rail or selector
  - support create-new policy from the same surface
  - opening a policy shows a policy builder window/drawer/page instead of raw JSON
  - the builder presents form controls that compile into deterministic policy JSON
  - policy fields should be derived from the selected resource set/profile fields where possible
  - operators should be constrained by field type/capability, similar to QueryStudio filter builders
  - raw JSON remains an advanced/support view, not the primary interface
- Builder concepts:
  - eligibility rules: who can be considered
  - scoring/ranking rules: who should be preferred
  - capacity/fairness rules: workload and availability constraints
  - no-match behavior: what happens when no resource qualifies
- Natural-language policy drafting should be a first-class builder feature:
  - user describes matching intent in plain English
  - workspace FlowForge LLM role proposes policy JSON
  - system validates fields/operators against the resource set
  - UI renders the generated policy as editable form rules
  - simulation explains why resources matched, were ranked, or were excluded
- Recommended implementation sequence:
  - start with a policy list/create/open shell
  - add resource-field/operator discovery endpoint or derive from snapshot record profiles if backend support already exists
  - build form-to-policy JSON for eligibility first
  - add scoring/ranking form controls second
  - add NL draft-to-form flow after deterministic builder and validation are stable

## FlowForge Matching Policy Builder First Slice

- Implemented the first usable policy-builder pass on the FlowForge Matching Policies page.
- The page now derives selectable policy fields from the selected resource set's active resource records, with common fallback fields for empty resource sets.
- Eligibility is now configured through field/operator/value form controls instead of requiring raw JSON.
- Scoring/ranking is now configured through field/operator/value/weight form controls that compile to the current backend-supported matching engine shape.
- The generated policy uses supported operators such as `equals` and `gt`; the prior sample `weight_desc` shape is not used because the backend matcher does not support it.
- Simulation now defaults to saved records from the selected resource set when available, while fallback test resource JSON remains available under Advanced.
- Raw policy JSON and test-resource JSON are now tucked under an Advanced section; the deterministic builder is the primary path.
- Added a placeholder Natural Language Drafting card to keep the target direction visible without pretending the NL-to-form loop is wired yet.
- Frontend version bumped to `0.4.52`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`4 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI changes.

## FlowForge Matching Policy NL Drafting UI

- Wired the Matching Policies natural-language drafting panel to the existing backend `POST /flowforge/matching-policies/{id}/llm-drafts` endpoint.
- The UI now sends the selected policy id, selected resource set id, plain-language prompt, and resource field metadata to the draft endpoint.
- Successful LLM/heuristic drafts hydrate the deterministic builder form from `generated_policy` instead of forcing users into raw JSON.
- Draft summaries are displayed inline so the user can understand what was generated before simulation or save.
- Drafting is disabled until a policy is selected or saved, preserving the backend audit model where LLM drafts belong to a matching policy.
- Extracted reusable matching-policy builder helpers into `src/features/flowforge/model/matchingPolicyBuilder.ts` to keep the page from accumulating parsing, field inference, and policy compilation logic.
- Frontend version bumped to `0.4.53`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`4 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI and backend changes.

## FlowForge Matching Policy Blank Draft Mode

- Added an explicit `Create New Policy` action to the FlowForge Matching Policies page.
- New policy creation now enters a separate blank draft mode instead of implicitly editing/selecting the first existing policy.
- Blank draft mode resets policy key/display name, resource selection, builder rules, draft prompt/summary, advanced JSON state, simulation results, and mutation errors.
- Existing policy selection exits blank draft mode and loads the selected policy metadata into the form.
- AI drafting remains disabled for a blank draft until the policy is saved, preserving the backend requirement that LLM drafts attach to an auditable matching policy id.
- Frontend version bumped to `0.4.54`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`5 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI and backend changes.

## FlowForge Matching Policy Resource Field Gate

- Matching policy eligibility/scoring fields are no longer shown before an explicit resource pool is selected.
- Removed the implicit first-resource-set fallback for field discovery, simulation, and save behavior.
- Removed the implicit first-policy active state; users now explicitly select an existing policy or click `Create New Policy`.
- The builder now shows clear field-gate messaging until a resource pool is selected.
- Generated builder JSON, simulation, and save actions are disabled/gated until a resource pool is selected.
- Frontend version bumped to `0.4.55`.
- Verification completed:
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`5 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for tracked UI and backend changes.

## FlowForge Matching Policy Version Deletion

- Added backend support for deleting FlowForge matching policy drafts and other non-published versions.
- Deletion is implemented as a soft delete by setting `version_status = 'deleted'`; no schema migration was needed.
- Published versions are protected from deletion and return a validation error.
- Matching policy version lists now exclude soft-deleted versions.
- If the deleted version is the policy's current draft, `current_draft_version_id` is cleared.
- Added `DELETE /api/v1/flowforge/matching-policies/{matching_policy_id}/versions/{matching_policy_version_id}` behind `flowforge:designer`.
- Frontend Matching Policies now exposes a version delete action for non-published versions and labels published versions as protected.
- Backend version bumped to `0.3.379`; frontend version bumped to `0.4.56`.
- Verification completed:
  - Focused backend repository/service/route tests passed (`4 passed`).
  - Full backend `./scripts/lint.sh` passed (`3120 passed, 81 skipped`).
  - FlowForge admin UI focused tests passed (`5 passed`).
  - Frontend build passed with existing legacy warnings.
  - `git diff --check` passed in backend and frontend repos.

## FlowForge Matching Policy Saved-Query Style Cards

- Updated the FlowForge Matching Policies UI to show existing policies as compact saved-query-style cards with a right-aligned ellipsis menu.
- The policy builder/editor remains hidden until the user selects a policy or starts a new policy.
- Moved matching policy setup guidance into a collapsible help box so it is not the primary page content.
- Added policy-level soft delete support:
  - `DELETE /api/v1/flowforge/matching-policies/{matching_policy_id}`
  - archives the policy header
  - marks non-published policy versions deleted
  - blocks deletion when any visible version is published
- Version delete actions now live behind each version card ellipsis menu.
- Backend version bumped to `0.3.380`; frontend version bumped to `0.4.57`.
- Verification completed:
  - Focused backend repository/service/route delete tests passed (`7 passed`).
  - Full backend `./scripts/lint.sh` passed (`3124 passed, 81 skipped`).
  - FlowForge admin UI focused tests passed (`6 passed`).
  - Frontend build passed with existing legacy warnings.

## FlowForge Matching Policy UI Polish

- Narrowed the Matching Policies sidebar and widened the policy builder column.
- Split Existing Policies and Saved Versions into separate boxed sidebar sections.
- Changed matching policy status pills from ovals to rounded rectangles.
- Replaced the large Existing Policies `Create New Policy` button with a compact plus icon button while keeping the accessible name.
- Expanded the Matching Policies builder to support multiple eligibility and scoring rule rows, still compiling to the existing backend `eligibility[]` and `scoring[]` policy JSON arrays.
- Frontend version bumped through `0.4.64`.
- Verification completed:
  - FlowForge admin UI focused tests passed (`6 passed`).
  - Frontend build passed with existing legacy warnings.

## FlowForge Balanced Matching Selection

- Added backend support for `selection.strategy = "balanced_top_ranked"` in deterministic FlowForge matching policies.
- Existing policies without `selection`, or with `top_ranked`/`highest_score`, remain backwards compatible and continue sorting by score, display name, and source record key.
- Balanced selection keeps the current model order: eligibility filters first, scoring second, final selection third.
- The balanced strategy rotates only among candidates within `selection.fairness.within_score_delta` points of the top score, defaulting to `5`.
- Within that near-equal candidate pool, matching prefers lower `active_offer_count`, then older/no `last_offered_at`, then higher score and deterministic name/key tie-breakers.
- This prevents one near-top resource from receiving every offer while preserving clear score winners when the score gap is larger than the configured delta.
- The heuristic matching-policy draft generator now emits the balanced selection block by default.
- Frontend policy builder defaults were updated to emit the same balanced selection block for newly created policies.
- Backend version bumped to `0.3.381`; frontend version bumped to `0.4.65`.
- Verification completed:
  - `./scripts/pytest.sh tests/features/flowforge/test_matching_engine.py tests/features/flowforge/test_llm_drafting.py -v` passed (`9 passed`).
  - `ruff check app/features/flowforge/matching.py app/features/flowforge/llm_drafting.py tests/features/flowforge/test_matching_engine.py tests/features/flowforge/test_llm_drafting.py` passed.
  - `npm test -- --run src/features/flowforge/__tests__/FlowForgeAdminPages.test.tsx` passed (`6 passed`).
  - `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.

## FlowForge Matching Policy Fairness Window Control

- Exposed the balanced-selection score-delta control in the Matching Policies UI as `Fairness Window`.
- The control maps directly to `selection.fairness.within_score_delta`.
- Policy builder state now hydrates the fairness window from saved or AI-generated policy JSON and defaults to `5` when omitted.
- Form-built policies still emit `selection.strategy = "balanced_top_ranked"` with active-offer and least-recently-offered fairness enabled.
- Frontend version bumped to `0.4.66`.
- Verification completed:
  - FlowForge admin UI focused tests passed (`6 passed`).
  - Frontend build passed with existing legacy warnings.

## FlowForge Fairness Window Numeric Spinner

- Updated the FlowForge Matching Policies `Fairness Window` control to default to `0`.
- The UI keeps the field as a native number input so the browser provides up/down spinner controls.
- The frontend now prevents/sanitizes non-whole-number input for this field.
- The heuristic matching-policy draft generator now emits `selection.fairness.within_score_delta = 0` by default.
- Backend version bumped to `0.3.382`; frontend version bumped to `0.4.67`.
- Verification completed:
  - `./scripts/pytest.sh tests/features/flowforge/test_llm_drafting.py -v` passed (`2 passed`).
  - Backend ruff check passed for the touched draft generator and test.
  - FlowForge admin UI focused tests passed (`6 passed`).
  - Frontend build passed with existing legacy warnings.

## FlowForge Matching Policy QueryStudio Layout

- Reworked the Matching Policies frontend toward the QueryStudio workbench pattern.
- The page now uses a left saved-policy rail/panel, center `Build and Test a Policy` workspace, and right `FlowForge AI` copilot panel.
- Saved policies and saved versions remain in the left panel with the existing card actions.
- Natural-language policy drafting now lives in the right copilot panel instead of inside the center builder form.
- Existing backend routes and policy behavior were unchanged.
- Frontend version bumped to `0.4.68`.
- Verification completed:
  - FlowForge admin UI focused tests passed (`6 passed`).
  - Frontend build passed with existing legacy warnings.

## FlowForge Saved Policy Rail Toggle

- Updated the Matching Policies frontend so the saved-policy rail folder button hides/displays the saved-policy panel.
- The folder button now mirrors QueryStudio saved-query behavior with `aria-expanded`, and the panel exposes `aria-hidden` when collapsed.
- Existing new-policy and saved-version behavior was unchanged.
- Frontend version bumped to `0.4.69`.
- Verification completed:
  - FlowForge admin UI focused tests passed (`6 passed`).
  - Frontend build passed with existing legacy warnings.

## FlowForge Matching Policy Rail Position

- Nudged the Matching Policies saved-policy rail cluster 20px left in the frontend to better align with QueryStudio/ForgeMatch rail placement.
- Frontend version bumped through `0.4.71`.
- Verification completed:
  - FlowForge admin UI focused tests passed (`6 passed`).
  - Frontend `git diff --check` passed.

## FlowForge Matching Policy Collapsed Rail Expansion

- Updated the Matching Policies frontend so hiding the saved-policy panel collapses the left grid column to rail width and lets the center builder expand into the freed space.
- Added an accessible `Matching policy studio` region and UI test assertions for open/collapsed layout classes.
- Adjusted the collapsed saved-policy column to `47px` to account for the rail's negative left offset and move the expanded builder farther left.
- Frontend version bumped through `0.4.74`.
- Verification completed:
  - FlowForge admin UI focused tests passed (`6 passed`).
  - Frontend build passed with existing legacy warnings.
  - Frontend `git diff --check` passed.

## FlowForge Data Movement Automation Foundation

- Began the governed data import/export automation workstream with a modeling and validation slice.
- Backend workflow validation now recognizes trigger primitives (`schedule_trigger`, `webhook_trigger`, `file_watch_trigger`) and data movement nodes (`query_extract`, `export`, `import`, `map_transform`, `approval`).
- Guardrails added:
  - `schedule_trigger` requires schedule/rrule/cron/interval config.
  - trigger nodes cannot have incoming edges.
  - `query_extract` must reference a governed saved query, semantic plan, or query-builder artifact and rejects raw SQL fields such as `raw_sql`, `sql`, or `query`.
  - `export` requires an allowlisted destination key/id.
  - `import` requires an allowlisted source key/id or resource-set staging target.
  - `map_transform` warns when no field mapping or validation rules are configured.
- Runtime node execution now safely recognizes the new primitives, records trigger/data-movement metadata in node events, and defers side effects until artifact storage, allowlisted destinations/sources, and approval/audit execution services are built.
- Approval nodes pause the run as a waiting gate.
- Designer palette now exposes schedule/webhook/file-watch triggers plus query extract, map/transform, approval, export, and import nodes with starter config and icons.
- FlowForge AI assistant now suggests the new primitives for scheduled exports, saved query extracts, imports, transforms, and approvals.
- Backend version bumped to `0.3.388`; frontend version bumped to `0.4.92`.
- Verification completed:
  - API: `./scripts/pytest.sh tests/features/flowforge/test_service.py tests/features/flowforge/test_runtime_dispatcher.py -q` passed (`74 passed`).
  - API lint: `.venv/bin/ruff check app/features/flowforge/models.py app/features/flowforge/runtime/node_executor.py app/features/flowforge/service/workflows.py app/features/flowforge/schemas/workflows.py tests/features/flowforge/test_service.py tests/features/flowforge/test_runtime_dispatcher.py` passed.
  - UI: `npm test -- --run src/features/flowforge/__tests__/FlowForgeStudioPage.test.tsx` passed (`17 passed`).
  - UI build: `npm run build` passed with existing legacy Vite asset/CSS/chunk warnings.
  - `git diff --check` passed for both API and UI repos.

## FlowForge Data Movement Implementation Plan

- Added persisted implementation plan: `/Users/mmaslak/Local Documents/projects/query_forge/docs/plans/2026-05-06-flowforge-data-movement-implementation-plan.md`.
- The plan defines product goals, non-goals, governance rules, workflow primitive contracts, proposed tables, runtime context shape, phase order, test gates, open decisions, and the recommended next implementation batch.
- Recommended next batch is Phase 1 plus the schedule ledger foundation:
  - `flowforge_dataset_artifacts`
  - `flowforge_data_movement_audit`
  - `flowforge_data_sources`
  - `flowforge_data_destinations`
  - `flowforge_schedule_runs`
- No version bump required because this was documentation/memory only.

## FlowForge Data Movement Phase 1 Persistence

- Implemented Phase 1 of the persisted data movement plan in the backend.
- Added migration `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-api/migrations/20260506_flowforge_data_movement.sql` with:
  - `flowforge_dataset_artifacts`
  - `flowforge_data_movement_audit`
  - `flowforge_data_sources`
  - `flowforge_data_destinations`
  - `flowforge_schedule_runs`
- Added `FlowForgeDataMovementRepository` and wired it into `FlowForgeService`.
- Kept data movement persistence modular to avoid god files:
  - repository composition stays in `repositories/data_movement.py`;
  - artifact, audit, allowlist, schedule, and decoder responsibilities live in separate repository mixins;
  - service validation and serialization/redaction helpers live outside the main service contract mixin.
- Added service contract methods for dataset artifact create/list/read, data movement audit recording/listing, source allowlist upsert/list/enablement, and destination allowlist upsert/list/enablement.
- Source/destination configs are stored for future runtime use but redacted in service responses.
- Scope intentionally remains DB-write-only: no query extract, import, export, transform, approval, scheduler, or external destination/source side effects.
- Backend version bumped to `0.3.390`.
- Verification completed:
  - `./scripts/pytest.sh tests/features/flowforge/test_schema_migrations.py tests/features/flowforge/test_repository_foundation.py tests/features/flowforge/test_service.py -q` passed (`125 passed`).
  - `.venv/bin/ruff check app/features/flowforge/repositories/data_movement.py app/features/flowforge/repositories/__init__.py app/features/flowforge/repositories/foundation.py app/features/flowforge/service/base.py app/features/flowforge/service/__init__.py app/features/flowforge/service/data_movement.py tests/features/flowforge/test_schema_migrations.py tests/features/flowforge/test_repository_foundation.py tests/features/flowforge/test_service.py` passed.
  - `git diff --check` passed for the API repo.

## FlowForge Data Movement Phase 2 Schedule Runtime

- Implemented Phase 2 of the data movement automation plan in the backend.
- Added `FlowForgeScheduleRuntime` for schedule trigger discovery and idempotent run creation.
- Added `ScheduleWindowCalculator` so schedule math stays separate from runtime orchestration.
- Workflow repository now lists published workflow versions that contain `schedule_trigger` nodes.
- Schedule ledger now records `trigger_node_id`, `window_start`, and `window_end`.
- Scheduler supports interval, cron, and RRULE schedule windows.
- Scheduler skips disabled trigger nodes and test-mode trigger nodes unless `allow_test_dispatch` is explicitly true.
- Duplicate scheduler executions reuse the schedule/run idempotency key and do not create duplicate runs.
- Created schedule-trigger runs get a `workflow.run.created` event with trigger/window metadata and are enqueued for FlowForge runtime dispatch.
- Added Celery task and beat registration for `qf.flowforge.dispatch_due_schedules`.
- Backend version bumped to `0.3.391`.
- Verification completed:
  - `./scripts/pytest.sh tests/features/flowforge -q` passed (`207 passed`).
  - `.venv/bin/ruff check` passed for touched scheduler, repository, task, and test files.
  - `git diff --check` passed for the API repo.

## FlowForge Data Movement Phase 3 Governed Query Extract Preview

- Implemented Phase 3 of the data movement automation plan in the backend.
- Added modular runtime pieces:
  - `runtime/query_extract.py` for query extract orchestration and audit/artifact writes.
  - `runtime/query_extract_sources.py` for governed source resolution.
  - `runtime/artifacts.py` for artifact schema, sensitivity metadata, and stable checksum calculation.
- The default resolver executes governed saved queries through the existing QueryForge preview path and rejects unresolved semantic-plan/query-builder artifact sources until their registries are wired.
- `query_extract` execution now enforces configurable preview row limits.
- Raw SQL fields remain rejected before resolver execution and failed extracts write failed audit rows.
- Successful extracts create dataset artifact metadata with row count, schema, sensitivity classification, checksum, and source descriptor.
- Runtime dispatcher now routes `query_extract` nodes to the dedicated executor and merges artifact references into run context.
- Backend version bumped to `0.3.392`.
- Verification completed:
  - `./scripts/pytest.sh tests/features/flowforge -q` passed (`212 passed`).
  - `.venv/bin/ruff check` passed for touched query extract, artifact, dispatcher, and test files.
  - `git diff --check` passed for the API repo.

## FlowForge Query Extract Limit Policy Adjustment

- Replaced the hardcoded `query_extract` preview clamp of 500 rows with configurable limits.
- `FLOWFORGE_QUERY_EXTRACT_DEFAULT_LIMIT` controls omitted node limits and defaults to `100`.
- `FLOWFORGE_QUERY_EXTRACT_MAX_LIMIT` controls an optional deployment ceiling and defaults to `0`, meaning requested limits are uncapped.
- The executor still rejects non-integer and non-positive limits.
- Backend version bumped to `0.3.393`.
- Verification completed:
  - `./scripts/pytest.sh tests/features/flowforge/test_query_extract_runtime.py tests/features/flowforge/test_runtime_dispatcher.py -q` passed (`13 passed`).
  - `.venv/bin/ruff check app/config/__init__.py app/features/flowforge/runtime/query_extract.py tests/features/flowforge/test_query_extract_runtime.py` passed.

## FlowForge Data Movement Phase 4 Map Transform Execution

- Implemented Phase 4 of the data movement automation plan in the backend.
- Added modular runtime pieces:
  - `runtime/map_transform.py` for transform orchestration, artifact reads/writes, audit rows, and run-context artifact refs.
  - `runtime/map_transform_engine.py` for deterministic field mapping and validation rules.
- Query extract preview artifact metadata now stores JSON-safe preview rows and columns in the artifact `storage_ref`, enabling downstream transform execution without putting row payloads in run context.
- `map_transform` can resolve its input artifact from `input_artifact_id`, `input_node_id`, or the run context `last_artifact`.
- Field mapping supports dictionary and list mapping shapes, dot-path source fields, defaults, and optional unmapped-field passthrough.
- Validation supports required, type, enum, regex, min, max, and date parse checks. Invalid rows are excluded from the output artifact and summarized with rejected-row samples.
- Successful transforms create a `transform` dataset artifact with row count, schema, validation metadata, checksum, inline preview rows, and a completed data movement audit row.
- Failed transforms write failed data movement audit rows before surfacing the node execution error.
- Runtime dispatcher now routes `map_transform` nodes through the dedicated executor and merges produced artifact refs into run context.
- Backend version bumped to `0.3.394`.
- Verification completed:
  - `./scripts/pytest.sh tests/features/flowforge/test_map_transform_runtime.py tests/features/flowforge/test_runtime_dispatcher.py tests/features/flowforge/test_query_extract_runtime.py -q` passed (`16 passed`).
  - `./scripts/pytest.sh tests/features/flowforge -q` passed (`216 passed`).
  - `.venv/bin/ruff check app/features/flowforge/runtime/artifacts.py app/features/flowforge/runtime/map_transform.py app/features/flowforge/runtime/map_transform_engine.py app/features/flowforge/runtime/dispatcher.py tests/features/flowforge/test_map_transform_runtime.py tests/features/flowforge/test_runtime_dispatcher.py tests/features/flowforge/test_query_extract_runtime.py` passed.
  - `git diff --check` passed for the API repo.

## FlowForge Data Movement Phase 5 Controlled Export

- Implemented Phase 5 of the data movement automation plan in the backend.
- Added modular runtime pieces:
  - `runtime/export.py` for export orchestration, destination checks, artifact writes, audit rows, and run-context artifact refs.
  - `runtime/export_adapters.py` for the first low-risk `local_file_test` CSV adapter.
  - `runtime/export_policy.py` for export policy enforcement stubs.
  - `runtime/dataset_artifact_io.py` for shared inline preview artifact row/column reading.
- `export` nodes now resolve input artifacts from `input_artifact_id`, `input_node_id`, or run context `last_artifact`.
- Export execution requires an enabled allowlisted destination and currently only executes `local_file_test` destinations in `test` mode.
- The local-file test adapter writes CSV files, computes byte count and SHA-256 checksum, and returns a destination ref with the local path.
- Export policy enforcement currently supports `max_rows` and `block_sensitive` destination policy checks through `config.export_policy`.
- Successful exports create an `export_payload` dataset artifact and completed data movement audit row with destination ref, row count, byte count, checksum, and policy result.
- Failed exports write failed audit rows before surfacing the node execution error.
- Runtime dispatcher now routes `export` nodes through the dedicated executor and merges produced artifact refs into run context.
- Backend version bumped to `0.3.395`.
- Verification completed:
  - `./scripts/pytest.sh tests/features/flowforge/test_export_runtime.py tests/features/flowforge/test_runtime_dispatcher.py tests/features/flowforge/test_map_transform_runtime.py -q` passed (`15 passed`).
  - `./scripts/pytest.sh tests/features/flowforge -q` passed (`221 passed`).
  - `.venv/bin/ruff check app/features/flowforge/runtime/dataset_artifact_io.py app/features/flowforge/runtime/export.py app/features/flowforge/runtime/export_adapters.py app/features/flowforge/runtime/export_policy.py app/features/flowforge/runtime/map_transform.py app/features/flowforge/runtime/dispatcher.py tests/features/flowforge/test_export_runtime.py tests/features/flowforge/test_runtime_dispatcher.py tests/features/flowforge/test_map_transform_runtime.py` passed.
  - `git diff --check` passed for the API repo.
