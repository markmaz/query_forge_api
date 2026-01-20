from __future__ import annotations

import json

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain.domain_column_sample_read_service import DomainColumnSampleReadService
from tests._support.fakes import FakeSQLExecutor


def test_sample_column_missing_name() -> None:
    service = DomainColumnSampleReadService(sql=FakeSQLExecutor())
    with pytest.raises(ServiceError):
        service.sample_column_values(
            workspace_id="ws1",
            user_id="u1",
            workspace_table_id=1,
            column_name="",
        )


def test_sample_column_no_workspace_table() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [[]]
    service = DomainColumnSampleReadService(sql=sql)
    with pytest.raises(ServiceError, match="workspace_table not found"):
        service.sample_column_values(
            workspace_id="ws1",
            user_id="u1",
            workspace_table_id=1,
            column_name="col",
        )


def test_sample_column_no_model_table() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [[{"model_table_id": None, "full_name": "main.asset.tbl"}]]
    service = DomainColumnSampleReadService(sql=sql)
    res = service.sample_column_values(
        workspace_id="ws1",
        user_id="u1",
        workspace_table_id=1,
        column_name="col",
    )
    assert res["error"]


def test_sample_column_success() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [{"model_table_id": 10, "full_name": "main.asset.tbl"}],
        [
            {
                "sample_values_json": json.dumps([1, 2, 3]),
                "sample_stats_json": json.dumps({"min": 1}),
                "sample_ran_at": None,
                "sample_error": None,
            }
        ],
    ]
    service = DomainColumnSampleReadService(sql=sql)
    res = service.sample_column_values(
        workspace_id="ws1",
        user_id="u1",
        workspace_table_id=1,
        column_name="col",
        limit=2,
    )
    assert res["values"] == [1, 2]
