from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.workspace_access_service import WorkspaceAccessService


class _StubSQL:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute_query(self, _query: str, _params):
        self.calls += 1
        return self.rows


def test_assert_workspace_access_allows_when_membership_exists():
    svc = WorkspaceAccessService(sql=_StubSQL(rows=[{"ok": 1}]))
    assert svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1") == "ws-1"


def test_assert_workspace_access_denies_when_membership_missing():
    svc = WorkspaceAccessService(sql=_StubSQL(rows=[]))
    with pytest.raises(ServiceError) as exc:
        svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1")
    assert exc.value.status_code == 403


def test_assert_workspace_access_caches_within_request(app):
    sql = _StubSQL(rows=[{"ok": 1}])
    svc = WorkspaceAccessService(sql=sql)
    with app.test_request_context("/"):
        assert svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1") == "ws-1"
        assert svc.assert_workspace_access(user_id="user-1", workspace_id="ws-1") == "ws-1"
    assert sql.calls == 1
