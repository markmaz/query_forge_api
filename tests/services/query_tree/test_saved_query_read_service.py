from __future__ import annotations

from datetime import datetime

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.query_tree.saved_query_read_service import SavedQueryReadService
from tests._support.fakes import FakeForgeQueryPort


def test_get_query_library_access() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "query_id": "q1",
                "workspace_id": None,
                "scope": "LIBRARY",
                "owner_user_id": "user1",
                "folder_id": None,
                "title": "Lib Query",
                "description": None,
                "sql_json": {"meta": {"tool": "builder"}},
                "created_at": None,
                "updated_at": None,
            }
        ]
    ]
    svc = SavedQueryReadService(workspace_id="ws1", user_id="user1", is_admin=False, sql=sql)
    payload = svc.get_query("q1")
    assert payload["accessVia"] == "library"
    assert payload["canEdit"] is False


def test_get_query_owner_access() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "query_id": "q2",
                "workspace_id": "ws1",
                "scope": "MINE",
                "owner_user_id": "user1",
                "folder_id": "f1",
                "title": "Mine",
                "description": "d",
                "sql_json": {"meta": {"tool": "builder"}},
                "created_at": datetime(2024, 1, 1),
                "updated_at": None,
            }
        ]
    ]
    svc = SavedQueryReadService(workspace_id="ws1", user_id="user1", sql=sql)
    payload = svc.get_query("q2")
    assert payload["accessVia"] == "owner"
    assert payload["canEdit"] is True


def test_get_query_shared_access() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "query_id": "q3",
                "workspace_id": "ws1",
                "scope": "MINE",
                "owner_user_id": "other",
                "folder_id": None,
                "title": "Shared",
                "description": None,
                "sql_json": {"meta": {"tool": "builder"}},
                "created_at": None,
                "updated_at": None,
            }
        ],
        [{"can_edit": 1, "n": 1}],
    ]
    svc = SavedQueryReadService(workspace_id="ws1", user_id="user1", sql=sql)
    payload = svc.get_query("q3")
    assert payload["accessVia"] == "share"
    assert payload["canEdit"] is True


def test_get_query_wrong_workspace() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "query_id": "q4",
                "workspace_id": "ws2",
                "scope": "MINE",
                "owner_user_id": "other",
                "folder_id": None,
                "title": "Wrong",
                "description": None,
                "sql_json": {"meta": {"tool": "builder"}},
                "created_at": None,
                "updated_at": None,
            }
        ]
    ]
    svc = SavedQueryReadService(workspace_id="ws1", user_id="user1", sql=sql)
    with pytest.raises(ForgeError, match="Query not found in this workspace"):
        svc.get_query("q4")


def test_fetch_recent_queries() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": "q1",
                "title": "Recent",
                "updated_at": datetime(2024, 1, 2),
                "created_at": datetime(2024, 1, 1),
                "scope": "MINE",
                "sql_json": {"meta": {"tool": "builder"}},
                "folder_id": None,
            }
        ]
    ]
    svc = SavedQueryReadService(workspace_id="ws1", user_id="user1", sql=sql)
    res = svc.fetch_recent_queries(limit=-1)
    assert res["rows"][0]["queryType"] == "builder"


def test_fetch_recent_queries_uses_default_limit_for_parse_errors() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    svc = SavedQueryReadService(workspace_id="ws1", user_id="user1", sql=sql)

    assert svc.fetch_recent_queries(limit="bad") == {"rows": []}
    assert sql.query_mappings_calls[-1].params["lim"] == 20


def test_fetch_recent_queries_surfaces_unexpected_limit_int_errors() -> None:
    class ExplosiveInt:
        def __int__(self) -> int:
            raise AssertionError("unexpected int conversion failure")

    sql = FakeForgeQueryPort()
    svc = SavedQueryReadService(workspace_id="ws1", user_id="user1", sql=sql)

    with pytest.raises(AssertionError, match="unexpected int conversion failure"):
        svc.fetch_recent_queries(limit=ExplosiveInt())
