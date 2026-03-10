from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.exceptions.forge_error import ForgeError
from app.services.query_tree.saved_query_folder_write_service import (
    SavedQueryFolderWriteService,
    _bind_in,
    _qf_in_params,
    _req,
)
from tests._support.fakes import FakeForgeQueryPort


def test_create_folder_validations() -> None:
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        service.create_folder(name="")


def test_create_folder_success(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_normalize_parent_id", lambda *_args, **_kwargs: None)

    res = service.create_folder(name="My Folder")
    assert res["name"] == "My Folder"
    assert sql.write_calls


def test_rename_move_delete_folder(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses = [1, 1, 1]
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_assert_folder_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_is_descendant", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(service, "_count_child_folders", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(service, "_count_child_queries", lambda *_args, **_kwargs: 0)

    assert service.rename_folder(folder_id="f1", name="Renamed")["name"] == "Renamed"
    assert service.move_folder(folder_id="f1", qf_new_parent_folder_id=None)["folderId"] == "f1"
    assert service.delete_folder(folder_id="f1")["deleted"] is True


def test_rename_folder_duplicate(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.write_exceptions = [IntegrityError("dup", None, None)]
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_assert_folder_exists", lambda *_args, **_kwargs: None)
    with pytest.raises(ForgeError):
        service.rename_folder(folder_id="f1", name="Dup")


def test_move_folder_invalid_descendant(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_assert_folder_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_is_descendant", lambda *_args, **_kwargs: True)
    with pytest.raises(ForgeError):
        service.move_folder(folder_id="f1", qf_new_parent_folder_id="f2")


def test_delete_folder_not_empty(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_assert_folder_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_count_child_folders", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(service, "_count_child_queries", lambda *_args, **_kwargs: 0)
    with pytest.raises(ForgeError):
        service.delete_folder(folder_id="f1")


def test_trash_folder(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_assert_folder_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_collect_subtree", lambda *_args, **_kwargs: (["f1", "f2"], ["q1"]))

    res = service.trash_folder(folder_id="f1")
    assert res["deleted"] is True
    assert sql.write_calls


def test_restore_folder(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_assert_folder_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_collect_ancestor_chain", lambda *_args, **_kwargs: ["root"])
    monkeypatch.setattr(service, "_collect_subtree", lambda *_args, **_kwargs: (["f1"], ["q1"]))
    res = service.restore_folder(folder_id="f1")
    assert res["restored"] is True
    assert sql.write_calls


def test_purge_folder(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    monkeypatch.setattr(service, "_assert_folder_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_collect_subtree", lambda *_args, **_kwargs: (["f1", "f2"], ["q1"]))
    monkeypatch.setattr(service, "_depths_for_ids", lambda *_args, **_kwargs: {"f1": 1, "f2": 2})
    res = service.purge_folder(folder_id="f1")
    assert res["purged"] is True
    assert sql.write_calls


def test_internal_helpers() -> None:
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=FakeForgeQueryPort())
    assert service._normalize_parent_id("user:user1") is None


def test_assert_folder_exists_missing() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    with pytest.raises(ForgeError):
        service._assert_folder_exists("f1")


def test_count_children_helpers() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"n": 2}], [{"n": 3}]]
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    assert service._count_child_folders(folder_id="f1") == 2
    assert service._count_child_queries(folder_id="f1") == 3


def test_is_descendant_true() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"parent_id": "a"}]]
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    assert service._is_descendant(descendant_id="c", ancestor_id="a") is True


def test_is_descendant_missing() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    assert service._is_descendant(descendant_id="c", ancestor_id="a") is False


def test_collect_subtree_and_queries() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": "root", "parent_id": None, "is_deleted": 0}, {"id": "child", "parent_id": "root", "is_deleted": 0}],
        [{"id": "q1"}],
    ]
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    folders, queries = service._collect_subtree(folder_id="root", qf_include_deleted=False)
    assert set(folders) == {"root", "child"}
    assert queries == ["q1"]


def test_collect_ancestor_chain_and_depths() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": "root", "parent_id": None}, {"id": "child", "parent_id": "root"}],
        [{"id": "root", "parent_id": None}, {"id": "child", "parent_id": "root"}],
    ]
    service = SavedQueryFolderWriteService(workspace_id="ws1", user_id="user1", sql=sql)
    chain = service._collect_ancestor_chain(folder_id="child")
    assert chain == ["root", "child"]
    depths = service._depths_for_ids(["root", "child"])
    assert depths["child"] > depths["root"]


def test_helper_funcs() -> None:
    assert _req("x", "field") == "x"
    assert _qf_in_params("p", 3) == ":p0,:p1,:p2"
    assert _qf_in_params("p", 0) == "NULL"
    assert _bind_in("p", ["a", "b"]) == {"p0": "a", "p1": "b"}
