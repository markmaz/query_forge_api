from __future__ import annotations

from datetime import datetime

import pytest

from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import ExecuteResult
from app.services.forge_insights_threads_service import ForgeInsightsThreadsService
from tests._support.fakes import FakeSQLExecutor


def _project_row(*, project_id: int, archived: int = 0) -> dict:
    return {
        "id": project_id,
        "workspace_id": "ws-1",
        "user_id": "user-1",
        "name": "Project A",
        "description": "Desc",
        "is_archived": archived,
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
        "updated_at": datetime(2026, 1, 1, 12, 1, 0),
    }


def _thread_row(*, thread_id: int, conversation_id: str = "fi_x") -> dict:
    return {
        "id": thread_id,
        "workspace_id": "ws-1",
        "user_id": "user-1",
        "project_id": 7,
        "conversation_id": conversation_id,
        "title": "T1",
        "preview_text": "Preview",
        "is_pinned": 1,
        "is_archived": 0,
        "last_message_at": datetime(2026, 1, 1, 12, 2, 0),
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
        "updated_at": datetime(2026, 1, 1, 12, 3, 0),
    }


def test_create_project_success() -> None:
    sql = FakeSQLExecutor()
    sql.insert_responses = [ExecuteResult(rowcount=1, lastrowid=12)]
    sql.query_mappings_responses = [[_project_row(project_id=12)]]

    svc = ForgeInsightsThreadsService(sql=sql)
    out = svc.create_project(workspace_id="ws-1", user_id="user-1", name="Project A", description="Desc")

    assert out["id"] == 12
    assert out["name"] == "Project A"
    assert out["is_archived"] is False


def test_create_thread_generates_conversation_id_when_missing() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [{"id": 7}],  # assert project exists
        [_thread_row(thread_id=21, conversation_id="fi_generated")],  # fetch created thread
    ]
    sql.insert_responses = [ExecuteResult(rowcount=1, lastrowid=21)]
    svc = ForgeInsightsThreadsService(sql=sql)

    out = svc.create_thread(
        workspace_id="ws-1",
        user_id="user-1",
        project_id=7,
        title="Thread title",
        preview_text="P",
    )

    assert out["id"] == 21
    assert out["conversation_id"] == "fi_generated"
    assert "ON DUPLICATE KEY UPDATE" in sql.insert_calls[0].query
    assert str(sql.insert_calls[0].params["conversation_id"]).startswith("fi_")


def test_list_threads_filters_and_normalizes() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [[_thread_row(thread_id=1, conversation_id="fi_1")]]
    svc = ForgeInsightsThreadsService(sql=sql)

    out = svc.list_threads(workspace_id="ws-1", user_id="user-1", project_id=7, include_archived=False, limit=10, offset=0)
    assert len(out) == 1
    assert out[0]["is_pinned"] is True
    assert out[0]["conversation_id"] == "fi_1"
    assert "forge_insights_conversation" in sql.query_mappings_calls[0].query
    assert sql.query_mappings_calls[0].params["include_stale"] == 0


def test_list_threads_falls_back_to_legacy_query_when_conversation_table_missing() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_exceptions = [Exception("no such table: forge_insights_conversation")]
    sql.query_mappings_responses = [[_thread_row(thread_id=2, conversation_id="fi_2")]]
    svc = ForgeInsightsThreadsService(sql=sql)

    out = svc.list_threads(
        workspace_id="ws-1",
        user_id="user-1",
        include_archived=False,
        include_stale=True,
        limit=10,
        offset=0,
    )
    assert len(out) == 1
    assert out[0]["conversation_id"] == "fi_2"
    assert len(sql.query_mappings_calls) == 2
    assert "forge_insights_conversation" in sql.query_mappings_calls[0].query
    assert "FROM forge_insights_thread" in sql.query_mappings_calls[1].query


def test_update_thread_missing_raises_404() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [[]]  # assert thread exists -> missing
    svc = ForgeInsightsThreadsService(sql=sql)

    with pytest.raises(ServiceError) as exc:
        svc.update_thread(
            workspace_id="ws-1",
            user_id="user-1",
            thread_id=999,
            title="Renamed",
        )
    assert exc.value.status_code == 404


def test_delete_project_missing_raises_404() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [[]]  # assert exists
    svc = ForgeInsightsThreadsService(sql=sql)

    with pytest.raises(ServiceError) as exc:
        svc.delete_project(workspace_id="ws-1", user_id="user-1", project_id=99)
    assert exc.value.status_code == 404
