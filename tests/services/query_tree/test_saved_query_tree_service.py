from __future__ import annotations

from datetime import datetime

from app.services.query_tree.saved_query_tree_service import FolderRow, QueryRow, SavedQueryTreeService
from tests._support.fakes import FakeSQLExecutor


def test_get_tree_my(monkeypatch) -> None:
    sql = FakeSQLExecutor()
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=sql)
    monkeypatch.setattr(service, "_fetch_folders_my", lambda: [FolderRow("f1", None, "Folder", 0)])
    monkeypatch.setattr(
        service,
        "_fetch_queries_my",
        lambda: [QueryRow("q1", "f1", "Query", "u1", "MINE", datetime(2024, 1, 1))],
    )

    tree = service.get_tree(view="my")
    root = tree["rootNodes"][0]
    assert root["isRoot"] is True
    assert root["children"][0]["nodeType"] == "folder"


def test_get_tree_library(monkeypatch) -> None:
    sql = FakeSQLExecutor()
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=sql)
    monkeypatch.setattr(service, "_fetch_folders_library", lambda: [])
    monkeypatch.setattr(service, "_fetch_queries_library", lambda: [])
    tree = service.get_tree(view="library")
    assert tree["view"] == "library"


def test_get_tree_shared() -> None:
    sql = FakeSQLExecutor()
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
    sql = FakeSQLExecutor()
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=sql)
    monkeypatch.setattr(service, "_fetch_folders_trash", lambda: [])
    monkeypatch.setattr(service, "_fetch_queries_trash", lambda: [])
    tree = service.get_tree(view="trash")
    assert tree["rootNodes"][0]["isRoot"] is True


def test_build_trash_tree() -> None:
    service = SavedQueryTreeService(workspace_id="ws1", user_id="u1", user_display_name="User", sql=FakeSQLExecutor())
    folders = [FolderRow("f1", None, "TrashFolder", 0, deleted_at=datetime(2024, 1, 1))]
    queries = [
        QueryRow("q1", "f1", "DeletedQuery", "u1", "MINE", datetime(2024, 1, 2), deleted_at=datetime(2024, 1, 3))
    ]
    nodes = service._build_trash_tree(folders, queries)
    assert nodes[0]["nodeType"] == "folder"
