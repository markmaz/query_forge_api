# Frontend Prompt — Dynamic External Links by Workspace Datasource

You are implementing QueryForge frontend menu behavior.

Goal:
Replace the static left-nav child `External Links > Databricks` with a dynamic link based on current `workspace_id` datasource binding.

## Backend endpoint
Use:
- `GET /api/v1/workspaces/{workspace_id}/external-links`

Response shape:
```json
{
  "workspace_id": "927164193773577",
  "datasource_type": "snowflake",
  "links": [
    {
      "key": "snowflake_console",
      "label": "Snowflake",
      "url": "https://xy12345.snowflakecomputing.com",
      "provider": "snowflake",
      "is_default": true
    }
  ]
}
```

## Requirements
1. Keep workspace-first behavior: resolve from current `workspace_id`.
2. Do not hardcode Databricks label or URL.
3. If links array is empty:
   - hide child link OR show disabled `External Console` item.
4. Use returned `label` as menu text and `url` as href.
5. Open external target in new tab with `rel="noopener noreferrer"`.

## React implementation outline
1. Add API client method:
```ts
getWorkspaceExternalLinks(workspaceId: string): Promise<WorkspaceExternalLinksResponse>
```
2. On app shell/nav load (or workspace switch), fetch endpoint.
3. Cache by workspace id (React Query/SWR key: `workspace-external-links:${workspaceId}`).
4. Render first `is_default=true` link under `External Links` group.
5. Fallback behavior:
   - no links: hide group or show disabled item `External Console`.

## Suggested types
```ts
type WorkspaceExternalLink = {
  key: string;
  label: string;
  url: string;
  provider: string;
  is_default: boolean;
};

type WorkspaceExternalLinksResponse = {
  workspace_id: string;
  datasource_type: string | null;
  links: WorkspaceExternalLink[];
};
```

## Menu behavior examples
- datasource_type=`databricks` -> label `Databricks`
- datasource_type=`snowflake` -> label `Snowflake`
- datasource_type unsupported/no URL -> no child link shown

## Tests
1. Given response with Databricks link -> nav renders `Databricks` and opens correct URL.
2. Given response with Snowflake link -> nav renders `Snowflake`.
3. Given empty links -> nav hides/disabled item.
4. Workspace switch invalidates and reloads link.
