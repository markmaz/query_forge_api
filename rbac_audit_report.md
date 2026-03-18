# RBAC Audit Report

## Section 1 - Summary

Total route methods audited: 324
Currently unprotected:       16
Proposed @public:            14
High confidence proposals:   276
Needs review:                25

## Section 2 - Full Route Table

| File | Resource class | Method | HTTP | Current protection | Feature | Proposed decorator | Confidence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| auth_routes.py | Authenticate | post | POST | none | auth | @public | high | Currently unprotected credential authentication endpoint that issues JWT and refresh tokens. |
| auth_routes.py | Login | post | POST | other: non-auth decorators only (@expect + @response + @doc + @doc) | auth | @public | high | Currently unprotected credential check endpoint that starts the OTP/TOTP challenge flow. |
| auth_routes.py | StartTotpEnrollment | post | POST | @token_required | auth | @token_required only | high |  |
| auth_routes.py | ConfirmTotpEnrollment | post | POST | @token_required | auth | @token_required only | high |  |
| auth_routes.py | VerifyTotpChallenge | post | POST | other: non-auth decorators only (@expect + @doc) | auth | @public | high | Currently unprotected TOTP challenge verification endpoint. |
| auth_routes.py | DisableTotp | post | POST | @token_required | auth | @token_required only | high |  |
| auth_routes.py | Refresh | post | POST | none | auth | @public | high | Currently unprotected refresh-token rotation endpoint. |
| auth_routes.py | Logout | post | POST | none | auth | @token_required only | medium | Currently unprotected logout/token revocation endpoint; likely should require an authenticated token or refresh cookie. |
| auth_routes.py | InviteValidationResource | get | GET | none | auth | @public | high | Currently unprotected invite token validation endpoint. |
| auth_routes.py | InviteAcceptResource | post | POST | other: non-auth decorators only (@expect + @doc) | auth | @public | high | Currently unprotected invite acceptance endpoint. |
| auth_routes.py | ResetPasswordRequest | post | POST | none | auth | @public | high | Currently unprotected password-reset request endpoint. |
| auth_routes.py | ResetPasswordValidate | post | POST | none | auth | @public | high | Currently unprotected reset-token validation endpoint. |
| auth_routes.py | ResetPassword | post | POST | none | auth | @public | high | Currently unprotected password-reset completion endpoint. |
| otp_routes.py | VerifyOTP | post | POST | none | auth | @public | high | Currently unprotected OTP verification endpoint. |
| public_sales_inquiry.py | SalesInquiry | post | POST | other: non-auth decorators only (@expect + @doc) | cross-feature | @public | high | Currently unprotected public sales inquiry form; touches public website intake and internal sales lead capture. |
| user_routes.py | UserList | post | POST | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserList | get | GET | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserUpdates | put | PUT | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserUpdates | delete | DELETE | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserUpdates | get | GET | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserWorkspaces | get | GET | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserDirectRoles | get | GET | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserDirectRoles | post | POST | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserDirectRoles | put | PUT | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserDirectRoleById | patch | PATCH | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserDirectRoleById | delete | DELETE | @token_required | users | @require_admin() | high |  |
| user_routes.py | UserWorkspaceDashboard | get | GET | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches users + workspaces + external dashboard embeds, and the handler is currently a disabled stub, so ownership is unclear. |
| user_routes.py | UserCounts | get | GET | @token_required | users | @require_admin() | high |  |
| user_routes.py | ResentInvite | post | POST | @token_required | users | @require_admin() | high |  |
| user_routes.py | BulkInviteUsers | post | POST | @token_required | users | @require_admin() | high |  |
| user_workspace_routes.py | UserWorkspaceMap | post | POST | @token_required | users | @require_admin() | high |  |
| user_workspace_routes.py | UserWorkspaceMap | delete | DELETE | @token_required | users | @require_admin() | high |  |
| user_workspace_routes.py | UserWorkspaceMap | put | PUT | @token_required | users | @require_admin() | high |  |
| role_routes.py | RoleList | get | GET | @token_required | users | @require_admin() | high |  |
| role_routes.py | RoleList | post | POST | @token_required | users | @require_admin() | high |  |
| role_routes.py | RoleDetails | delete | DELETE | @token_required | users | @require_admin() | high |  |
| role_routes.py | RoleDetails | get | GET | @token_required | users | @require_admin() | high |  |
| workspace_routes.py | Workspaces | get | GET | @token_required | workspaces | @require_access("workspaces") | high |  |
| workspace_routes.py | WorkSpaceDetails | get | GET | @token_required | workspaces | @require_access("workspaces") | high |  |
| workspace_routes.py | WorkspaceUsers | get | GET | @token_required | workspaces | @require_admin() | high |  |
| workspace_routes.py | WorkspaceNamespaces | get | GET | @token_required | workspaces | @require_access("workspaces") | high |  |
| workspace_routes.py | GetWorkspaceUsersFromSystem | get | GET | @token_required | workspaces | @require_admin() | high |  |
| workspace_routes.py | WorkspaceExternalLinks | get | GET | @token_required | workspaces | @require_access("workspaces") | high |  |
| workspace_table_routes.py | WorkspaceTableColumns | get | GET | @token_required | workspaces | @require_access("workspaces") | high |  |
| workspace_llm_routes.py | LLMRolesList | get | GET | @token_required | workspaces | @require_admin() | high |  |
| workspace_llm_routes.py | LLMProvidersList | get | GET | @token_required | workspaces | @require_admin() | high |  |
| workspace_llm_routes.py | WorkspaceLLMList | get | GET | @token_required | workspaces | @require_admin() | high |  |
| workspace_llm_routes.py | WorkspaceLLMList | post | POST | @token_required | workspaces | @require_admin() | high |  |
| workspace_llm_routes.py | WorkspaceLLMDetail | get | GET | @token_required | workspaces | @require_admin() | high |  |
| workspace_llm_routes.py | WorkspaceLLMDetail | put | PUT | @token_required | workspaces | @require_admin() | high |  |
| workspace_llm_routes.py | WorkspaceLLMDetail | delete | DELETE | @token_required | workspaces | @require_admin() | high |  |
| workspace_llm_routes.py | WorkspaceLLMTest | post | POST | @token_required | workspaces | @require_admin() | high |  |
| admin_routes.py | ShowHealth | get | GET | none | system | @public | high | Currently unprotected public liveness check (`/healthz`). |
| admin_routes.py | DetailedHealth | get | GET | other: @token_required + _require_admin() helper | system | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | BrokerHealth | get | GET | other: @token_required + _require_admin() helper | system | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | PipelineProfileList | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | AdminPromptFeedbackList | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | AdminPromptFeedbackDelete | delete | DELETE | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | RebuildSemanticConceptVectors | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | ReindexDomainVectors | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | RebuildEmbeddingVectors | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | RebuildAllVectors | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DomainProfileList | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DomainProfileList | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DomainProfileDetail | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DomainProfileDetail | put | PUT | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DomainProfileDetail | delete | DELETE | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DomainProfileGenerateOne | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DomainProfileGenerateBatch | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DomainProfileGenerateAll | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | SemanticCatalogBuild | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | TenancyBootstrap | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationListCreate | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationListCreate | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationDetail | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationDetail | patch | PATCH | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationDetail | delete | DELETE | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationMembershipListCreate | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationMembershipListCreate | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationMembershipDetail | patch | PATCH | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationMembershipDetail | delete | DELETE | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationDatasourceListCreate | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | OrganizationDatasourceListCreate | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DatasourceDetail | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DatasourceDetail | patch | PATCH | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DatasourceDetail | delete | DELETE | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | DatasourceConnectionTest | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | WorkspaceBindingList | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | WorkspaceBindingList | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | WorkspaceBindingDetail | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | WorkspaceBindingDetail | patch | PATCH | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | WorkspaceMembershipListCreate | get | GET | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | WorkspaceMembershipListCreate | post | POST | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | WorkspaceMembershipDetail | patch | PATCH | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| admin_routes.py | WorkspaceMembershipDetail | delete | DELETE | other: @token_required + _require_admin() helper | admin | @require_role("system:admin") | high | Uses `_require_admin()` helper after token auth. |
| version_routes.py | VersionInfo | get | GET | none | system | @public | high | Currently unprotected version endpoint. |
| product_routes.py | ProductList | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| product_routes.py | ProductList | post | POST | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| product_routes.py | ProductCounts | get | GET | none | catalog | NEEDS REVIEW | needs-review | Currently unprotected product count summary; it appears to expose internal catalog/admin data and may be missing auth.; Currently unprotected internal-looking product count endpoint; confirm whether it should be public or admin-only. |
| product_routes.py | ProductStandard | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| product_routes.py | ProductStandard | delete | DELETE | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| product_routes.py | ProductStandard | put | PUT | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| product_routes.py | ProductRoles | get | GET | @token_required | catalog | @require_admin() | high |  |
| product_routes.py | ProductRoles | put | PUT | @token_required | catalog | @require_admin() | high |  |
| product_routes.py | DeleteProductRoles | delete | DELETE | @token_required | catalog | @require_admin() | high |  |
| product_groups_routes.py | ProductGroupList | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| product_groups_routes.py | ProductGroupList | post | POST | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| product_groups_routes.py | ProductGroupStandard | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| product_groups_routes.py | ProductGroupStandard | delete | DELETE | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| product_groups_routes.py | ProductGroupMembership | put | PUT | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| product_groups_routes.py | ProductGroupMembership | delete | DELETE | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| value_override_routes.py | ValueOverrideIndex | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| value_override_routes.py | ValueOverridePreview | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| value_override_routes.py | ValueOverrideVisibility | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| value_override_routes.py | ValueOverrideUpload | post | POST | @token_required | catalog | @require_access("catalog") | medium |  |
| value_override_routes.py | ValueOverrideTemplateDownload | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| value_override_routes.py | ValueOverrideDetail | patch | PATCH | @token_required | catalog | NEEDS REVIEW | needs-review | Share-state changes are owner-enforced in the service (`assert_owner`), so owner-vs-feature-admin policy needs a decision. |
| value_override_routes.py | ValueOverrideDetail | delete | DELETE | @token_required | catalog | NEEDS REVIEW | needs-review | List deletion is owner-enforced in the service (`assert_owner`), so owner-vs-feature-admin policy needs a decision. |
| catalog_routes.py | CatalogSamples | post | POST | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| catalog_routes.py | CatalogTableSample | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| catalog_routes.py | CatalogSync | post | POST | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| catalog_routes.py | CatalogRecon | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| catalog_routes.py | CatalogReconCounts | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| catalog_routes.py | CatalogUnmappedTables | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| dictionary_routes.py | DictionaryTables | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| dictionary_routes.py | DictionaryTableDetail | patch | PATCH | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| dictionary_routes.py | DictionaryColumns | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| dictionary_routes.py | DictionaryColumnsSearch | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| dictionary_routes.py | DictionaryColumn | patch | PATCH | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| dictionary_routes.py | DictionaryColumnsImport | post | POST | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| skills_routes.py | SkillList | get | GET | @token_required | skills | @require_access("skills") | high |  |
| skills_routes.py | SkillList | post | POST | @token_required | skills | @require_access("skills", role="admin") | high |  |
| skills_routes.py | SkillDetail | get | GET | @token_required | skills | @require_access("skills") | high |  |
| skills_routes.py | SkillDetail | put | PUT | @token_required | skills | @require_access("skills", role="admin") | high |  |
| skills_routes.py | SkillDetail | delete | DELETE | @token_required | skills | @require_access("skills", role="admin") | high |  |
| skills_routes.py | SkillExecute | post | POST | @token_required | skills | @require_access("skills") | medium |  |
| skills_routes.py | SkillExecutionList | get | GET | @token_required | skills | @require_access("skills") | high |  |
| skills_routes.py | SkillScheduleList | get | GET | @token_required | skills | @require_access("skills") | high |  |
| skills_routes.py | SkillScheduleCreate | post | POST | @token_required | skills | @require_access("skills", role="admin") | high |  |
| skills_routes.py | SkillScheduleDetail | put | PUT | @token_required | skills | @require_access("skills", role="admin") | high |  |
| skills_routes.py | SchedulerStatus | get | GET | @token_required | skills | @require_access("skills", role="admin") | high |  |
| skills_routes.py | SkillScheduleUpcoming | get | GET | @token_required | skills | @require_access("skills") | high |  |
| skills_routes.py | SkillAlertAcknowledge | post | POST | @token_required | skills | @require_access("skills") | medium |  |
| skills_routes.py | ScheduleValidate | post | POST | @token_required | skills | @require_access("skills") | high |  |
| destination_routes.py | DestinationTypeList | get | GET | @token_required | skills | @require_access("skills") | high |  |
| destination_routes.py | DestinationList | get | GET | @token_required | skills | @require_access("skills") | high |  |
| destination_routes.py | DestinationList | post | POST | other: @token_required + _require_admin() helper | skills | @require_access("skills", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| destination_routes.py | DestinationDetail | get | GET | @token_required | skills | @require_access("skills") | high |  |
| destination_routes.py | DestinationDetail | put | PUT | other: @token_required + _require_admin() helper | skills | @require_access("skills", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| destination_routes.py | DestinationDetail | delete | DELETE | other: @token_required + _require_admin() helper | skills | @require_access("skills", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| destination_routes.py | DestinationTest | post | POST | other: @token_required + _require_admin() helper | skills | @require_access("skills", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| query_forge_routes.py | QueryForgeRun | post | POST | @token_required | query_studio | NEEDS REVIEW | needs-review | Mixed access pattern: normal query execution is user-level, but the optional `datasource` override path is admin-gated today. |
| query_forge_routes.py | QueryForgePlan | post | POST | @token_required | query_studio | @require_access("query_studio") | high |  |
| query_studio_routes.py | QueryStudioDomains | get | GET | @token_required | query_studio | @require_access("query_studio") | high |  |
| query_studio_routes.py | QueryStudioDomainExplorer | get | GET | @token_required | query_studio | @require_access("query_studio") | high |  |
| query_tree_routes.py | QueryTree | get | GET | @token_required | query_studio | @require_access("query_studio") | high |  |
| query_tree_routes.py | Folders | post | POST | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | FolderRename | patch | PATCH | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | FolderMove | patch | PATCH | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | FolderDelete | delete | DELETE | @token_required | query_studio | NEEDS REVIEW | needs-review | User-owned folder deletion is scoped by `user_id` in the service, so owner-vs-feature-admin policy needs a decision. |
| query_tree_routes.py | FolderTrash | post | POST | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | FolderRestore | post | POST | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | FolderPurge | delete | DELETE | @token_required | query_studio | NEEDS REVIEW | needs-review | User-owned folder purge is scoped by `user_id` in the service, so owner-vs-feature-admin policy needs a decision. |
| query_tree_routes.py | RecentQueries | get | GET | @token_required | query_studio | @require_access("query_studio") | high |  |
| query_tree_routes.py | SavedQueryCreate | post | POST | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | SavedQuery | get | GET | @token_required | query_studio | @require_access("query_studio") | high |  |
| query_tree_routes.py | SavedQuery | patch | PATCH | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | SavedQueryMove | patch | PATCH | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | SavedQueryDelete | post | POST | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | SavedQueryRestore | post | POST | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | SavedQueryPurge | delete | DELETE | @token_required | query_studio | NEEDS REVIEW | needs-review | User-owned saved-query purge is scoped by `user_id` in the service, so owner-vs-feature-admin policy needs a decision. |
| query_tree_routes.py | SavedQueryShares | get | GET | @token_required | query_studio | @require_access("query_studio") | high |  |
| query_tree_routes.py | SavedQueryShares | post | POST | @token_required | query_studio | @require_access("query_studio") | medium |  |
| query_tree_routes.py | SavedQueryShares | delete | DELETE | @token_required | query_studio | NEEDS REVIEW | needs-review | Saved-query unshare uses collaboration/owner semantics that the target decorator set does not express directly. |
| query_analysis_routes.py | QueryAnalyze | post | POST | @token_required | query_studio | @require_access("query_studio") | high |  |
| query_analysis_routes.py | QueryAnalyzeInline | post | POST | @token_required | query_studio | @require_access("query_studio") | high |  |
| forge_match_routes.py | ForgeMatchSessionList | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_match_routes.py | ForgeMatchUpload | post | POST | @token_required | forge_match | @require_access("forge_match") | medium |  |
| forge_match_routes.py | ForgeMatchAnalyze | post | POST | @token_required | forge_match | @require_access("forge_match") | medium |  |
| forge_match_routes.py | ForgeMatchAnalyzeStart | post | POST | @token_required | forge_match | @require_access("forge_match") | medium |  |
| forge_match_routes.py | ForgeMatchAnalyzeStatus | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_match_routes.py | ForgeMatchAnalyzeCancel | post | POST | @token_required | forge_match | @require_access("forge_match") | medium |  |
| forge_match_routes.py | ForgeMatchAnalyzeHistory | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_match_routes.py | ForgeMatchSession | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_match_routes.py | ForgeMatchMappings | patch | PATCH | @token_required | forge_match | @require_access("forge_match") | medium |  |
| forge_match_routes.py | ForgeMatchExport | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_match_routes.py | ForgeMatchCreateViewDraft | post | POST | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches forge_match + query_studio by converting a match session into a view draft. |
| forge_match_routes.py | ForgeMatchCreateDomainDraft | post | POST | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches forge_match + catalog by converting a match session into a domain draft. |
| forge_insights.py | ForgeInsightsProjectsRoute | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_insights.py | ForgeInsightsProjectsRoute | post | POST | @token_required | forge_match | NEEDS REVIEW | needs-review | Forge Insights projects are user-owned and service-scoped by `user_id`, so owner-vs-feature-admin policy needs a decision. |
| forge_insights.py | ForgeInsightsProjectRoute | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_insights.py | ForgeInsightsProjectRoute | patch | PATCH | @token_required | forge_match | NEEDS REVIEW | needs-review | Forge Insights projects are user-owned and service-scoped by `user_id`, so owner-vs-feature-admin policy needs a decision. |
| forge_insights.py | ForgeInsightsProjectRoute | delete | DELETE | @token_required | forge_match | NEEDS REVIEW | needs-review | Forge Insights projects are user-owned and service-scoped by `user_id`, so owner-vs-feature-admin policy needs a decision. |
| forge_insights.py | ForgeInsightsThreadsRoute | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_insights.py | ForgeInsightsThreadsRoute | post | POST | @token_required | forge_match | NEEDS REVIEW | needs-review | Forge Insights threads are user-owned and service-scoped by `user_id`, so owner-vs-feature-admin policy needs a decision. |
| forge_insights.py | ForgeInsightsThreadRoute | get | GET | @token_required | forge_match | @require_access("forge_match") | high |  |
| forge_insights.py | ForgeInsightsThreadRoute | patch | PATCH | @token_required | forge_match | NEEDS REVIEW | needs-review | Forge Insights threads are user-owned and service-scoped by `user_id`, so owner-vs-feature-admin policy needs a decision. |
| forge_insights.py | ForgeInsightsThreadRoute | delete | DELETE | @token_required | forge_match | NEEDS REVIEW | needs-review | Forge Insights threads are user-owned and service-scoped by `user_id`, so owner-vs-feature-admin policy needs a decision. |
| planner_domain.py | PlannerPlanDomain | post | POST | @token_required | planner | @require_access("planner") | high |  |
| planner_domain.py | PlannerPlanDomainProfile | get | GET | @token_required | planner | @require_access("planner") | high |  |
| planner_domain.py | PlannerPlanDomainNextActions | post | POST | @token_required | planner | @require_access("planner") | high |  |
| planner_llm.py | PlannerPlanLLM | post | POST | @token_required | planner | @require_access("planner") | high |  |
| planner_extract.py | PlannerExtract | post | POST | @token_required | planner | @require_access("planner") | high |  |
| ai.py | AISuggest | post | POST | @token_required | ai | @require_access("ai") | high |  |
| ai.py | AISuggestSemanticAdapter | post | POST | @token_required | ai | @require_access("ai") | high |  |
| ai.py | AIHealth | get | GET | none | system | @public | high | Currently unprotected upstream AI/vLLM health check. |
| nlp_routes.py | NlpExtract | post | POST | @token_required | ai | @require_access("ai") | high |  |
| nlp_routes.py | NlpExtractAndSearch | post | POST | @token_required | ai | @require_access("ai") | high |  |
| nlp_tier2.py | Tier2Parse | post | POST | @token_required | ai | @require_access("ai") | high |  |
| nlp_review.py | NlpReviewQueue | post | POST | @token_required | ai | @require_access("ai") | medium |  |
| nlp_review.py | NlpReviewQueue | get | GET | @token_required | ai | @require_access("ai", role="admin") | high |  |
| nlp_review.py | NlpReviewQueueItem | patch | PATCH | @token_required | ai | @require_access("ai", role="admin") | high |  |
| nlp_review.py | NlpReviewQueueApprove | post | POST | @token_required | ai | @require_access("ai", role="admin") | high |  |
| nlp_review.py | NlpReviewQueueExport | post | POST | @token_required | ai | @require_access("ai", role="admin") | high |  |
| chat_minimal.py | MinimalChatRoute | post | POST | @token_required | ai | @require_access("ai") | high |  |
| chat_minimal.py | ForgeInsightsChatRoute | post | POST | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches ai + forge_match through the Forge Insights chat/router flow. |
| chat_minimal.py | ForgeInsightsConversationListRoute | get | GET | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches ai + forge_match conversation memory for Forge Insights chat. |
| chat_minimal.py | ForgeInsightsConversationDetailRoute | get | GET | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches ai + forge_match conversation memory for Forge Insights chat. |
| chat_minimal.py | ForgeInsightsConversationDetailRoute | delete | DELETE | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches ai + forge_match conversation reset/deletion for Forge Insights chat. |
| prompt_feedback.py | PromptFeedback | post | POST | @token_required | ai | @require_access("ai") | high |  |
| execution_routes.py | ExecutionStart | post | POST | @token_required | exports | @require_access("exports") | medium |  |
| execution_routes.py | ExecutionStatus | get | GET | @token_required | exports | @require_access("exports") | high |  |
| execution_routes.py | ExecutionCancel | post | POST | @token_required | exports | @require_access("exports") | medium |  |
| execution_routes.py | ExecutionResults | get | GET | @token_required | exports | @require_access("exports") | high |  |
| export_routes.py | ExcelExport | post | POST | @token_required | exports | @require_access("exports") | high |  |
| export_routes.py | ExcelDownload | get | GET | @token_required | exports | @require_access("exports") | high |  |
| semantic_concepts.py | SemanticConceptCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticConceptCollection | post | POST | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptKeyCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticConceptById | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticConceptById | patch | PATCH | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptById | delete | DELETE | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptSeed | post | POST | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptRebuildIndex | post | POST | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptBackfillPrimaryKeys | post | POST | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptAliasCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticConceptAliasCollection | post | POST | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptAliasById | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticConceptAliasById | patch | PATCH | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptAliasById | delete | DELETE | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticValueAliasCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticValueAliasCollection | post | POST | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticValueAliasById | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticValueAliasById | patch | PATCH | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticValueAliasById | delete | DELETE | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptColumnMapCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticConceptColumnMapCollection | post | POST | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptColumnMapById | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_concepts.py | SemanticConceptColumnMapById | patch | PATCH | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_concepts.py | SemanticConceptColumnMapById | delete | DELETE | other: @token_required + _require_admin() helper | semantic | @require_access("semantic", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| semantic_routes.py | SemanticPlan | post | POST | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_routes.py | SemanticSuggestColumns | post | POST | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_registry_routes.py | SemanticRegistryCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_registry_routes.py | SemanticRegistryCollection | post | POST | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_registry_routes.py | SemanticRegistryById | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_registry_routes.py | SemanticRegistryById | patch | PATCH | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_registry_routes.py | SemanticRegistryById | delete | DELETE | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_registry.py | SemanticRegistryCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_registry.py | SemanticRegistryCollection | post | POST | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_registry.py | SemanticRegistryById | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_registry.py | SemanticRegistryById | patch | PATCH | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_registry.py | SemanticRegistryById | delete | DELETE | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_mappings.py | SemanticMappingsCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_mappings.py | SemanticMappingsCollection | post | POST | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_mappings.py | SemanticMappingsById | delete | DELETE | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_relationships.py | SemanticRelationshipsCollection | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_relationships.py | SemanticRelationshipsCollection | post | POST | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_relationships.py | SemanticRelationshipConceptLookup | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_relationships.py | SemanticRelationshipsById | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_relationships.py | SemanticRelationshipsById | patch | PATCH | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_relationships.py | SemanticRelationshipsById | delete | DELETE | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_suggestions.py | SuggestionRuns | post | POST | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_suggestions.py | SuggestionRunExecute | post | POST | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_suggestions.py | SuggestionRunById | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_suggestions.py | SuggestionItems | get | GET | @token_required | semantic | @require_access("semantic") | high |  |
| semantic_suggestions.py | SuggestionItemById | patch | PATCH | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| semantic_suggestions.py | SuggestionRunApply | post | POST | @token_required | semantic | @require_access("semantic", role="admin") | high |  |
| ingestion_routes.py | IngestionSync | post | POST | @token_required + g.is_admin | ingestion | @require_access("ingestion", role="admin") | high |  |
| ingestion_routes.py | IngestionStatus | get | GET | @token_required | ingestion | @require_access("ingestion", role="admin") | high |  |
| ingestion_routes.py | IngestionDiagnostics | get | GET | @token_required + g.is_admin | ingestion | @require_access("ingestion", role="admin") | high |  |
| ingestion_routes.py | IngestionCancel | post | POST | @token_required + g.is_admin | ingestion | @require_access("ingestion", role="admin") | high |  |
| ingestion_routes.py | IngestionHistory | get | GET | @token_required | ingestion | @require_access("ingestion", role="admin") | high |  |
| ingestion_routes.py | IngestionSchemas | get | GET | @token_required + g.is_admin | ingestion | @require_access("ingestion", role="admin") | high |  |
| datasource_routes.py | DatasourceList | get | GET | @token_required | system | @require_role("system:admin") | high |  |
| vector_domains.py | DomainVectorSearch | post | POST | @token_required | vector | @require_access("vector") | high |  |
| embeddings.py | EmbeddingsRebuild | post | POST | @token_required | vector | @require_access("vector", role="admin") | high |  |
| embeddings.py | EmbeddingsSearch | post | POST | @token_required | vector | @require_access("vector") | high |  |
| embeddings.py | EmbeddingsDomainUpsert | post | POST | @token_required | vector | @require_access("vector", role="admin") | high |  |
| embeddings.py | EmbeddingsColumnUpsert | post | POST | @token_required | vector | @require_access("vector", role="admin") | high |  |
| domain_profile_embeddings.py | DomainProfileGenerateOne | post | POST | other: @token_required + _require_admin() helper | vector | @require_access("vector", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| domain_profile_embeddings.py | DomainProfileGenerateBatch | post | POST | other: @token_required + _require_admin() helper | vector | @require_access("vector", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| domain_profile_embeddings.py | DomainProfileGenerateAll | post | POST | other: @token_required + _require_admin() helper | vector | @require_access("vector", role="admin") | high | Uses `_require_admin()` helper after token auth. |
| domain_routes.py | DomainsRoot | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainsRoot | post | POST | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | DomainById | patch | PATCH | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | DomainById | delete | DELETE | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | ColumnSample | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | WorkspaceTables | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainTables | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainTables | post | POST | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | DomainPrimaryTable | patch | PATCH | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | DomainJoins | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainJoins | post | POST | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | DomainJoin | patch | PATCH | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | DomainJoin | delete | DELETE | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | DomainUsers | get | GET | @token_required | catalog | @require_admin() | high |  |
| domain_routes.py | DomainUsers | post | POST | @token_required | catalog | @require_admin() | high |  |
| domain_routes.py | DomainUserById | delete | DELETE | @token_required | catalog | @require_admin() | high |  |
| domain_routes.py | DomainSummary | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainCapabilities | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainOverlayMetrics | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainProfileMetrics | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainProfileMetrics | put | PUT | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | DomainTimePolicy | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | DomainTimePolicy | put | PUT | @token_required | catalog | @require_access("catalog", role="admin") | high |  |
| domain_routes.py | BuilderTables | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| domain_routes.py | BuilderColumns | get | GET | @token_required | catalog | @require_access("catalog") | high |  |
| workspace_inventory_routes.py | WorkspaceInventorySync | post | POST | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches workspaces + catalog metadata snapshot/reconciliation, so the owning feature boundary needs a decision. |
| workspace_inventory_routes.py | WorkspaceInventoryUnmapped | get | GET | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches workspaces + catalog metadata snapshot/reconciliation, so the owning feature boundary needs a decision. |
| workspace_inventory_routes.py | WorkspaceInventoryRecon | get | GET | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches workspaces + catalog metadata snapshot/reconciliation, so the owning feature boundary needs a decision. |
| workspace_inventory_routes.py | WorkspaceInventoryReconCounts | get | GET | @token_required | cross-feature | NEEDS REVIEW | needs-review | Touches workspaces + catalog metadata snapshot/reconciliation, so the owning feature boundary needs a decision. |
| data_environment.py | LLMStart | post | POST | @token_required | system | @require_role("system:admin") | high |  |
| data_environment.py | LLMStop | post | POST | @token_required | system | @require_role("system:admin") | high |  |
| data_environment.py | LLMStatus | get | GET | @token_required | system | @require_role("system:admin") | high |  |
