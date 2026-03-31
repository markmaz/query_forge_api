from app.exceptions.forge_error import ForgeError
from app.services.user.user_workspace_access_service import UserWorkspaceAccessService
from tests._support.fakes import FakeForgeQueryPort


class _StubUserService:
    def __init__(self, workspaces=None, role_names=None):
        self._workspaces = workspaces or []
        self._role_names = role_names or []

    def get_user_workspaces(self, user_id: str, scope_workspace_id=None):
        return list(self._workspaces)

    def get_user_effective_role_names(self, user_id: str):
        return list(self._role_names)


def test_workspace_access_service_rejects_duplicate_mapping() -> None:
    sql = FakeForgeQueryPort()
    service = UserWorkspaceAccessService(sql=sql)
    stub = _StubUserService(workspaces=[{"workspace_id": "ws1"}])

    try:
        service.map_user_workspace(stub, "u1", "ws1", False)
    except ForgeError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("expected duplicate mapping error")


def test_workspace_access_service_includes_all_workspaces_for_super_admin() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[
        {"workspace_id": "ws-a", "is_default": 0},
        {"workspace_id": "ws-b", "is_default": 0},
    ]]
    service = UserWorkspaceAccessService(sql=sql)
    stub = _StubUserService(role_names=["super_admin"])

    rows = service.get_user_workspaces(stub, "u1")

    assert [row["workspace_id"] for row in rows] == ["ws-a", "ws-b"]
    assert rows[0]["is_default"] is True
