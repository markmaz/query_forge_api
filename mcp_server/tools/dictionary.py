from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..schemas.dictionary import SearchDictionaryRequest
from ..tool_registry import execute_tool


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.tool(
        name="search_dictionary",
        description=(
            "Search visible QueryForge metadata and semantic dictionary entries. "
            "Results can be constrained to a specific domain and filtered to columns, metrics, dimensions, and filters."
        ),
    )
    async def search_dictionary(request: SearchDictionaryRequest, ctx: Context) -> dict:
        adapter = dependencies.get_dictionary_adapter()
        return await execute_tool(
            kind="tool",
            name="search_dictionary",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.search_dictionary(
                request_context=request_context,
                query=request.query,
                domain_key=request.domain_key,
                types=list(request.types),
                limit=request.limit,
            ),
        )
