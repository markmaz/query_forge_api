from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.models.user import User
from app.services.user_service import UserService
from tests._support.fakes import FakeSQLExecutor


def test_get_user_effective_role_names_merges_and_dedupes() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {"product_role_id": "pr1", "role_id": "viewer", "role_name": "Viewer"},
            {"product_role_id": "pr2", "role_id": "admin", "role_name": "Admin"},
        ],
        [
            {"role_id": "admin", "role_name": "Admin"},
            {"role_id": "editor", "role_name": "Editor"},
        ],
    ]

    svc = UserService(sql=sql)
    names = svc.get_user_effective_role_names("u1")
    assert names == ["Admin", "Editor", "Viewer"]


def test_sync_user_direct_roles_insert_and_delete() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {"role_id": "viewer"},
            {"role_id": "editor"},
        ]
    ]

    svc = UserService(sql=sql)
    with sql.transaction() as tx:
        svc._sync_user_direct_roles(tx, "u1", ["viewer", "admin"])

    assert any("DELETE FROM user_global_roles" in call.query for call in sql.write_calls)
    assert any("INSERT INTO user_global_roles" in call.query for call in sql.write_calls)


def test_add_user_direct_role_success() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [{"user_id": "u1"}],
        [{"role_id": "admin"}],
        [],
        [{"role_id": "admin", "role_name": "Admin"}],
    ]
    svc = UserService(sql=sql)
    out = svc.add_user_direct_role("u1", "admin")
    assert out["user_id"] == "u1"
    assert out["role_id"] == "admin"
    assert out["created"] is True
    assert any("INSERT INTO user_global_roles" in call.query for call in sql.write_calls)


def test_remove_user_direct_role_not_found() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [{"user_id": "u1"}],
    ]
    sql.write_responses = [0]
    svc = UserService(sql=sql)
    with pytest.raises(ServiceError) as exc:
        svc.remove_user_direct_role("u1", "admin")
    assert exc.value.status_code == 404


def test_update_user_syncs_rbac_role_ids() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [],
    ]
    svc = UserService(sql=sql)
    svc.get_user = lambda _user_id: User(user_id="u1", user_name="alice")  # type: ignore[assignment]

    out = svc.update_user("u1", User(rbac_role_ids=["admin"]))
    assert out.user_id == "u1"
    assert any("INSERT INTO user_global_roles" in call.query for call in sql.write_calls)
