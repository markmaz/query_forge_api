from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.models.tenancy.user import User
from app.services.user_service import UserService
from tests._support.fakes import FakeForgeQueryPort


def test_get_user_effective_role_names_dedupes_direct_roles() -> None:
    svc = UserService(sql=FakeForgeQueryPort())
    svc.get_user_effective_roles = lambda user_id, workspace_id=None: [  # type: ignore[assignment]
        {"role_id": "1", "role_name": "Admin"},
        {"role_id": "2", "role_name": "Editor"},
        {"role_id": "1", "role_name": "Admin"},
    ]
    names = svc.get_user_effective_role_names("u1")
    assert names == ["Admin", "Editor"]


def test_sync_user_direct_roles_insert_and_delete() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {"id": 1, "role_name": "viewer"},
            {"id": 2, "role_name": "editor"},
        ],
    ]

    svc = UserService(sql=sql)
    removed: list[tuple[str, str | None]] = []
    added: list[tuple[str, str | None]] = []
    svc.remove_user_direct_role = lambda user_id, role_name, workspace_id=None, tx=None: removed.append((role_name, workspace_id)) or {"deleted": True}  # type: ignore[assignment]
    svc.add_user_direct_role = lambda user_id, role_name, workspace_id=None, tx=None: added.append((role_name, workspace_id)) or {"created": True}  # type: ignore[assignment]

    with sql.transaction() as tx:
        svc._sync_user_direct_roles(tx, "u1", ["viewer", "admin"], workspace_id="ws-1")

    assert removed == [("editor", "ws-1")]
    assert added == [("admin", "ws-1")]


def test_add_user_direct_role_success() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"user_id": "u1"}],
        [{"id": 7, "role_id": "7", "role_name": "admin"}],
        [],
    ]
    svc = UserService(sql=sql)
    out = svc.add_user_direct_role("u1", "admin", workspace_id="ws-1")
    assert out["user_id"] == "u1"
    assert out["workspace_id"] == "ws-1"
    assert out["role_name"] == "admin"
    assert out["created"] is True
    assert any("INSERT INTO user_roles" in call.query for call in sql.write_calls)


def test_remove_user_direct_role_not_found() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"user_id": "u1"}],
    ]
    sql.write_responses = [0]
    svc = UserService(sql=sql)
    with pytest.raises(ForgeError) as exc:
        svc.remove_user_direct_role("u1", "admin", workspace_id="ws-1")
    assert exc.value.status_code == 404


def test_update_user_syncs_rbac_role_names() -> None:
    sql = FakeForgeQueryPort()
    svc = UserService(sql=sql)
    svc.get_user = lambda _user_id, workspace_id=None: User(user_id="u1", user_name="alice")  # type: ignore[assignment]
    svc._sync_user_direct_roles = lambda *_args, **_kwargs: None  # type: ignore[assignment]

    out = svc.update_user("u1", User(rbac_role_names=["admin"]), workspace_id="ws-1")
    assert out.user_id == "u1"
    assert sql.write_calls == []


def test_add_user_direct_role_requires_workspace_for_non_global() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"user_id": "u1"}],
        [{"id": 7, "role_id": "7", "role_name": "admin"}],
    ]
    svc = UserService(sql=sql)
    with pytest.raises(ForgeError) as exc:
        svc.add_user_direct_role("u1", "admin")
    assert exc.value.status_code == 400
