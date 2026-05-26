from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.exceptions.forge_error import ForgeError
from app.models.tenancy.user import User
from app.models.tenancy.user_workspace import UserWorkspace
from app.services.auth.token_lifecycle_service import TokenLifecycleService
from app.services import auth_service
from app.services.auth_service import AuthService


def test_authenticate_success(monkeypatch) -> None:
    class DummyUserService:
        def find_user_by_username(self, _username: str) -> User:
            return User(
                user_id="u1",
                user_name="u1",
                password="hashed",
                status="active",
                email="a@b.com",
                workspaces=[UserWorkspace(workspace_id="ws-1", is_default=True)],
            )

        def update_last_login(self, _user_id: str) -> None:
            return None

    monkeypatch.setattr(auth_service, "UserService", DummyUserService)
    monkeypatch.setattr(auth_service, "check_password_hash", lambda *_args, **_kwargs: True)

    svc = AuthService()
    res = svc.authenticate("u1", "pw")
    assert res["user_id"] == "u1"
    assert res["workspace_id"] == "ws-1"
    assert res["workspaceId"] == "ws-1"


def test_authenticate_inactive_user(monkeypatch) -> None:
    class DummyUserService:
        def find_user_by_username(self, _username: str) -> User:
            return User(user_id="u1", user_name="u1", password="hashed", status="deactivated")

    monkeypatch.setattr(auth_service, "UserService", DummyUserService)
    monkeypatch.setattr(auth_service, "check_password_hash", lambda *_args, **_kwargs: True)

    svc = AuthService()
    with pytest.raises(ForgeError, match="Invalid credentials") as exc:
        svc.authenticate("u1", "pw")
    assert exc.value.status_code == 401


def test_authenticate_invalid_password(monkeypatch) -> None:
    class DummyUserService:
        def find_user_by_username(self, _username: str) -> User:
            return User(user_id="u1", user_name="u1", password="hashed", status="active")

    monkeypatch.setattr(auth_service, "UserService", DummyUserService)
    monkeypatch.setattr(auth_service, "check_password_hash", lambda *_args, **_kwargs: False)

    svc = AuthService()
    with pytest.raises(ForgeError, match="Invalid credentials") as exc:
        svc.authenticate("u1", "pw")
    assert exc.value.status_code == 401


def test_authenticate_missing_user(monkeypatch) -> None:
    class DummyUserService:
        def find_user_by_username(self, _username: str):
            return None

    monkeypatch.setattr(auth_service, "UserService", DummyUserService)
    monkeypatch.setattr(auth_service, "check_password_hash", lambda *_args, **_kwargs: False)

    svc = AuthService()
    with pytest.raises(ForgeError, match="Invalid credentials") as exc:
        svc.authenticate("missing", "pw")
    assert exc.value.status_code == 401


def test_non_interactive_authentication_success(monkeypatch) -> None:
    class DummyUserService:
        def find_user_by_username(self, _username: str) -> User:
            return User(user_id="u1", user_name="u1", password="hashed", status="active")

        def update_last_login(self, _user_id: str) -> None:
            return None

    monkeypatch.setattr(auth_service, "UserService", DummyUserService)
    monkeypatch.setattr(auth_service, "check_password_hash", lambda *_args, **_kwargs: True)

    svc = AuthService()
    user = svc.non_interactive_authentication("u1", "pw")
    assert user.user_id == "u1"


def test_non_interactive_authentication_operational_error(monkeypatch) -> None:
    class DummyUserService:
        def find_user_by_username(self, _username: str) -> User:
            raise OperationalError("select 1", {}, Exception("boom"))

    monkeypatch.setattr(auth_service, "UserService", DummyUserService)

    svc = AuthService()
    with pytest.raises(ForgeError, match="Connection failure"):
        svc.non_interactive_authentication("u1", "pw")


def test_generate_and_verify_token() -> None:
    svc = AuthService()
    token = svc.generate_token(User(user_id="u1", user_name="u1"))
    payload = svc.verify_token(token)
    assert payload["sub"] == "u1"

    assert svc.verify_token("bad.token") is None


def test_issue_tokens_includes_roles_claims(monkeypatch) -> None:
    class FakeCache:
        def setex(self, *_args, **_kwargs):
            return True

    class DummyUserService:
        def get_user_effective_role_names(self, _user_id: str):
            return ["Admin", "Viewer"]

    monkeypatch.setattr(auth_service, "UserService", DummyUserService)
    monkeypatch.setattr(auth_service, "cache", FakeCache())

    svc = AuthService()
    tokens = svc.issue_tokens(User(user_id="u1", user_name="user1"))
    payload = svc.decode_and_verify(tokens["access_token"], expected_typ="access")
    assert payload["roles"] == ["Admin", "Viewer"]
    assert payload["is_admin"] is True
    assert payload["username"] == "user1"


