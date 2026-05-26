from __future__ import annotations

from app.features.flowforge.service import FlowForgeService

from ..context import RequestContext
from ..exceptions import MCPError
from ..schemas.flowforge import (
    FlowForgeHumanTaskListResponse,
    FlowForgeMatchingSummaryResponse,
    FlowForgeOperatorNoteResponse,
    FlowForgeReportSummaryResponse,
    FlowForgeResourceProfileResponse,
    FlowForgeRunListResponse,
    FlowForgeRunResponse,
    FlowForgeRunTimelineResponse,
)


class FlowForgeAdapter:
    def __init__(self, *, service: FlowForgeService | None = None) -> None:
        self._service = service or FlowForgeService()

    def list_runs(
        self,
        *,
        request_context: RequestContext,
        status: str | None,
        mode: str | None,
        limit: int,
        offset: int,
    ) -> FlowForgeRunListResponse:
        self._require_read_access(request_context)
        payload = self._service.list_runs(
            workspace_id=request_context.workspace_id,
            status=status,
            mode=mode,
            limit=limit,
            offset=offset,
        )
        return FlowForgeRunListResponse(**payload)

    def get_run(self, *, request_context: RequestContext, run_id: int) -> FlowForgeRunResponse:
        self._require_read_access(request_context)
        run = self._service.get_run(workspace_id=request_context.workspace_id, run_id=run_id)
        if run is None:
            raise MCPError(
                error_code="NOT_FOUND",
                message=f"FlowForge run '{run_id}' was not found",
                status_code=404,
            )
        return FlowForgeRunResponse(workspace_id=request_context.workspace_id, run=run)

    def get_run_timeline(
        self,
        *,
        request_context: RequestContext,
        run_id: int,
        limit: int,
    ) -> FlowForgeRunTimelineResponse:
        self._require_read_access(request_context)
        payload = self._service.list_run_events(
            workspace_id=request_context.workspace_id,
            run_id=run_id,
            limit=limit,
        )
        return FlowForgeRunTimelineResponse(**payload)

    def list_human_tasks(
        self,
        *,
        request_context: RequestContext,
        run_id: int,
        limit: int,
    ) -> FlowForgeHumanTaskListResponse:
        self._require_read_access(request_context)
        payload = self._service.list_run_human_tasks(
            workspace_id=request_context.workspace_id,
            run_id=run_id,
            limit=limit,
        )
        return FlowForgeHumanTaskListResponse(**payload)

    def get_needs_attention(
        self,
        *,
        request_context: RequestContext,
        limit: int,
        offset: int,
    ) -> FlowForgeRunListResponse:
        self._require_read_access(request_context)
        payload = self._service.list_runs(
            workspace_id=request_context.workspace_id,
            status="needs_attention",
            mode=None,
            limit=limit,
            offset=offset,
        )
        return FlowForgeRunListResponse(**payload)

    def get_resource_profile(
        self,
        *,
        request_context: RequestContext,
        resource_set_id: int,
        snapshot_batch_id: int,
        source_record_key: str,
    ) -> FlowForgeResourceProfileResponse:
        self._require_read_access(request_context)
        payload = self._service.get_resource_profile(
            workspace_id=request_context.workspace_id,
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
            source_record_key=source_record_key,
        )
        return FlowForgeResourceProfileResponse(workspace_id=request_context.workspace_id, **payload)

    def get_matching_summary(self, *, request_context: RequestContext) -> FlowForgeMatchingSummaryResponse:
        self._require_read_access(request_context)
        policies = self._service.list_matching_policies(workspace_id=request_context.workspace_id)
        return FlowForgeMatchingSummaryResponse(workspace_id=request_context.workspace_id, policies=policies)

    def get_report_summary(
        self,
        *,
        request_context: RequestContext,
        mode: str | None,
    ) -> FlowForgeReportSummaryResponse:
        self._require_read_access(request_context)
        payload = self._service.get_report_summary(workspace_id=request_context.workspace_id, mode=mode)
        return FlowForgeReportSummaryResponse(**payload)

    def add_operator_note(
        self,
        *,
        request_context: RequestContext,
        run_id: int,
        note: str,
        idempotency_key: str | None,
    ) -> FlowForgeOperatorNoteResponse:
        self._require_operate_access(request_context)
        event = self._service.add_run_note(
            workspace_id=request_context.workspace_id,
            run_id=run_id,
            payload={"note": note, "idempotency_key": idempotency_key},
            actor_user_id=request_context.user_id,
        )
        return FlowForgeOperatorNoteResponse(
            workspace_id=request_context.workspace_id,
            run_id=run_id,
            event=event,
        )

    def _require_read_access(self, request_context: RequestContext) -> None:
        if request_context.principal_type == "app":
            return
        if self._has_role(request_context, "flowforge:user") or self._has_role(request_context, "flowforge:admin"):
            return
        raise MCPError(
            error_code="FORBIDDEN",
            message="FlowForge MCP read tools require flowforge:user access",
            status_code=403,
        )

    def _require_operate_access(self, request_context: RequestContext) -> None:
        if request_context.principal_type == "app":
            return
        if self._has_role(request_context, "flowforge:admin"):
            return
        raise MCPError(
            error_code="FORBIDDEN",
            message="FlowForge MCP operation tools require flowforge:admin access",
            status_code=403,
        )

    @staticmethod
    def _has_role(request_context: RequestContext, role: str) -> bool:
        roles = {str(value or "").strip() for value in list(request_context.effective_roles or [])}
        return role in roles
