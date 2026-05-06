# QueryForge MCP Server

The QueryForge MCP server is the governed AI-facing semantic access layer for QueryForge.

It is a standalone Python process that reuses the existing QueryForge service layer instead of exposing Flask routes directly.

## Product Contract

The MCP server supports:

- workspace-scoped domain discovery
- concise domain profiles
- dictionary and semantic metadata lookup
- semantic planning and deterministic validation
- compile-to-SQL-JSON
- preview-only execution
- saved query discovery and preview execution
- resource summaries for grounding

It does not support:

- arbitrary SQL input
- writes, DDL, or DML
- unrestricted schema crawling
- bypassing QueryForge planner or policy enforcement

## Entry Point

```bash
python -m mcp_server
```

This command runs the wrapped ASGI app through `uvicorn`, not `FastMCP.run()` directly. The wrapper is required because it mounts the MCP streamable HTTP endpoint and the operational endpoints below.

## Health Check

The standalone MCP process exposes:

- `GET /healthz`

This endpoint is intentionally unauthenticated so local probes, nginx upstream checks, Docker healthchecks, and backend admin health checks can verify the MCP process without requiring an MCP OAuth token.

The backend admin health payload reads `MCP_RESOURCE_URL`, calls `${MCP_RESOURCE_URL}/healthz`, and exposes the result as `checks.mcp` on `/api/v1/admin/health/detailed`.

Main implementation files:

- `mcp_server/server.py`
- `mcp_server/auth.py`
- `mcp_server/dependencies.py`
- `mcp_server/adapters/`
- `mcp_server/tools/`
- `mcp_server/resources/`

## Tools

The v1 tool set is:

- `search_domains`
- `get_domain_profile`
- `search_dictionary`
- `plan_query`
- `validate_query_plan`
- `compile_query`
- `preview_query`
- `list_saved_queries`
- `run_saved_query`
- `flowforge_list_runs`
- `flowforge_get_run`
- `flowforge_get_run_timeline`
- `flowforge_list_human_tasks`
- `flowforge_get_needs_attention`
- `flowforge_get_resource_profile`
- `flowforge_get_matching_summary`
- `flowforge_get_report_summary`
- `flowforge_add_operator_note`

FlowForge tools call `FlowForgeService` rather than raw runtime tables. Human read calls require the existing MCP channel grant plus `flowforge:user` or `flowforge:admin`; `flowforge_add_operator_note` requires `flowforge:admin` for human callers. App principals remain controlled by `mcp_principal_grants.allowed_tools`.

## Resources

The v1 resource set is:

- `qf://workspace/{workspace_id}/domains`
- `qf://workspace/{workspace_id}/domain/{domain_key}`
- `qf://workspace/{workspace_id}/planner-policies`
- `qf://workspace/{workspace_id}/semantic-registry/{concept_key}`
- `qf://workspace/{workspace_id}/saved-queries`

## Auth Model

- bearer token required for all non-OPTIONS requests
- MCP tokens must use `typ=mcp_access` and an audience matching `MCP_RESOURCE_URL`
- global `MCP_ENABLED` and workspace MCP settings are enforced before any tool/resource execution
- human callers require the workspace-scoped `queryforge_mcp:user` RBAC role
- preview tools require `queryforge_mcp:preview` plus normal Query Studio access by default
- app principals use `client_credentials` tokens and active `mcp_principal_grants` rows
- app-principal grants constrain workspace, tools, domain keys, preview permission, and preview row limits
- workspace access and visible domains for human callers are derived server-side
- per-principal, per-client, and preview-specific coarse rate limits are enforced before adapter execution
- audit events are persisted to `mcp_oauth_audit_log` when `MCP_AUDIT_LOGGING=true`

No MCP tool trusts client-supplied visibility.

## Important Runtime Settings

- `MCP_HOST`
- `MCP_PORT`
- `MCP_STREAMABLE_HTTP_PATH`
- `MCP_ALLOWED_ORIGINS`
- `MCP_INCLUDE_RAW_SQL`
- `MCP_PREVIEW_DEFAULT_LIMIT`
- `MCP_PREVIEW_HARD_LIMIT`
- `MCP_PREVIEW_TIMEOUT_SECONDS`
- `MCP_ENABLE_RESOURCES`
- `MCP_ENABLE_SAVED_QUERIES`
- `MCP_AUDIT_LOGGING`
- `MCP_RATE_LIMIT_PER_USER_PER_MINUTE`
- `MCP_RATE_LIMIT_PER_CLIENT_PER_MINUTE`
- `MCP_RATE_LIMIT_PREVIEW_PER_USER_PER_MINUTE`
- `MCP_DEBUG`

## Testing

```bash
./scripts/pytest.sh -q mcp_server/tests
```

The MCP tests cover:

- auth resolution
- wrapper error mapping
- domain and dictionary adapter behavior
- planner validation and compile/preview behavior
- saved query behavior
- server registration and semantic resource summaries
