from app.services.user.user_profile_read_service import UserProfileReadService
from tests._support.fakes import FakeForgeQueryPort


def test_profile_read_service_maps_user_row() -> None:
    user = UserProfileReadService.map_user_row(
        {
            "user_id": "u1",
            "username": "alice",
            "email": "alice@example.com",
            "user_status": "Active",
        }
    )

    assert user.user_id == "u1"
    assert user.user_name == "alice"
    assert user.email == "alice@example.com"
    assert user.workspaces == []


def test_profile_read_service_checks_existing_user() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"user_id": "u1"}]]

    service = UserProfileReadService(sql=sql)

    assert service.check_for_existing_user("alice") is True
