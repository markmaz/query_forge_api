from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..schemas.saved_queries import ListSavedQueriesRequest, RunSavedQueryRequest
from ..tool_registry import execute_tool


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.tool(
        name="list_saved_queries",
        description=(
            "List saved queries visible to the caller in the active workspace. "
            "This is metadata-only and does not return query bodies unless the caller follows up with a specific query read or execution tool."
        ),
    )
    async def list_saved_queries(request: ListSavedQueriesRequest, ctx: Context) -> dict:
        adapter = dependencies.get_saved_query_adapter()
        return await execute_tool(
            kind="tool",
            name="list_saved_queries",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.list_saved_queries(
                request_context=request_context,
                folder_id=request.folder_id,
            ),
        )

    @mcp.tool(
        name="run_saved_query",
        description=(
            "Run a previously governed saved query in preview mode only. "
            "This enforces the same saved-query visibility rules as QueryForge and applies preview row limits."
        ),
    )
    async def run_saved_query(request: RunSavedQueryRequest, ctx: Context) -> dict:
        adapter = dependencies.get_saved_query_adapter()
        return await execute_tool(
            kind="tool",
            name="run_saved_query",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.run_saved_query(
                request_context=request_context,
                query_id=request.query_id,
                limit=request.limit,
            ),
        )
