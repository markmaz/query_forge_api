from app.exceptions.forge_error import ForgeError
from app.services.user.user_role_resolution_service import UserRoleResolutionService
from tests._support.fakes import FakeForgeQueryPort


class _StubUserService:
    def get_user_effective_roles(self, user_id: str, workspace_id=None):
        return [
            {"role_id": "1", "role_name": "Admin"},
            {"role_id": "2", "role_name": "Editor"},
            {"role_id": "1", "role_name": "Admin"},
        ]


def test_role_resolution_service_dedupes_effective_role_names() -> None:
    service = UserRoleResolutionService(sql=FakeForgeQueryPort())

    names = service.get_user_effective_role_names(_StubUserService(), "u1")

    assert names == ["Admin", "Editor"]


def test_role_resolution_service_requires_workspace_for_non_global_roles() -> None:
    try:
        UserRoleResolutionService.normalize_role_workspace("admin", None)
    except ForgeError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected workspace validation error")
