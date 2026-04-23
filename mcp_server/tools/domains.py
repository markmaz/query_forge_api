from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..schemas.domains import GetDomainProfileRequest, SearchDomainsRequest
from ..tool_registry import execute_tool


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.tool(
        name="search_domains",
        description=(
            "Search visible QueryForge domains for a business question. "
            "This tool is workspace-scoped, filters out inaccessible domains, "
            "and returns concise capability flags rather than raw schema internals."
        ),
    )
    async def search_domains(request: SearchDomainsRequest, ctx: Context) -> dict:
        adapter = dependencies.get_domain_adapter()
        return await execute_tool(
            kind="tool",
            name="search_domains",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.search_domains(
                request_context=request_context,
                query=request.query,
                limit=request.limit,
            ),
        )

    @mcp.tool(
        name="get_domain_profile",
        description=(
            "Return a concise, planner-friendly QueryForge domain profile. "
            "The response is intentionally redacted to business-facing metadata: "
            "recommended metrics, recommended dimensions, supported intents, time fields, and grain notes."
        ),
    )
    async def get_domain_profile(request: GetDomainProfileRequest, ctx: Context) -> dict:
        adapter = dependencies.get_domain_adapter()
        return await execute_tool(
            kind="tool",
            name="get_domain_profile",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.get_domain_profile(
                request_context=request_context,
                domain_key=request.domain_key,
            ),
        )
