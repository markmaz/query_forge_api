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

## Resources

The v1 resource set is:

- `qf://workspace/{workspace_id}/domains`
- `qf://workspace/{workspace_id}/domain/{domain_key}`
- `qf://workspace/{workspace_id}/planner-policies`
- `qf://workspace/{workspace_id}/semantic-registry/{concept_key}`
- `qf://workspace/{workspace_id}/saved-queries`

## Auth Model

- bearer token required for all non-OPTIONS requests
- authenticated user context is resolved before every tool/resource execution
- workspace access is verified against QueryForge services
- visible domains are derived server-side
- preview and saved-query permissions are derived server-side

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
- `MCP_DEBUG`

## Testing

```bash
pytest -q mcp_server/tests
```

The MCP tests cover:

- auth resolution
- wrapper error mapping
- domain and dictionary adapter behavior
- planner validation and compile/preview behavior
- saved query behavior
- server registration and semantic resource summaries
