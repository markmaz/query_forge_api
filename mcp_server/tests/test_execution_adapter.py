from __future__ import annotations

from types import SimpleNamespace

from mcp_server.adapters.execution_adapter import ExecutionAdapter
from mcp_server.context import RequestContext
from mcp_server.schemas.planner import QueryPlan


def test_execution_adapter_delegates_preview_to_planner():
    observed: dict[str, object] = {}

    def _preview_query(*, request_context, plan, limit):
        observed["workspace_id"] = request_context.workspace_id
        observed["plan"] = plan
        observed["limit"] = limit
        return {"rows": [{"ok": True}]}

    adapter = ExecutionAdapter(
        planner_adapter=SimpleNamespace(preview_query=_preview_query)
    )
    request_context = RequestContext(
        user_id="user-1",
        workspace_id="ws-1",
        allowed_domain_keys=["students"],
        can_preview=True,
        can_run_saved_queries=True,
        trace_id="trace-1",
        effective_roles=["query_studio:user"],
        is_admin=False,
    )
    plan = QueryPlan(intent="listing", domain_key="students")

    response = adapter.preview_query(
        request_context=request_context,
        plan=plan,
        limit=50,
    )

    assert response == {"rows": [{"ok": True}]}
    assert observed["workspace_id"] == "ws-1"
    assert observed["plan"] == plan
    assert observed["limit"] == 50
