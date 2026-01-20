from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain.domain_admin_write_service import DomainAdminWriteService
from tests._support.fakes import FakeSQLExecutor


def test_create_domain_success() -> None:
    sql = FakeSQLExecutor()
    sql.query_responses = [[]]
    sql.query_mappings_responses = [
        [
            {
                "id": 1,
                "name": "Domain",
                "kind": None,
                "description": None,
                "model_table_id": None,
                "column_name_policy": "DEDUP_PRIMARY_FIRST",
                "model_table_name": None,
                "is_active": 1,
                "created_at": None,
                "updated_at": None,
            }
        ]
    ]
    service = DomainAdminWriteService(sql=sql)
    res = service.create_domain(workspace_id="ws1", user_id="u1", name="Domain")
    assert res["name"] == "Domain"


def test_create_domain_invalid_policy() -> None:
    service = DomainAdminWriteService(sql=FakeSQLExecutor())
    with pytest.raises(ServiceError):
        service.create_domain(workspace_id="ws1", user_id="u1", name="Domain", column_name_policy="BAD")


def test_patch_domain_success() -> None:
    sql = FakeSQLExecutor()
    sql.query_responses = [[("ok",)]]
    sql.query_mappings_responses = [
        [
            {
                "id": 1,
                "name": "Domain",
                "kind": None,
                "description": None,
                "model_table_id": None,
                "column_name_policy": "DEDUP_PRIMARY_FIRST",
                "model_table_name": None,
                "is_active": 1,
                "created_at": None,
                "updated_at": None,
            }
        ]
    ]
    service = DomainAdminWriteService(sql=sql)
    res = service.patch_domain(workspace_id="ws1", user_id="u1", domain_id=1, name="Domain")
    assert res["name"] == "Domain"


def test_patch_domain_no_fields() -> None:
    sql = FakeSQLExecutor()
    sql.query_responses = [[("ok",)]]
    service = DomainAdminWriteService(sql=sql)
    with pytest.raises(ServiceError, match="No fields to update"):
        service.patch_domain(workspace_id="ws1", user_id="u1", domain_id=1)


def test_delete_domain_not_found() -> None:
    sql = FakeSQLExecutor()
    sql.query_responses = [[("ok",)]]
    sql.write_responses = [0]
    service = DomainAdminWriteService(sql=sql)
    with pytest.raises(ServiceError, match="Domain not found"):
        service.delete_domain(workspace_id="ws1", user_id="u1", domain_id=1)
