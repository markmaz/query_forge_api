from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..resource_registry import execute_resource


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.resource(
        "qf://workspace/{workspace_id}/domains",
        name="workspace_domains_index",
        description="Compact read-only index of domains visible to the caller in the specified workspace.",
    )
    async def workspace_domains(workspace_id: str, ctx: Context) -> str:
        adapter = dependencies.get_domain_adapter()
        return await execute_resource(
            name="workspace_domains_index",
            workspace_id=workspace_id,
            request_summary={"workspace_id": workspace_id},
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.domains_resource(request_context=request_context),
        )

    @mcp.resource(
        "qf://workspace/{workspace_id}/domain/{domain_key}",
        name="domain_profile_summary",
        description="Concise planner-safe QueryForge domain profile for one visible domain.",
    )
    async def domain_profile(workspace_id: str, domain_key: str, ctx: Context) -> str:
        adapter = dependencies.get_domain_adapter()
        return await execute_resource(
            name="domain_profile_summary",
            workspace_id=workspace_id,
            request_summary={"workspace_id": workspace_id, "domain_key": domain_key},
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.get_domain_profile(
                request_context=request_context,
                domain_key=domain_key,
            ),
        )