def test_decode_and_verify_allows_resource_bound_tokens_for_mcp_audience_check() -> None:
    service = TokenLifecycleService(
        secret="test-secret-value-that-is-long-enough",
        algorithm="HS256",
        access_ttl_seconds=900,
        refresh_ttl_seconds=3600,
        leeway_seconds=30,
        verify_iat=False,
        refresh_prefix="qf:refresh:",
        cache=None,
        access_claims_provider=lambda _user_id, _username=None: {},
    )
    token = service._encode(
        {
            "sub": "user-1",
            "typ": "mcp_access",
            "aud": "https://mcp.query-forge.com",
        }
    )

    payload = service.decode_and_verify(token, expected_typ="mcp_access")

    assert payload["aud"] == "https://mcp.query-forge.com"


def test_send_reset_request_and_reset_password(monkeypatch) -> None:
    class FakePipeline:
        def __init__(self, data):
            self._data = data
            self._key = None

        def hgetall(self, key):
            self._key = key
            return self

        def delete(self, _key):
            return self

        def execute(self):
            return self._data.get(self._key, {}), None

    class FakeCache:
        def __init__(self):
            self.data = {}

        def hset(self, key, mapping):
            self.data[key] = mapping

        def expire(self, _key, _ttl):
            return True

        def exists(self, key):
            return int(key in self.data)

        def pipeline(self):
            return FakePipeline(self.data)

    class DummyUserService:
        def find_user_by_username(self, _email: str) -> User:
            return User(user_id="u1", email="u1@example.com")

        def update_user(self, _user_id: str, _user: User):
            return {"ok": True}

    class DummyTask:
        def delay(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(auth_service, "cache", FakeCache())
    monkeypatch.setattr(auth_service, "UserService", DummyUserService)
    monkeypatch.setattr(auth_service, "generate", lambda _uid: "tok")
    monkeypatch.setattr("app.tasks.email_tasks.send_password_reset", DummyTask())

    svc = AuthService()
    assert svc.send_reset_request("u1@example.com") == ("", 204)

    key = auth_service.cache_key("tok")
    auth_service.cache.data[key] = {
        "user_id": "u1",
        "purpose": "password_reset",
    }

    assert svc.validate_token("tok") == 1
    assert svc.reset_password("pw", auth_service.hash_token("tok")) == ("", 204)


def test_reset_password_invalid_token(monkeypatch) -> None:
    class FakePipeline:
        def hgetall(self, _key):
            return self

        def delete(self, _key):
            return self

        def execute(self):
            return {"purpose": "wrong"}, None

    class FakeCache:
        def pipeline(self):
            return FakePipeline()

    monkeypatch.setattr(auth_service, "cache", FakeCache())

    svc = AuthService()
    assert svc.reset_password("pw", "hashed") == ("", 400)


def test_send_reset_request_unknown_email_is_still_success(monkeypatch) -> None:
    class FakeCache:
        def hset(self, *_args, **_kwargs):
            raise AssertionError("hset should not be called for unknown email")

        def expire(self, *_args, **_kwargs):
            raise AssertionError("expire should not be called for unknown email")

    class DummyUserService:
        def find_user_by_username(self, _email: str):
            return None

    monkeypatch.setattr(auth_service, "cache", FakeCache())
    monkeypatch.setattr(auth_service, "UserService", DummyUserService)

    svc = AuthService()
    assert svc.send_reset_request("unknown@example.com") == ("", 204)


def test_reset_password_enforces_password_policy(monkeypatch) -> None:
    class FakePipeline:
        def hgetall(self, _key):
            return self

        def delete(self, _key):
            return self

        def execute(self):
            return {"purpose": "password_reset", "user_id": "u1"}, None

    class FakeCache:
        def pipeline(self):
            return FakePipeline()

    class DummyUserService:
        def update_user(self, _user_id: str, _user: User):
            raise ForgeError("Password violates policy rules.", 422)

    monkeypatch.setattr(auth_service, "cache", FakeCache())
    monkeypatch.setattr(auth_service, "UserService", DummyUserService)

    svc = AuthService()
    with pytest.raises(ForgeError) as exc:
        svc.reset_password("weak", "hashed")
    assert exc.value.status_code == 422
