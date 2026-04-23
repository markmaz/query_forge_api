from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..schemas.planner import CompileQueryRequest, PlanQueryRequest, ValidateQueryPlanRequest
from ..tool_registry import execute_tool


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.tool(
        name="plan_query",
        description=(
            "Convert a business question into a governed semantic QueryForge plan. "
            "The result contains semantic field/filter/sort choices plus internal compilation hints, but never returns arbitrary SQL."
        ),
    )
    async def plan_query(request: PlanQueryRequest, ctx: Context) -> dict:
        adapter = dependencies.get_planner_adapter()
        return await execute_tool(
            kind="tool",
            name="plan_query",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.plan_query(
                request_context=request_context,
                prompt=request.prompt,
                domain_key=request.domain_key,
                context=request.context.model_dump(mode="json"),
            ),
        )

    @mcp.tool(
        name="validate_query_plan",
        description=(
            "Deterministically validate and normalize a semantic QueryForge plan. "
            "This checks visible field access, role compatibility, operators, and preview eligibility without executing the query."
        ),
    )
    async def validate_query_plan(request: ValidateQueryPlanRequest, ctx: Context) -> dict:
        adapter = dependencies.get_planner_adapter()
        return await execute_tool(
            kind="tool",
            name="validate_query_plan",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.validate_query_plan(
                request_context=request_context,
                plan=request.plan,
            ),
        )

    @mcp.tool(
        name="compile_query",
        description=(
            "Compile a validated QueryForge semantic plan into SQL JSON and a parameterized compiled statement summary. "
            "Raw SQL is redacted unless MCP_INCLUDE_RAW_SQL is enabled."
        ),
    )
    async def compile_query(request: CompileQueryRequest, ctx: Context) -> dict:
        adapter = dependencies.get_planner_adapter()
        return await execute_tool(
            kind="tool",
            name="compile_query",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.compile_query(
                request_context=request_context,
                plan=request.plan,
            ),
        )
