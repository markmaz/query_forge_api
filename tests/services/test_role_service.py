from __future__ import annotations

import pytest
from sqlalchemy import exc

from app.exceptions.forge_error import ForgeError
from app.services.role_service import RoleService
from tests._support.fakes import FakeForgeQueryPort


def test_get_roles_success() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"role_id": "r1", "role_name": "Admin"}]]
    service = RoleService(sql=sql)
    res = service.get_roles()
    assert res[0]["role_name"] == "Admin"


def test_get_roles_db_error() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_exceptions = [exc.SQLAlchemyError("boom")]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Failed to retrieve"):
        service.get_roles()


def test_add_role_duplicate() -> None:
    sql = FakeForgeQueryPort()
    service = RoleService(sql=sql)
    service.get_roles = lambda: [{"role_name": "Admin"}]
    with pytest.raises(ForgeError, match="already exists"):
        service.add_role("Admin")


def test_add_role_success() -> None:
    sql = FakeForgeQueryPort()
    service = RoleService(sql=sql)
    service.get_roles = lambda: []
    res = service.add_role("Viewer")
    assert res["role_name"] == "Viewer"
    assert sql.write_calls


def test_add_role_db_error() -> None:
    sql = FakeForgeQueryPort()
    sql.write_exceptions = [exc.SQLAlchemyError("boom")]
    service = RoleService(sql=sql)
    service.get_roles = lambda: []
    with pytest.raises(ForgeError, match="Database error"):
        service.add_role("Viewer")


def test_get_role_not_found() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Role not found"):
        service.get_role("missing")


def test_get_role_db_error() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_exceptions = [exc.SQLAlchemyError("boom")]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Database error"):
        service.get_role("admin")


def test_get_role_success() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"role_id": "1", "role_name": "Admin"}]]
    service = RoleService(sql=sql)
    role = service.get_role("Admin")
    assert role["role_id"] == "1"


def test_delete_role_success() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"role_id": "1", "role_name": "viewer", "is_system": 0}]]
    sql.write_responses = [1]
    service = RoleService(sql=sql)
    res, status = service.delete_role("viewer")
    assert status == 200
    assert res["message"] == "Role deleted successfully"


def test_delete_role_db_error() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"role_id": "1", "role_name": "viewer", "is_system": 0}]]
    sql.write_exceptions = [exc.SQLAlchemyError("boom")]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Database error"):
        service.delete_role("viewer")


