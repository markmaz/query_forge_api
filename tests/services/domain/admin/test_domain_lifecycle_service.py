from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain.admin.domain_lifecycle_service import DomainLifecycleService
from tests._support.fakes import FakeForgeQueryPort


def test_create_domain_success() -> None:
    sql = FakeForgeQueryPort()
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
    service = DomainLifecycleService(sql=sql)
    res = service.create_domain(workspace_id="ws1", user_id="u1", name="Domain")
    assert res["name"] == "Domain"


def test_patch_domain_no_fields() -> None:
    sql = FakeForgeQueryPort()
    sql.query_responses = [[("ok",)]]
    service = DomainLifecycleService(sql=sql)
    with pytest.raises(ForgeError, match="No fields to update"):
        service.patch_domain(workspace_id="ws1", user_id="u1", domain_id=1)
