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
