from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.exceptions.service_error import ServiceError
from app.models.product import Product
from app.models.product_role import ProductRole
from app.models.role import Role
from app.models.user import User
from app.models.user_invitation import UserInvitation
from app.models.user_workspace import Workspace
from app.services import user_service as user_service_mod
from app.services.user_service import UserService
from tests._support.fakes import FakeSQLExecutor


class _EmailTask:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_update_status_updates_login(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    fake.write_responses = [1, 1]
    svc = UserService(sql=fake)

    svc.update_status("u1", "Active")
    assert len(fake.write_calls) == 2


def test_update_status_db_error() -> None:
    fake = FakeSQLExecutor()
    fake.write_exceptions = [user_service_mod.exc.SQLAlchemyError("err")]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.update_status("u1", "Active")


def test_get_counts_includes_all() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"status": "Active", "count": 2}]]
    svc = UserService(sql=fake)
    counts = svc.get_counts()
    assert counts["Active"] == 2
    assert counts["All"] == 2
    assert "Invited" in counts


def test_get_counts_db_error() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_exceptions = [user_service_mod.exc.SQLAlchemyError("err")]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.get_counts()


def test_resend_invite_sends_email(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _EmailTask()
    import app.tasks.email_tasks as email_tasks
    monkeypatch.setattr(email_tasks, "send_invite_email_task", task)
    fake = FakeSQLExecutor()
    fake.write_responses = [1]
    svc = UserService(sql=fake)

    resp = svc.resend_invite("u1", "a@example.com")
    assert resp["user_id"] == "u1"
    assert task.calls


def test_create_user_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    fake.write_responses = [1]
    svc = UserService(sql=fake)
    monkeypatch.setattr(svc, "check_for_existing_user", lambda username: False)
    monkeypatch.setattr(user_service_mod, "validate_password_policy", lambda password: 200)

    resp = svc.create_user("alice", "Password1!", "a@example.com", "A", "B")
    assert resp["username"] == "alice"
    assert fake.write_calls


def test_create_user_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = UserService(sql=FakeSQLExecutor())
    monkeypatch.setattr(svc, "check_for_existing_user", lambda username: True)
    with pytest.raises(ServiceError):
        svc.create_user("alice", "Password1!", "a@example.com", "A", "B")


def test_create_user_bad_password(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = UserService(sql=FakeSQLExecutor())
    monkeypatch.setattr(svc, "check_for_existing_user", lambda username: False)
    monkeypatch.setattr(
        user_service_mod,
        "validate_password_policy",
        lambda password: (_ for _ in ()).throw(ServiceError("Password violates policy rules.", 422)),
    )
    with pytest.raises(ServiceError):
        svc.create_user("alice", "bad", "a@example.com", "A", "B")


def test_create_user_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    fake.write_exceptions = [user_service_mod.exc.SQLAlchemyError("err")]
    svc = UserService(sql=fake)
    monkeypatch.setattr(svc, "check_for_existing_user", lambda username: False)
    monkeypatch.setattr(user_service_mod, "validate_password_policy", lambda password: 200)
    with pytest.raises(ServiceError):
        svc.create_user("alice", "Password1!", "a@example.com", "A", "B")


def test_create_invite_bulk_skips_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    fake.write_responses = [1, 0]
    svc = UserService(sql=fake)
    task = _EmailTask()
    import app.tasks.email_tasks as email_tasks
    monkeypatch.setattr(email_tasks, "send_invite_email_task", task)
    monkeypatch.setattr(svc, "map_user_workspace", lambda *a, **k: None)
    monkeypatch.setattr(svc, "map_user_product", lambda *a, **k: None)
    monkeypatch.setattr(svc, "map_user_product_role", lambda *a, **k: None)

    resp = svc.create_invite_bulk(
        emails=["a@example.com", "b@example.com"],
        products=[{"product_id": "p1", "product_role_id": "r1"}],
        workspaces=[{"workspace_id": "ws1", "is_default": True}],
    )
    assert resp["invites_sent"] == 1
    assert resp["users_skipped"] == 1
    assert len(task.calls) == 1


def test_create_invite_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = UserService(sql=FakeSQLExecutor())
    monkeypatch.setattr(svc, "check_for_existing_user", lambda email: True)
    invite = UserInvitation(email="a@example.com", products=[], workspaces=[])
    with pytest.raises(ServiceError):
        svc.create_invite(invite)


def test_create_invite_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    fake.write_responses = [1]
    svc = UserService(sql=fake)
    task = _EmailTask()
    import app.tasks.email_tasks as email_tasks
    monkeypatch.setattr(email_tasks, "send_invite_email_task", task)
    monkeypatch.setattr(svc, "check_for_existing_user", lambda email: False)
    monkeypatch.setattr(svc, "map_user_workspace", lambda *a, **k: None)
    monkeypatch.setattr(svc, "map_user_product", lambda *a, **k: None)
    monkeypatch.setattr(svc, "map_user_product_role", lambda *a, **k: None)

    invite = UserInvitation(
        email="a@example.com",
        products=[Product(product_id="p1", roles=[ProductRole(product_role_id="r1", role=Role(role_id="r1", role_name="R"))])],
        workspaces=[Workspace(workspace_id="ws1", is_default=True)],
    )
    resp = svc.create_invite(invite)
    assert resp["email"] == "a@example.com"
    assert task.calls


def test_create_invite_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    fake.write_exceptions = [user_service_mod.exc.SQLAlchemyError("err")]
    svc = UserService(sql=fake)
    task = _EmailTask()
    import app.tasks.email_tasks as email_tasks
    monkeypatch.setattr(email_tasks, "send_invite_email_task", task)
    monkeypatch.setattr(svc, "check_for_existing_user", lambda email: False)
    invite = UserInvitation(email="a@example.com", products=[], workspaces=[])
    with pytest.raises(ServiceError):
        svc.create_invite(invite)


def test_update_user_updates_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    fake.write_responses = [1]
    svc = UserService(sql=fake)
    existing = User(user_id="u1", first_name="Old", last_name="Name")
    monkeypatch.setattr(svc, "get_user", lambda user_id: existing)
    monkeypatch.setattr(svc, "_sync_user_workspaces", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_sync_user_product_roles", lambda *a, **k: None)

    updated = User(first_name="New", last_name="Name")
    resp = svc.update_user("u1", updated)
    assert resp.user_id == "u1"
    assert fake.write_calls


def test_update_user_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = UserService(sql=FakeSQLExecutor())
    monkeypatch.setattr(svc, "get_user", lambda user_id: None)
    with pytest.raises(ServiceError):
        svc.update_user("u1", User(first_name="New"))


def test_update_user_password_enforces_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    svc = UserService(sql=fake)
    existing = User(user_id="u1", first_name="Old", last_name="Name")
    monkeypatch.setattr(svc, "get_user", lambda user_id: existing)
    monkeypatch.setattr(
        user_service_mod,
        "validate_password_policy",
        lambda _password: (_ for _ in ()).throw(ServiceError("Password violates policy rules.", 422)),
    )

    with pytest.raises(ServiceError) as exc:
        svc.update_user("u1", User(password="weak"))
    assert exc.value.status_code == 422
    assert not fake.write_calls


def test_update_user_password_hashes_after_policy_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    fake.write_responses = [1]
    svc = UserService(sql=fake)
    existing = User(user_id="u1", first_name="Old", last_name="Name")
    monkeypatch.setattr(svc, "get_user", lambda user_id: existing)
    monkeypatch.setattr(user_service_mod, "validate_password_policy", lambda _password: 200)

    svc.update_user("u1", User(password="StrongPass1!"))

    assert fake.write_calls
    call = fake.write_calls[0]
    assert "password = :password" in call.query
    assert call.params["password"] != "StrongPass1!"


def test_sync_user_workspaces_inserts_and_updates() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"workspace_id": "ws1", "is_default": 0}]]
    svc = UserService(sql=fake)
    with fake.transaction() as tx:
        svc._sync_user_workspaces(
            tx,
            "u1",
            [{"workspace_id": "ws1", "is_default": True}, {"workspace_id": "ws2", "is_default": False}],
        )
    assert fake.write_calls


