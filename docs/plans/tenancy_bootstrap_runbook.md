# Tenancy Bootstrap Runbook

Use this on a fresh environment after migrations are applied.

## Recommended onboarding order (org-first)
1. Create organization.
2. Create workspace under that organization.
3. Create datasource under that organization.
4. Bind workspace to datasource.
5. Add org/workspace memberships.

### API sequence
- `POST /api/v1/admin/organizations`
- `POST /api/v1/admin/workspaces`
- `POST /api/v1/admin/organizations/{organization_id}/datasources`
- `PATCH /api/v1/admin/workspaces/{workspace_id}/binding`
- `POST /api/v1/admin/organizations/{organization_id}/memberships`
- `POST /api/v1/admin/workspaces/{workspace_id}/memberships`

### Example: create workspace
```json
POST /api/v1/admin/workspaces
{
  "workspace_id": "ws_acme_001",
  "organization_id": "org_acme",
  "name": "Acme District Workspace",
  "description": "Primary analytics workspace",
  "is_active": true,
  "default_catalog": "ANALYTICS",
  "default_schema": "PUBLIC"
}
```

## Script
- `/Users/mmaslak/Local Documents/projects/query-forge-api/scripts/bootstrap_tenancy.py`

## What it does (idempotent)
1. Resolves or creates organization.
2. Resolves or creates datasource under that organization.
3. Binds an existing workspace to organization + datasource.
4. Optionally grants `org_admin` + `admin` memberships to a user.

## Example: Snowflake
```bash
python scripts/bootstrap_tenancy.py \
  --workspace-id 927164193773577 \
  --organization-name "Acme District" \
  --organization-slug acme-district \
  --datasource-name "Acme Snowflake" \
  --datasource-type snowflake \
  --datasource-slug acme-snowflake \
  --datasource-secret-ref env:ACME_SNOWFLAKE_PASSWORD \
  --datasource-config-json '{"account":"xy12345","user":"svc_queryforge","database":"ANALYTICS","warehouse":"COMPUTE_WH","schema":"PUBLIC","role":"ANALYST"}' \
  --default-catalog ANALYTICS \
  --default-schema PUBLIC \
  --admin-user-id ebc3f256-0520-40f6-a71f-140a1fb2af82
```

## Example: Databricks
```bash
python scripts/bootstrap_tenancy.py \
  --workspace-id 927164193773577 \
  --organization-name "Acme District" \
  --datasource-name "Acme Databricks" \
  --datasource-type databricks \
  --datasource-secret-ref env:ACME_DATABRICKS_TOKEN \
  --datasource-config-json '{"host":"https://adb-123.4.azuredatabricks.net","warehouse_id":"<warehouse-id>","catalog":"main","schema":"default"}'
```

## Using config file instead of inline JSON
```bash
python scripts/bootstrap_tenancy.py \
  --workspace-id 927164193773577 \
  --organization-name "Acme District" \
  --datasource-name "Acme MySQL" \
  --datasource-type mysql \
  --datasource-config-file ./config/acme_mysql_datasource.json
```

## Notes
- Workspace must already exist in `workspace` table.
- Secrets are not stored directly in datasource rows; use `--datasource-secret-ref`.
- Script output is JSON and can be captured for deployment logs.

## Admin API option
You can run the same bootstrap via API (admin token required):

`POST /api/v1/admin/tenancy/bootstrap`

Example body:
```json
{
  "workspace_id": "927164193773577",
  "organization_name": "Acme District",
  "organization_slug": "acme-district",
  "datasource_name": "Acme Snowflake",
  "datasource_type": "snowflake",
  "datasource_secret_ref": "env:ACME_SNOWFLAKE_PASSWORD",
  "datasource_config_json": {
    "account": "xy12345",
    "user": "svc_queryforge",
    "database": "ANALYTICS",
    "warehouse": "COMPUTE_WH",
    "schema": "PUBLIC",
    "role": "ANALYST"
  },
  "default_catalog": "ANALYTICS",
  "default_schema": "PUBLIC",
  "admin_user_id": "ebc3f256-0520-40f6-a71f-140a1fb2af82"
}
```
