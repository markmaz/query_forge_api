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
    res = service.add_role("Admin")
    assert isinstance(res, ForgeError)


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
        service.get_role("r1")


def test_get_role_success() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"role_id": "r1", "role_name": "Admin"}]]
    service = RoleService(sql=sql)
    role = service.get_role("r1")
    assert role["role_id"] == "r1"


def test_delete_role_success() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses = [1, 1]
    service = RoleService(sql=sql)
    res, status = service.delete_role("r1")
    assert status == 200
    assert res["message"] == "Role deleted successfully"


def test_delete_role_db_error() -> None:
    sql = FakeForgeQueryPort()
    sql.write_exceptions = [exc.SQLAlchemyError("boom")]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Database error"):
        service.delete_role("r1")


def test_map_product_to_role(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    service = RoleService(sql=sql)
    monkeypatch.setattr(service, "has_role", lambda *_args, **_kwargs: False)
    res = service.map_product_to_role("p1", "r1")
    assert res["product_id"] == "p1"

    monkeypatch.setattr(service, "has_role", lambda *_args, **_kwargs: True)
    with pytest.raises(ForgeError):
        service.map_product_to_role("p1", "r1")


def test_map_product_to_role_db_error(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.write_exceptions = [exc.SQLAlchemyError("boom")]
    service = RoleService(sql=sql)
    monkeypatch.setattr(service, "has_role", lambda *_args, **_kwargs: False)
    with pytest.raises(ForgeError, match="Database error"):
        service.map_product_to_role("p1", "r1")


def test_remove_role_from_product_success() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"product_role_id": "pr1"}],
        [{"cnt": 0}],
    ]
    sql.write_responses = [1, 1]
    service = RoleService(sql=sql)
    res = service.remove_role_from_product("p1", "r1")
    assert res["deleted_product_role_id"] == "pr1"


def test_remove_role_from_product_missing_mapping() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Role mapping not found"):
        service.remove_role_from_product("p1", "r1")


def test_remove_role_from_product_in_use() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"product_role_id": "pr1"}],
        [{"cnt": 2}],
    ]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Cannot delete"):
        service.remove_role_from_product("p1", "r1")


def test_remove_role_from_product_delete_missing() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"product_role_id": "pr1"}],
        [{"cnt": 0}],
    ]
    sql.write_responses = [0]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="concurrent"):
        service.remove_role_from_product("p1", "r1")


def test_remove_role_from_product_db_error() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"product_role_id": "pr1"}],
        [{"cnt": 0}],
    ]
    sql.write_exceptions = [exc.SQLAlchemyError("boom")]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Database error"):
        service.remove_role_from_product("p1", "r1")


def test_has_role() -> None:
    sql = FakeForgeQueryPort()
    sql.query_responses = [[("row",)]]
    service = RoleService(sql=sql)
    assert service.has_role("p1", "r1") is True
    sql.query_responses = [[]]
    assert service.has_role("p1", "r1") is False


def test_has_role_db_error() -> None:
    sql = FakeForgeQueryPort()
    sql.query_exceptions = [exc.SQLAlchemyError("boom")]
    service = RoleService(sql=sql)
    with pytest.raises(ForgeError, match="Database error"):
        service.has_role("p1", "r1")
