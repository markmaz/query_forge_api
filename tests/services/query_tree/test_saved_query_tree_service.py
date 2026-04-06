from __future__ import annotations

from datetime import datetime

import pytest

from app.services.query_tree.saved_query_tree_service import ForgeFolderRow, ForgeQueryRow, SavedQueryTreeService
from tests._support.fakes import FakeForgeQueryPort


def test_get_tree_my(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=sql)
    monkeypatch.setattr(service, "_fetch_folders_my", lambda: [ForgeFolderRow("f1", None, "Folder", 0)])
    monkeypatch.setattr(
        service,
        "_fetch_queries_my",
        lambda: [ForgeQueryRow("q1", "f1", "Query", "u1", "MINE", datetime(2024, 1, 1))],
    )

    tree = service.get_tree(view="my")
    root = tree["rootNodes"][0]
    assert root["isRoot"] is True
    assert root["children"][0]["nodeType"] == "folder"


def test_get_tree_library(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=sql)
    monkeypatch.setattr(service, "_fetch_folders_library", lambda: [])
    monkeypatch.setattr(service, "_fetch_queries_library", lambda: [])
    tree = service.get_tree(view="library")
    assert tree["view"] == "library"


def test_get_tree_shared() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "query_id": "q1",
                "name": "Shared",
                "owner_user_id": "u2",
                "scope": "MINE",
                "updated_at": datetime(2024, 1, 1),
                "sql_json": {"meta": {"tool": "builder"}},
                "can_edit": 1,
            }
        ]
    ]
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=sql)
    tree = service.get_tree(view="shared")
    assert tree["rootNodes"][0]["canEdit"] is True


def test_get_tree_trash(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=sql)
    monkeypatch.setattr(service, "_fetch_folders_trash", lambda: [])
    monkeypatch.setattr(service, "_fetch_queries_trash", lambda: [])
    tree = service.get_tree(view="trash")
    assert tree["rootNodes"][0]["isRoot"] is True


def test_build_trash_tree() -> None:
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=FakeForgeQueryPort())
    folders = [ForgeFolderRow("f1", None, "TrashFolder", 0, deleted_at=datetime(2024, 1, 1))]
    queries = [
        ForgeQueryRow("q1", "f1", "DeletedQuery", "u1", "MINE", datetime(2024, 1, 2), deleted_at=datetime(2024, 1, 3))
    ]
    nodes = service._build_trash_tree(folders, queries)
    assert nodes[0]["nodeType"] == "folder"


def test_tool_from_sql_json_returns_none_for_invalid_json_string() -> None:
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=FakeForgeQueryPort())
    assert service._tool_from_sql_json("{not-json}") is None


def test_tool_from_sql_json_surfaces_unexpected_json_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=FakeForgeQueryPort())

    def _boom(_payload):
        raise AssertionError("unexpected json loader failure")

    monkeypatch.setattr("app.services.query_tree.query_tree_read_model_service.json.loads", _boom)

    with pytest.raises(AssertionError, match="unexpected json loader failure"):
        service._tool_from_sql_json("{\"meta\": {\"tool\": \"builder\"}}")
