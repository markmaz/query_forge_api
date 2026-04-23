from __future__ import annotations

from ..context import RequestContext
from ..schemas.planner import PreviewQueryResponse, QueryPlan
from .planner_adapter import PlannerAdapter


class ExecutionAdapter:
    def __init__(self, *, planner_adapter: PlannerAdapter) -> None:
        self._planner = planner_adapter

    def preview_query(
        self,
        *,
        request_context: RequestContext,
        plan: QueryPlan,
        limit: int,
    ) -> PreviewQueryResponse:
        return self._planner.preview_query(
            request_context=request_context,
            plan=plan,
            limit=limit,
        )
