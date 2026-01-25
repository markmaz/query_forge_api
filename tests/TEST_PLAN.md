# Test Plan (Baseline)

## Routes (Namespaces)

- auth (`app/routes/auth_routes.py`)
- users (`app/routes/user_routes.py`)
- workspaces (`app/routes/workspace_routes.py`)
- workspace-tables (`app/routes/workspace_table_routes.py`)
- dashboards (`app/routes/dashboard_routes.py`)
- connections (`app/routes/connection_routes.py`)
- user-workspaces (`app/routes/user_workspace_routes.py`)
- roles (`app/routes/role_routes.py`)
- functions (`app/routes/functions_routes.py`)
- admin (`app/routes/admin_routes.py`)
- products (`app/routes/product_routes.py`)
- otp (`app/routes/otp_routes.py`)
- product-groups (`app/routes/product_groups_routes.py`)
- crosswalks (`app/routes/crosswalk_routes.py`)
- models (`app/routes/model_routes.py`)
- workspace-inventory (`app/routes/workspace_inventory_routes.py`)
- domains (`app/routes/domain_routes.py`)
- query (`app/routes/no_code_query_routes.py`)
- query-tree (`app/routes/query_tree_routes.py`)
- saved-queries (`app/routes/query_tree_routes.py`)
- catalog (`app/routes/catalog_routes.py`)

## Services (Public classes)

- Domain services: `DomainAdminWriteService`, `DomainJoinService`, `DomainTableReadService`, `DomainTableWriteService`, `DomainSummaryReadService`, `DomainUserReadService`, `DomainUserWriteService`, `BuilderColumnFeedService`, `DomainColumnSampleReadService`
- Query tree: `SavedQueryTreeService`, `SavedQueryReadService`, `SavedQueryWriteService`, `SavedQueryShareService`, `SavedQueryFolderWriteService`, `QueryFolderService`
- Models: `ModelReadService`, `ModelWriteService`, `ModelUpdateService`, `ModelUploadService`, `ModelSnapshotImportService`, `ModelSampleService`, `ModelColumnSampleReadService`
- Workspace inventory: `WorkspaceSnapshotService`, `WorkspaceSnapshotEnsureService`, `WorkspaceSampleWriteService`, `UnmappedWorkspaceTablesReadService`, `WorkspacePipelineService`
- Users: `UserService`, `WorkspaceUserReadService`
- Auth: `AuthService`, `OtpService`, `PasswordService`
- Products: `ProductService`, `ProductGroupService`, `RoleService`
- Crosswalks: `ListReadService`, `ListUploadService`, `ListTemplateService`, `ListWriter`/`DualListWriter`
- No-code: `NoCodeQueryService`
- Misc: `ConnectionService`, `DashboardService`, `WorkspaceService`, `WarehouseService`, `UdfService`
- Recon: `WorkspaceReconService`

## Ports / Adapters

- SQL executor port: `SQLExecutor`, `SQLTransaction` (`app/ports/sql_executor.py`)
- MySQL adapter: `MySQLSQLExecutor` (`app/adapters/mysql_sql_executor.py`)
- Databricks SQL adapter: `DatabricksSQLExecutor` (`app/adapters/databricks_sql_executor.py`)
- Domain resolver: `DomainResolver` (`app/services/domain_resolver.py`)
- Token managers: `DatabricksTokenManager`, `SigmaTokenManager` (`app/adapters/*`)