def test_sync_user_product_roles_inserts() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"product_role_id": "r1"}]]
    svc = UserService(sql=fake)
    with fake.transaction() as tx:
        svc._sync_user_product_roles(
            tx,
            "u1",
            [{"product_id": "p1", "roles": [{"product_role_id": "r2"}]}],
        )
    assert fake.write_calls


def test_delete_user_not_found() -> None:
    fake = FakeSQLExecutor()
    fake.write_responses = [1, 0]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.delete_user("u1")


def test_get_user_by_username() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"user_id": "u1", "username": "alice"}]]
    svc = UserService(sql=fake)
    row = svc.get_user_by_username("alice")
    assert row.user_id == "u1"


def test_get_user_missing() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[]]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.get_user("u1")


def test_get_users_empty() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[]]
    svc = UserService(sql=fake)
    users, next_cursor, prev_cursor, total = svc.get_users()
    assert users == []
    assert next_cursor is None
    assert prev_cursor is None
    assert total == 0


def test_get_users_with_products_and_workspaces() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [
        [
            {
                "user_id": "u1",
                "username": "alice",
                "password": "pw",
                "first_name": "A",
                "last_name": "B",
                "email": "a@example.com",
                "status": "Active",
                "tos_accepted": 1,
                "eula_accepted": 0,
                "otp_secret": None,
                "two_factor_preference": "Email",
                "last_log_in": None,
            }
        ],
        [
            {
                "user_id": "u1",
                "workspace_id": "ws1",
                "is_default": 1,
                "product_id": "p1",
                "product_name": "Prod",
                "status": "Active",
                "last_update": None,
                "product_role_id": "pr1",
                "role_id": "r1",
                "role_name": "Role",
            }
        ],
        [],
        [{"count": 1}],
    ]
    svc = UserService(sql=fake)
    users, next_cursor, prev_cursor, total = svc.get_users()
    base_query = fake.query_mappings_calls[0].query
    assert "password" not in base_query.lower()
    assert "otp_secret" not in base_query.lower()
    assert users[0].user_id == "u1"
    assert users[0].workspaces[0].workspace_id == "ws1"
    assert users[0].products[0].product_id == "p1"
    assert total == 1
    assert next_cursor is None
    assert prev_cursor is None


