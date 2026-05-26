from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from ..dependencies import MCPDependencies
from ..schemas.flowforge import (
    FlowForgeAddOperatorNoteRequest,
    FlowForgeLimitedRunRequest,
    FlowForgeListRunsRequest,
    FlowForgeNeedsAttentionRequest,
    FlowForgeReportSummaryRequest,
    FlowForgeResourceProfileRequest,
    FlowForgeRunRequest,
)
from ..tool_registry import execute_tool


def register(mcp: FastMCP, dependencies: MCPDependencies) -> None:
    @mcp.tool(
        name="flowforge_list_runs",
        description=(
            "List FlowForge workflow runs visible in a QueryForge workspace. "
            "This is a redacted operational view and does not expose raw intake payloads."
        ),
    )
    async def flowforge_list_runs(request: FlowForgeListRunsRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_list_runs",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.list_runs(
                request_context=request_context,
                status=request.status,
                mode=request.mode,
                limit=request.limit,
                offset=request.offset,
            ),
        )

    @mcp.tool(
        name="flowforge_get_run",
        description="Return one redacted FlowForge workflow run by id for operator inspection.",
    )
    async def flowforge_get_run(request: FlowForgeRunRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_get_run",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.get_run(
                request_context=request_context,
                run_id=request.run_id,
            ),
        )

    @mcp.tool(
        name="flowforge_get_run_timeline",
        description=(
            "Return the redacted append-only FlowForge event timeline for a workflow run. "
            "Sensitive event payload JSON is not exposed."
        ),
    )
    async def flowforge_get_run_timeline(request: FlowForgeLimitedRunRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_get_run_timeline",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.get_run_timeline(
                request_context=request_context,
                run_id=request.run_id,
                limit=request.limit,
            ),
        )

    @mcp.tool(
        name="flowforge_list_human_tasks",
        description="List redacted human tasks attached to a FlowForge workflow run.",
    )
    async def flowforge_list_human_tasks(request: FlowForgeLimitedRunRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_list_human_tasks",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.list_human_tasks(
                request_context=request_context,
                run_id=request.run_id,
                limit=request.limit,
            ),
        )

    @mcp.tool(
        name="flowforge_get_needs_attention",
        description="List FlowForge runs currently marked needs_attention for operator triage.",
    )
    async def flowforge_get_needs_attention(request: FlowForgeNeedsAttentionRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_get_needs_attention",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.get_needs_attention(
                request_context=request_context,
                limit=request.limit,
                offset=request.offset,
            ),
        )

    @mcp.tool(
        name="flowforge_get_resource_profile",
        description=(
            "Return one redacted FlowForge resource snapshot profile by resource set, snapshot batch, "
            "and source record key."
        ),
    )
    async def flowforge_get_resource_profile(request: FlowForgeResourceProfileRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_get_resource_profile",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.get_resource_profile(
                request_context=request_context,
                resource_set_id=request.resource_set_id,
                snapshot_batch_id=request.snapshot_batch_id,
                source_record_key=request.source_record_key,
            ),
        )

    @mcp.tool(
        name="flowforge_get_matching_summary",
        description="Return FlowForge matching-policy metadata for the workspace without policy publish mutation.",
    )
    async def flowforge_get_matching_summary(request: FlowForgeReportSummaryRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_get_matching_summary",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.get_matching_summary(request_context=request_context),
        )

    @mcp.tool(
        name="flowforge_get_report_summary",
        description="Return concise FlowForge run-count metrics for reporting and operational triage.",
    )
    async def flowforge_get_report_summary(request: FlowForgeReportSummaryRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_get_report_summary",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.get_report_summary(
                request_context=request_context,
                mode=request.mode,
            ),
        )

    @mcp.tool(
        name="flowforge_add_operator_note",
        description=(
            "Append a redacted operator note to a FlowForge run timeline. "
            "This does not advance workflow execution or alter assignment state."
        ),
    )
    async def flowforge_add_operator_note(request: FlowForgeAddOperatorNoteRequest, ctx: Context) -> dict:
        adapter = dependencies.get_flowforge_adapter()
        return await execute_tool(
            kind="tool",
            name="flowforge_add_operator_note",
            workspace_id=request.workspace_id,
            request_summary=request.model_dump(mode="json", exclude_none=True),
            ctx=ctx,
            dependencies=dependencies,
            handler=lambda request_context: adapter.add_operator_note(
                request_context=request_context,
                run_id=request.run_id,
                note=request.note,
                idempotency_key=request.idempotency_key,
            ),
        )
