from app.services.user.user_admin_service import UserAdminService
from tests._support.fakes import FakeForgeQueryPort


class _StubUserService:
    def __init__(self):
        self.checked = []

    def check_for_existing_user(self, username: str):
        self.checked.append(username)
        return False


def test_user_admin_service_create_user_uses_validator_and_returns_payload() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses = [1]
    admin = UserAdminService(sql=sql)
    stub = _StubUserService()
    seen = []

    out = admin.create_user(
        stub,
        "alice",
        "StrongPassword123!",
        "alice@example.com",
        "Alice",
        "Jones",
        password_validator=lambda password: seen.append(password),
    )

    assert out["username"] == "alice"
    assert seen == ["StrongPassword123!"]
    assert stub.checked == ["alice"]


def test_user_admin_service_delete_user_returns_success() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses = [1, 1, 1, 1, 1]
    admin = UserAdminService(sql=sql)

    out = admin.delete_user("u1")

    assert out["message"] == "User deleted successfully"
