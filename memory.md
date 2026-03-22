# Working Memory

Last updated: 2026-03-19

## Repos in play

- API repo: `/Users/mmaslak/Local Documents/projects/query-forge-api`
- UI repo: `/Users/mmaslak/Local Documents/projects/query_forge/query-forge-ui`

## Current context

- User wants long-running context persisted to a `memory.md` file so compressed context can be recovered later.
- This file is the canonical working memory for the current thread unless the user asks for a different location.

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
