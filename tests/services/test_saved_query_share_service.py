from __future__ import annotations

import datetime
import uuid

import pytest

from app.exceptions.service_error import ServiceError
from app.services.query_tree.saved_query_share_service import SavedQueryShareService, _req


class FakeSQL:
    def __init__(self, mappings_queue=None, write_returns=None):
        self._mappings_queue = list(mappings_queue or [])
        self._write_returns = list(write_returns or [])
        self.writes = []

    def execute_query_mappings(self, query: str, params):
        if self._mappings_queue:
            return self._mappings_queue.pop(0)
        return []

    def execute_write(self, query: str, params=None):
        self.writes.append((query, params))
        if self._write_returns:
            return self._write_returns.pop(0)
        return 0

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_init_requires_workspace_and_user():
    with pytest.raises(ServiceError):
        SavedQueryShareService(workspace_id="", user_id="user")
    with pytest.raises(ServiceError):
        SavedQueryShareService(workspace_id="ws", user_id="")


def test_share_to_workspace_inserts_acl(monkeypatch):
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(uuid, "uuid4", lambda: fixed_uuid)

    sql = FakeSQL(mappings_queue=[[{"id": "q1"}], []])
    svc = SavedQueryShareService(workspace_id="ws", user_id="user", sql=sql)

    out = svc.share_to_workspace(query_id="q1", can_edit=True)

    assert out["aclId"] == str(fixed_uuid)
    assert out["principalType"] == "WORKSPACE"
    assert out["permission"] == "WRITE"
    assert sql.writes


def test_share_to_user_updates_acl():
    sql = FakeSQL(mappings_queue=[[{"id": "q1"}], [{"id": "acl1", "permission": "READ"}]])
    svc = SavedQueryShareService(workspace_id="ws", user_id="user", sql=sql)

    out = svc.share_to_user(query_id="q1", shared_with_user_id="user-2", can_edit=True)

    assert out["aclId"] == "acl1"
    assert out["permission"] == "WRITE"
    assert "UPDATE saved_query_acl" in sql.writes[0][0]


def test_unshare_invalid_kind_raises():
    sql = FakeSQL(mappings_queue=[[{"id": "q1"}]])
    svc = SavedQueryShareService(workspace_id="ws", user_id="user", sql=sql)

    with pytest.raises(ServiceError):
        svc.unshare(query_id="q1", share_kind="bad")


def test_unshare_user_requires_shared_with_user_id():
    sql = FakeSQL(mappings_queue=[[{"id": "q1"}]])
    svc = SavedQueryShareService(workspace_id="ws", user_id="user", sql=sql)

    with pytest.raises(ServiceError):
        svc.unshare(query_id="q1", share_kind="USER", shared_with_user_id=None)


def test_unshare_workspace_success():
    sql = FakeSQL(mappings_queue=[[{"id": "q1"}]], write_returns=[1])
    svc = SavedQueryShareService(workspace_id="ws", user_id="user", sql=sql)

    out = svc.unshare(query_id="q1", share_kind="WORKSPACE")

    assert out["removed"] is True
    assert out["shareKind"] == "WORKSPACE"


def test_list_shares_formats_created_at():
    created = datetime.datetime(2024, 1, 2, 3, 4, 5)
    sql = FakeSQL(
        mappings_queue=[
            [{"id": "q1"}],
            [
                {
                    "id": "a1",
                    "principal_type": "WORKSPACE",
                    "principal_id": "ws",
                    "permission": "READ",
                    "created_at": created,
                },
                {
                    "id": "a2",
                    "principal_type": "USER",
                    "principal_id": "user-2",
                    "permission": "WRITE",
                    "created_at": None,
                },
            ],
        ]
    )
    svc = SavedQueryShareService(workspace_id="ws", user_id="user", sql=sql)

    out = svc.list_shares(query_id="q1")

    assert out["shares"][0]["createdAt"] == created.isoformat()
    assert out["shares"][1]["createdAt"] is None


def test_assert_query_owner_not_found():
    sql = FakeSQL(mappings_queue=[[]])
    svc = SavedQueryShareService(workspace_id="ws", user_id="user", sql=sql)

    with pytest.raises(ServiceError):
        svc.list_shares(query_id="q1")


def test_find_acl_returns_none():
    sql = FakeSQL(mappings_queue=[[]])
    svc = SavedQueryShareService(workspace_id="ws", user_id="user", sql=sql)

    assert svc._find_acl(saved_query_id="q1", principal_type="USER", principal_id="user-2") is None


def test_req_validates_values():
    with pytest.raises(ServiceError):
        _req("", "field")
    assert _req(" value ", "field") == "value"
