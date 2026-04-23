from __future__ import annotations

from types import MethodType, SimpleNamespace

import pytest

from mcp_server.adapters.planner_adapter import PlannerAdapter
from mcp_server.config import MCPSettings
from mcp_server.context import RequestContext
from mcp_server.exceptions import MCPError
from mcp_server.schemas.planner import (
    CompileQueryResponse,
    PlanField,
    PlanFilter,
    PlanSort,
    PreviewQueryResponse,
    QueryPlan,
    ValidateQueryPlanResponse,
)


def _request_context() -> RequestContext:
    return RequestContext(
        user_id="user-1",
        workspace_id="ws-1",
        allowed_domain_keys=["students"],
        can_preview=True,
        can_run_saved_queries=True,
        trace_id="trace-1",
        effective_roles=["query_studio:user"],
        is_admin=False,
    )


def _capabilities():
    return {
        "dimensions": [
            {
                "column_key": "wt12.school_name",
                "label": "School Name",
                "workspace_table_id": 12,
                "column_name": "school_name",
                "filterable": True,
                "table_name": "dim_school",
            },
            {
                "column_key": "wt12.calendar_date",
                "label": "Calendar Date",
                "workspace_table_id": 12,
                "column_name": "calendar_date",
                "filterable": True,
                "table_name": "dim_calendar",
            },
        ],
        "domain_metrics": [
            {
                "metric_key": "enrollment",
                "label": "Enrollment",
                "agg": "count",
            }
        ],
    }


def _adapter(settings: MCPSettings) -> PlannerAdapter:
    return PlannerAdapter(
        settings=settings,
        planner_feature_service=SimpleNamespace(plan_domain=lambda *args, **kwargs: {}),
        capabilities_service=SimpleNamespace(
            get_domain_capabilities=lambda workspace_id, user_id, domain_id: _capabilities()
        ),
        domain_adapter=SimpleNamespace(
            resolve_domain=lambda request_context, domain_key: {"id": 1, "key": "students"}
        ),
        context_builder=SimpleNamespace(build=lambda workspace_id: SimpleNamespace(sql_exec=object())),
    )


def test_validate_query_plan_normalizes_fields_and_operators():
    adapter = _adapter(MCPSettings())
    plan = QueryPlan(
        intent="listing",
        domain_key="students",
        selected_fields=[PlanField(key="wt12.school_name", role="dimension", label="School")],
        filters=[PlanFilter(key="wt12.school_name", operator="EQUALS", value="Barksdale Elementary")],
        sort=[PlanSort(key="wt12.school_name", direction="asc")],
    )

    response = adapter.validate_query_plan(request_context=_request_context(), plan=plan)

    assert response.valid is True
    assert response.normalized_plan.selected_fields[0].label == "School Name"
    assert response.normalized_plan.filters[0].operator == "equals"


def test_validate_query_plan_rejects_aggregate_without_metric():
    adapter = _adapter(MCPSettings())
    plan = QueryPlan(
        intent="aggregate",
        domain_key="students",
        selected_fields=[PlanField(key="wt12.school_name", role="dimension")],
    )

    response = adapter.validate_query_plan(request_context=_request_context(), plan=plan)

    assert response.valid is False
    assert response.errors[0]["path"] == "intent"


def test_compile_query_redacts_sql_when_disabled():
    adapter = _adapter(MCPSettings(include_raw_sql=False, preview_default_limit=25))
    adapter._prepare_query = MethodType(  # type: ignore[method-assign]
        lambda self, workspace_id, sql_json, limit: SimpleNamespace(qf_rendered_sql="select * from secure_table"),
        adapter,
    )
    plan = QueryPlan(
        intent="listing",
        domain_key="students",
        selected_fields=[PlanField(key="wt12.school_name", role="dimension")],
        internal={"sql_json": {"meta": {"tool": "planner"}}},
    )

    response = adapter.compile_query(request_context=_request_context(), plan=plan)

    assert isinstance(response, CompileQueryResponse)
    assert response.compiled["sql"] is None
    assert response.execution_metadata.row_limit == 25


def test_compile_query_ignores_client_supplied_internal_sql_json():
    adapter = _adapter(MCPSettings(include_raw_sql=False, preview_default_limit=25))
    observed: dict[str, object] = {}

    def _prepare_query(self, workspace_id, sql_json, limit):
        observed["sql_json"] = sql_json
        return SimpleNamespace(qf_rendered_sql="select 1")

    adapter._prepare_query = MethodType(_prepare_query, adapter)  # type: ignore[method-assign]
    plan = QueryPlan(
        intent="listing",
        domain_key="students",
        selected_fields=[PlanField(key="wt12.school_name", role="dimension")],
        internal={"sql_json": {"meta": {"tool": "malicious_override"}, "columns": [{"unsafe": True}]}},
    )

    response = adapter.compile_query(request_context=_request_context(), plan=plan)

    assert isinstance(response, CompileQueryResponse)
    assert response.sql_json["meta"]["tool"] == "queryforge_mcp"
    assert response.sql_json["meta"]["tool"] != "malicious_override"


def test_preview_query_caps_limit_and_returns_rows(monkeypatch: pytest.MonkeyPatch):
    adapter = _adapter(MCPSettings(preview_default_limit=100, preview_hard_limit=150))
    observed: dict[str, int] = {}

    adapter.validate_query_plan = MethodType(  # type: ignore[method-assign]
        lambda self, request_context, plan: ValidateQueryPlanResponse(
            valid=True,
            errors=[],
            warnings=[],
            normalized_plan=plan,
        ),
        adapter,
    )
    adapter._compile_sql_json = MethodType(  # type: ignore[method-assign]
        lambda self, request_context, plan: {"columns": [], "meta": {"tool": "queryforge_mcp"}},
        adapter,
    )

    class FakeQueryForgeService:
        def __init__(self, executor, domain_resolver):
            pass

        def run(self, sql_json, mode, limit, offset):
            observed["limit"] = limit
            return SimpleNamespace(
                columns=[{"name": "school_name", "type": "STRING", "label": "School Name"}],
                rows=[{"school_name": "Barksdale"}, {"school_name": "Carver"}],
                total=4,
            )

    monkeypatch.setattr("mcp_server.adapters.planner_adapter.QueryForgeService", FakeQueryForgeService)
    monkeypatch.setattr(
        "mcp_server.adapters.planner_adapter.DomainResolver",
        lambda workspace_id: SimpleNamespace(workspace_id=workspace_id),
    )

    plan = QueryPlan(
        intent="listing",
        domain_key="students",
        selected_fields=[PlanField(key="wt12.school_name", role="dimension")],
    )
    response = adapter.preview_query(
        request_context=_request_context(),
        plan=plan,
        limit=120,
    )

    assert isinstance(response, PreviewQueryResponse)
    assert observed["limit"] == 100
    assert response.truncated is True
    assert response.row_count_returned == 2


def test_preview_query_rejects_limit_over_hard_cap():
    adapter = _adapter(MCPSettings(preview_default_limit=100, preview_hard_limit=150))
    plan = QueryPlan(intent="listing", domain_key="students")

    with pytest.raises(MCPError) as exc_info:
        adapter.preview_query(request_context=_request_context(), plan=plan, limit=151)

    assert exc_info.value.error_code == "PREVIEW_LIMIT_EXCEEDED"
