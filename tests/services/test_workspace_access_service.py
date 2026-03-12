from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.workspace_access_service import WorkspaceAccessService


class _StubSQL:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0
        self.raise_once = False

    def execute_query(self, _query: str, _params):
        self.calls += 1
        if self.raise_once and self.calls == 1:
            raise RuntimeError("table does not exist")
        return self.rows


def test_assert_workspace_access_allows_when_membership_exists():
    svc = WorkspaceAccessService(sql=_StubSQL(rows=[{"ok": 1}]))
    assert svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1") == "ws-1"


def test_assert_workspace_access_denies_when_membership_missing():
    svc = WorkspaceAccessService(sql=_StubSQL(rows=[]))
    with pytest.raises(ForgeError) as exc:
        svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1")
    assert exc.value.status_code == 403


def test_assert_workspace_access_caches_within_request(app):
    sql = _StubSQL(rows=[{"ok": 1}])
    svc = WorkspaceAccessService(sql=sql)
    with app.test_request_context("/"):
        assert svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1") == "ws-1"
        assert svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1") == "ws-1"
    assert sql.calls == 1


def test_workspace_access_does_not_fallback_to_legacy_query_on_schema_error():
    sql = _StubSQL(rows=[{"ok": 1}])
    sql.raise_once = True
    svc = WorkspaceAccessService(sql=sql)
    with pytest.raises(RuntimeError):
        svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1")
    assert sql.calls == 1
