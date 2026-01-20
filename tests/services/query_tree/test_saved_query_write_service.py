from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.query_tree.saved_query_write_service import SavedQueryWriteService
from tests._support.fakes import FakeSQLExecutor


def test_save_query_create(monkeypatch) -> None:
    sql = FakeSQLExecutor()
    service = SavedQueryWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_create_cohort_view_if_needed", lambda **_kwargs: None)

    res = service.save_query(title="My Query", sql_json={"meta": {"tool": "builder"}})
    assert res["created"] is True
    assert res["name"] == "My Query"
    assert sql.write_calls


def test_save_query_update_missing(monkeypatch) -> None:
    sql = FakeSQLExecutor()
    sql.write_responses = [0]
    service = SavedQueryWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_create_cohort_view_if_needed", lambda **_kwargs: None)

    with pytest.raises(ServiceError, match="Saved query not found"):
        service.save_query(title="My Query", sql_json={"meta": {}}, query_id="qid")


def test_build_view_name() -> None:
    service = SavedQueryWriteService(workspace_id="ws1", user_id="user1", sql=FakeSQLExecutor())
    name = service._build_view_name("My Cohort Name")
    assert name.startswith("cohort_my_cohort_name_")


def test_delete_restore_purge_move(monkeypatch) -> None:
    sql = FakeSQLExecutor()
    sql.write_responses = [1, 1, 1]
    sql.query_mappings_responses = [
        [
            {
                "folder_id": None,
                "query_deleted": True,
                "folder_deleted": False,
            }
        ]
    ]

    service = SavedQueryWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_create_cohort_view_if_needed", lambda **_kwargs: None)

    assert service.delete_query(query_id="q1")["deleted"] is True
    assert service.restore_query(query_id="q1")["restored"] is True
    assert service.purge_query(query_id="q1")["purged"] is True

    sql.write_responses = [1]
    assert service.move_query(query_id="q1", folder_id=f"user:{service._uid}")["folderId"] is None

