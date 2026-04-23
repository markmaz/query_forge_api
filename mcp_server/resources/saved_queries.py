from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..resource_registry import execute_resource


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.resource(
        "qf://workspace/{workspace_id}/saved-queries",
        name="saved_queries_index",
        description="Read-only index of saved queries visible to the caller in the specified workspace.",
    )
    async def saved_queries_index(workspace_id: str, ctx: Context) -> str:
        adapter = dependencies.get_saved_query_adapter()
        return await execute_resource(
            name="saved_queries_index",
            workspace_id=workspace_id,
            request_summary={"workspace_id": workspace_id},
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.saved_queries_resource(request_context=request_context),
        )
