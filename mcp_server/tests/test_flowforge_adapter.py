from __future__ import annotations

import pytest

from mcp_server.adapters.flowforge_adapter import FlowForgeAdapter
from mcp_server.context import RequestContext
from mcp_server.exceptions import MCPError


def _request_context(*, roles: list[str] | None = None, principal_type: str = "user") -> RequestContext:
    return RequestContext(
        user_id="user-1",
        workspace_id="ws-1",
        allowed_domain_keys=[],
        can_preview=True,
        can_run_saved_queries=True,
        trace_id="trace-1",
        effective_roles=roles or ["flowforge:user", "queryforge_mcp:user"],
        is_admin=False,
        principal_type=principal_type,
        principal_id="principal-1",
        client_id="client-1",
        oauth_scopes=["qf:mcp:read"],
        allowed_tools=[],
        preview_row_limit=100,
    )


class _Service:
    def __init__(self) -> None:
        self.notes: list[dict[str, object]] = []

    def list_runs(self, **kwargs):
        return {
            "workspace_id": kwargs["workspace_id"],
            "status": kwargs.get("status"),
            "mode": kwargs.get("mode"),
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
            "runs": [{"id": 1, "status": kwargs.get("status") or "waiting"}],
        }

    def get_run(self, **kwargs):
        if kwargs["run_id"] == 404:
            return None
        return {"id": kwargs["run_id"], "workspace_id": kwargs["workspace_id"], "status": "waiting"}

    def list_run_events(self, **kwargs):
        return {
            "workspace_id": kwargs["workspace_id"],
            "run_id": kwargs["run_id"],
            "limit": kwargs["limit"],
            "events": [{"id": 10, "event_type": "workflow.run.created"}],
        }

    def list_run_human_tasks(self, **kwargs):
        return {
            "workspace_id": kwargs["workspace_id"],
            "run_id": kwargs["run_id"],
            "limit": kwargs["limit"],
            "tasks": [{"id": 20, "status": "pending"}],
        }

    def list_matching_policies(self, **kwargs):
        return [
            {
                "id": 30,
                "workspace_id": kwargs["workspace_id"],
                "policy_key": "intake-routing",
                "display_name": "Intake Routing",
                "resource_set_id": 40,
                "status": "draft",
            }
        ]

    def get_resource_profile(self, **kwargs):
        return {
            "resource_set_id": kwargs["resource_set_id"],
            "snapshot_batch_id": kwargs["snapshot_batch_id"],
            "source_record_key": kwargs["source_record_key"],
            "record": {"display_name": "Taylor Resource"},
        }

    def get_report_summary(self, **kwargs):
        return {"workspace_id": kwargs["workspace_id"], "mode": kwargs["mode"], "metrics": {"run_count": 2}}

    def add_run_note(self, **kwargs):
        self.notes.append(kwargs)
        return {"id": 99, "event_type": "workflow.operator.note", "event_payload": kwargs["payload"]}


def test_flowforge_adapter_returns_read_payloads():
    service = _Service()
    adapter = FlowForgeAdapter(service=service)
    ctx = _request_context()

    assert adapter.list_runs(request_context=ctx, status=None, mode="production", limit=25, offset=0).runs[0]["id"] == 1
    assert adapter.get_run(request_context=ctx, run_id=1).run["status"] == "waiting"
    assert adapter.get_run_timeline(request_context=ctx, run_id=1, limit=20).events[0]["id"] == 10
    assert adapter.list_human_tasks(request_context=ctx, run_id=1, limit=20).tasks[0]["id"] == 20
    assert adapter.get_needs_attention(request_context=ctx, limit=20, offset=0).runs[0]["status"] == "needs_attention"
    assert adapter.get_matching_summary(request_context=ctx).policies[0]["policy_key"] == "intake-routing"
    assert adapter.get_resource_profile(
        request_context=ctx,
        resource_set_id=40,
        snapshot_batch_id=50,
        source_record_key="resource-1",
    ).record["display_name"] == "Taylor Resource"
    assert adapter.get_report_summary(request_context=ctx, mode=None).metrics["run_count"] == 2


def test_flowforge_adapter_requires_flowforge_role_for_human_reads():
    adapter = FlowForgeAdapter(service=_Service())

    with pytest.raises(MCPError) as exc_info:
        adapter.list_runs(
            request_context=_request_context(roles=["queryforge_mcp:user"]),
            status=None,
            mode=None,
            limit=25,
            offset=0,
        )

    assert exc_info.value.error_code == "FORBIDDEN"


def test_flowforge_adapter_add_operator_note_requires_admin_for_human_principal():
    service = _Service()
    adapter = FlowForgeAdapter(service=service)

    with pytest.raises(MCPError):
        adapter.add_operator_note(
            request_context=_request_context(roles=["flowforge:user", "queryforge_mcp:user"]),
            run_id=1,
            note="Check manually.",
            idempotency_key=None,
        )

    event = adapter.add_operator_note(
        request_context=_request_context(roles=["flowforge:admin", "queryforge_mcp:user"]),
        run_id=1,
        note="Check manually.",
        idempotency_key="note-1",
    )

    assert event.event["event_type"] == "workflow.operator.note"
    assert service.notes[0]["actor_user_id"] == "user-1"


def test_flowforge_adapter_returns_not_found_for_missing_run():
    adapter = FlowForgeAdapter(service=_Service())

    with pytest.raises(MCPError) as exc_info:
        adapter.get_run(request_context=_request_context(), run_id=404)

    assert exc_info.value.error_code == "NOT_FOUND"