def test_get_users_prev_cursor() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [
        [
            {
                "user_id": "u2",
                "username": "alice",
                "password": "pw",
                "first_name": "A",
                "last_name": "B",
                "email": "a@example.com",
                "status": "Active",
                "tos_accepted": 1,
                "eula_accepted": 0,
                "otp_secret": None,
                "two_factor_preference": "Email",
                "last_log_in": None,
            }
        ],
        [],
        [],
        [{"user_id": "u1"}],
        [{"count": 2}],
    ]
    svc = UserService(sql=fake)
    users, next_cursor, prev_cursor, total = svc.get_users(cursor="u1", direction="forward")
    base_query = fake.query_mappings_calls[0].query
    assert "password" not in base_query.lower()
    assert "otp_secret" not in base_query.lower()
    assert users[0].user_id == "u2"
    assert prev_cursor == "u1"
    assert total == 2


def test_map_user_workspace_first_default() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[]]
    svc = UserService(sql=fake)
    resp = svc.map_user_workspace("u1", "ws1", False)
    assert resp["mapping"]["is_default"] is True


def test_get_user_workspaces_and_delete() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"workspace_id": "ws1", "is_default": 1}]]
    fake.write_responses = [1]
    svc = UserService(sql=fake)
    rows = svc.get_user_workspaces("u1")
    assert rows[0]["workspace_id"] == "ws1"
    resp = svc.delete_user_workspace("u1", "ws1")
    assert resp["message"] == "Mapping deleted successfully"


def test_map_user_workspace_duplicate() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"workspace_id": "ws1"}]]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.map_user_workspace("u1", "ws1", False)


def test_map_user_product_role_maps() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[]]
    fake.write_responses = [1]
    svc = UserService(sql=fake)
    resp = svc.map_user_product_role("u1", "r1")
    assert resp["mapping"]["product_role_id"] == "r1"


def test_map_user_product_role_existing_returns_none() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"product_role_id": "r1"}]]
    svc = UserService(sql=fake)
    assert svc.map_user_product_role("u1", "r1") is None


def test_map_user_product_maps() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[]]
    fake.write_responses = [1]
    svc = UserService(sql=fake)
    resp = svc.map_user_product("u1", "p1")
    assert resp["mapping"]["product_id"] == "p1"


def test_map_user_product_existing_returns_none() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"product_id": "p1"}]]
    svc = UserService(sql=fake)
    assert svc.map_user_product("u1", "p1") is None


def test_get_user_products() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"product_id": "p1"}]]
    svc = UserService(sql=fake)
    rows = svc.get_user_products("u1")
    assert rows[0]["product_id"] == "p1"


def test_set_workspace_default_success() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"workspace_id": "ws1", "is_default": 0}]]
    fake.write_responses = [1, 1]
    svc = UserService(sql=fake)
    resp = svc.set_workspace_default("u1", "ws1", True)
    assert resp["mapping"]["is_default"] is True


def test_set_workspace_default_missing_mapping() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[]]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.set_workspace_default("u1", "ws1", True)


def test_set_workspace_default_cannot_unset_only_default() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"workspace_id": "ws1", "is_default": 1}]]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.set_workspace_default("u1", "ws1", False)


def test_check_for_existing_user_true() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [[{"user_id": "u1"}]]
    svc = UserService(sql=fake)
    assert svc.check_for_existing_user("alice") is True


def test_get_user_product_roles_error() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_exceptions = [user_service_mod.exc.SQLAlchemyError("err")]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.get_user_product_roles("u1")


def test_delete_user_workspace_error() -> None:
    fake = FakeSQLExecutor()
    fake.write_exceptions = [user_service_mod.exc.SQLAlchemyError("err")]
    svc = UserService(sql=fake)
    with pytest.raises(ServiceError):
        svc.delete_user_workspace("u1", "ws1")


def test_map_user_with_products_builds_user() -> None:
    svc = UserService(sql=FakeSQLExecutor())
    rows = [
        {
            "user_id": "u1",
            "username": "alice",
            "email": "a@example.com",
            "product_id": "p1",
            "product_name": "Prod",
            "product_role_id": "pr1",
            "role_id": "r1",
            "role_name": "Role",
            "workspace_id": "ws1",
            "is_default": True,
        }
    ]
    user = svc.map_user_with_products(rows)
    assert user.user_id == "u1"
    assert user.workspaces[0].workspace_id == "ws1"


def test_map_user_with_products_empty() -> None:
    svc = UserService(sql=FakeSQLExecutor())
    with pytest.raises(ValueError):
        svc.map_user_with_products([])


def test_update_last_login() -> None:
    fake = FakeSQLExecutor()
    fake.write_responses = [1]
    svc = UserService(sql=fake)
    svc.update_last_login("u1")
    assert isinstance(fake.write_calls[0].params["now"], datetime)
    assert fake.write_calls[0].params["now"].tzinfo == timezone.utc
