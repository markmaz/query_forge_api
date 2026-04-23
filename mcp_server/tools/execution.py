from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..schemas.planner import PreviewQueryRequest
from ..tool_registry import execute_tool


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.tool(
        name="preview_query",
        description=(
            "Run a preview-only QueryForge execution. "
            "This enforces preview caps, uses the governed QueryForge compiler, and returns JSON-safe rows only."
        ),
    )
    async def preview_query(request: PreviewQueryRequest, ctx: Context) -> dict:
        adapter = dependencies.get_execution_adapter()
        return await execute_tool(
            kind="tool",
            name="preview_query",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.preview_query(
                request_context=request_context,
                plan=request.plan,
                limit=request.limit,
            ),
        )
