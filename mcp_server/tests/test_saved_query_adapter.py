from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp_server.adapters.saved_query_adapter import SavedQueryAdapter
from mcp_server.config import MCPSettings
from mcp_server.context import RequestContext
from mcp_server.exceptions import MCPError


def _request_context(*, can_run_saved_queries: bool = True) -> RequestContext:
    return RequestContext(
        user_id="user-1",
        workspace_id="ws-1",
        allowed_domain_keys=["students"],
        can_preview=True,
        can_run_saved_queries=can_run_saved_queries,
        trace_id="trace-1",
        effective_roles=["query_studio:user"],
        is_admin=False,
    )


def test_list_saved_queries_filters_by_folder_and_scope(monkeypatch: pytest.MonkeyPatch):
    class FakeSavedQueryReadService:
        def __init__(self, workspace_id, user_id, is_admin):
            pass

        def get_tree(self, view):
            return {
                "rootNodes": [
                    {"nodeType": "query", "id": "q1", "folderId": "f1", "name": "My Query"},
                    {"nodeType": "query", "id": "q2", "folderId": "f2", "name": "Shared Query"},
                ]
            }

        def get_query(self, query_id):
            payloads = {
                "q1": {"id": "q1", "name": "My Query", "scope": "MINE", "sqlJson": {"domainId": 1}, "updatedAt": "2026-04-22T10:00:00Z"},
                "q2": {"id": "q2", "name": "Shared Query", "scope": "SHARED", "sqlJson": {"domainId": 1}, "updatedAt": "2026-04-22T11:00:00Z"},
            }
            return payloads[query_id]

    monkeypatch.setattr("mcp_server.adapters.saved_query_adapter.SavedQueryReadService", FakeSavedQueryReadService)

    adapter = SavedQueryAdapter(
        settings=MCPSettings(),
        context_builder=SimpleNamespace(build=lambda workspace_id: SimpleNamespace(sql_exec=object())),
        domain_adapter=SimpleNamespace(
            list_visible_domains=lambda request_context: [{"id": 1, "key": "students"}]
        ),
    )

    response = adapter.list_saved_queries(request_context=_request_context(), folder_id="f1")

    assert [item.query_id for item in response.items] == ["q1"]
    assert response.items[0].owner_scope == "user"
    assert response.items[0].domain_key == "students"


def test_run_saved_query_enforces_limit_and_returns_preview_rows(monkeypatch: pytest.MonkeyPatch):
    class FakeSavedQueryReadService:
        def __init__(self, workspace_id, user_id, is_admin):
            pass

        def get_query(self, query_id):
            return {"id": query_id, "sqlJson": {"domainId": 1}}

    class FakeQueryForgeService:
        def __init__(self, executor, domain_resolver):
            pass

        def run(self, sql_json, mode, limit, offset):
            assert limit == 75
            return SimpleNamespace(
                columns=[{"name": "school_name", "type": "STRING"}],
                rows=[{"school_name": "Barksdale"}],
                total=2,
            )

    monkeypatch.setattr("mcp_server.adapters.saved_query_adapter.SavedQueryReadService", FakeSavedQueryReadService)
    monkeypatch.setattr("mcp_server.adapters.saved_query_adapter.QueryForgeService", FakeQueryForgeService)
    monkeypatch.setattr(
        "mcp_server.adapters.saved_query_adapter.DomainResolver",
        lambda workspace_id: SimpleNamespace(workspace_id=workspace_id),
    )

    adapter = SavedQueryAdapter(
        settings=MCPSettings(preview_default_limit=75, preview_hard_limit=100),
        context_builder=SimpleNamespace(build=lambda workspace_id: SimpleNamespace(sql_exec=object())),
        domain_adapter=SimpleNamespace(list_visible_domains=lambda request_context: []),
    )

    response = adapter.run_saved_query(
        request_context=_request_context(),
        query_id="q1",
        limit=90,
    )

    assert response.query_id == "q1"
    assert response.truncated is True
    assert response.rows == [{"school_name": "Barksdale"}]


def test_run_saved_query_rejects_when_disabled():
    adapter = SavedQueryAdapter(
        settings=MCPSettings(),
        context_builder=SimpleNamespace(build=lambda workspace_id: SimpleNamespace(sql_exec=object())),
        domain_adapter=SimpleNamespace(list_visible_domains=lambda request_context: []),
    )

    with pytest.raises(MCPError) as exc_info:
        adapter.run_saved_query(
            request_context=_request_context(can_run_saved_queries=False),
            query_id="q1",
            limit=25,
        )

    assert exc_info.value.error_code == "FORBIDDEN"
